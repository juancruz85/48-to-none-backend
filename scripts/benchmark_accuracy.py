"""Compare Phi-4-mini with local instruction models on held-out transactions."""

import argparse
import ctypes
import gc
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import datasheet as da
from src import managerdaemon as MD
from src import model
from src.mattsheet import Sheet


DEFAULT_DATA = ROOT / "data" / "staging" / "fdb-sparkov-search"
DEFAULT_OUTPUT = ROOT / "logs" / "accuracy-comparison.json"
DEFAULT_MODELS = (model.MODEL_ID, "Qwen/Qwen2.5-3B-Instruct")
MIN_FREE_RAM_GIB = 8.5
MODEL_LIMIT = 50
ITEM_HISTORY_MINIMUM = 3


def _free_ram_gib():
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


def _write_checkpoint(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary.replace(path)


def _metrics(actual, predicted):
    if len(actual) != len(predicted):
        raise ValueError("actual and predicted labels must have the same length")
    tp = sum(bool(a) and bool(p) for a, p in zip(actual, predicted))
    fp = sum(not bool(a) and bool(p) for a, p in zip(actual, predicted))
    tn = sum(not bool(a) and not bool(p) for a, p in zip(actual, predicted))
    fn = sum(bool(a) and not bool(p) for a, p in zip(actual, predicted))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    specificity = tn / (tn + fp) if tn + fp else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else 0.0
    total = tp + fp + tn + fn
    return {
        "n": total,
        "positive": tp + fn,
        "negative": tn + fp,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "accuracy": (tp + tn) / total if total else None,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "f1": f1,
    }


def _item_key(value):
    return " ".join(str(value).casefold().split())


def _target_purchase(prepared, target_row, candidates):
    if target_row in candidates:
        return candidates[target_row]

    target = prepared.loc[target_row]
    target_date = target["Date"]
    if pd.isna(target_date):
        raise ValueError(f"target row {target_row} has no valid date")
    target_day = target_date.normalize()
    item = str(target["Item"])
    item_key = _item_key(item)
    prior = prepared.loc[prepared["Date"] < target_date]
    same_item = prior["Item"].map(_item_key) == item_key
    prior_amounts = prior.loc[same_item, "Amount"].astype(float)
    amount = float(target["Amount"])
    times_seen = len(prior_amounts)
    times_bought = int(
        (same_item & (prior["Date"].dt.normalize() == target_day) & (prior["Amount"] == amount)).sum()
    )

    median_amount = mad_amount = threshold_amount = None
    if times_seen >= ITEM_HISTORY_MINIMUM:
        median_amount = float(prior_amounts.median())
        mad_amount = float((prior_amounts - median_amount).abs().median())
        threshold_amount = median_amount + max(3 * 1.4826 * mad_amount, median_amount)

    return {
        "row": int(target_row),
        "date": str(target_date.date()),
        "item": item,
        "amount": amount,
        "times_bought": times_bought,
        "times_seen": times_seen,
        "baseline": {
            "ready": times_seen >= ITEM_HISTORY_MINIMUM,
            "history_count": times_seen,
            "minimum_history": ITEM_HISTORY_MINIMUM,
            "median_amount": round(median_amount, 2) if median_amount is not None else None,
            "mad_amount": round(mad_amount, 2) if mad_amount is not None else None,
            "upper_threshold": round(threshold_amount, 2) if threshold_amount is not None else None,
        },
        "signals": [],
    }


def _load_pipeline(model_id):
    from transformers import pipeline

    return pipeline("text-generation", model=model_id, device=-1, dtype="auto")


def _evaluate_model(model_id, cases, reply_logger):
    import torch

    pipeline = _load_pipeline(model_id)
    model._pipe = pipeline
    isolated_actual = []
    isolated_predicted = []
    production_predicted = []
    records = []
    started = time.perf_counter()
    try:
        for case in cases:
            messages, prompt = model._single_prompt(case["purchase"])
            output = model._ask(case["sheet"], messages, max_new_tokens=40)
            reply = output[0]["generated_text"].strip()
            match = model.VERDICT.search(reply)
            prediction = bool(match and match.group(1).upper() == "FRAUD")
            isolated_actual.append(case["actual"])
            isolated_predicted.append(prediction)
            production_predicted.append(prediction if case["target_is_candidate"] else False)
            reply_logger.info(
                "===== %s | model: %s | %s | target row %s =====\nASKED: %s\nAI REPLIED: %s\nCOUNTED AS: %s\n",
                datetime.now().isoformat(sep=" ", timespec="seconds"),
                model_id,
                case["filename"],
                case["target_row"],
                prompt,
                reply,
                match.group(1).upper() if match else "UNCLEAR (not counted as fraud)",
            )
            records.append({
                "file": case["filename"],
                "actual": int(case["actual"]),
                "target_row": case["target_row"],
                "heuristic_candidate_count": case["candidate_count"],
                "target_is_candidate": case["target_is_candidate"],
                "raw_reply": reply,
                "parsed_verdict": match.group(1).upper() if match else None,
                "isolated_prediction": int(prediction),
                "production_prediction": int(production_predicted[-1]),
            })
    finally:
        model._pipe = None
        del pipeline
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    return {
        "model_id": model_id,
        "revision": getattr(pipeline.model.config, "_commit_hash", None),
        "device": "CPU",
        "seconds": round(time.perf_counter() - started, 3),
        "isolated_model_only": _metrics(isolated_actual, isolated_predicted),
        "production_pipeline": _metrics(isolated_actual, production_predicted),
        "unclear_replies": sum(record["parsed_verdict"] is None for record in records),
        "predictions": records,
    }


def _load_cases(data_dir):
    labels_path = data_dir / "evaluation_labels.json"
    manifest_path = data_dir / "manifest.json"
    if not labels_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"expected evaluation_labels.json and manifest.json under {data_dir}")
    labels_by_file = json.loads(labels_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("dataset", "").startswith("FDB #4"):
        raise ValueError("this benchmark expects the staged FDB #4 account dataset")

    cases = []
    for filename, labels in sorted(labels_by_file.items()):
        path = data_dir / filename
        raw = pd.read_csv(path)
        if len(raw) != len(labels) or not labels:
            raise ValueError(f"label count does not match rows in {filename}")
        target_row = len(labels) - 1
        prepared = da.prepare(raw)
        if target_row not in prepared.index:
            raise ValueError(f"target row {target_row} is missing from {filename}")
        target_date = prepared.loc[target_row, "Date"]
        if pd.isna(target_date) or target_date != prepared["Date"].max():
            raise ValueError(f"held-out target in {filename} is not the latest transaction")

        found = da.irregular(prepared)
        candidates = {purchase["row"]: purchase for purchase in found}
        selected = sorted(found, key=lambda purchase: (-len(purchase["signals"]), -purchase["amount"]))[:MODEL_LIMIT]
        selected_rows = {purchase["row"] for purchase in selected}
        cases.append({
            "filename": filename,
            "target_row": target_row,
            "actual": int(labels[target_row]),
            "candidate_count": len(selected),
            "target_is_candidate": target_row in selected_rows,
            "purchase": _target_purchase(prepared, target_row, candidates),
            "sheet": Sheet(sheet_id=filename, data=raw, source=str(path)),
        })
    return cases


def run(data_dir=DEFAULT_DATA, output_path=DEFAULT_OUTPUT, model_ids=DEFAULT_MODELS):
    data_dir = Path(data_dir)
    output_path = Path(output_path)
    free_ram = _free_ram_gib()
    if free_ram < MIN_FREE_RAM_GIB:
        raise MemoryError(
            f"only {free_ram:.2f} GiB RAM is available; prior Phi inference used about 8.2 GiB. "
            f"Free at least {MIN_FREE_RAM_GIB:.1f} GiB before model inference."
        )

    cases = _load_cases(data_dir)
    actual = [case["actual"] for case in cases]
    heuristic_predictions = [int(case["target_is_candidate"]) for case in cases]
    manifest_path = data_dir / "manifest.json"
    report = {
        "dataset": "FDB #4 / Kaggle kartik2112/fraud-detection, version 1",
        "dataset_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "free_ram_before_inference_gib": round(free_ram, 2),
        "target_cases": len(cases),
        "heuristic_gate": {
            "metrics": _metrics(actual, heuristic_predictions),
            "targets_sent_to_model": sum(heuristic_predictions),
        },
        "models": [],
        "limitations": [
            "The staged data is synthetic and is not representative real-cardholder data.",
            "There are 30 fraud targets and only 1 clean target; precision and specificity are highly uncertain.",
            "Model-only scores bypass the production heuristic gate and are not end-to-end app scores.",
            "Production scores use the heuristic gate; an unselected target is not sent to the model.",
            "Labels are loaded only for scoring and are never included in model prompts.",
        ],
    }

    old_log_dir = MD.LOG_DIR
    MD.LOG_DIR = output_path.parent / "accuracy-comparison"
    MD.start_logging()
    try:
        for model_id in model_ids:
            current_ram = _free_ram_gib()
            if current_ram < MIN_FREE_RAM_GIB:
                raise MemoryError(
                    f"only {current_ram:.2f} GiB RAM is available before loading {model_id}; "
                    f"need {MIN_FREE_RAM_GIB:.1f} GiB."
                )
            result = _evaluate_model(model_id, cases, model.replies)
            report["models"].append(result)
            _write_checkpoint(output_path, report)
    finally:
        MD.stop_logging()
        MD.LOG_DIR = old_log_dir
    _write_checkpoint(output_path, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    args = parser.parse_args()
    result = run(args.data_dir, args.output, args.models)
    print(json.dumps({
        "target_cases": result["target_cases"],
        "heuristic_gate": result["heuristic_gate"],
        "models": [
            {
                "model_id": item["model_id"],
                "isolated_model_only": item["isolated_model_only"],
                "production_pipeline": item["production_pipeline"],
                "unclear_replies": item["unclear_replies"],
                "seconds": item["seconds"],
            }
            for item in result["models"]
        ],
        "output": str(args.output),
    }, indent=2))
