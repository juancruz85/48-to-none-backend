"""
_______________________________________________________

TZWATZWATZWA!!!

_____________________________________________________

MANAGER STATE MACHINE
AKA "MSM"
__________________________________________________

S1:
OPERATIONAL
    routines and actions to imp

    ---sequential
    1. Wakeup routine - msm
    2. Run error watchdog - subaction (if error watchdog detects error then togglestate)
    3. Keep log
    4. activate full green protocol
    --- concurrent routines and actions (full green protocol)
    *** Work as intended
    1. Create datasheet object based on inputted csv
    2. organize and attatch metadata (keep everything batched)
    3. send to AI model
    4. recapture AI results, organise them with the same batch and then send to dashboard.
    5. manage AI crossreference requests.
    6. Manage requests


S2:
ERROR
    routines and actions

    1. Stop all concurrent and all operations
    2. Save log
    3. Diagnose
    4. Attempt to fix
    5. Either complete fix and toggle or use safeguard 1
    ---
    5.5. if safeguard 1 is in place then diagnose again and either toggle or activate safeguard 2
    5.7. wait for resolution if safeguard 2


"""




"""
*** LIBRARIES ***
"""

import numpy as np
import pandas as pd


"""
[[[ GLOBAL VARIABLES ]]]
"""

operationalstate = False
errorstate = False
toggleallow = False
errordetected = False




"""
=== FUNCTIONS ===
"""

#handle state
#switch state
#allow actions
#yada yada
#coast vs stop in state

#s1 - operational
# if not error variable == true then assume operational. Operational handles actions

#s2 - error
# if error send diagnose






def togglestate():
#global vars
    global toggleallow
    global operationalstate
    global errorstate
#logic block
    if toggleallow is not False:

        if operationalstate is False and errorstate is True:

            operationalstate = True
            errorstate = False
            x = errorstate
            z = operationalstate
            return z and x
        
        elif operationalstate is not False and errorstate is not True:

            errorstate = True
            operationalstate = False
            x = operationalstate
            z = errorstate
            return z and x
        
        elif operationalstate is False and errorstate is False:

            operationalstate = True
            return operationalstate

#in case of toggleallow false
    else:
        print(f'Toggle unsuccessful! :(')        

#_______________________________________________________

def initial_msm():
    #global vars
    global toggleallow
    global operationalstate
    global errorstate
    #initial turn on toggle allow
    toggleallow = True
    togglestate()
    #_______________________________



def print_state():
    #global vars
    global toggleallow
    global operationalstate
    global errorstate

    #_________________________

    if errorstate is not False:
        state = "errorstate"
    else:
        state = "operationalstate"
    
    print(state)


def errorcheck():
    global errordetected
    #error check runs error check across all actions and systems.
    pass



def hardstop():
    global errordetected
    if errordetected is not False:
        #insert all stop commands
        pass
    else:
        #still insert stop commands becasue this is absolute
        pass



















#_____________________________________________________________________
#TEST SCRIPTS
#0000000000000000
"""

__name__ == "__main__":
initial_msm()
print_state()
togglestate()
print_state()

"""
#000000000000000



#XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX