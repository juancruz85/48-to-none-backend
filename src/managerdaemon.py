"""
_______________________________________________________

TZWATZWATZWA!!!

_____________________________________________________

DAEMON PROTOCOL FOR BACKEND
'Man the Manager'

__________________________________________________
DUTIES:
=== Manage Backend ===

-DAEMON LOGIC AND STATE


+ Backend management looks like intelligent allocation of resources

+ Organize data

- Backend maintainance
+ Edge cases (if something diff)
+ Constant refreshes, regular upkeep.

- Backend Failsafes
+ Failsafe 1: Pwr cycle our backend
+ Failsafe 2: Cry to Dev Team



"""


#*****************************************************************************

"""
notes:


Basically, the way this manager daemon works is that the manager is an active program that runs constantly.
During this constant runtime, it will either be in two states.

Operational or Error
for operational:
    the manager daemon will do it's normal actions and routines, handling concurrent requests and data management.
    Actions can be queued concurrently per datasheet but never the same time for their respective datasheet


For Error: 
    The manager will first save a log of everything, disabling the frontend and backend connection, 
    then start documenting the error.
    It will attempt to resolve the issue on it's own, after that it will go into failsafe mode 1.
    In case of failsafe mode 1 not saving us, failsafe 2 will go into effect calling for out help

Actions themselves are simply functions like "managercall()" which do subactions that pertain to the file they are manipulating.
these subactions are made in the files where they happen, so think of it like subsystems and this is like some sort of main file
with a brain.

TLDR:
Autonomous for application.

"""

#*****************************************************************************


"""
*** LIBRARIES ***
"""

import logging
import traceback
from concurrent.futures import CancelledError, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from . import msm as ms
from . import mattsheet as ds
from . import datasheet as da
from . import model as mo

"""
[[[ GLOBAL VARIABLES ]]]
"""

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
log = logging.getLogger("manager")
log.addHandler(logging.NullHandler())
log.propagate = False

# data enters
sheets = {}

# data leaves
dashboard = {}

# where the csvs were loaded from and each csv's modified time when it was read, for refresh
source_dir = None
mtimes = {}

_workers = {}

"""
=== FUNCTIONS ===

prefix for msm
D_function
D = data

"""


def D_load(data_dir):
    global sheets, source_dir
    paths = sorted(Path(data_dir).glob("*.csv"))
    if not paths:
        raise FileNotFoundError(f"No csv input found in {data_dir}")
    stop_requests()
    source_dir = Path(data_dir)
    mtimes.clear()
    sheets = {path.name: D_createsheet(path) for path in paths}
    log.info("loaded %d sheet(s) from %s: %s", len(sheets), data_dir, sorted(sheets))
    return sheets


def start_services():
    #start backend, api, frontend
    #only the model exists so far. loading it here means every sheet reuses the same loaded model.
    mo.load()


def D_createsheet(csv, person_name="", banks=None):
    #you'll need to have the watchdog create the datasheet objects from the csvs.
    csv = Path(csv)
    data = pd.read_csv(csv)
    mtimes[csv.name] = csv.stat().st_mtime_ns
    places = sorted(set(data["Description"].dropna())) if "Description" in data.columns else []
    return ds.Sheet(
        sheet_id=csv.name,
        data=data,
        source=str(csv),
        person_name=person_name,
        banks=list(banks or []),
        places=places,
    )


def D_organize(sheet):
    #Organize
    #use the actions in datasheet.
    if "Date" in sheet.data.columns:
        sheet.sort("Date")
    sheet.results["vet"] = sheet.vet()
    return sheet

def D_analyze(sheet):
    prepared = da.prepare(sheet.data)
    sheet.results["analysis"] = da.report(prepared)
    sheet.results["irregular"] = da.irregular(prepared)
    return sheet


def D_send(sheet, model=None):
    #send to model then return
    #pass another function as model to swap out the real one, e.g. in tests.
    response = (model or mo.respond)(sheet)
    return {"sheet_id": sheet.sheet_id, "response": response}


