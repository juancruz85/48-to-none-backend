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

import numpy as np
import pandas as pd
from . import msm as ms
from . import mattsheet as ds
from . import managerdaemon as MD
from . import common as c

""" FUNCTIONS """





# def Initilize():
"""
set startup global to true then false
Wake man, fetch data, start processes
"""