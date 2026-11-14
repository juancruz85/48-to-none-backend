"""
_________________________________________

TZWATZWATZWA!!!

_____________________________________________________
"""
###################################################################
"""
DATASHEET CODE
"""
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
using this meta data and history we can reorganize it and vet it (vet meaning analyze/check if it's right) to the manager than the manager can send it over to the


"""

"""
LIBS
"""
#XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
from dataclasses import dataclass


#XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX




@dataclass 
class Sheet:
    #class for a respective datasheet.
    #has transaction history, has date, has specific data (please fill in later)

    #add method to reset datasheet
    #add variable to mark data sheet corrct 

    is_sorted bool = False

    pass
