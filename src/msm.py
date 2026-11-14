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
    7. 


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


def togglestate():
#global vars
    global toggleallow
    global operationalstate
#logic block
    if toggleallow is not False:

        if operationalstate is False and errorstate is True:

            operationalstate = True
            errorstate = False
            x = errorstate
            z = operationalstate
            return z and x
        
        elif errorstate is not False and errorstate is not True:

            errorstate = True
            operationalstate = False
            x = operationalstate
            z = errorstate
            return z and x
#in case of toggleallow false
    else:
        print(f'Toggle unsuccessful! :(')        


#s2 - error
# if error send diagnose



#_____________________________________________________________________
togglestate()





#XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX