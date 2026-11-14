"""Create a small, isolated app-format sample from Kaggle's simulated data.

The source has no fraud labels. This adapter is for ingestion and behavioral
checks only; its output must stay outside purchase_data/.
"""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = PROJECT_ROOT / "data" / "external" / "simulated-transactions" / "transactions.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "staging" / "simulated-transactions"
REQUIRED = {"CUST_ID", "DATE", "EXP_TYPE", "AMOUNT"}


def prepare(source: Path, output: Path, customer_limit: int, rows_per_customer: int):
    if customer_limit < 1 or rows_per_customer < 1:
        raise ValueError("customer and row limits must be positive")
    source = source.resolve()
    output = output.resolve()
    production = (PROJECT_ROOT / "purchase_data").resolve()
    if output == production or production in output.parents:
        raise ValueError("output must not be inside purchase_data/")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output folder is not empty: {output}")

    output.mkdir(parents=True, exist_ok=True)
    selected = {}
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or ())
        missing = REQUIRED - fields
        if missing:
            raise ValueError(f"source is missing expected columns: {sorted(missing)}")
        for row in reader:
            customer = (row.get("CUST_ID") or "").strip()
            if not customer:
                continue
            if customer not in selected:
                if len(selected) >= customer_limit:
                    # Kaggle v1's published generator writes each customer's
                    # transactions together. Seeing the next ID means the
                    # selected prefix customers are complete; stop reading.
                    break
                selected[customer] = []
            rows = selected[customer]
            if len(rows) < rows_per_customer:
                rows.append(row)

    entries = []
    for index, (customer, rows) in enumerate(selected.items(), start=1):
        if not rows:
            continue
        safe_id = hashlib.sha256(customer.encode("utf-8")).hexdigest()[:12]
        target = output / f"customer_{index:03}_{safe_id}.csv"
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["Date", "Description", "Amount"])
            writer.writeheader()
            for row in rows:
                amount = float(row["AMOUNT"])
                if not math.isfinite(amount):
                    raise ValueError(f"non-finite amount for source customer {safe_id}")
                # The app interprets Description-formatted bank CSV amounts as
                # outflows (negative) and normalizes spending to positive.
                writer.writerow({"Date": row["DATE"], "Description": row["EXP_TYPE"], "Amount": -abs(amount)})
        entries.append({"file": target.name, "source_customer_id_sha256_prefix": safe_id, "rows": len(rows)})

    manifest = {
        "source": "Kaggle conorsully1/simulated-transactions, version 1",
        "source_file": source.name,
        "source_sha256": _sha256(source),
        "license": "CC0: Public Domain (per Kaggle dataset metadata)",
        "purpose": "ingestion and behavioral checks only; no fraud labels",
        "limits": {"customers": customer_limit, "rows_per_customer": rows_per_customer},
        "customers_written": len(entries),
        "sheets": entries,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--customers", type=int, default=1)
    parser.add_argument("--rows-per-customer", type=int, default=10)
    args = parser.parse_args()
    report = prepare(args.source, args.output, args.customers, args.rows_per_customer)
    print(f"Prepared {report['customers_written']} customer sheets in {args.output}")
    print("These unlabeled synthetic records are for ingestion checks, not fraud accuracy.")


if __name__ == "__main__":
    main()
