"""Acquire and project the pinned official AdventureWorksDW sample locally."""

import argparse
import calendar
from collections import Counter, defaultdict
import csv
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[1]
COLUMNS = (
    "order_date", "sales_order_number", "product_id", "product_name",
    "territory_id", "territory_name", "sales_amount", "total_product_cost",
)
MAX_ARCHIVE_BYTES = 20_000_000
MAX_MEMBER_BYTES = 40_000_000
MAX_EXPANDED_BYTES = 150_000_000
TABLE_WIDTHS = {
    "FactInternetSales.csv": 26, "DimDate.csv": 19,
    "DimProduct.csv": 36, "DimSalesTerritory.csv": 6,
}


class SampleDataError(ValueError):
    """The sample could not be verified or safely projected."""


def _verify(data, expected, label):
    if len(data) != expected["size_bytes"]:
        raise SampleDataError(f"{label}: byte count does not match manifest")
    if hashlib.sha256(data).hexdigest() != expected["sha256"]:
        raise SampleDataError(f"{label}: SHA256 does not match manifest")


def _write_atomic(path, data):
    staged = path.with_name(path.name + ".part-" + uuid.uuid4().hex)
    try:
        with staged.open("xb") as stream:
            stream.write(data)
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def _download(archive, source):
    url = urllib.parse.urlsplit(source["url"])
    if (
        url.scheme != "https" or url.netloc != "github.com"
        or not url.path.startswith("/microsoft/sql-server-samples/releases/download/")
    ):
        raise SampleDataError("Download URL must be an official HTTPS Microsoft sample release")
    limit = min(source["max_download_bytes"], MAX_ARCHIVE_BYTES)
    if not 0 < source["size_bytes"] <= limit:
        raise SampleDataError("Pinned download size exceeds byte limit")
    started = time.monotonic()
    content = bytearray()
    request = urllib.request.Request(source["url"], headers={"User-Agent": "AdventureWorks-local-audit/1"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            final = urllib.parse.urlsplit(response.geturl())
            if final.scheme != "https" or final.hostname not in (
                "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
            ):
                raise SampleDataError("Download redirected outside official GitHub HTTPS assets")
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) != source["size_bytes"]:
                raise SampleDataError("Download Content-Length does not match pinned byte count")
            while True:
                chunk = response.read1(min(65536, limit + 1 - len(content)))
                content.extend(chunk)
                if len(content) > limit:
                    raise SampleDataError("Download exceeds byte limit")
                if time.monotonic() - started > 120:
                    raise SampleDataError("Download exceeds 120-second time limit")
                if not chunk:
                    break
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SampleDataError(f"Official sample download failed: {exc}") from exc
    _verify(content, source, "Download")
    archive.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(archive, content)


def _read_tables(archive, manifest):
    source = manifest["source"]
    limit = min(source["max_download_bytes"], MAX_ARCHIVE_BYTES)
    if archive.stat().st_size > limit:
        raise SampleDataError("Archive exceeds byte limit")
    with archive.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise SampleDataError("Archive exceeds byte limit")
    _verify(content, source, "Archive")
    tables = {}
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zipped:
            infos = zipped.infolist()
            if len(infos) > 128 or sum(i.file_size for i in infos) > MAX_EXPANDED_BYTES:
                raise SampleDataError("ZIP exceeds member count or expanded byte limit")
            names = set()
            for info in infos:
                name = info.filename
                if (
                    name in names or "/" in name or "\\" in name or ":" in name
                    or name in (".", "..") or info.is_dir()
                    or stat.S_ISLNK(info.external_attr >> 16)
                    or info.flag_bits & 1
                    or info.file_size > MAX_MEMBER_BYTES
                    or info.file_size > max(1, info.compress_size) * 1000
                ):
                    raise SampleDataError(f"Unsafe, duplicate or oversized ZIP member: {name}")
                names.add(name)
            for name, expected in manifest["members"].items():
                if name not in TABLE_WIDTHS and name not in ("instawdbdw.sql", "DimCurrency.csv"):
                    raise SampleDataError(f"Manifest member is not in the nonpersonal input allow-list: {name}")
                if name not in names:
                    raise SampleDataError(f"Missing ZIP member: {name}")
                if zipped.getinfo(name).file_size != expected["size_bytes"]:
                    raise SampleDataError(f"{name}: byte count does not match manifest")
                with zipped.open(name) as stream:
                    data = stream.read(MAX_MEMBER_BYTES + 1)
                _verify(data, expected, name)
                if name.endswith(".csv"):
                    tables[name] = list(csv.reader(
                        io.StringIO(data.decode("utf-8")), delimiter="|", quoting=csv.QUOTE_NONE
                    ))
    except (zipfile.BadZipFile, UnicodeError, RuntimeError, NotImplementedError) as exc:
        raise SampleDataError(f"Invalid sample ZIP: {exc}") from exc
    return tables


def _integer(value, label):
    if not re.fullmatch(r"0|[1-9][0-9]*", value):
        raise SampleDataError(f"{label}: expected canonical nonnegative integer")


def _money(value, label):
    if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)?\.[0-9]{4}", value):
        raise SampleDataError(f"{label}: expected exact four-place SQL money text")
    amount = Decimal(value)
    if not Decimal("-922337203685477.5808") <= amount <= Decimal("922337203685477.5807"):
        raise SampleDataError(f"{label}: exceeds SQL money range")
    return amount


def _project(tables, manifest):
    widths = dict(TABLE_WIDTHS)
    if "currency_filter" in manifest or "DimCurrency.csv" in tables:
        widths["DimCurrency.csv"] = 3
    for name, width in widths.items():
        if name not in tables:
            raise SampleDataError(f"Missing required table: {name}")
        rows = tables[name]
        if not rows or len(rows) != manifest["members"][name]["rows"]:
            raise SampleDataError(f"{name}: empty table or unexpected row count")
        if any(len(row) != width for row in rows):
            raise SampleDataError(f"{name}: unexpected column count (expected {width})")
    dimensions = {}
    for name, column in (("DimDate.csv", 1), ("DimProduct.csv", 5), ("DimSalesTerritory.csv", 2)):
        lookup = {}
        for row in tables[name]:
            _integer(row[0], f"{name} key")
            if row[0] in lookup:
                raise SampleDataError(f"{name}: duplicate surrogate key {row[0]}")
            value = row[column]
            if not value.strip() or any(ord(char) < 32 for char in value):
                raise SampleDataError(f"{name}: missing or invalid projected label")
            if name == "DimDate.csv":
                try:
                    parsed = date.fromisoformat(value)
                except ValueError as exc:
                    raise SampleDataError("DimDate: invalid ISO date") from exc
                if parsed.isoformat() != value or parsed.strftime("%Y%m%d") != row[0]:
                    raise SampleDataError("DimDate: DateKey and FullDateAlternateKey disagree")
            lookup[row[0]] = value
        dimensions[name] = lookup
    dates = dimensions["DimDate.csv"]
    products = dimensions["DimProduct.csv"]
    territories = dimensions["DimSalesTerritory.csv"]
    projected, line_keys, order_conventions = [], set(), {}
    for number, row in enumerate(tables["FactInternetSales.csv"], 1):
        label = f"FactInternetSales row {number}"
        for column in (0, 1, 6, 7, 9, 11):
            _integer(row[column], label)
        for key, lookup, table in (
            (row[0], products, "DimProduct"), (row[1], dates, "DimDate"),
            (row[7], territories, "DimSalesTerritory"),
        ):
            if key not in lookup:
                raise SampleDataError(f"{label}: missing {table} key {key}")
        order_date = dates[row[1]]
        if row[23] != order_date + " 00:00:00.000":
            raise SampleDataError(f"{label}: OrderDate does not match midnight OrderDateKey")
        if not re.fullmatch(r"SO[0-9]+", row[8]) or int(row[9]) < 1:
            raise SampleDataError(f"{label}: invalid order number or line number")
        key = (row[8], row[9])
        if key in line_keys:
            raise SampleDataError(f"{label}: duplicate order-line key")
        line_keys.add(key)
        convention = (order_date, row[7], row[6])
        if row[8] in order_conventions and order_conventions[row[8]] != convention:
            raise SampleDataError(f"{label}: inconsistent date, territory or currency within order")
        order_conventions[row[8]] = convention
        amounts = {i: _money(row[i], label) for i in (12, 13, 16, 17, 18)}
        quantity = int(row[11])
        if quantity < 1 or amounts[12] * quantity != amounts[13] or amounts[16] * quantity != amounts[17]:
            raise SampleDataError(f"{label}: inconsistent quantity, extended amount or cost")
        # The pinned sample has zero discounts; do not reinterpret SQL float discounts.
        if row[14] != "0.0" or row[15] != "0.0" or amounts[18] != amounts[13]:
            raise SampleDataError(f"{label}: expected undiscounted source money convention")
        projected.append((
            order_date, row[8], row[0], products[row[0]], row[7],
            territories[row[7]], row[18], row[17],
        ))
    return projected


def _summary(rows):
    return {
        "rows": len(rows),
        "orders": len({r[1] for r in rows}),
        "products": len({r[2] for r in rows}),
        "territories": len({r[4] for r in rows}),
        "min_order_date": min(r[0] for r in rows),
        "max_order_date": max(r[0] for r in rows),
        "sales_amount": str(sum((Decimal(r[6]) for r in rows), Decimal("0.0000"))),
        "total_product_cost": str(sum((Decimal(r[7]) for r in rows), Decimal("0.0000"))),
    }


def _filter_currency(rows, tables, manifest):
    scope = {
        "applied": False, "input_fact_rows": len(rows),
        "output_fact_rows": len(rows), "excluded_fact_rows": 0,
    }
    selection = manifest.get("currency_filter")
    if selection is None:
        return rows, scope
    currencies = {}
    for row in tables["DimCurrency.csv"]:
        _integer(row[0], "DimCurrency key")
        if row[0] in currencies or not re.fullmatch(r"[A-Z]{3}", row[1]) or not row[2].strip():
            raise SampleDataError("DimCurrency: duplicate key or invalid currency identity")
        currencies[row[0]] = (row[1], row[2])
    if currencies.get(selection["key"]) != (selection["code"], selection["name"]):
        raise SampleDataError("Selected currency key/code/name does not match verified DimCurrency")
    for row in tables["FactInternetSales.csv"]:
        if row[6] not in currencies:
            raise SampleDataError(f"FactInternetSales: missing DimCurrency key {row[6]}")
    selected = [
        projected for projected, source in zip(rows, tables["FactInternetSales.csv"])
        if source[6] == selection["key"]
    ]
    if not selected:
        raise SampleDataError("Selected currency has no Internet Sales rows")
    return selected, {
        **scope, "applied": True, "currency": selection,
        "output_fact_rows": len(selected), "excluded_fact_rows": len(rows) - len(selected),
        "sql_predicate": f"[fis].[CurrencyKey] = {selection['key']}",
        "evidence": "CurrencyKey, CurrencyAlternateKey and CurrencyName verified against pinned "
                    "official DimCurrency.csv; all source fact currency joins validated.",
    }


def _audit(rows, tables, manifest, manifest_path, scope):
    output = _summary(rows)
    for key, expected in manifest.get("expected_output", {}).items():
        if output.get(key) != expected:
            raise SampleDataError(f"Output {key} does not match pinned expectation")
    monthly = defaultdict(list)
    yearly = defaultdict(list)
    for row in rows:
        monthly[row[0][:7]].append(row)
        yearly[row[0][:4]].append(row)
    months = {}
    for month, month_rows in sorted(monthly.items()):
        year, month_number = map(int, month.split("-"))
        days = calendar.monthrange(year, month_number)[1]
        observed = {r[0] for r in month_rows}
        missing = [
            date(year, month_number, day).isoformat()
            for day in range(1, days + 1)
            if date(year, month_number, day).isoformat() not in observed
        ]
        boundary = month in (output["min_order_date"][:7], output["max_order_date"][:7])
        partial = boundary and (
            min(observed) != f"{month}-01" or max(observed) != f"{month}-{days:02}"
        )
        months[month] = {
            **_summary(month_rows),
            "calendar_days": days,
            "active_days": len(observed),
            "dates_without_fact_rows": missing,
            "status": "partial_boundary" if partial else "observed_not_certified",
        }
    periods = []
    selected_facts = [
        row for row in tables["FactInternetSales.csv"]
        if not scope["applied"] or row[6] == scope["currency"]["key"]
    ]
    money_attestation = (
        f"Monetary scope is the verified CurrencyKey {scope['currency']['key']} "
        f"({scope['currency']['code']} / {scope['currency']['name']}) subset. "
        "Source monetary values are preserved without FX conversion; "
        "currency identity does not certify production accounting completeness."
        if scope["applied"] else
        "Monetary totals are source-unit experiments across multiple CurrencyKey values, "
        "not certified financial amounts; reporting denomination is unverified and "
        "no FX conversion is performed."
    )
    for period in manifest.get("demonstration_periods", []):
        start, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
        if not output["min_order_date"] < start.isoformat() <= end.isoformat() < output["max_order_date"]:
            raise SampleDataError("Demonstration periods must be interior to the sample snapshot")
        selected = [r for r in rows if start.isoformat() <= r[0] <= end.isoformat()]
        calendar_dates = {
            (start + timedelta(days=offset)).isoformat()
            for offset in range((end - start).days + 1)
        }
        if {r[0] for r in selected} != calendar_dates:
            raise SampleDataError("Reviewed demonstration period lacks daily activity")
        periods.append({
            **period, **_summary(selected),
            "interval_convention": "inclusive start and end",
            "calendar_days": len(calendar_dates), "active_days": len(calendar_dates),
            "completeness": "reviewed_official_sample_interior_period_assumption",
            "production_certified": False,
        })
    analysis_contract = {}
    if periods:
        by_name = {period["name"]: period for period in periods}
        if len(periods) != 2 or set(by_name) != {"baseline", "comparison"}:
            raise SampleDataError("Analysis coverage requires baseline and comparison demonstration months")
        intervals = {}
        for source_name, output_name in (("baseline", "baseline"), ("comparison", "current")):
            period = by_name[source_name]
            start, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
            if start.day != 1 or (start.year, start.month) != (end.year, end.month) or end.day != calendar.monthrange(end.year, end.month)[1]:
                raise SampleDataError("Analysis coverage requires reviewed full calendar months")
            intervals[output_name] = {
                "start": start.isoformat(), "end": (end + timedelta(days=1)).isoformat(),
            }
        if intervals["baseline"]["end"] != intervals["current"]["start"]:
            raise SampleDataError("Analysis coverage requires contiguous reviewed demonstration months")
        analysis_contract = {
            **intervals,
            "analysis_interval_convention": "[start,end)",
            "coverage": {
                "start": intervals["baseline"]["start"],
                "end": intervals["current"]["end"],
                "attestation": "Reviewed official sample snapshot assumption for the explicitly selected "
                               f"interior full months [{intervals['baseline']['start']},"
                               f"{intervals['current']['end']}), supported by pinned "
                               "source hashes, reviewed daily activity and validated joins/counts; "
                               "not a production data completeness guarantee or data-owner certification. "
                               "Coverage is explicitly selected, not inferred from the maximum fact date. "
                               "No extract watermark, source reconciliation or late-arrival policy is supplied. "
                               + money_attestation,
            },
        }
    return {
        "audit_version": 1,
        "manifest_sha256": hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(),
        "source": manifest["source"],
        "source_tables": {
            name: {**manifest["members"][name], "rows": len(table)}
            for name, table in tables.items()
        },
        "verified_members": manifest["members"],
        "output": {**output, "file": "internet_sales.csv", "columns": list(COLUMNS)},
        "date_dimension": {
            "min_date": min(r[1] for r in tables["DimDate.csv"]),
            "max_date": max(r[1] for r in tables["DimDate.csv"]),
            "distinct_dates": len({r[1] for r in tables["DimDate.csv"]}),
        },
        "validation": {
            "missing_dimension_keys": 0, "duplicate_dimension_keys": 0,
            "duplicate_order_line_keys": 0, "order_date_mismatches": 0,
            "invalid_monetary_values": 0, "dropped_fact_rows": 0,
            "intentionally_filtered_fact_rows": scope["excluded_fact_rows"],
            "missing_currency_keys": 0 if scope["applied"] else None,
            "quantity_cost_and_sales_conventions": "verified",
        },
        "currency_key_row_counts": dict(sorted(Counter(
            r[6] for r in tables["FactInternetSales.csv"]
        ).items())),
        "scope_filter": scope,
        "output_currency_key_row_counts": dict(sorted(Counter(r[6] for r in selected_facts).items())),
        "currency_key_period_row_counts": {
            period["name"]: dict(sorted(Counter(
                r[6] for r in selected_facts
                if period["start"] <= r[23][:10] <= period["end"]
            ).items()))
            for period in periods
        },
        "monetary_interpretation": {
            "label": (
                f"Verified {scope['currency']['code']}-CurrencyKey subset; exact source monetary measures"
                if scope["applied"] else "source-unit experimental totals; not certified financial amounts"
            ),
            "distinct_currency_keys": len({r[6] for r in selected_facts}),
            "source_distinct_currency_keys": len({r[6] for r in tables["FactInternetSales.csv"]}),
            "base_currency_certified": False,
            "currency_conversion_performed": False,
            "evidence": money_attestation,
            "production_gate": "The single-CurrencyKey scope avoids aggregating different currency keys. "
                               "An official key/code/name mapping verifies currency identity, not a general "
                               "base-currency conversion model or production accounting certification. "
                               "Retain sample-snapshot limitations; wider-scope financial comparisons need "
                               "authoritative reporting-currency and conversion evidence.",
            "single_currency_subset_applied": scope["applied"],
        },
        "source_money_without_leading_zero": sum(r[7].startswith(".") for r in rows),
        "months": months,
        "years": {year: _summary(year_rows) for year, year_rows in sorted(yearly.items())},
        "demonstration_periods": periods,
        **analysis_contract,
        "completeness": {
            **manifest.get("completeness_policy", {}),
            "production_certified": False,
            "evidence": "Pinned official snapshot bytes, exact table counts, unique dimension joins, "
                        "order-line uniqueness, source date agreement and calendar activity.",
            "limitations": manifest.get("completeness_policy", {}).get(
                "limitations",
                "Internal consistency is not completeness. No production data-owner certification, "
                "extract watermark, source reconciliation or late-arrival policy is supplied."
            ),
            "boundary_periods_observed": [
                month for month, values in months.items() if values["status"] == "partial_boundary"
            ],
        },
        "conventions": manifest.get("format", {}),
    }


