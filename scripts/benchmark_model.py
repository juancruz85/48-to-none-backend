"""Compare single-purchase and batched inference on the same CSV files.

This loads the real Phi model and can download it on first use. It reports
runtime and call counts plus disagreements; it cannot report accuracy without
human-labeled fraud outcomes.
"""

import argparse
import json
import time
from pathlib import Path

from src import managerdaemon as MD
from src import model


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILES = sorted((PROJECT_ROOT / "purchase_data").glob("*.csv"))


def check_file(path, batch_size):
    sheet = MD.D_createsheet(path)
    MD.D_organize(sheet)
    if sheet.results["vet"]:
        return {
            "file": path.name,
            "error": sheet.results["vet"],
            "candidates": 0,
            "calls": 0,
            "seconds": 0,
            "fraud_rows": [],
        }
    MD.D_analyze(sheet)

    calls = 0
    original_ask = model._ask

    def counted_ask(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_ask(*args, **kwargs)

    model._ask = counted_ask
    started = time.perf_counter()
    try:
        fraud = model.respond(sheet, batch_size=batch_size)
        error = None
    except Exception as failure:
        fraud = []
        error = repr(failure)
    finally:
        model._ask = original_ask
    return {
        "file": path.name,
        "error": error,
        "candidates": len(sheet.results["irregular"]),
        "calls": calls,
        "seconds": round(time.perf_counter() - started, 3),
        "fraud_rows": sorted(item["row"] for item in fraud),
    }


def run(paths, batch_size):
    pipe = model.load()
    # Warm up the pipeline before timing either strategy.
    pipe(
        [{"role": "user", "content": "Reply OK."}],
        max_new_tokens=1,
        return_full_text=False,
        do_sample=False,
    )
    report = {"single": [], "batched": []}
    for path in paths:
        report["single"].append(check_file(path, 1))
    for path in paths:
        report["batched"].append(check_file(path, batch_size))

    for single, batched in zip(report["single"], report["batched"]):
        report.setdefault("comparison", []).append({
            "file": single["file"],
            "single_calls": single["calls"],
            "batched_calls": batched["calls"],
            "call_reduction_percent": round(
                100 * (single["calls"] - batched["calls"]) / single["calls"], 1
            ) if single["calls"] else 0,
            "single_seconds": single["seconds"],
            "batched_seconds": batched["seconds"],
            "single_error": single["error"],
            "batched_error": batched["error"],
            "verdict_disagreements": (
                sorted(set(single["fraud_rows"]) ^ set(batched["fraud_rows"]))
                if single["error"] is None and batched["error"] is None
                else None
            ),
        })
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=model.BATCH_SIZE)
    parser.add_argument("files", nargs="*", type=Path)
    args = parser.parse_args()
    if args.batch_size < 2:
        parser.error("--batch-size must be at least 2")
    files = args.files or DEFAULT_FILES
    if not files:
        parser.error("no CSV files found; provide paths explicitly")
    run(files, args.batch_size)
