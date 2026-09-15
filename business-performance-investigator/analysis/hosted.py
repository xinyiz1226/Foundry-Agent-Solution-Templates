"""Private analytical snapshot lifecycle; no network or identity setup on import."""

from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
import re
from uuid import UUID

import pytds

from probe_agent.config import Settings
from probe_agent.sql_probe import ProbeFailure, SqlProbe, require_private_candidates, resolve_candidates

from .core import Coverage, Investigator, Limits, Period, run_baseline
from .sql_source import SqlSalesSource


PERMISSIONS = {
    "view_select": ("reporting.v_internet_sales", "OBJECT", "SELECT", 1),
    "manifest_view_select": ("reporting.v_analysis_manifest", "OBJECT", "SELECT", 1),
    "base_select": ("reporting.internet_sales_snapshot", "OBJECT", "SELECT", 0),
    "base_insert": ("reporting.internet_sales_snapshot", "OBJECT", "INSERT", 0),
    "base_update": ("reporting.internet_sales_snapshot", "OBJECT", "UPDATE", 0),
    "base_delete": ("reporting.internet_sales_snapshot", "OBJECT", "DELETE", 0),
    "manifest_base_select": ("reporting.analysis_snapshot_manifest", "OBJECT", "SELECT", 0),
    "manifest_base_insert": ("reporting.analysis_snapshot_manifest", "OBJECT", "INSERT", 0),
    "manifest_base_update": ("reporting.analysis_snapshot_manifest", "OBJECT", "UPDATE", 0),
    "manifest_base_delete": ("reporting.analysis_snapshot_manifest", "OBJECT", "DELETE", 0),
    "view_insert": ("reporting.v_internet_sales", "OBJECT", "INSERT", 0),
    "view_update": ("reporting.v_internet_sales", "OBJECT", "UPDATE", 0),
    "view_delete": ("reporting.v_internet_sales", "OBJECT", "DELETE", 0),
    "schema_alter": ("reporting", "SCHEMA", "ALTER", 0),
    "database_create_table": (None, "DATABASE", "CREATE TABLE", 0),
    "database_create_view": (None, "DATABASE", "CREATE VIEW", 0),
    "database_control": (None, "DATABASE", "CONTROL", 0),
}
_CHECKS = ",\n".join(
    f"HAS_PERMS_BY_NAME({'DB_NAME()' if name is None else chr(39) + name + chr(39)}, '{kind}', '{permission}') AS {alias}"
    for alias, (name, kind, permission, expected) in PERMISSIONS.items()
)
SECURITY_SQL = f"""SELECT TOP (2)
CAST(USER_NAME() AS nvarchar(128)) AS database_principal,
(SELECT CASE WHEN DATALENGTH(sid)=16 THEN CAST(sid AS uniqueidentifier) ELSE NULL END
 FROM sys.database_principals WHERE principal_id=USER_ID()) AS database_principal_sid,
CAST(DB_NAME() AS nvarchar(128)) AS database_name,
m.source_sha256, m.dataset_id, m.row_count,
totals.actual_row_count, totals.sales_amount, totals.total_product_cost,
{_CHECKS}
FROM reporting.v_analysis_manifest AS m
CROSS JOIN (
 SELECT COUNT_BIG(*) AS actual_row_count, SUM(sales_amount) AS sales_amount,
 SUM(total_product_cost) AS total_product_cost FROM reporting.v_internet_sales
) AS totals;"""


