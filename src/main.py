"""


                                           ............
                                            ..........
                                    .+##.    ........    +##+.
                                 ########     ......    +#######+
                              ############.    ....    +###########+
                           .###############     ..    +##############+
                          ##################.        +#################+
                         ####################.      +###################+
                       .######################.    #######################
                       ########################.  +#######################+
                      .#########################.##########################
                      +####################################################

               .    . .     ........   ....      ...   ....   ....   ...   ...........
             +.+  ++   #       ++    +.    .#     ..++   .  #.    .+  .+#.  .   .+
           .  .+   ..+#+       ++   .#      #.    ..  #. . .#     .#  .. .# .   .#..+
              .+  +.   +       ++    .+    ++     .+   .#.  ++    #.  ..   +#   .#    +


                              .####################################+
                                 .##############################+
                                    .#########################+
                                          ################
"""




"""

Main routines

initialize all .py files

call and wakeup manager daemon into working

call fresh or non-fresh model into existence

handle active server; backend, api, and frontend

refresh routines



Initilize and call the routine that starts everything.
this fuction will be recalled when failsafe 1 kicks in.
"""



""" LIBS """

from pathlib import Path

import numpy as np
import pandas as pd
import paramiko as pm
from . import msm as ms
from . import mattsheet as ds
from . import managerdaemon as MD
from . import common as c

""" FUNCTIONS """





DATA_DIR = Path(__file__).resolve().parent.parent / "purchase_data"


def initialize(data_dir=DATA_DIR):
    """
    set startup global to true then false
    Wake man, fetch data, start processes

    Returns the loaded input data, or None if startup failed (manager is then in error state).
    """
    # Failsafe 1 recalls this while the manager is still up so power cycle first.
    if ms.state is not ms.State.STOPPED:
        MD.shutdown()

    MD.start()
    try:
        sheets = MD.D_load(data_dir)
        MD.start_services()
    except Exception as error:
        MD.report_error(error)
        print(f"startup failed: {error}")
        return None

    MD.startup_succeeded()
    return sheets


if __name__ == "__main__":
    initialize()
    ms.print_state()