def _prepare_sample_data(manifest_path, artifacts_dir, *, offline):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    artifacts = Path(artifacts_dir)
    archive_name = manifest["source"]["archive_name"]
    if not archive_name or any(char in archive_name for char in ("/", "\\", ":")) or archive_name in (".", ".."):
        raise SampleDataError("Manifest archive_name must be a plain file name")
    archive = artifacts / archive_name
    if offline and not archive.is_file():
        raise SampleDataError(f"Offline mode requires the verified archive: {archive}")
    if not archive.is_file():
        _download(archive, manifest["source"])
    tables = _read_tables(archive, manifest)
    all_rows = _project(tables, manifest)
    source_summary = _summary(all_rows)
    for key, expected in manifest.get("expected_source_output", {}).items():
        if source_summary.get(key) != expected:
            raise SampleDataError(f"Source {key} does not match pinned expectation")
    rows, scope = _filter_currency(all_rows, tables, manifest)
    audit = _audit(rows, tables, manifest, manifest_path, scope)
    audit["source_fact_summary"] = {
        **source_summary,
        "monetary_label": "all-key source-unit experimental totals; not certified financial amounts",
    }
    output = artifacts / "internet_sales.csv"
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerows(rows)
    content = stream.getvalue().encode("utf-8")
    audit["output"]["sha256"] = hashlib.sha256(content).hexdigest()
    config = None
    if "coverage" in audit:
        config = {
            "dataset_id": manifest.get("dataset_id", "local-sample-source-unit-experiment"),
            "csv_sha256": audit["output"]["sha256"],
            "coverage": audit["coverage"], "baseline": audit["baseline"], "current": audit["current"],
            "top_k": 5,
            "limits": {"max_requests": 10, "max_groups": 1000, "max_seconds": 30},
            "view": {"schema": "reporting", "name": "v_internet_sales"},
        }
        audit["analysis_config"] = "analysis-config.json"
    serialized_audit = (json.dumps(audit, indent=2) + "\n").encode("utf-8")
    _write_atomic(output, content)
    _write_atomic(artifacts / "audit.json", serialized_audit)
    if config is not None:
        _write_atomic(
            artifacts / "analysis-config.json",
            (json.dumps(config, indent=2) + "\n").encode("utf-8"),
        )
    return audit


def prepare_sample_data(manifest_path, artifacts_dir, *, offline=False):
    """Acquire/verify a pinned archive and return its privacy-minimized CSV audit.

    Outputs are internet_sales.csv, audit.json and, when reviewed periods are
    configured, analysis-config.json inside artifacts_dir. Existing
    archives are always reverified, never silently replaced on a hash mismatch.
    Failed validation leaves previously verified outputs untouched. Readers must
    compare the CSV SHA256 to audit.output.sha256 before accepting the pair.
    """
    try:
        return _prepare_sample_data(manifest_path, artifacts_dir, offline=offline)
    except SampleDataError:
        raise
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as exc:
        raise SampleDataError(f"Cannot prepare local sample data: {exc}") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "adventureworks-manifest.json")
    parser.add_argument("--artifacts-dir", type=Path, default=ROOT / ".artifacts" / "adventureworks")
    parser.add_argument("--offline", action="store_true", help="Require the cached archive; never use network")
    args = parser.parse_args(argv)
    try:
        audit = prepare_sample_data(args.manifest, args.artifacts_dir, offline=args.offline)
    except SampleDataError as exc:
        print(f"Sample data error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "csv": str(args.artifacts_dir / "internet_sales.csv"),
        "audit": str(args.artifacts_dir / "audit.json"),
        "config": str(args.artifacts_dir / "analysis-config.json") if "analysis_config" in audit else None,
        "output": audit["output"],
        "demonstration_periods": audit["demonstration_periods"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
