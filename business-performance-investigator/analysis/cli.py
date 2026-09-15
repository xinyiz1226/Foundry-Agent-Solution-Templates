import argparse
import csv
import html
import json
from pathlib import Path
import sys

from .core import Coverage, CsvSalesSource, Investigator, Limits, Period, run_baseline
from .queries import View


def _text(value) -> str:
    return html.escape(str(value), quote=False).replace("|", r"\|").replace("\r", " ").replace("\n", " ")


def render_markdown(report: dict) -> str:
    comparison = report["comparison"]
    lines = [
        "# Business Performance Investigator: fixed baseline",
        "",
        ("**Execution:** offline CSV; SQL plans below were not executed. No model was called."
         if report["execution"]["mode"] == "offline_csv"
         else "**Execution:** caller-supplied SQL snapshot cursor. No model was called."),
        "",
        f"**Status:** {_text(report['status'])}.",
        "",
        f"Baseline: `{report['baseline_period']['start']}` to `{report['baseline_period']['end_exclusive']}` (exclusive).",
        f"Current: `{report['current_period']['start']}` to `{report['current_period']['end_exclusive']}` (exclusive).",
        "",
        "Money uses four decimal places in source units; ratios use six. No currency conversion is assumed.",
        "",
        "## Observed facts",
        "",
        "| Metric | Baseline | Current | Change |",
        "|---|---:|---:|---:|",
    ]
    for key in ("sales", "orders", "gross_profit", "gross_margin"):
        change_key = "gross_margin_percentage_points" if key == "gross_margin" else key
        change = comparison["change"][change_key]
        lines.append(
            f"| {key} | {_text(comparison['baseline'][key])} | {_text(comparison['current'][key])} | {_text(change)} |"
        )
    lines += ["", "Gross-margin change is in percentage points; other changes are absolute.",
              "Evidence: " + ", ".join(comparison["evidence_ids"]) + "."]
    for title, result in (("Territory sales contributions", report["territories"]), ("Product drilldown", report["products"])):
        if result is None:
            continue
        lines += ["", f"## {title}", ""]
        if title == "Product drilldown":
            selected = report["selected_territory"]
            lines += [f"Scope: {_text(selected['name'])} (ID `{_text(selected['id'])}`).", ""]
        lines += ["| Segment ID | Name | Baseline sales | Current sales | Change |",
                  "|---|---|---:|---:|---:|"]
        for row in result["segments"]:
            lines.append(f"| {_text(row['id'])} | {_text(row['name'])} | {row['baseline_sales']} | {row['current_sales']} | {row['change']} |")
        other = result["other"]
        lines += [
            f"| Other | {other['group_count']} remaining groups | {other['baseline_sales']} | {other['current_sales']} | {other['change']} |",
            "",
            f"Reconciled total change: {result['total_change']}. Contribution share status: {result['contribution_share_status']}.",
            "Evidence: " + ", ".join(result["evidence_ids"]) + ".",
        ]
    lines += ["", "## Hypotheses and missing evidence", "",
              "No causal conclusion is established by these sales aggregates."]
    lines.extend("- " + item for item in report["missing_evidence"])
    lines += ["", "## Completeness declaration", "", _text(report["coverage"]["attestation"]),
              "", "## Reproduction evidence", ""]
    for evidence in report["evidence"]:
        lines += [
            f"### {evidence['id']}",
            "",
            f"Dataset: {_text(evidence['dataset_id'])}; SHA-256: `{evidence['source_sha256']}`.",
            ("Execution mode: offline CSV. Azure SQL plan **not executed**."
             if not evidence["sql_executed"] else "SQL executed through the caller-supplied cursor; no source snapshot hash is claimed."),
            "",
            "```sql", evidence["query_plan"]["sql"], "```",
            "",
            "Parameters: `" + _text(json.dumps(evidence["query_plan"]["parameters"])) + "`.",
            "",
            "Result:",
            "```json", json.dumps(evidence["result"], ensure_ascii=True, indent=2), "```",
            "",
        ]
    return "\n".join(lines) + "\n"


def _object(value, allowed: set[str], required: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) - allowed or required - set(value):
        raise ValueError(f"Invalid {label} configuration fields.")
    return value


def load_investigation(csv_path: Path, config_path: Path):
    raw = config_path.read_text(encoding="utf-8-sig")
    if len(raw) > 65536:
        raise ValueError("Analysis configuration exceeds its size budget.")
    config = _object(
        json.loads(raw),
        {"dataset_id", "csv_sha256", "coverage", "baseline", "current", "top_k", "limits", "view"},
        {"dataset_id", "csv_sha256", "coverage", "baseline", "current"},
        "analysis",
    )
    coverage = _object(config["coverage"], {"start", "end", "attestation"}, {"start", "end", "attestation"}, "coverage")
    for key in ("baseline", "current"):
        _object(config[key], {"start", "end"}, {"start", "end"}, key)
    limits = _object(config.get("limits", {}), {"max_requests", "max_groups", "max_seconds"}, set(), "limits")
    view = _object(config.get("view", {}), {"schema", "name"}, set(), "view")
    source = CsvSalesSource.from_csv(csv_path, dataset_id=config["dataset_id"], expected_sha256=config["csv_sha256"])
    investigator = Investigator(
        source,
        Coverage(Period.parse(coverage["start"], coverage["end"]), coverage["attestation"]),
        limits=Limits(**limits),
        view=View(**view),
    )
    baseline = Period.parse(**config["baseline"])
    current = Period.parse(**config["current"])
    return investigator, baseline, current, config.get("top_k", 5)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the offline, deterministic Internet Sales baseline. No Azure or model calls.")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        investigator, baseline, current, top_k = load_investigation(args.csv, args.config)
        report = run_baseline(investigator, baseline, current, top_k=top_k)
        markdown = render_markdown(report)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (args.output / "report.md").write_text(markdown, encoding="utf-8")
        print(json.dumps({"output": str(args.output.resolve()), **report["execution"]}))
        return 0
    except (ValueError, OSError, csv.Error) as error:
        print(f"Baseline analysis failed: {error}", file=sys.stderr)
        return 1
