"""
THE MODEL

Lives here in the backend, next to the csv data.
Pretrained Phi-4-mini-instruct from Hugging Face (microsoft/Phi-4-mini-instruct, MIT license).

Its only job is fraud detection: look at a person's irregular purchases and flag the ones that are fraud.
The irregular purchases are shortlisted in datasheet.py (irregular), the model makes the fraud call on each.

load() runs once at startup (see start_services in managerdaemon). first run downloads about 7.7 GB.
The manager calls respond() once per sheet (see D_send in managerdaemon).
"""

import logging
import re
import threading
import time
from datetime import datetime

MODEL_ID = "microsoft/Phi-4-mini-instruct"

SYSTEM = (
    "You are a fraud detector for one person's purchase history. You are given one purchase that looked "
    "irregular, with the reason it stood out. Decide: FRAUD if it looks like a charge the person did not make "
    "or did not agree to, such as a duplicate charge, a burst of charges close together, an amount far above "
    "what they normally pay, or a seller they do not normally use. OK if it looks like a normal purchase made "
    "by this person. "
    "Reply with one line and nothing else, in one of these two forms:\n"
    "FRAUD - <short reason>\n"
    "OK - <short reason>"
)

# the verdict has to be the first word: "NOT FRAUD" or "no fraud here" must not count as fraud.
VERDICT = re.compile(r"^\W*(FRAUD|OK)\b\W*(.*)", re.IGNORECASE)

# seconds one question may take before the model counts as stuck (a normal one takes a few seconds).
STALL_TIMEOUT = 120

_pipe = None

# every question to the model and its reply, written to logs/ai_replies.txt (see start_logging in managerdaemon)
replies = logging.getLogger("ai")
replies.addHandler(logging.NullHandler())
replies.propagate = False

# sheets are checked at the same time but there is one model, and it is not safe to run it from two threads at once.
_lock = threading.Lock()
_busy_since = None


def load():
    global _pipe
    if _pipe is None:
        import torch
        from transformers import pipeline

        device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        _pipe = pipeline("text-generation", model=MODEL_ID, device=device, dtype="auto")
    return _pipe


def _ask(sheet, messages):
    global _busy_since
    #waiting for a model that is answering other sheets counts as progress, waiting for a stuck one does not.
    while not _lock.acquire(timeout=1):
        started = _busy_since
        if started is not None and time.monotonic() - started > STALL_TIMEOUT:
            raise TimeoutError(f"the model has been stuck on one question for over {STALL_TIMEOUT} seconds")
        sheet.touch()
    try:
        _busy_since = time.monotonic()
        return load()(messages, max_new_tokens=40, return_full_text=False, do_sample=False)
    finally:
        _busy_since = None
        _lock.release()
        sheet.touch()


def respond(sheet):
    #the model is asked about one purchase at a time (it skips purchases when given the whole list at once).
    fraud = []
    for p in sheet.results["irregular"]:
        #one line and a sane length: the text comes straight from the csv and goes into the prompt and the reply log.
        item = " ".join(str(p["item"]).split())[:120]
        question = (
            f"{p['date']}, {item}, ${p['amount']:.2f}. This person has paid for {item} "
            f"{p['times_seen']} time(s) in total, {p['times_bought']} time(s) at this price. "
            f"Stood out because: {'; '.join(p['signals'])}."
        )
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
        ]
        output = _ask(sheet, messages)
        reply = output[0]["generated_text"].strip()
        verdict = VERDICT.search(reply)
        replies.info(
            "===== %s | %s | row %s =====\nASKED: %s\nAI REPLIED: %s\nCOUNTED AS: %s\n",
            datetime.now().isoformat(sep=" ", timespec="seconds"), sheet.sheet_id, p["row"], question, reply,
            verdict.group(1).upper() if verdict else "UNCLEAR (not counted as fraud)",
        )
        if verdict and verdict.group(1).upper() == "FRAUD":
            fraud.append({**p, "reason": verdict.group(2).strip()})
    return fraud
