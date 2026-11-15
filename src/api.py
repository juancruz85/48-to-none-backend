"""
LOCAL API FOR THE DASHBOARD

Runs the whole program (startup, model, fraud check, refresh) and serves what the manager knows as
JSON, so the frontend can show the real results instead of fake data. It also takes the csv uploads:
every csv belongs to one account of one profile.

Run it from the repo root:
    .venv/bin/python -m src.api
    .venv/bin/python -m src.api --port 8000 --interval 30 --data-dir user_data

Routes:
    GET    /health                                   is the server up
    GET    /report?profile=<profile_id>              everything the dashboard needs for one profile
    GET    /report                                   every sheet in the folder (no profile filter)
    PUT    /sheets/<profile_id>/<account_id>/<name>  upload a csv (the body is the file)
    DELETE /sheets/<profile_id>/<account_id>/<name>  delete one csv
    DELETE /sheets/<profile_id>/<account_id>         delete every csv of an account

Uploads are saved in user_data/ as <profile_id>__<account_id>__<name>.csv. The manager only knows
csv files in one folder, so who owns a sheet is kept in its file name.

It only listens on this machine (127.0.0.1) and trusts whoever calls it: the frontend server checks
who is signed in before it calls. The model is too big for the AWS Lambda the profile api runs on,
so this part stays local for now.
"""

import argparse
import json
import logging
import math
import io
import os
import re
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote

import pandas as pd

from . import datasheet as da
from . import main as app
from . import managerdaemon as MD
from . import model as mo
from . import msm as ms

USER_DATA_DIR = Path(__file__).resolve().parent.parent / "user_data"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

# set when the background run could not be fixed and gave up (failsafe 2), so the dashboard can say so.
gave_up = None

# the csv folder being served, and the alarm that wakes the manager thread as soon as a csv is uploaded or deleted.
data_dir = None
_wake = threading.Event()

_ID = re.compile(r"[0-9a-fA-F-]{8,64}")
_OWNED = re.compile(r"^(?P<profile>[0-9a-fA-F-]{8,64})__(?P<account>[0-9a-fA-F-]{8,64})__(?P<name>.+)$")


class BadRequest(Exception):
    pass


def owner(sheet_id):
    """(profile_id, account_id, name) kept in an uploaded sheet's file name, or (None, None, sheet_id)."""
    match = _OWNED.match(sheet_id)
    if match is None:
        return None, None, sheet_id
    return match["profile"], match["account"], match["name"]


def _check_id(value, kind):
    if not _ID.fullmatch(value or ""):
        raise BadRequest(f"{kind} id is not valid")
    return value


def _file_name(name):
    #the name ends up in a path, so nothing that could leave the folder or hide the file is kept.
    name = re.sub(r"[^A-Za-z0-9._ ()-]", "_", Path(str(name)).name).strip(" .")
    if not name.lower().endswith(".csv"):
        raise BadRequest("the file must be a .csv")
    stem = name[:-4].strip(" .")[:80]
    if not stem:
        raise BadRequest("the file needs a name")
    return f"{stem}.csv"


