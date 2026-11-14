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


def run(data_dir=DATA_DIR):
    """
    The whole program: start up, then check every sheet for fraud, supervised.

    One sheet breaking only stops that sheet: its entry carries the error and the other sheets are still checked.
    If startup fails or every sheet breaks, the manager stops work and tries to fix itself:
    first recovery, then failsafe 1 (power cycle, initialize is recalled), and the work is tried again after each.
    If nothing helps, failsafe 2 writes a report for the dev team.

    Returns {sheet_id: dashboard entry}, or None if it could not be fixed (manager is then in error state).
    """
    MD.start_logging()
    initialize(data_dir)
    fixes = [
        ("first try", None),
        ("recovery", MD.recover),
        ("failsafe 1 (power cycle)", lambda: initialize(data_dir)),
    ]
    for name, fix in fixes:
        if fix is not None:
            MD.log.warning("trying %s", name)
            fix()
        if ms.state is ms.State.OPERATIONAL:
            try:
                return MD.D_run()
            except Exception as error:
                MD.report_error(error)
    MD.failsafe2()
    return None


if __name__ == "__main__":
    results = run()
    ms.print_state()
    if results is None:
        print(f"run failed, last error: {ms.last_error!r}")
    for sheet_id, entry in (results or {}).items():
        if entry["error"]:
            print(f"\n{sheet_id}: FAILED, the other sheets were not affected: {entry['error']}")
            continue
        if entry["vet"]:
            print(f"\n{sheet_id}: not checked, fix the data first: {entry['vet']}")
            continue
        print(f"\n{sheet_id}: {len(entry['fraud'])} possible fraud out of {len(entry['irregular'])} irregular purchases")
        for purchase in entry["fraud"]:
            print(f"  row {purchase['row']} | {purchase['date']} | {purchase['item']} | ${purchase['amount']:.2f} | {purchase['reason']}")