"""Local transactional ledger. This is not the source project's Blob adapter."""

from contextlib import contextmanager
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Iterator

from .contracts import (
    Action, Attempt, Block, Blocked, Candidate, Chunk, Claim, Conflict, Evidence,
    FailureCode, IntegrityError, InvalidInput, Metric, NotFound, Plan, Record, ReviewStatus,
    Snapshot, StaleRevision, Status, TokenUsage,
)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _plan(value: dict) -> Plan:
    return Plan(
        **{key: item for key, item in value.items() if key != "chunks"},
        chunks=tuple(
            Chunk(chunk["id"], tuple(Block(**block) for block in chunk["blocks"]))
            for chunk in value["chunks"]
        ),
    )


def _snapshot(payload: str, digest: str) -> Snapshot:
    if _hash(payload) != digest:
        raise IntegrityError("checkpoint_digest_mismatch")
    data = json.loads(payload)
    return Snapshot(
        **{key: item for key, item in data.items()
           if key not in {"plan", "status", "completed_chunk_ids", "attempts", "candidates", "claim"}},
        plan=_plan(data["plan"]),
        status=Status(data["status"]),
        completed_chunk_ids=tuple(data["completed_chunk_ids"]),
        attempts=tuple(Attempt(
            **{key: item for key, item in attempt.items()
               if key not in {"failure_code", "usage", "covered_block_ids"}},
            failure_code=FailureCode(attempt["failure_code"]) if attempt["failure_code"] else None,
            usage=TokenUsage(**attempt["usage"]) if attempt["usage"] is not None else None,
            covered_block_ids=tuple(attempt["covered_block_ids"]),
        ) for attempt in data["attempts"]),
        candidates=tuple(Candidate(
            **{key: item for key, item in candidate.items()
               if key not in {"record", "evidence", "review_status"}},
            record=Record(**{**candidate["record"], "metric": Metric(candidate["record"]["metric"])}),
            evidence=tuple(Evidence(**evidence) for evidence in candidate["evidence"]),
            review_status=ReviewStatus(candidate["review_status"]),
        ) for candidate in data["candidates"]),
        claim=Claim(**{**data["claim"], "action": Action(data["claim"]["action"])})
        if data["claim"] is not None else None,
    )