def _check_csv(content):
    """Refuse an upload the analysis could never read, with a message the user can act on."""
    if not content.strip():
        raise BadRequest("the file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise BadRequest(f"the file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    try:
        columns = set(pd.read_csv(io.BytesIO(content), nrows=5).columns)
    except Exception as error:
        raise BadRequest(f"the file could not be read as a csv: {error}")
    missing = []
    if "Date" not in columns:
        missing.append("Date")
    if not columns & {"Amount", "Amount (USD)"}:
        missing.append("Amount")
    if not columns & {"Item", "Description"}:
        missing.append("Item or Description")
    if missing:
        raise BadRequest(f"the csv is missing the column(s): {', '.join(missing)}. it has: {', '.join(sorted(map(str, columns)))}")


def save_sheet(profile_id, account_id, name, content):
    _check_id(profile_id, "profile")
    _check_id(account_id, "account")
    name = _file_name(name)
    _check_csv(content)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{profile_id}__{account_id}__{name}"
    #written under another name first so the manager never reads a half written csv.
    partial = path.with_name(path.name + ".part")
    partial.write_bytes(content)
    partial.replace(path)
    _wake.set()
    return path.name


def delete_sheets(profile_id, account_id, name=None):
    """Delete one csv of an account, or all of them when no name is given. Returns how many were deleted."""
    _check_id(profile_id, "profile")
    _check_id(account_id, "account")
    prefix = f"{profile_id}__{account_id}__"
    if name is not None:
        paths = [data_dir / f"{prefix}{_file_name(name)}"]
    else:
        paths = [path for path in _files() if path.name.startswith(prefix)]
    deleted = 0
    for path in paths:
        try:
            path.unlink()
            deleted += 1
        except FileNotFoundError:
            pass
    if deleted:
        _wake.set()
    return deleted


def _files():
    if data_dir is None or not data_dir.is_dir():
        return []
    return sorted(path for path in data_dir.iterdir() if path.suffix.lower() == ".csv" and path.is_file())


def _clean(value):
    """Make a value safe for JSON: no NaN/inf, no numpy or pandas types."""
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_clean(item) for item in value]
    if value is None or isinstance(value, (str, bool)):
        return value
    if hasattr(value, "item") and not isinstance(value, (int, float)):
        #numpy numbers
        try:
            value = value.item()
        except (AttributeError, ValueError):
            return str(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, int):
        return value
    return str(value)


def _transactions(sheet, entry):
    """Every row of the sheet with what happened to it.

    fraud = the model flagged this purchase. suspicious = part of a rising-charge pattern the model says
    to take a look at. cleared = looked irregular, the model passed it. ok = nothing stood out.
    """
    try:
        prepared = da.prepare(sheet.data)
    except Exception:
        #a sheet that fails vetting cannot always be prepared. it is reported through "vet" instead.
        return []
    irregular = {purchase["row"]: purchase for purchase in (entry or {}).get("irregular") or []}
    fraud = {purchase["row"]: purchase for purchase in (entry or {}).get("fraud") or []}
    suspicious = {row: pattern for pattern in (entry or {}).get("suspicious") or [] for row in pattern["rows"]}
    rows = []
    for row, purchase in prepared.iterrows():
        amount = purchase["Amount"]
        date = purchase["Date"]
        if row in fraud:
            status = "fraud"
        elif row in suspicious:
            status = "suspicious"
        elif row in irregular:
            status = "cleared"
        else:
            status = "ok"
        rows.append({
            "row": int(row),
            "date": None if pd.isna(date) else str(date.date()),
            "item": str(purchase["Item"]),
            "amount": None if pd.isna(amount) else float(amount),
            "type": str(purchase["Transaction_Type"]),
            "status": status,
            "signals": irregular.get(row, {}).get("signals", [])
                       + ([suspicious[row]["signal"]] if row in suspicious else []),
            "reason": (fraud.get(row) or suspicious.get(row) or {}).get("reason", ""),
        })
    return rows


