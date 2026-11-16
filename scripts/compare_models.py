"""Run two local models through the same backend flow and compare their verdicts.

Each model runs in its own process so only one is in memory at a time:

    python -m scripts.compare_models --model microsoft/Phi-4-mini-instruct
    python -m scripts.compare_models --model Qwen/Qwen2.5-3B-Instruct
    python -m scripts.compare_models --summarize

Nothing about the backend changes between runs except model.MODEL_ID: the same shortlist
(D_analyze), the same prompts and the same parsing (model.respond, model.review_patterns).

Labeled inputs:
- the 8-trial profile experiment (scripts/profile_model_experiment.py): the planted fraud is the
  2026-01-10 purchase in each fraud account.
- sample_uploads/: every APPLE.COM/BILL charge is planted, everything else is a normal purchase.
- designed cases (generated here): one year of ordinary spending plus one event that reaches the
  shortlist. Half the events are normal on purpose (a second coffee, a big grocery shop, a group
  dinner, a day out) so a model that calls everything fraud is caught.
- Sparkov (Fraud Dataset Benchmark #4): whole card histories with the source's own fraud labels.
  Needs the archive from scripts/prepare_fdb_sparkov.py; skipped when it is not there.
purchase_data/ has no labels, so it only counts towards how often the two models agree.
"""

import argparse
import csv
import json
import random
import re
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import prepare_fdb_sparkov as sparkov
from scripts import profile_model_experiment as experiment
from src import managerdaemon as MD
from src import model

OUTPUT_DIR = PROJECT_ROOT / "logs" / "model-compare"
PLANTED_DATE = "2026-01-10"
PLANTED_SELLER = "apple.com/bill"
DESIGNED_ROOT = PROJECT_ROOT / "data" / "staging" / "profile-model-experiment-designed"
SPARKOV_ROOT = PROJECT_ROOT / "data" / "staging" / "fdb-sparkov-compare"
SPARKOV_HISTORY = 400

# event name -> (is it fraud, the purchases added on the event day as (seller, amount or multiple of usual))
USUAL = {"Grocery store": 62.0, "Corner coffee": 5.25, "Gas station": 41.0, "Family restaurant": 36.0}
EVENTS = {
    "second_coffee": (False, [("Corner coffee", 5.25), ("Corner coffee", 5.25)]),
    "two_cinema_tickets": (False, [("Cinema ticket", 12.5), ("Cinema ticket", 12.5)]),
    "parking_twice": (False, [("City parking", 3.0), ("City parking", 3.0)]),
    "holiday_groceries": (False, [("Grocery store", ("x", 2.15, 2.45))]),
    "group_dinner": (False, [("Family restaurant", ("x", 2.2, 2.7))]),
    "day_out": (False, [("Museum cafe", 9.4), ("Souvenir shop", 14.0), ("Ice cream stand", 6.5), ("Bookshop", 17.9)]),
    "huge_grocery_charge": (True, [("Grocery store", ("x", 5.5, 8.0))]),
    "huge_gas_charge": (True, [("Gas station", ("x", 6.0, 9.0))]),
    "rent_charged_twice": (True, [("Parkside rent", 1200.0), ("Parkside rent", 1200.0)]),
    "phone_bill_three_times": (True, [("Mobile phone bill", 45.0)] * 3),
    "card_testing": (True, [("Online gift cards", 1.0)] * 4 + [("Online gift cards", 200.0)]),
    "spending_spree": (True, [("Electronics outlet", 899.0), ("Jewelry store", 640.0), ("Online gift cards", 500.0),
                              ("Luxury watches", 1150.0)]),
}


def _slug(model_id):
    return re.sub(r"[^a-z0-9]+", "-", model_id.lower()).strip("-")


def _key(day, item, amount):
    return (str(day)[:10], " ".join(str(item).casefold().split()), round(float(amount), 2))


def _labeled(fraud_keys):
    keys = {tuple(key) for key in fraud_keys}
    return lambda purchase: _key(purchase["date"], purchase["item"], purchase["amount"]) in keys


