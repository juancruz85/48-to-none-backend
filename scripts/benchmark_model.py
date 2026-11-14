"""Sweep real-model batch sizes against the single-purchase baseline.

The script loads Phi once, evaluates every shortlisted purchase, and writes a
checkpoint after each file/size. It reports runtime, response validity,
verdict disagreements, and call reduction. It cannot report accuracy without
human-labeled fraud outcomes. Batched chunks continue after malformed replies
so one bad response does not hide results for the remaining chunks.
"""

import argparse
import json
import time
from pathlib import Path

from src import managerdaemon as MD
from src import model


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILES = sorted((PROJECT_ROOT / "purchase_data").glob("*.csv"))
DEFAULT_SIZES = (2, 3, 4, 5, 8)


def prepare(path):
    sheet = MD.D_createsheet(path)
    MD.D_organize(sheet)
    if sheet.results["vet"]:
        return sheet, sheet.results["vet"]
    MD.D_analyze(sheet)
    return sheet, None


def run_single(sheet):
    calls = 0
    original_ask = model._ask

    def counted_ask(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_ask(*args, **kwargs)

    model._ask = counted_ask
    started = time.perf_counter()
    error = None
    fraud = []
    try:
        fraud = model.respond(sheet, batch_size=1)
    except Exception as failure:
        error = repr(failure)
    finally:
        model._ask = original_ask
    return {
        "batch_size": 1,
        "candidates": len(sheet.results["irregular"]),
        "calls": calls,
        "valid_batches": calls if error is None else 0,
        "invalid_batches": [],
        "seconds": round(time.perf_counter() - started, 3),
        "error": error,
        "fraud_rows": sorted(item["row"] for item in fraud),
    }


def run_batched(sheet, batch_size):
    purchases = sheet.results["irregular"]
    profile = sheet.results.get("profile", {})
    fraud, invalid = [], []
    calls = 0
    started = time.perf_counter()

    for offset in range(0, len(purchases), batch_size):
        batch = purchases[offset:offset + batch_size]
        messages, prompt = model._batch_prompt(profile, batch)
        calls += 1
        reply = ""
        try:
            output = model._ask(sheet, messages, max_new_tokens=max(40, len(batch) * 32))
            reply = output[0]["generated_text"].strip()
            fraud.extend(model._parse_batch(reply, batch))
        except Exception as failure:
            invalid.append({
                "rows": [purchase["row"] for purchase in batch],
                "error": repr(failure),
                "reply": reply[:1200],
            })

    return {
        "batch_size": batch_size,
        "candidates": len(purchases),
        "calls": calls,
        "valid_batches": calls - len(invalid),
        "invalid_batches": invalid,
        "seconds": round(time.perf_counter() - started, 3),
        "error": None,
        "fraud_rows": sorted(item["row"] for item in fraud),
    }


def _write_checkpoint(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary.replace(path)


def run(paths, batch_sizes=DEFAULT_SIZES, output_path=None):
    output_path = output_path or PROJECT_ROOT / "logs" / "batch-sweep.json"
    pipe = model.load()
    pipe(
        [{"role": "user", "content": "Reply OK."}],
        max_new_tokens=1,
        return_full_text=False,
        do_sample=False,
    )
    report = {
        "files": {},
        "batch_sizes": list(batch_sizes),
        "model": model.MODEL_ID,
        "notes": [
            "Responses are compared with the same run's single-purchase baseline; this is not accuracy.",
            "Malformed batches are recorded and later batches continue.",
        ],
    }
    _write_checkpoint(output_path, report)

    for path in paths:
        sheet, vet_error = prepare(path)
        file_result = {"vet_error": vet_error, "runs": []}
        report["files"][path.name] = file_result
        if vet_error is not None:
            _write_checkpoint(output_path, report)
            continue

        baseline = run_single(sheet)
        file_result["baseline"] = baseline
        _write_checkpoint(output_path, report)
        print(f"{path.name}: baseline finished ({baseline['calls']} calls, {baseline['seconds']} s)", flush=True)

        for batch_size in batch_sizes:
            measured = run_batched(sheet, batch_size)
            measured["call_reduction_percent"] = round(
                100 * (baseline["calls"] - measured["calls"]) / baseline["calls"], 1
            ) if baseline["calls"] else 0
            measured["verdict_disagreements"] = (
                sorted(set(baseline["fraud_rows"]) ^ set(measured["fraud_rows"]))
                if baseline["error"] is None and not measured["invalid_batches"]
                else None
            )
            file_result["runs"].append(measured)
            _write_checkpoint(output_path, report)
            print(
                f"{path.name}: batch {batch_size} finished "
                f"({measured['valid_batches']}/{measured['calls']} valid calls, "
                f"{measured['seconds']} s)",
                flush=True,
            )

    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-sizes", type=int, nargs="+", default=DEFAULT_SIZES)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "logs" / "batch-sweep.json")
    parser.add_argument("files", nargs="*", type=Path)
    args = parser.parse_args()
    if any(size < 2 for size in args.batch_sizes):
        parser.error("all --batch-sizes values must be at least 2")
    files = args.files or DEFAULT_FILES
    if not files:
        parser.error("no CSV files found; provide paths explicitly")
    run(files, args.batch_sizes, args.output)
