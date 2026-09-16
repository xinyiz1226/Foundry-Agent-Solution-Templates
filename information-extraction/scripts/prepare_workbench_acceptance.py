"""Prepare a fresh synthetic acceptance manifest locally; never provision or invoke Azure."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


def prepare(parent: Path) -> Path:
    """Allocate a create-only directory and distinct server-owned identities."""
    identifier = uuid4().hex
    directory = parent.resolve() / f"acceptance-{identifier}"
    directory.mkdir(parents=True, exist_ok=False)
    scenarios = []
    for name, allowances in (("pause-resume", [1, 1]), ("single-start", [2])):
        job_id = f"acceptance-{identifier}-{name}"
        scenarios.append({
            "name": name,
            "local_state_dir": str(directory / name),
            "hosted_environment": {
                "EXTRACTION_JOB_ID": job_id,
                "EXTRACTION_BLOB_PREFIX": job_id,
            },
            "round_attempt_allowances": allowances,
            "round_duration_seconds": 120,
            "expected_final_revision": 2,
            "expected_committed_attempts": 2,
            "expected_candidates": [
                {"metric": "revenue", "value": 120, "unit": "USD_millions", "block_id": "block-1"},
                {"metric": "operating_income", "value": 18, "unit": "USD_millions", "block_id": "block-3"},
            ],
        })
    manifest = {
        "format_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "synthetic_only": True,
        "azure_changes_performed": False,
        "cloud_execution_authorized": False,
        "scenarios": scenarios,
        "future_cloud_window": {
            "max_public_seconds": 600,
            "max_new_sessions": 2,
            "max_total_committed_attempts": 4,
            "real_model_calls": 0,
            "deadline_created_only_when_window_opens": True,
        },
        "preservation_rules": [
            "Do not overwrite a previous job, Blob prefix, state directory, or source artifact.",
            "Keep the current hosted version and its environment as a rollback reference.",
            "Apply job_id and Blob prefix together on a new hosted version; never retarget old sessions.",
            "Read current first and require the exact expected job_id with no round and no pending request.",
            "Only explicit Start and Resume authorize new rounds; retries preserve the original request.",
            "Unknown outcomes block further mutations; do not replace claims or renew deadlines.",
        ],
        "cleanup_rules": [
            "Capture baseline sessions before enabling the endpoint.",
            "Close public access, stop the owned web app, restore Always On, and disable the owned agent.",
            "Stop only new sessions established as belonging to this window; preserve baseline sessions.",
            "Retain synthetic ledgers and manifests as evidence; do not delete historical state.",
        ],
    }
    path = directory / "acceptance.json"
    with path.open("x", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)
        file.write("\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / ".local-data" / "acceptance")
    args = parser.parse_args()
    try:
        path = prepare(args.output_root)
    except OSError:
        print(json.dumps({"error": "acceptance_preparation_failed", "azure_changes_performed": False}))
        return 1
    print(json.dumps({"manifest": str(path), "azure_changes_performed": False, "cloud_execution_authorized": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