def prepare_designed():
    """One sheet per event and seed. The event falls on 2026-01-17, after a year of ordinary spending."""
    DESIGNED_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = []
    event_day = date(2026, 1, 17)
    for name, (fraud, added) in EVENTS.items():
        for seed in (1, 2, 3):
            rng = random.Random(f"{name}-{seed}")
            rows = []
            for month in range(1, 13):
                rows.append([date(2025, month, 1), "Parkside rent", 1200.0])
                rows.append([date(2025, month, 3), "Mobile phone bill", 45.0])
                for day in (5, 12, 19, 26):
                    rows.append([date(2025, month, day), "Grocery store", round(62 * rng.uniform(0.8, 1.2), 2)])
                for day in rng.sample(range(2, 28), 8):
                    rows.append([date(2025, month, day), "Corner coffee", 5.25])
                for day in (9, 23):
                    rows.append([date(2025, month, day), "Gas station", round(41 * rng.uniform(0.85, 1.15), 2)])
                for day in (14, 27):
                    rows.append([date(2025, month, day), "Family restaurant", round(36 * rng.uniform(0.75, 1.25), 2)])
                if month % 2 == 0:
                    rows.append([date(2025, month, 20), "Cinema ticket", 12.5])
                    rows.append([date(2025, month, 21), "City parking", 3.0])
            fraud_keys = []
            for seller, amount in added:
                if isinstance(amount, tuple):
                    amount = round(USUAL[seller] * rng.uniform(amount[1], amount[2]), 2)
                rows.append([event_day, seller, amount])
                if fraud:
                    fraud_keys.append(_key(event_day, seller, amount))
            filename = f"{name}_{seed}.csv"
            with (DESIGNED_ROOT / filename).open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Date", "Description", "Amount"])
                writer.writerows([day.isoformat(), seller, -amount] for day, seller, amount in sorted(rows))
            manifest.append({"file": filename, "event": name, "fraud": fraud, "fraud_keys": fraud_keys})
    (DESIGNED_ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def prepare_sparkov(fraud_cards=6, clean_cards=3, seed=4804):
    """Whole card histories from the Sparkov training file: the purchases up to and through a card's first
    run of fraud, or the latest purchases of a card with no fraud. Labels stay in the manifest."""
    SPARKOV_ROOT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(sparkov.ARCHIVE) as bundle:
        member, _ = sparkov._members(bundle)
        counts = {}
        for row in sparkov._rows(bundle, member):
            total = counts.setdefault(row["cc_num"], [0, 0])
            total[0] += 1
            total[1] += int(row["is_fraud"])
        rng = random.Random(seed)
        enough = sorted(card for card, (rows, _) in counts.items() if rows >= SPARKOV_HISTORY + 50)
        chosen = (rng.sample([card for card in enough if counts[card][1]], fraud_cards)
                  + rng.sample([card for card in enough if not counts[card][1]], clean_cards))
        histories = {card: [] for card in chosen}
        for row in sparkov._rows(bundle, member):
            if row["cc_num"] in histories:
                histories[row["cc_num"]].append(row)

    manifest = []
    for number, card in enumerate(chosen, start=1):
        rows = sorted(histories[card], key=lambda row: row["trans_date_trans_time"])
        frauds = [index for index, row in enumerate(rows) if row["is_fraud"] == "1"]
        if frauds:
            first = frauds[0]
            started = datetime.fromisoformat(rows[first]["trans_date_trans_time"])
            last = max(index for index in frauds
                       if datetime.fromisoformat(rows[index]["trans_date_trans_time"]) - started <= timedelta(days=14))
            rows = rows[max(0, first - SPARKOV_HISTORY):last + 21]
        else:
            rows = rows[-(SPARKOV_HISTORY + 20):]
        filename = f"card_{number:02d}_{'fraud' if frauds else 'clean'}.csv"
        fraud_keys = []
        with (SPARKOV_ROOT / filename).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["Date", "Description", "Amount"])
            writer.writeheader()
            for row in rows:
                app_row = sparkov._app_row(row)
                writer.writerow(app_row)
                if row["is_fraud"] == "1":
                    fraud_keys.append(_key(app_row["Date"], app_row["Description"], -app_row["Amount"]))
        manifest.append({"file": filename, "rows": len(rows), "fraud_rows": len(fraud_keys), "fraud_keys": fraud_keys})
    (SPARKOV_ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def inputs():
    """Every sheet to check: (group, name, path, is_fraud(purchase) or None, is_bad_seller(item) or None)."""
    manifest_path = experiment.DATA_ROOT / "experiment-manifest.json"
    if not manifest_path.is_file():
        experiment.prepare_experiment()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    found = []
    for trial in manifest["trials"]:
        for account in trial["accounts"]:
            planted = account["name"] in trial["fraud_accounts"]
            found.append((
                "profile_experiment", account["file"], experiment.DATA_ROOT / account["file"],
                lambda purchase, planted=planted: planted and str(purchase["date"])[:10] == PLANTED_DATE,
                lambda item: False,
            ))
    for path in sorted((PROJECT_ROOT / "sample_uploads").glob("*.csv")):
        found.append((
            "sample_uploads", path.name, path,
            lambda purchase: str(purchase["item"]).casefold().strip() == PLANTED_SELLER,
            lambda item: str(item).casefold().strip() == PLANTED_SELLER,
        ))
    for path in sorted((PROJECT_ROOT / "purchase_data").glob("*.csv")):
        found.append(("purchase_data", path.name, path, None, None))

    designed_manifest = DESIGNED_ROOT / "manifest.json"
    designed = json.loads(designed_manifest.read_text(encoding="utf-8")) if designed_manifest.is_file() else prepare_designed()
    for sheet in designed:
        found.append(("designed", sheet["file"], DESIGNED_ROOT / sheet["file"], _labeled(sheet["fraud_keys"]), None))

    sparkov_manifest = SPARKOV_ROOT / "manifest.json"
    if sparkov_manifest.is_file() or sparkov.ARCHIVE.is_file():
        staged = json.loads(sparkov_manifest.read_text(encoding="utf-8")) if sparkov_manifest.is_file() else prepare_sparkov()
        for sheet in staged:
            found.append(("sparkov", sheet["file"], SPARKOV_ROOT / sheet["file"], _labeled(sheet["fraud_keys"]), None))
    return found


def prepare(path):
    sheet = MD.D_createsheet(path)
    MD.D_organize(sheet)
    if sheet.results["vet"]:
        return sheet, sheet.results["vet"]
    MD.D_analyze(sheet)
    return sheet, None


def check(sheet):
    """model.respond and model.review_patterns, unchanged, with every reply and its time recorded."""
    asked = []
    original_ask = model._ask

    def recorded_ask(*args, **kwargs):
        started = time.perf_counter()
        output = original_ask(*args, **kwargs)
        asked.append((output[0]["generated_text"].strip(), round(time.perf_counter() - started, 3)))
        return output

    model._ask = recorded_ask
    try:
        fraud_rows = {flag["row"] for flag in model.respond(sheet)}
        purchase_replies = list(asked)
        asked.clear()
        suspicious_items = {pattern["item"] for pattern in model.review_patterns(sheet)}
        pattern_replies = list(asked)
    finally:
        model._ask = original_ask
    return fraud_rows, purchase_replies, suspicious_items, pattern_replies


def run_model(model_id, dry_run=False):
    model.MODEL_ID = model_id
    report = {"model": model_id, "complete": False, "sheets": []}
    output_path = OUTPUT_DIR / f"{_slug(model_id)}.json"

    if not dry_run:
        started = time.perf_counter()
        pipe = model.load()
        pipe([{"role": "user", "content": "Reply OK."}], max_new_tokens=1, return_full_text=False, do_sample=False)
        report["load_seconds"] = round(time.perf_counter() - started, 1)
        report["device"] = str(pipe.device)
        report["dtype"] = str(pipe.model.dtype)
        report["parameters_billion"] = round(sum(p.numel() for p in pipe.model.parameters()) / 1e9, 2)

    for group, name, path, is_fraud, is_bad_seller in inputs():
        sheet, vet_error = prepare(path)
        entry = {"group": group, "sheet": name, "vet_error": vet_error, "purchases": [], "patterns": []}
        report["sheets"].append(entry)
        if vet_error:
            continue
        purchases = sheet.results["irregular"]
        patterns = sheet.results["patterns"]
        if dry_run:
            print(f"{group}/{name}: {len(purchases)} purchases and {len(patterns)} patterns go to the model")
            continue

        fraud_rows, purchase_replies, suspicious_items, pattern_replies = check(sheet)
        for purchase, (reply, seconds) in zip(purchases, purchase_replies):
            verdict = model.VERDICT.search(reply)
            entry["purchases"].append({
                "row": purchase["row"], "date": str(purchase["date"])[:10], "item": purchase["item"],
                "amount": purchase["amount"], "signals": purchase["signals"],
                "planted": None if is_fraud is None else bool(is_fraud(purchase)),
                "flagged": purchase["row"] in fraud_rows,
                "clear_reply": bool(verdict), "reply": reply, "seconds": seconds,
            })
        for pattern, (reply, seconds) in zip(patterns, pattern_replies):
            verdict = model.PATTERN_VERDICT.search(reply)
            entry["patterns"].append({
                "item": pattern["item"], "charges": pattern["charges"], "rising_charges": pattern["rising_charges"],
                "planted": None if is_bad_seller is None else bool(is_bad_seller(pattern["item"])),
                "flagged": pattern["item"] in suspicious_items,
                "clear_reply": bool(verdict), "reply": reply, "seconds": seconds,
            })
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"{group}/{name}: {len(fraud_rows)} of {len(purchases)} purchases flagged, "
              f"{len(suspicious_items)} of {len(patterns)} patterns suspicious", flush=True)

    if not dry_run:
        report["complete"] = True
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"saved {output_path}")
    return report