def _sheet(sheet_id, sheet):
    #D_check empties a sheet's results when it starts and D_result fills "fraud" in when it is done,
    #so a sheet without it is still waiting for the model.
    done = "fraud" in sheet.results
    entry = MD.dashboard.get(sheet_id) if done else None
    transactions = _transactions(sheet, entry)
    paid = [t for t in transactions if t["amount"] is not None and t["amount"] > 0]
    flagged = [t for t in transactions if t["status"] == "fraud"]
    watch = [t for t in transactions if t["status"] == "suspicious"]
    reviewed = {pattern["item"]: pattern for pattern in (entry or {}).get("suspicious") or []}
    #every pattern that was found, with the model's call on it. rows are left out, the transactions carry them.
    patterns = [
        {**{key: value for key, value in pattern.items() if key != "rows"},
         "suspicious": pattern["item"] in reviewed,
         "reason": reviewed.get(pattern["item"], {}).get("reason", "")}
        for pattern in (entry or {}).get("patterns") or []
    ]
    if not done:
        status = "checking"
    elif entry is None or entry.get("error"):
        status = "failed"
    elif entry.get("vet"):
        status = "needs_fixing"
    else:
        status = "done"
    baseline = (entry or {}).get("baseline") or {}
    _, account_id, name = owner(sheet_id)
    return {
        "sheet_id": sheet_id,
        "account_id": account_id,
        "name": name,
        "status": status,
        "stuck": sheet_id in MD.abandoned,
        "error": (entry or {}).get("error"),
        "vet": (entry or {}).get("vet") or [],
        "totals": {
            "transactions": len(transactions),
            "paid": len(paid),
            "spent": round(sum(t["amount"] for t in paid), 2),
            "irregular": (entry or {}).get("irregular_total", 0),
            "sent_to_model": len((entry or {}).get("irregular") or []),
            "fraud": len(flagged),
            "at_risk": round(sum(t["amount"] or 0 for t in flagged), 2),
            "suspicious": len(watch),
            "suspicious_amount": round(sum(t["amount"] or 0 for t in watch), 2),
        },
        "patterns": patterns,
        "baseline": {
            "ready": baseline.get("ready", False),
            "as_of": baseline.get("as_of"),
            "overall": baseline.get("overall") or {},
        },
        "analysis": (entry or {}).get("analysis"),
        "transactions": transactions,
    }


def _waiting_sheet(sheet_id, error=None):
    #a csv that is in the folder but the manager has not picked up yet, or could not read.
    _, account_id, name = owner(sheet_id)
    return {
        "sheet_id": sheet_id,
        "account_id": account_id,
        "name": name,
        "status": "failed" if error else "checking",
        "stuck": False,
        "error": error,
        "vet": [],
        "totals": {"transactions": 0, "paid": 0, "spent": 0, "irregular": 0, "sent_to_model": 0, "fraud": 0, "at_risk": 0,
                   "suspicious": 0, "suspicious_amount": 0},
        "patterns": [],
        "baseline": {"ready": False, "as_of": None, "overall": {}},
        "analysis": None,
        "transactions": [],
    }