def D_result(result):
    #send data
    #no frontend yet, so the dashboard payload is returned and kept in ``dashboard``.
    sheet = sheets[result["sheet_id"]]
    sheet.results["fraud"] = result["response"]
    dashboard[sheet.sheet_id] = {
        "sheet_id": sheet.sheet_id,
        "person_name": sheet.person_name,
        "banks": sheet.banks,
        "places": sheet.places,
        "vet": sheet.results.get("vet", []),
        "analysis": sheet.results.get("analysis"),
        "irregular": sheet.results.get("irregular", []),
        "fraud": sheet.results["fraud"],
        "error": sheet.results.get("error"),
    }
    return dashboard[sheet.sheet_id]


def D_process(sheet, model=None):
    D_organize(sheet)
    if sheet.results["vet"]:
        return D_result({"sheet_id": sheet.sheet_id, "response": None})
    D_analyze(sheet)
    return D_result(D_send(sheet, model))


def D_check(sheet, model=None):
    #checked before every sheet so work stops as soon as an error is reported.
    if ms.state is not ms.State.OPERATIONAL:
        raise RuntimeError(f"manager is {ms.state.value}, not operational")
    log.info("checking %s", sheet.sheet_id)
    sheet.results.clear()
    try:
        entry = D_process(sheet, model)
    except Exception as error:
        log.error("%s failed, the other sheets carry on: %r", sheet.sheet_id, error, exc_info=error)
        sheet.results["error"] = repr(error)
        return D_result({"sheet_id": sheet.sheet_id, "response": None}), error
    if entry["vet"]:
        log.warning("%s not checked, failed vetting: %s", sheet.sheet_id, entry["vet"])
    else:
        log.info("%s done: %d irregular, %d possible fraud", sheet.sheet_id, len(entry["irregular"]), len(entry["fraud"]))
    return entry, None


def D_run(model=None, only=None):
    names = list(sheets) if only is None else list(only)
    futures = {name: request(name, D_check, model) for name in names}
    results, errors, stopped = {}, [], None
    #every future is waited for before anything is raised, so no sheet is still being worked on when supervision takes over.
    for name, future in futures.items():
        try:
            results[name], error = future.result()
        except CancelledError:
            stopped = stopped or RuntimeError(f"manager is {ms.state.value}, work on {name} was stopped")
        except RuntimeError as not_operational:
            stopped = stopped or not_operational
        else:
            if error is not None:
                errors.append(error)
    #an error reported while the sheets were being checked: both may have finished, but supervision has to take over.
    if stopped is None and ms.state is not ms.State.OPERATIONAL:
        stopped = RuntimeError(f"manager is {ms.state.value}, not operational")
    if stopped is not None:
        raise stopped
    #if every sheet breaks the problem is not the sheets, so the error goes up to supervision.
    if errors and len(errors) == len(sheets):
        raise errors[-1]
    return results


#_________________________________________________________________
# REQUESTS
# every sheet has its own single worker, so actions on the same sheet run one at a time in the order they were
# asked for, while different sheets run at the same time. anything that reads or edits a sheet should go through request.


def _submit(sheet_id, work):
    worker = _workers.get(sheet_id) or _workers.setdefault(
        sheet_id, ThreadPoolExecutor(max_workers=1, thread_name_prefix=sheet_id)
    )
    return worker.submit(work)


def request(sheet_id, action, *args, **kwargs):
    """Queue action(sheet, *args, **kwargs) on a sheet. Returns a Future, call .result() on it to wait for the answer."""
    if ms.state is not ms.State.OPERATIONAL:
        raise RuntimeError(f"manager is {ms.state.value}, not operational")
    if sheet_id not in sheets:
        raise KeyError(sheet_id)
    log.info("request: %s on %s", getattr(action, "__name__", action), sheet_id)
    #the sheet is looked up when the action runs, not now, because a refresh may have replaced it in between.
    return _submit(sheet_id, lambda: action(sheets[sheet_id], *args, **kwargs))


def stop_requests():
    #wait=False because a worker can be the one reporting the error, and it cannot wait for itself.
    #queued work is dropped, work that is already running finishes.
    for worker in list(_workers.values()):
        worker.shutdown(wait=False, cancel_futures=True)
    _workers.clear()


def D_refresh(model=None):
    #brings the sheets in line with the csv folder: new csv -> new sheet, changed csv -> sheet rebuilt, deleted csv -> sheet dropped.
    #only new and changed sheets are checked again.
    if ms.state is not ms.State.OPERATIONAL:
        raise RuntimeError(f"manager is {ms.state.value}, not operational")
    paths = {path.name: path for path in Path(source_dir).glob("*.csv")}

    for name in [name for name in sheets if name not in paths]:
        worker = _workers.pop(name, None)
        if worker is not None:
            worker.shutdown(wait=True)
        sheets.pop(name)
        dashboard.pop(name, None)
        mtimes.pop(name, None)
        log.info("refresh: %s was deleted, sheet dropped", name)

    changed = []
    for name, path in sorted(paths.items()):
        mtime = path.stat().st_mtime_ns
        if mtimes.get(name) == mtime:
            continue
        try:
            sheet = D_createsheet(path)
        except Exception as error:
            #remembered as seen so a file that cannot be read is not retried (and logged) on every refresh, only when it changes.
            mtimes[name] = mtime
            log.error("refresh: could not read %s, skipped until it changes: %r", name, error, exc_info=error)
            continue
        #swapped in by the sheet's own worker so it lands after any actions still queued on the old sheet.
        _submit(name, lambda name=name, sheet=sheet: sheets.__setitem__(name, sheet)).result()
        log.info("refresh: %s is new or changed, sheet rebuilt", name)
        changed.append(name)
    return D_run(model, only=changed) if changed else {}


#_________________________________________________________________
# SUPERVISION
# order when something breaks: report_error (log it, stop work) -> recover -> failsafe 1 -> failsafe 2.
# failsafe 1 is the power cycle, it lives in main (initialize is recalled there).


def start_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    files = [
        (log, "manager.log", "%(asctime)s %(levelname)s %(message)s"),
        (mo.replies, "ai_replies.txt", "%(message)s"),
    ]
    for logger, name, layout in files:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        handler = logging.FileHandler(LOG_DIR / name)
        handler.setFormatter(logging.Formatter(layout))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


def recover():
    if ms.state is not ms.State.ERROR:
        return ms.state
    log.warning("recovery: checking data and model")
    begin_recovery()
    try:
        if not sheets:
            raise RuntimeError("no data is loaded")
        mo.load()
    except Exception as error:
        log.error("recovery failed: %r", error, exc_info=error)
        return recovery_failed(error)
    return recovery_succeeded()


def failsafe2():
    #there is no email/slack/etc hooked up yet, the report file and the printed message are the cry to the dev team.
    error = ms.last_error
    report = LOG_DIR / "dev_report.txt"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    details = "".join(traceback.format_exception(error)) if isinstance(error, BaseException) else f"{error}\n"
    with report.open("a") as file:
        file.write(
            f"===== {datetime.now().isoformat(timespec='seconds')} FAILSAFE 2 =====\n"
            f"manager state: {ms.state.value}\n"
            f"sheets loaded: {sorted(sheets)}\n"
            f"tried: recovery, then failsafe 1 (power cycle). both failed.\n"
            f"last error: {error!r}\n"
            f"{details}"
            f"full activity log: {LOG_DIR / 'manager.log'}\n\n"
        )
    log.critical("failsafe 2: dev team report written to %s", report)
    print(f"FAILSAFE 2: the backend could not fix itself. report for the dev team: {report}")
    return report


def start():
    """Begin manager startup without running work during module import."""
    return ms.start()


def startup_succeeded():
    """Mark backend initialization complete."""
    return ms.startup_succeeded()


def report_error(error):
    """Log the error, enter error state and invoke the stop hook for active work."""
    log.error("error reported: %r", error, exc_info=error if isinstance(error, BaseException) else None)
    ms.enter_error(error)
    ms.hardstop()
    stop_requests()
    return ms.state


def begin_recovery():
    return ms.begin_recovery()


def recovery_succeeded():
    return ms.recovery_succeeded()


def recovery_failed(error=None):
    return ms.recovery_failed(error)


def shutdown():
    stop_requests()
    return ms.shutdown()
