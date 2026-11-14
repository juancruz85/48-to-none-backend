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

from pathlib import Path

import numpy as np
import pandas as pd
from . import msm as ms
from . import mattsheet as ds

"""
[[[ GLOBAL VARIABLES ]]]
"""

# data enters
sheets = {}

"""
=== FUNCTIONS ===

prefix for msm
D_function
D = data

"""


def D_load(data_dir):
    global sheets
    paths = sorted(Path(data_dir).glob("*.csv"))
    if not paths:
        raise FileNotFoundError(f"No csv input found in {data_dir}")
    sheets = {path.name: D_createsheet(path) for path in paths}
    return sheets


def start_services():
    #start backend, api, frontend
    print("start_services called")


def D_createsheet(csv, person_name="", banks=None):
    #you'll need to have the watchdog create the datasheet objects from the csvs.
    #one sheet per csv. the file name is the sheet's identity.
    csv = Path(csv)
    data = pd.read_csv(csv)
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
    #sorts by date, vets, and keeps the vet problems on the sheet. same sheet comes back out.
    if "Date" in sheet.data.columns:
        sheet.sort("Date")
    sheet.results["vet"] = sheet.vet()
    return sheet

def D_send(data = "blank" ): #default arg is a ruler
    #send to model then return
    #(data is a csv file.)
    #(use paramiko library to send file to a server.)




    pass

def D_result(results):
    #send data






    
    pass

    


def start():
    """Begin manager startup without running work during module import."""
    return ms.start()


def startup_succeeded():
    """Mark backend initialization complete."""
    return ms.startup_succeeded()


def report_error(error):
    """Enter error state and invoke the stop hook for active work."""
    ms.enter_error(error)
    ms.hardstop()
    return ms.state


def begin_recovery():
    return ms.begin_recovery()


def recovery_succeeded():
    return ms.recovery_succeeded()


def recovery_failed(error=None):
    return ms.recovery_failed(error)


def shutdown():
    return ms.shutdown()
