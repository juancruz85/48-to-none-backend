"""Safely download and stage a bounded CSV sample from FDB dataset #2.

The source has no merchant or account identifiers. The generated CSV is only
an ingestion probe; source class labels remain in a separate manifest and are
not sent to the application/model.
"""

import argparse
import csv
import hashlib
import json
import random
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
URL = "https://www.kaggle.com/api/v1/datasets/download/mlg-ulb/creditcardfraud?datasetVersionNumber=3"
MAX_ARCHIVE_BYTES = 300 * 1024 * 1024
ARCHIVE = ROOT / "data" / "external" / "fdb-creditcardfraud" / "source.zip"
OUTPUT = ROOT / "data" / "staging" / "fdb-creditcardfraud"
REQUIRED = {"Time", "Amount", "Class"} | {f"V{i}" for i in range(1, 29)}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("existing archive exceeds the 300 MiB safety limit")
        return
    temp = path.with_suffix(path.suffix + ".part")
    temp.unlink(missing_ok=True)
    request = urllib.request.Request(URL, headers={"User-Agent": "48-to-none bounded dataset importer"})
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=30) as response, temp.open("wb") as output:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_ARCHIVE_BYTES:
                    raise ValueError("download exceeded the 300 MiB safety limit; aborted")
                output.write(block)
        if total == 0:
            raise ValueError("download returned an empty archive")
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.replace(path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def stage(archive, output, per_class=100, seed=4801):
    if per_class < 1:
        raise ValueError("per-class sample size must be positive")
    output = output.resolve()
    protected = (ROOT / "purchase_data").resolve()
    if output == protected or protected in output.parents:
        raise ValueError("staging output must not be inside purchase_data/")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty output folder: {output}")
    if not zipfile.is_zipfile(archive):
        raise ValueError("download is not a valid ZIP archive")

    rng = random.Random(seed)
    selected = {0: [], 1: []}
    seen = {0: 0, 1: 0}
    with zipfile.ZipFile(archive) as bundle:
        bad_member = bundle.testzip()
        if bad_member:
            raise ValueError(f"ZIP CRC check failed for {bad_member}")
        csv_names = [name for name in bundle.namelist() if name.lower().endswith(".csv")]
        if len(csv_names) != 1:
            raise ValueError(f"expected one CSV in archive, found {len(csv_names)}")
        source_name = csv_names[0]
        with bundle.open(source_name) as binary, __import__("io").TextIOWrapper(binary, encoding="utf-8", newline="") as text:
            reader = csv.DictReader(text)
            missing = REQUIRED - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"source CSV missing required columns: {sorted(missing)}")
            for row in reader:
                label = int(row["Class"])
                if label not in selected:
                    raise ValueError(f"unexpected class label: {label}")
                seen[label] += 1
                bucket = selected[label]
                item = (float(row["Time"]), float(row["Amount"]))
                if len(bucket) < per_class:
                    bucket.append(item)
                else:
                    position = rng.randrange(seen[label])
                    if position < per_class:
                        bucket[position] = item

    if any(len(selected[label]) != per_class for label in (0, 1)):
        raise ValueError("source does not contain enough rows for both classes")
    records = [(t, amount, label) for label, rows in selected.items() for t, amount in rows]
    records.sort(key=lambda item: item[0])
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "balanced_sample.csv"
    labels = {}
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Date", "Description", "Amount"])
        writer.writeheader()
        for output_row, (seconds, amount, label) in enumerate(records):
            date = datetime(2013, 9, 1) + timedelta(seconds=seconds)
            writer.writerow({"Date": date.isoformat(sep=" "), "Description": "Card transaction", "Amount": -abs(amount)})
            labels[str(output_row)] = label
    (output / "labels.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")
    manifest = {
        "dataset": "FDB #2 / Kaggle mlg-ulb/creditcardfraud, version 3",
        "source_file": source_name,
        "source_sha256": sha256(archive),
        "license": "Open Database Contents License (per FDB source metadata)",
        "source_rows_by_class": {str(k): v for k, v in seen.items()},
        "sample_rows_by_class": {str(k): len(v) for k, v in selected.items()},
        "seed": seed,
        "sample_csv": csv_path.name,
        "sample_sha256": sha256(csv_path),
        "labels_file": "labels.json (kept out of model input)",
        "limitations": [
            "No account or merchant identifiers; rows are not personal transaction histories.",
            "PCA features are omitted because the app accepts date, description, and amount only.",
            "Class-stratified sampling changes prevalence; this is not an accuracy benchmark.",
            "Time is represented as seconds after 2013-09-01; the source has no calendar date.",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--per-class", type=int, default=100)
    parser.add_argument("--seed", type=int, default=4801)
    args = parser.parse_args()
    download(args.archive)
    report = stage(args.archive, args.output, args.per_class, args.seed)
    print(f"Staged {sum(report['sample_rows_by_class'].values())} rows at {args.output}")
    print("The CSV omits Class labels and PCA features; labels are stored separately.")
    print("This balanced, aggregate sample is for pipeline inspection, not model accuracy.")


if __name__ == "__main__":
    main()
