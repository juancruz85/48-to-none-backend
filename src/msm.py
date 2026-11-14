"""
_______________________________________________________

TZWATZWATZWA!!!

_____________________________________________________

MANAGER STATE MACHINE
AKA "MSM"
__________________________________________________

S1:
OPERATIONAL

S2:
ERROR

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


def toggle():
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
toggle()





#XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX