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

import numpy as np
import pandas as pd
from . import msm as ms

"""
[[[ GLOBAL VARIABLES ]]]
"""



"""
=== FUNCTIONS ===

prefix for msm
D_function
D = data

"""


def D_createsheet(csv):
    #you'll need to have the watchdog create the datasheet objects from the csvs.
    pass


def D_organize(data):
    #Organize
    #use the actions in datasheet.



    pass

def D_send(data = "blank" ): #default arg is a ruler
    #send to model then return
    #(data is a csv file.)
    #(use paramiko library to send file to a server.)




    pass

def D_result(results):
    #send data






    
    pass

    

#_________________________________________________________________

"""
Operational Code
"""

while ms.operationalstate is not False:
    #run usual routine periodic
    #also include log startup and error watchdog periodic
    pass
#if we recieve the error signal in this phase we must signal to abort all current processes then enter error mode.



"""
Error Code
"""

#Stop, Diagnose, Decide, and report.


while ms.errorstate is not False:
    #stopall func.
    ms.hardstop()