class SessionFailure(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class HostedPolicy:
    dataset_id: str
    source_sha256: str
    row_count: int
    sales_amount: Decimal
    total_product_cost: Decimal
    database_principal: str
    coverage: Coverage
    baseline: Period
    current: Period

    @classmethod
    def load(cls, path: Path):
        raw = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object)
        expected = {
            "schema_version", "dataset_id", "source_sha256", "row_count",
            "sales_amount", "total_product_cost", "database_principal",
            "coverage", "baseline", "current",
        }
        if (not isinstance(raw, dict) or set(raw) != expected
                or type(raw["schema_version"]) is not int or raw["schema_version"] != 1):
            raise ValueError("Invalid hosted sample policy.")
        if not isinstance(raw["source_sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", raw["source_sha256"]):
            raise ValueError("Hosted policy requires a source SHA-256.")
        if type(raw["row_count"]) is not int or not 1 <= raw["row_count"] <= 200000:
            raise ValueError("Hosted policy row count is outside the sample budget.")
        if raw["database_principal"] != "bpi_probe_agent":
            raise ValueError("Hosted analysis requires its dedicated experimental SQL user.")
        if not isinstance(raw["dataset_id"], str) or not 1 <= len(raw["dataset_id"]) <= 256:
            raise ValueError("Hosted dataset identity is invalid.")
        for key in ("sales_amount", "total_product_cost"):
            if not isinstance(raw[key], str) or not re.fullmatch(r"-?\d{1,18}\.\d{4}", raw[key], flags=re.ASCII):
                raise ValueError("Hosted expected totals require exact four-place monetary strings.")
        sales, cost = Decimal(raw["sales_amount"]), Decimal(raw["total_product_cost"])
        for key, fields in (("coverage", {"start", "end", "attestation"}),
                            ("baseline", {"start", "end"}), ("current", {"start", "end"})):
            if not isinstance(raw[key], dict) or set(raw[key]) != fields:
                raise ValueError("Hosted coverage and period fields are invalid.")
        coverage = Coverage(Period.parse(raw["coverage"]["start"], raw["coverage"]["end"]), raw["coverage"]["attestation"])
        baseline, current = Period.parse(**raw["baseline"]), Period.parse(**raw["current"])
        coverage.validate(baseline)
        coverage.validate(current)
        if baseline.end > current.start:
            raise ValueError("Hosted comparison periods must be disjoint.")
        return cls(raw["dataset_id"], raw["source_sha256"], raw["row_count"], sales, cost,
                   raw["database_principal"], coverage, baseline, current)


class PrivateAnalysisSession:
    def __init__(self, settings: Settings, credential, policy: HostedPolicy, *, connect=pytds.connect, resolver=resolve_candidates):
        if settings.local_development:
            raise SessionFailure("identity_mode", "Hosted analysis never substitutes a developer identity.")
        self.settings, self.credential, self.policy = settings, credential, policy
        self._connect, self._resolver = connect, resolver
        self.connection = self.cursor = self._source = None
        self._transaction = False
        self.security = {}

    @property
    def source(self):
        if self._source is None:
            raise SessionFailure("session_inactive", "The analytical snapshot is not active.")
        return self._source

    def __enter__(self):
        complete = False
        try:
            addresses = require_private_candidates(self.settings.server, self.settings.connect_timeout, self._resolver)
            options = SqlProbe(self.settings, self.credential).connection_options()
            options.update(as_dict=False, appname="business-performance-analysis")
            self.connection = self._connect(**options)
            self.cursor = self.connection.cursor()
            self.cursor.execute("SET TRANSACTION ISOLATION LEVEL SNAPSHOT; BEGIN TRANSACTION;")
            self._transaction = True
            self.cursor.execute(SECURITY_SQL)
            rows = self.cursor.fetchmany(2)
            description = self.cursor.description
            if len(rows) != 1 or not description or len(rows[0]) != len(description):
                raise SessionFailure("snapshot_metadata", "Expected exactly one complete snapshot evidence row.")
            names = [column[0] for column in description]
            if len(names) != len(set(names)):
                raise SessionFailure("snapshot_metadata", "Snapshot evidence columns are ambiguous.")
            record = dict(zip(names, rows[0]))
            required = {"database_principal", "database_principal_sid", "database_name",
                        "source_sha256", "dataset_id", "row_count", "actual_row_count",
                        "sales_amount", "total_product_cost", *PERMISSIONS}
            if set(record) != required:
                raise SessionFailure("snapshot_metadata", "Snapshot evidence fields do not match the contract.")
            try:
                sid = UUID(str(record["database_principal_sid"]))
            except ValueError:
                raise SessionFailure("identity_mismatch", "SQL did not return a valid service-principal SID.") from None
            if (sid.int == 0 or record["database_principal"] != self.policy.database_principal
                    or record["database_name"] != self.settings.database):
                raise SessionFailure("identity_mismatch", "SQL identity/database differs from the approved experiment.")
            if (record["source_sha256"] != self.policy.source_sha256 or record["dataset_id"] != self.policy.dataset_id
                    or any(type(record[key]) is not int or record[key] != self.policy.row_count for key in ("row_count", "actual_row_count"))
                    or not isinstance(record["sales_amount"], Decimal) or record["sales_amount"] != self.policy.sales_amount
                    or not isinstance(record["total_product_cost"], Decimal) or record["total_product_cost"] != self.policy.total_product_cost):
                raise SessionFailure("snapshot_mismatch", "SQL snapshot identity/counts/totals differ from the pinned sample.")
            for key, (_, _, _, expected) in PERMISSIONS.items():
                if type(record[key]) is not int or record[key] != expected:
                    raise SessionFailure("permission_mismatch", "Required SQL permissions are missing, excessive or unknown.")
            self.security = {
                "status": "passed", "identity_mode": "managed_identity",
                "database_principal": record["database_principal"], "database_principal_sid": str(sid),
                "database_name": record["database_name"], "source_sha256": record["source_sha256"],
                "actual_row_count": record["actual_row_count"],
                "permissions": {key: record[key] for key in PERMISSIONS},
                "dns_candidates": addresses, "all_candidates_private": True,
                "tls": {"hostname_verification": True, "full_session_encryption": True, "ca_source": "certifi"},
                "snapshot": "explicit SNAPSHOT transaction",
                "hash_note": "Initializer-attested source hash plus checked totals; not a runtime hash of every SQL row.",
                "network_note": "Cloud validation must independently check public access disabled and the approved private endpoint.",
                "identity_note": "Cloud validation must match this SID to the deployed agent application/client ID.",
            }
            self._source = SqlSalesSource(
                self.cursor, dataset_id=self.policy.dataset_id,
                snapshot_attestation="One explicit SNAPSHOT transaction; managed-identity connection, verified TLS/private DNS, driver-enforced query timeout.",
            )
            complete = True
            return self
        except (ProbeFailure, pytds.Error, OSError):
            raise SessionFailure("private_sql_failed", "Private SQL snapshot setup failed; inspect identity, TLS, snapshot configuration and owned initialization.") from None
        finally:
            if not complete:
                self._close()

    def _close(self):
        failures = []
        if self.cursor is not None and self._transaction:
            try:
                self.cursor.execute("IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;")
            except Exception:
                failures.append("rollback")
        for label, resource in (("cursor", self.cursor), ("connection", self.connection)):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    failures.append(label)
        self.cursor = self.connection = self._source = None
        self._transaction = False
        self.security["connection_closed"] = not failures
        if failures:
            raise SessionFailure("cleanup_failed", "Analytical SQL resources did not close cleanly.")

    def __exit__(self, exc_type, exc, traceback):
        self._close()
        return False


RESULT_MARKER = "BPI_ANALYSIS_RESULT="


def render_analysis_result(report: dict) -> str:
    encoded = json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    encoded = encoded.replace(RESULT_MARKER, "BPI_ANALYSIS_RESULT\\u003d")
    return "Business analysis evidence follows; this is not a causal explanation.\n\n" + RESULT_MARKER + encoded


def analysis_error(code: str, message: str) -> str:
    return render_analysis_result({"schema_version": 1, "status": "failed", "error": {"code": code, "message": message}})


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate request key")
        result[key] = value
    return result


class AnalysisAgent:
    def __init__(self, settings: Settings, credential, client, policy: HostedPolicy, *, session_factory=None, adaptive_runner=None):
        if settings.model_api != "chat_completions":
            raise ValueError("Adaptive hosted analysis requires the explicit Chat Completions transport.")
        self.settings, self.credential, self.client, self.policy = settings, credential, client, policy
        self._session_factory = session_factory or (lambda: PrivateAnalysisSession(settings, credential, policy))
        self._adaptive_runner = adaptive_runner

    def answer(self, user_input: str) -> str:
        try:
            if not isinstance(user_input, str) or not user_input.strip() or len(user_input) > 4000:
                raise ValueError("Invalid question")
            request = (
                json.loads(user_input, object_pairs_hook=_unique_object)
                if user_input.lstrip().startswith("{")
                else {"mode": "adaptive", "question": user_input}
            )
            if not isinstance(request, dict) or set(request) != {"mode", "question"}:
                raise ValueError("Only mode and question are accepted")
            if request["mode"] not in ("baseline", "adaptive"):
                raise ValueError("Unsupported mode")
            question = request["question"]
            if not isinstance(question, str) or not question.strip() or len(question) > 3000:
                raise ValueError("Invalid question")
        except (ValueError, TypeError):
            return analysis_error("invalid_input", "Supply a bounded question or JSON with only mode (baseline/adaptive) and question. Periods, views and SQL are not request parameters.")
        try:
            with self._session_factory() as session:
                investigator = Investigator(session.source, self.policy.coverage, limits=Limits(max_seconds=120))
                if request["mode"] == "baseline":
                    report = run_baseline(investigator, self.policy.baseline, self.policy.current)
                else:
                    from .adaptive import AdaptiveLimits, run_adaptive
                    runner = self._adaptive_runner
                    if runner is None:
                        runner = run_adaptive
                    report = runner(investigator, self.policy.baseline, self.policy.current, question,
                                    client=self.client, model=self.settings.model,
                                    limits=AdaptiveLimits(max_seconds=120))
            report["security"] = dict(session.security)
            report["approved_sample_policy"] = {
                "source_sha256": self.policy.source_sha256,
                "row_count": self.policy.row_count,
                "periods_are_model_controlled": False,
            }
            report["sql_control_operations"] = {
                "snapshot_begin": 1, "identity_manifest_permission_query": 1, "rollback": 1,
                "note": "These fixed control operations are additional to analytical data requests.",
            }
            return render_analysis_result(report)
        except SessionFailure as error:
            return analysis_error(error.code, str(error))
        except (ValueError, TypeError, KeyError, pytds.Error, OSError):
            return analysis_error("analysis_failed", "The analytical request failed; no unsupported result or raw database/model exception is returned.")
