"""Offline replay CLI. Inference needs explicit approval AND a caller-injected client."""

import argparse
import json
from pathlib import Path
import sys

from .adaptive import AdaptiveLimits, strict_json
from .cli import load_investigation
from .evaluate import run_evaluation
from .model_client import ReplayClient


DEFAULT_REPLAY = Path(__file__).resolve().parents[1] / "evaluation" / "replays" / "synthetic-north.json"


def _read_replay(path, dataset_id):
    with Path(path).open(encoding="utf-8") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("Replay exceeds its size budget.")
    fixture = strict_json(raw)
    required = {"schema_version", "label", "question", "target_territory_ids", "expected_dataset_id", "steps"}
    if (not isinstance(fixture, dict) or set(fixture) != required
            or type(fixture["schema_version"]) is not int or fixture["schema_version"] != 1
            or fixture["expected_dataset_id"] != dataset_id):
        raise ValueError("Replay schema or dataset identity mismatch.")
    return fixture


def main(argv=None, *, client=None, model=None, caller_identity=None, limits=AdaptiveLimits(), prices=None):
    parser = argparse.ArgumentParser(description="Matched offline baseline/adaptive replay evaluation. No default network access.")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--question")
    parser.add_argument("--target-territory", action="append")
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--approve-model-inference", action="store_true",
                        help="Explicit approval for this invocation only; still requires injected client, model and caller identity.")
    args = parser.parse_args(argv)
    inference = args.approve_model_inference
    if inference:
        if (args.replay is not None or not callable(getattr(client, "create", None))
                or getattr(client, "execution_kind", None) == "replay"
                or not isinstance(model, str) or not model.strip()
                or not isinstance(caller_identity, str) or not caller_identity.strip() or len(caller_identity) > 256
                or not args.question):
            print("Inference requires explicit question, injected client/model/caller identity, and no replay.", file=sys.stderr)
            return 2
    elif any(value is not None for value in (client, model, caller_identity, prices)):
        print("Injected model configuration cannot run without --approve-model-inference.", file=sys.stderr)
        return 2
    try:
        investigator, baseline, current, top_k = load_investigation(args.csv, args.config)
        if args.top_k is not None:
            top_k = args.top_k
        if not inference:
            fixture = _read_replay(args.replay or DEFAULT_REPLAY, investigator.source.dataset_id)
            client, model = ReplayClient(fixture["steps"]), "offline-replay"
            question = args.question or fixture["question"]
            targets = args.target_territory if args.target_territory is not None else fixture["target_territory_ids"]
        else:
            question, targets = args.question, args.target_territory or []
        report = run_evaluation(investigator, baseline, current, question, client, model,
                                limits=limits, top_k=top_k, target_territory_ids=targets, prices=prices)
        report["authorization"] = {
            "model_inference_explicitly_approved": inference,
            "caller_identity_supplied": caller_identity is not None,
            "cloud_deployment_approved": False,
        }
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "evaluation.json").write_text(
            json.dumps(report, ensure_ascii=True, allow_nan=False, indent=2) + "\n", encoding="utf-8",
        )
        print(json.dumps({
            "execution_kind": report["execution_kind"],
            "baseline_status": report["baseline"]["report"]["status"],
            "adaptive_status": report["adaptive"]["report"]["status"],
            "report": str(args.output / "evaluation.json"),
        }))
        return 0 if all(report[key]["report"]["status"] == "ok" for key in ("baseline", "adaptive")) else 1
    except Exception:
        print("Adaptive evaluation failed; no successful report is claimed. Raw exception details are omitted.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