class SQLiteStore:
    """One file, fresh connection per operation, no connection during inference."""

    def __init__(self, path: str | Path, *, timeout: float = 5.0):
        if not isinstance(path, (str, Path)) or not str(path).strip() or str(path) == ":memory:":
            raise InvalidInput("persistent_database_path_required")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0:
            raise InvalidInput("invalid_storage_timeout")
        self.path = Path(path)
        if self.path.is_dir():
            raise InvalidInput("persistent_database_path_required")
        self.timeout = timeout
        with self._transaction() as connection:
            for statement in (
                """CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY, plan TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, revision INTEGER NOT NULL)""",
                """CREATE TABLE IF NOT EXISTS checkpoints (
                    job_id TEXT NOT NULL REFERENCES jobs(job_id), revision INTEGER NOT NULL,
                    payload TEXT NOT NULL, digest TEXT NOT NULL,
                    PRIMARY KEY(job_id, revision))""",
                """CREATE TABLE IF NOT EXISTS requests (
                    request_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    fingerprint TEXT NOT NULL, result TEXT, digest TEXT)""",
                """CREATE TABLE IF NOT EXISTS claims (
                    job_id TEXT NOT NULL REFERENCES jobs(job_id), revision INTEGER NOT NULL,
                    request_id TEXT NOT NULL UNIQUE REFERENCES requests(request_id),
                    action TEXT NOT NULL, chunk_id TEXT NOT NULL,
                    PRIMARY KEY(job_id, revision))""",
            ):
                connection.execute(statement)

    @contextmanager
    def _transaction(self, *, write: bool = True) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=self.timeout)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            with connection:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield connection
        finally:
            connection.close()

    def _read(self, connection: sqlite3.Connection, job_id: str) -> Snapshot:
        job = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if job is None:
            raise NotFound("job_not_found")
        if _hash(job["plan"]) != job["fingerprint"]:
            raise IntegrityError("plan_digest_mismatch")
        checkpoint = connection.execute(
            "SELECT * FROM checkpoints WHERE job_id = ? AND revision = ?",
            (job_id, job["revision"]),
        ).fetchone()
        if checkpoint is None:
            raise IntegrityError("checkpoint_missing")
        result = _snapshot(checkpoint["payload"], checkpoint["digest"])
        if result.plan_fingerprint != job["fingerprint"] or _json(asdict(result.plan)) != job["plan"]:
            raise IntegrityError("checkpoint_plan_mismatch")
        claim = connection.execute(
            "SELECT * FROM claims WHERE job_id = ? AND revision = ?",
            (job_id, job["revision"]),
        ).fetchone()
        if claim:
            result = replace(result, status=Status.IN_PROGRESS, claim=Claim(
                claim["request_id"], claim["revision"], Action(claim["action"]), claim["chunk_id"],
            ))
        return result

    def read(self, job_id: str) -> Snapshot:
        with self._transaction(write=False) as connection:
            return self._read(connection, job_id)

    def _replay(
        self, connection: sqlite3.Connection, request_id: str, fingerprint: str
    ) -> Snapshot | None:
        request = connection.execute(
            "SELECT * FROM requests WHERE request_id = ?", (request_id,)
        ).fetchone()
        if request is None:
            return None
        if request["fingerprint"] != fingerprint:
            raise Conflict("request_identity_conflict")
        if request["result"] is None:
            raise Blocked("unresolved_claim")
        return _snapshot(request["result"], request["digest"])

    def create(self, job_id: str, plan: Plan, request_id: str) -> Snapshot:
        encoded = _json(asdict(plan))
        fingerprint = _hash(encoded)
        identity = _hash(_json(["create", job_id, fingerprint]))
        with self._transaction() as connection:
            replay = self._replay(connection, request_id, identity)
            if replay is not None:
                return replay
            existing = connection.execute(
                "SELECT fingerprint FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if existing is not None:
                if existing["fingerprint"] != fingerprint:
                    raise Conflict("job_identity_conflict")
                result = self._read(connection, job_id)
            else:
                result = Snapshot(job_id, plan, fingerprint)
                connection.execute(
                    "INSERT INTO jobs VALUES (?, ?, ?, 0)", (job_id, encoded, fingerprint)
                )
                payload = _json(asdict(result))
                connection.execute(
                    "INSERT INTO checkpoints VALUES (?, 0, ?, ?)", (job_id, payload, _hash(payload))
                )
            payload = _json(asdict(result))
            connection.execute(
                "INSERT INTO requests VALUES (?, ?, ?, ?, ?)",
                (request_id, job_id, identity, payload, _hash(payload)),
            )
            return result

    def claim(
        self, job_id: str, expected_revision: int, request_id: str, action: Action
    ) -> Snapshot:
        identity = _hash(_json([action, job_id, expected_revision]))
        with self._transaction() as connection:
            replay = self._replay(connection, request_id, identity)
            if replay is not None:
                return replay
            result = self._read(connection, job_id)
            if result.revision != expected_revision:
                raise StaleRevision("stale_revision")
            if result.status == Status.IN_PROGRESS:
                raise Blocked("unresolved_claim")
            if result.status == Status.COMPLETED:
                raise Conflict("job_completed")
            if (result.status == Status.FAILED) != (action == Action.RESUME):
                raise Conflict("explicit_resume_required_or_not_applicable")
            chunk = result.plan.chunks[len(result.completed_chunk_ids)]
            claim = Claim(request_id, expected_revision, action, chunk.id)
            connection.execute(
                "INSERT INTO requests VALUES (?, ?, ?, NULL, NULL)", (request_id, job_id, identity)
            )
            connection.execute(
                "INSERT INTO claims VALUES (?, ?, ?, ?, ?)",
                (job_id, expected_revision, request_id, action, chunk.id),
            )
            return replace(result, status=Status.IN_PROGRESS, claim=claim)

    def publish(self, claimed: Snapshot, result: Snapshot) -> Snapshot:
        with self._transaction() as connection:
            current = self._read(connection, claimed.job_id)
            if current != claimed or claimed.claim is None:
                raise Conflict("publication_owner_conflict")
            if result.revision != claimed.revision + 1 or result.claim is not None:
                raise Conflict("publication_revision_conflict")
            payload = _json(asdict(result))
            digest = _hash(payload)
            connection.execute(
                "INSERT INTO checkpoints VALUES (?, ?, ?, ?)",
                (result.job_id, result.revision, payload, digest),
            )
            connection.execute(
                "UPDATE jobs SET revision = ? WHERE job_id = ?", (result.revision, result.job_id)
            )
            connection.execute(
                "UPDATE requests SET result = ?, digest = ? WHERE request_id = ? AND result IS NULL",
                (payload, digest, claimed.claim.request_id),
            )
            return result
