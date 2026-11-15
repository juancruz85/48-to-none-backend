"""Download FDB #4 and stage small account histories with labels kept separate.

Only synthetic merchant/category/date/amount fields enter the app CSV. Card
numbers, names, addresses, and source fraud labels stay outside model input.
"""

import argparse
import csv
import hashlib
import json
import random
import sys
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
URL = "https://www.kaggle.com/api/v1/datasets/download/kartik2112/fraud-detection?datasetVersionNumber=1"
MAX_ARCHIVE_BYTES = 400 * 1024 * 1024
ARCHIVE = ROOT / "data" / "external" / "fdb-sparkov" / "source.zip"
OUTPUT = ROOT / "data" / "staging" / "fdb-sparkov"
REQUIRED = {"trans_date_trans_time", "cc_num", "merchant", "category", "amt", "is_fraud"}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.stat().st_size > MAX_ARCHIVE_BYTES or not zipfile.is_zipfile(path):
            raise ValueError("existing archive is invalid or exceeds the 400 MiB limit")
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
                    raise ValueError("download exceeded 400 MiB; aborted")
                output.write(block)
        if total == 0 or not zipfile.is_zipfile(temp):
            raise ValueError("download is empty or not a ZIP archive")
        with zipfile.ZipFile(temp) as bundle:
            bad = bundle.testzip()
            if bad:
                raise ValueError(f"ZIP CRC check failed for {bad}")
        temp.replace(path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _members(bundle):
    names = {Path(name).name.lower(): name for name in bundle.namelist() if name.lower().endswith(".csv")}
    train = names.get("fraudtrain.csv")
    test = names.get("fraudtest.csv")
    if not train or not test:
        raise ValueError(f"expected fraudTrain.csv and fraudTest.csv, found {sorted(names)}")
    return train, test


def _rows(bundle, member):
    with bundle.open(member) as raw:
        import io
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{Path(member).name} missing required columns: {sorted(missing)}")
        yield from reader


def _app_row(row):
    merchant = (row.get("merchant") or "Unknown merchant").strip()
    if merchant.casefold().startswith("fraud_"):
        merchant = merchant[6:]
    category = (row.get("category") or "unknown category").strip()
    amount = float(row["amt"])
    if amount < 0 or not (amount == amount and abs(amount) != float("inf")):
        raise ValueError("source amount is invalid")
    return {
        "Date": row["trans_date_trans_time"],
        "Description": f"{merchant} ({category})",
        "Amount": -amount,
    }


def stage(archive, output, history_rows=25, fraud_cases=2, seed=4804):
    if history_rows < 3 or fraud_cases < 1:
        raise ValueError("history_rows must be at least 3 and fraud_cases positive")
    output = output.resolve()
    protected = (ROOT / "purchase_data").resolve()
    if output == protected or protected in output.parents:
        raise ValueError("output must not be inside purchase_data/")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty output folder: {output}")

    rng = random.Random(seed)
    with zipfile.ZipFile(archive) as bundle:
        train_member, test_member = _members(bundle)
        stats = defaultdict(lambda: [0, 0])
        for row in _rows(bundle, train_member):
            card = row["cc_num"]
            stats[card][0] += 1
            stats[card][1] += int(row["is_fraud"])

        fraud_targets = {}
        clean_targets = {}
        for row in _rows(bundle, test_member):
            card = row["cc_num"]
            history = stats.get(card)
            if not history or history[0] < history_rows or history[1] != 0:
                continue
            label = int(row["is_fraud"])
            if label == 1:
                fraud_targets.setdefault(card, row)
            elif label == 0:
                clean_targets.setdefault(card, row)

        if len(fraud_targets) < fraud_cases or not clean_targets:
            raise ValueError(
                f"not enough eligible accounts: fraud={len(fraud_targets)}, clean={len(clean_targets)}"
            )
        selected_fraud_cards = rng.sample(sorted(fraud_targets), fraud_cases)
        selected_clean_card = rng.choice(sorted(clean_targets))
        targets = {card: fraud_targets[card] for card in selected_fraud_cards}
        targets[selected_clean_card] = clean_targets[selected_clean_card]

        histories = defaultdict(list)
        for row in _rows(bundle, train_member):
            card = row["cc_num"]
            if card in targets:
                histories[card].append(row)

    output.mkdir(parents=True, exist_ok=True)
    import pandas as pd
    from src.datasheet import irregular, prepare

    label_manifest = {}
    account_manifest = []
    candidate_report = []
    fraud_written = clean_written = 0
    for index, (card, target) in enumerate(targets.items(), start=1):
        target_time = datetime.strptime(target["trans_date_trans_time"], "%Y-%m-%d %H:%M:%S")
        prior = [
            row for row in histories[card]
            if datetime.strptime(row["trans_date_trans_time"], "%Y-%m-%d %H:%M:%S") < target_time
        ]
        prior.sort(key=lambda row: row["trans_date_trans_time"])
        prior = prior[-history_rows:]
        if len(prior) < history_rows:
            raise ValueError(f"selected account had only {len(prior)} prior rows")
        records = prior + [target]
        app_rows = [_app_row(row) for row in records]
        prepared = prepare(pd.DataFrame(app_rows))
        found = irregular(prepared)
        target_row = len(prepared) - 1
        target_candidate = any(item["row"] == target_row for item in found)
        label = int(target["is_fraud"])
        group = "fraud" if label else "clean"
        group_index = (fraud_written + 1) if label else (clean_written + 1)
        if label:
            fraud_written += 1
        else:
            clean_written += 1
        filename = f"{group}_{group_index:02}.csv"
        with (output / filename).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["Date", "Description", "Amount"])
            writer.writeheader()
            writer.writerows(app_rows)
        label_manifest[filename] = [0] * history_rows + [label]
        account_manifest.append({
            "file": filename,
            "history_rows": history_rows,
            "target_label": label,
            "target_candidate_from_current_heuristic": target_candidate,
            "heuristic_candidate_count": len(found),
        })
        candidate_report.append((filename, label, target_candidate, len(found)))

    (output / "evaluation_labels.json").write_text(json.dumps(label_manifest, indent=2), encoding="utf-8")
    manifest = {
        "dataset": "FDB #4 / Kaggle kartik2112/fraud-detection, version 1",
        "source_files": [Path(train_member).name, Path(test_member).name],
        "source_sha256": sha256(archive),
        "license": "CC0: Public Domain (per FDB source metadata)",
        "seed": seed,
        "history_rows_per_account": history_rows,
        "accounts": account_manifest,
        "labels_file": "evaluation_labels.json (never included in model input)",
        "limitations": [
            "Synthetic data; results do not establish performance on real cardholders.",
            "Only source training history labeled clean and held-out test targets are used.",
            "Personal names, card numbers, addresses, and source fraud labels are omitted from CSVs.",
            "Fraud-prefixed merchant strings are stripped to avoid a direct label cue.",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest, candidate_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--history-rows", type=int, default=25)
    parser.add_argument("--fraud-cases", type=int, default=2)
    parser.add_argument("--seed", type=int, default=4804)
    args = parser.parse_args()
    download(args.archive)
    report, candidates = stage(args.archive, args.output, args.history_rows, args.fraud_cases, args.seed)
    print(f"Staged {len(report['accounts'])} account CSVs under {args.output}")
    for filename, label, candidate, count in candidates:
        print(f"{filename}: target_class={label}, heuristic_candidate={candidate}, candidates={count}")
    print("Source labels are separate from model input; data is synthetic and not a real-world accuracy test.")


if __name__ == "__main__":
    main()
