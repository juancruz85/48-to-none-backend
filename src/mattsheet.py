"""
_________________________________________

TZWATZWATZWA!!!

_____________________________________________________
"""
###################################################################
"""
DATASHEET CODE
"""
#####################################################################
"""
ABS:
Datasheet is a class
each class has actions such as moving specific cells and lists and other data groups
these actions are functions themselves and can edit the main csv file attatched to the csv object.

In layman's terms:

Datasheet class

Datasheet object owns it's own csv.
the csv can be manipulated through actions innate to datasheet class

datasheet class is a dataclass

datasheets have
transaction history
log dates
person name
bank(s) -> add logic for variable banks
places

essentially metadata^^
using this metadata and history we can reorganize it and vet it (vet meaning analyze/check if it's right) to the manager than the manager can send it over to the


datasheet subactions:
move cell
delete cell





"""
#XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXxx








"""
LIBS
"""
#XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
from dataclasses import dataclass


#XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX


"""
Glob Var
"""


#####################################################
"""
CLASSES
"""
#dataclass notes:
"""
Data class is just a class that omits some boilerplate code

__repr__ allows you to see the set data for a given object.


"""
@dataclass 
class Sheet:
    """Datasheet object for a specific CSV-backed sheet.

    Planned features and metadata:
    - transaction history: records of all actions and entries
    - log dates: timestamp tracking for each transaction or update
    - person name: who created/owns the sheet or submitted the data
    - bank(s): support for one or more bank sources/targets
    - places: location metadata tied to entries
    - sheet metadata: reusable information used to organize, analyze, and vet records
    - data actions: move cell, delete cell, add/remove rows/columns, sort, reset
    """

    # class for a respective datasheet.
    # has transaction history, has date, has specific data (please fill in later)

    # add method to reset datasheet
    # add method to sort rows/columns based on metadata and history
    # add method to vet/check entries for accuracy before export
    # add method to move a cell from one location to another
    # add method to delete a cell or record from the sheet

    # future metadata fields:
    # transaction_history: list = field(default_factory=list)
    # log_dates: list[str] = field(default_factory=list)
    # person_name: str = ""
    # banks: list[str] = field(default_factory=list)
    # places: list[str] = field(default_factory=list)

    # Variable to toggle once a data sheet is sorted/validated.




    
    is_sorted: bool = False

    pass
######################################################################################3




"""
Functions
"""


##################################################################