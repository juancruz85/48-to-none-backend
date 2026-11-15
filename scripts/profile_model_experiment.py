"""Generate/run an 8-trial, three-account profile experiment with Phi."""

import argparse
import csv
import ctypes
import json
import os
import random
import sys
from datetime import date
from pathlib import Path

os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import datasheet as da
from src.profiles import ProfileStore


DATA_ROOT = PROJECT_ROOT / "data" / "staging" / "profile-model-experiment-v2"
RESULT_PATH = PROJECT_ROOT / "logs" / "profile-model-experiment.json"
MIN_FREE_RAM_GB = 8.5

ACCOUNT_NAMES = ("everyday", "car-payment", "cleaning-supplies")
ACCOUNT_FILES = {name: f"{name}.csv" for name in ACCOUNT_NAMES}
PERSONAL_ITEMS = {
    "Video game shop": (39.99, 0.08, 2),
    "Snack shop": (8.50, 0.16, 10),
    "Grocery store": (62.00, 0.12, 20),
}
CAR_ITEM = "Car loan payment"
CAR_AMOUNT = 420.00
CLEANING_ITEM = "Cleaning supplies warehouse"
CLEANING_AMOUNT = 145.00


def _scenarios():
    controls = [
        {"trial_id": "no_fraud_1", "group": "no_fraud_control", "seed": 1101, "fraud_accounts": []},
        {"trial_id": "no_fraud_2", "group": "no_fraud_control", "seed": 1102, "fraud_accounts": []},
        {"trial_id": "all_fraud_1", "group": "all_fraud_control", "seed": 1201, "fraud_accounts": list(ACCOUNT_NAMES)},
        {"trial_id": "all_fraud_2", "group": "all_fraud_control", "seed": 1202, "fraud_accounts": list(ACCOUNT_NAMES)},
    ]
    randomized = [
        {"trial_id": f"random_fraud_{n}", "group": "randomized", "seed": 1300 + n, "fraud_accounts": None}
        for n in range(1, 5)
    ]
    selection_rng = random.Random(9321)
    randomized_account_order = list(ACCOUNT_NAMES)
    selection_rng.shuffle(randomized_account_order)
    for index, scenario in enumerate(randomized):
        account = randomized_account_order[index] if index < len(ACCOUNT_NAMES) else selection_rng.choice(ACCOUNT_NAMES)
        scenario["fraud_accounts"] = [account]
    return controls + randomized


def _account_rows(account_name, fraud, rng):
    rows = []
    if account_name == "everyday":
        for month in range(1, 13):
            for item, (base, spread, day) in PERSONAL_ITEMS.items():
                amount = round(base * rng.uniform(1 - spread, 1 + spread), 2)
                transaction_day = max(1, min(27, day + rng.randint(-2, 2)))
                rows.append([date(2025, month, transaction_day).isoformat(), item, amount])
        if fraud:
            item, (base, _, _) = rng.choice(list(PERSONAL_ITEMS.items()))
            rows.append(["2026-01-10", item, round(base * rng.uniform(5.5, 7.0), 2)])
    elif account_name == "car-payment":
        for month in range(1, 13):
            amount = round(CAR_AMOUNT * rng.uniform(0.985, 1.015), 2)
            rows.append([date(2025, month, rng.randint(5, 9)).isoformat(), CAR_ITEM, amount])
        if fraud:
            rows.append(["2026-01-10", CAR_ITEM, round(CAR_AMOUNT * rng.uniform(4.5, 6.0), 2)])
    else:
        for month in range(1, 13):
            amount = round(CLEANING_AMOUNT * rng.uniform(0.90, 1.10), 2)
            rows.append([date(2025, month, rng.randint(13, 18)).isoformat(), CLEANING_ITEM, amount])
        if fraud:
            rows.append(["2026-01-10", CLEANING_ITEM, round(CLEANING_AMOUNT * rng.uniform(5.0, 7.0), 2)])
    return sorted(rows)


def _make_profile_store():
    store = ProfileStore()
    profile = store.create_profile("synthetic-experiment-user")
    personal = store.create_tag(profile.profile_id, "Personal")
    business = store.create_tag(profile.profile_id, "Cleaning business")
    accounts = {
        "everyday": store.create_account(profile.profile_id, "Everyday purchases", personal.tag_id),
        "car-payment": store.create_account(profile.profile_id, "Car payment", personal.tag_id),
        "cleaning-supplies": store.create_account(profile.profile_id, "Cleaning supplies", business.tag_id),
    }
    return store, profile, {"Personal": personal.tag_id, "Cleaning business": business.tag_id}, accounts


def prepare_experiment():
    if DATA_ROOT.exists() and any(DATA_ROOT.iterdir()):
        raise FileExistsError(f"experiment folder is not empty: {DATA_ROOT}")
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    store, profile, tags, accounts = _make_profile_store()
    scenarios = _scenarios()
    manifest_trials = []

    for scenario in scenarios:
        rng = random.Random(scenario["seed"])
        trial_dir = DATA_ROOT / scenario["trial_id"]
        trial_dir.mkdir()
        for account_name in ACCOUNT_NAMES:
            rows = _account_rows(account_name, account_name in scenario["fraud_accounts"], rng)
            target = trial_dir / ACCOUNT_FILES[account_name]
            with target.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Date", "Item", "Amount (USD)"])
                writer.writerows(rows)
            store.attach_sheet(profile.profile_id, accounts[account_name].account_id,
                               f"{scenario['trial_id']}/{target.name}")

        manifest_trials.append({
            **scenario,
            "accounts": [
                {
                    "name": name,
                    "account_id": accounts[name].account_id,
                    "tag_id": accounts[name].tag_id,
                    "file": f"{scenario['trial_id']}/{ACCOUNT_FILES[name]}",
                }
                for name in ACCOUNT_NAMES
            ],
        })

    manifest = {
        "profile_id": profile.profile_id,
        "tags": {name: tag_id for name, tag_id in tags.items()},
        "account_count": len(accounts),
        "trials": manifest_trials,
        "labels_are_for_scoring_only": "The model runner loads CSV files only, never this manifest.",
    }
    (DATA_ROOT / "experiment-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _free_ram_gb():
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_uint32),
            ("dwMemoryLoad", ctypes.c_uint32),
            ("ullTotalPhys", ctypes.c_uint64),
            ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64),
            ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64),
            ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("could not read available system memory")
    return status.ullAvailPhys / 1024**3


def _write_checkpoint(report):
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = RESULT_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary.replace(RESULT_PATH)


def run_experiment(allow_low_memory=False):
    manifest_path = DATA_ROOT / "experiment-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"prepare the CSVs first: {manifest_path}")
    free_ram = _free_ram_gb()
    if free_ram < MIN_FREE_RAM_GB and not allow_low_memory:
        raise MemoryError(
            f"only {free_ram:.2f} GiB RAM is available; the local model used about 8.2 GiB last run. "
            f"Free at least {MIN_FREE_RAM_GB:.1f} GiB before model inference."
        )

    import pandas as pd
    from src import main, managerdaemon as MD

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    store, profile, _, accounts = _make_profile_store()
    if len(accounts) != manifest["account_count"]:
        raise RuntimeError("profile fixture does not match the prepared manifest")

    trial_results = []
    base_report = {
        "profile_id": profile.profile_id,
        "tag_layout": {"Personal": ["everyday", "car-payment"], "Cleaning business": ["cleaning-supplies"]},
        "model_id": "microsoft/Phi-4-mini-instruct",
        "device": "CPU (the installed PyTorch build is CPU-only)",
        "free_ram_before_run_gib": round(free_ram, 2),
    }
    try:
        for scenario in manifest["trials"]:
            trial_dir = DATA_ROOT / scenario["trial_id"]
            expected = set(scenario["fraud_accounts"])
            for account_name in ACCOUNT_NAMES:
                filename = ACCOUNT_FILES[account_name]
                rows = pd.read_csv(trial_dir / filename)
                if account_name in expected:
                    rows = rows.iloc[:-1]  # seed baseline only from regular history
                account = accounts[account_name]
                store.attach_sheet(profile.profile_id, account.account_id,
                                   f"{scenario['trial_id']}/{filename}")
                store.set_account_baseline(profile.profile_id, account.account_id,
                                           da.baseline(da.prepare(rows)))

            result = main.run(trial_dir)
            actual = set()
            account_results = []

            for account_name in ACCOUNT_NAMES:
                filename = ACCOUNT_FILES[account_name]
                entry = result.get(filename, {}) if result else {}
                fraud_flags = entry.get("fraud") or []
                if fraud_flags:
                    actual.add(account_name)

                account_results.append({
                    "account": account_name,
                    "expected_fraud": account_name in expected,
                    "candidates": len(entry.get("irregular") or []),
                    "model_flagged_count": len(fraud_flags),
                    "model_reasons": [flag.get("reason", "") for flag in fraud_flags],
                    "error": entry.get("error"),
                })

            trial_results.append({
                "trial_id": scenario["trial_id"],
                "group": scenario["group"],
                "expected_fraud_accounts": sorted(expected),
                "model_flagged_accounts": sorted(actual),
                "true_positives": len(expected & actual),
                "false_positives": len(actual - expected),
                "false_negatives": len(expected - actual),
                "accounts": account_results,
            })
            _write_checkpoint({
                **base_report,
                "complete": False,
                "trial_count": len(trial_results),
                "totals": {
                    key: sum(row[key] for row in trial_results)
                    for key in ("true_positives", "false_positives", "false_negatives")
                },
                "trials": trial_results,
            })
            MD.stop_logging()

        totals = {
            key: sum(row[key] for row in trial_results)
            for key in ("true_positives", "false_positives", "false_negatives")
        }
        report = {
            **base_report,
            "complete": True,
            "trial_count": len(trial_results),
            "totals": totals,
            "trials": trial_results,
        }
        _write_checkpoint(report)
        return report
    finally:
        MD.stop_logging()


def print_preflight(manifest):
    import pandas as pd

    print("trial,scenario,expected fraud accounts,baseline candidates")
    for scenario in manifest["trials"]:
        found = []
        for account_name in ACCOUNT_NAMES:
            path = DATA_ROOT / scenario["trial_id"] / ACCOUNT_FILES[account_name]
            purchases = da.irregular(da.prepare(pd.read_csv(path)))
            if purchases:
                found.append(account_name)
        print(f"{scenario['trial_id']},{scenario['group']},{'|'.join(scenario['fraud_accounts']) or 'none'},{'|'.join(found) or 'none'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true", help="generate CSVs and print a heuristic preflight")
    mode.add_argument("--run-model", action="store_true", help="run all 8 scenarios through the local model")
    parser.add_argument("--allow-low-memory", action="store_true",
                        help="run below the 8.5 GiB preflight threshold when explicitly accepted")
    args = parser.parse_args()
    if args.prepare:
        print_preflight(prepare_experiment())
    else:
        report = run_experiment(allow_low_memory=args.allow_low_memory)
        print("trial,scenario,expected fraud,flagged,TP,FP,FN")
        for trial in report["trials"]:
            print(
                f"{trial['trial_id']},{trial['group']},{'|'.join(trial['expected_fraud_accounts']) or 'none'},"
                f"{'|'.join(trial['model_flagged_accounts']) or 'none'},"
                f"{trial['true_positives']},{trial['false_positives']},{trial['false_negatives']}"
            )
        print(f"Aggregate: {report['totals']}")
        print(f"Detailed results: {RESULT_PATH}")