def _score(items):
    labeled = [item for item in items if item["planted"] is not None]
    tp = sum(item["planted"] and item["flagged"] for item in labeled)
    fp = sum(not item["planted"] and item["flagged"] for item in labeled)
    fn = sum(item["planted"] and not item["flagged"] for item in labeled)
    tn = sum(not item["planted"] and not item["flagged"] for item in labeled)
    seconds = [item["seconds"] for item in items]
    return {
        "asked": len(items), "labeled": len(labeled), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "unclear_replies": sum(not item["clear_reply"] for item in items),
        "seconds_total": round(sum(seconds), 1),
        "seconds_each": round(sum(seconds) / len(seconds), 2) if seconds else None,
    }


def summarize():
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(OUTPUT_DIR.glob("*.json"))
               if path.name != "summary.json"]
    summary = {"models": {}, "agreement": {}}
    verdicts = {}
    for report in reports:
        groups = {}
        for kind in ("purchases", "patterns"):
            for group in sorted({sheet["group"] for sheet in report["sheets"]}):
                items = [item for sheet in report["sheets"] if sheet["group"] == group for item in sheet[kind]]
                groups[f"{group}/{kind}"] = _score(items)
            groups[f"all/{kind}"] = _score([item for sheet in report["sheets"] for item in sheet[kind]])
        summary["models"][report["model"]] = {
            **{key: report.get(key) for key in ("complete", "load_seconds", "device", "dtype", "parameters_billion")},
            "groups": groups,
        }
        verdicts[report["model"]] = {
            (kind, sheet["group"], sheet["sheet"], item.get("row", item["item"])): item["flagged"]
            for sheet in report["sheets"] for kind in ("purchases", "patterns") for item in sheet[kind]
        }
    if len(verdicts) == 2:
        first, second = verdicts.values()
        shared = sorted(set(first) & set(second), key=str)
        differing = [key for key in shared if first[key] != second[key]]
        summary["agreement"] = {
            "compared": len(shared), "same": len(shared) - len(differing),
            "different": [" | ".join(str(part) for part in key) for key in differing],
        }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--model", help="Hugging Face model id to run through the backend")
    mode.add_argument("--summarize", action="store_true", help="compare the saved runs")
    parser.add_argument("--dry-run", action="store_true", help="count what would go to the model, without loading it")
    args = parser.parse_args()
    if args.summarize:
        summarize()
    else:
        run_model(args.model, dry_run=args.dry_run)
