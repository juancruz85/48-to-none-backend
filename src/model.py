"""
THE MODEL

Lives here in the backend, next to the csv data.
Pretrained Phi-4-mini-instruct from Hugging Face (microsoft/Phi-4-mini-instruct, MIT license).

Its only job is fraud detection: look at a person's irregular purchases and flag the ones that are fraud.
The irregular purchases are shortlisted in datasheet.py (irregular), the model makes the fraud call on each.

load() runs once at startup (see start_services in managerdaemon). first run downloads about 7.7 GB.
The manager calls respond() once per sheet (see D_send in managerdaemon).
"""

import re

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

VERDICT = re.compile(r"\b(FRAUD|OK)\b\W*(.*)", re.IGNORECASE)

_pipe = None


def load():
    global _pipe
    if _pipe is None:
        import torch
        from transformers import pipeline

        device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        _pipe = pipeline("text-generation", model=MODEL_ID, device=device, dtype="auto")
    return _pipe


def respond(sheet):
    #the model is asked about one purchase at a time (it skips purchases when given the whole list at once).
    fraud = []
    for p in sheet.results["irregular"]:
        question = (
            f"{p['date']}, {p['item']}, ${p['amount']:.2f}. This person has paid for {p['item']} "
            f"{p['times_seen']} time(s) in total, {p['times_bought']} time(s) at this price. "
            f"Stood out because: {'; '.join(p['signals'])}."
        )
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
        ]
        output = load()(messages, max_new_tokens=40, return_full_text=False, do_sample=False)
        verdict = VERDICT.search(output[0]["generated_text"])
        if verdict and verdict.group(1).upper() == "FRAUD":
            fraud.append({**p, "reason": verdict.group(2).strip()})
    return fraud