def report(profile_id=None):
    """Everything the dashboard shows, read from the manager at this moment. One profile's sheets if given."""
    if profile_id is not None:
        _check_id(profile_id, "profile")
    mine = lambda sheet_id: profile_id is None or owner(sheet_id)[0] == profile_id
    #copied first: the manager adds and drops sheets from its own threads.
    loaded = dict(MD.sheets)
    unreadable = {name: why for name, why in dict(MD.unreadable).items() if mine(name)}
    on_disk = {path.name for path in _files()}
    sheets = {sheet_id: _sheet(sheet_id, sheet) for sheet_id, sheet in loaded.items()
              if mine(sheet_id) and (sheet_id in on_disk or data_dir is None)}
    for sheet_id in on_disk:
        if mine(sheet_id) and sheet_id not in sheets:
            sheets[sheet_id] = _waiting_sheet(sheet_id, unreadable.get(sheet_id))
    sheets = [sheets[sheet_id] for sheet_id in sorted(sheets)]
    error = gave_up or ms.last_error
    return _clean({
        #"waiting" = nothing has been uploaded yet, so the manager has not been started.
        "state": "waiting" if ms.state is ms.State.STOPPED and gave_up is None else ms.state.value,
        "busy": any(sheet["status"] == "checking" for sheet in sheets),
        "gave_up": gave_up is not None,
        "last_error": None if error is None else repr(error),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": mo.MODEL_ID,
        "model_limit": MD.MODEL_LIMIT,
        "data_dir": None if MD.source_dir is None else str(MD.source_dir),
        "unreadable": unreadable,
        "sheets": sheets,
    })


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status, code, message):
        self._send(status, {"error": {"code": code, "message": message}})

    def _route(self, method):
        path, _, query = self.path.partition("?")
        parts = [unquote(part) for part in path.split("/") if part]
        try:
            if method == "GET" and parts == ["health"]:
                return self._send(200, {"ok": True, "state": ms.state.value})
            if method == "GET" and parts == ["report"]:
                profile_id = (parse_qs(query).get("profile") or [None])[0]
                return self._send(200, report(profile_id))
            if parts[:1] == ["sheets"] and len(parts) in (3, 4):
                profile_id, account_id = parts[1], parts[2]
                name = parts[3] if len(parts) == 4 else None
                if method == "PUT" and name is not None:
                    length = int(self.headers.get("Content-Length") or 0)
                    if length > MAX_UPLOAD_BYTES:
                        raise BadRequest(f"the file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
                    sheet_id = save_sheet(profile_id, account_id, name, self.rfile.read(length))
                    return self._send(201, {"sheet_id": sheet_id, "name": owner(sheet_id)[2]})
                if method == "DELETE":
                    return self._send(200, {"deleted": delete_sheets(profile_id, account_id, name)})
            return self._error(404, "NOT_FOUND", "Route not found.")
        except BadRequest as bad:
            message = str(bad)
            return self._error(400, "INVALID_REQUEST", message[:1].upper() + message[1:] + ".")
        except BrokenPipeError:
            pass
        except Exception as error:
            MD.log.error("api: %s %s failed: %r", method, path, error, exc_info=error)
            self._error(500, "SERVER_ERROR", repr(error))

    def do_GET(self):
        self._route("GET")

    def do_PUT(self):
        self._route("PUT")

    def do_DELETE(self):
        self._route("DELETE")

    def log_message(self, format, *args):
        #the dashboard polls, printing every request would bury the fraud results in the terminal.
        pass


def _work(interval):
    """The manager thread: start once there is a csv, then keep the sheets in line with the folder.

    Same order as serve() in main, but it can start with an empty folder and wakes up as soon as a csv
    is uploaded or deleted instead of only every `interval` seconds.
    """
    global gave_up
    try:
        #loaded while waiting for the first upload, so the first check does not also wait for the model.
        mo.load()
    except Exception as error:
        MD.log.error("api: the model did not load, startup will try again: %r", error)
    running = False
    while True:
        try:
            if not _files():
                #nothing to check. the manager is started by the first upload.
                if running and ms.state is ms.State.OPERATIONAL:
                    app.show(MD.D_refresh())
            elif not running or ms.state is not ms.State.OPERATIONAL:
                gave_up = None
                results = app.run(data_dir)
                app.show(results)
                app.show_unreadable()
                running = results is not None
                if results is None:
                    gave_up = ms.last_error or RuntimeError("the backend could not fix itself, see logs/dev_report.txt")
            else:
                app.show(MD.D_refresh())
        except Exception as error:
            #same as serve() in main: report it, the next pass runs supervision (recovery, failsafes) again.
            MD.log.error("api: refresh failed: %r", error, exc_info=error)
            if ms.state is ms.State.OPERATIONAL:
                MD.report_error(error)
        #after giving up, only a change to the folder is a reason to try again.
        _wake.wait(None if gave_up is not None else interval)
        _wake.clear()
        #an upload is often followed by another one, give them a moment to land together.
        time.sleep(0.2)


def serve(folder=USER_DATA_DIR, port=8000, interval=30, host="127.0.0.1"):
    global data_dir
    data_dir = Path(folder)
    data_dir.mkdir(parents=True, exist_ok=True)
    MD.start_logging()
    server = ThreadingHTTPServer((host, port), Handler)
    worker = threading.Thread(target=_work, args=(interval,), name="manager", daemon=True)
    worker.start()
    print(f"dashboard api on http://{host}:{port}/report, csv folder {data_dir} (ctrl-c to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        MD.stop_requests()
        MD.stop_logging()
        #the manager thread and any sheet stuck on the model never end on their own, same reason as the end of main.
        logging.shutdown()
        sys.stdout.flush()
        os._exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the fraud check and serve the results to the dashboard.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--interval", type=float, default=30, help="seconds between refreshes of the csv folder")
    parser.add_argument("--data-dir", type=Path, default=USER_DATA_DIR,
                        help="folder the uploaded CSVs are kept in (default: user_data)")
    args = parser.parse_args()
    serve(folder=args.data_dir, port=args.port, interval=args.interval)
