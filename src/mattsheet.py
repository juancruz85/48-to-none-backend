"""
_________________________________________

TZWATZWATZWA!!!

_____________________________________________________
"""

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
using this metadata and history we can reorganize it and vet it (vet meaning analyze/check if it's right) to the manager than the manager can send it over to the


datasheet subactions:
move cell
delete cell





"""


"""
LIBS
"""
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd


"""
Glob Var
"""


"""
CLASSES
"""
#dataclass notes:
"""
Data class is just a class that omits some boilerplate code

__repr__ allows you to see the set data for a given object.


"""
def D_dates(column):
    dayfirst = not column.astype(str).str.match(r"\d{4}-").any()
    return pd.to_datetime(column, errors="coerce", format="mixed", dayfirst=dayfirst)


@dataclass(eq=False)
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

    # sheet_id is the sheet's identity. it never changes, so results can always be routed back to the right sheet.
    sheet_id: str
    data: pd.DataFrame = field(repr=False)
    source: str = ""

    transaction_history: list = field(default_factory=list)
    log_dates: list[str] = field(default_factory=list)
    person_name: str = ""
    banks: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)

    # analysis output and model responses get attached here so they stay with their sheet.
    results: dict = field(default_factory=dict)

    # Variable to toggle once a data sheet is sorted/validated.




    
    is_sorted: bool = False

    def __post_init__(self):
        self._original = self.data.copy()

    def _log(self, action, **details):
        self.transaction_history.append({"action": action, **details})
        self.log_dates.append(datetime.now().isoformat(timespec="seconds"))

    def _check(self, row, column):
        if row not in self.data.index or column not in self.data.columns:
            raise KeyError(f"{self.sheet_id}: no cell at row {row!r}, column {column!r}")

    def reset(self):
        self.data = self._original.copy()
        self.is_sorted = False
        self._log("reset")

    def sort(self, by="Date", ascending=True):
        #rows are renumbered from 0 afterwards.
        key = D_dates if by == "Date" else None
        self.data = self.data.sort_values(by, ascending=ascending, key=key).reset_index(drop=True)
        self.is_sorted = True
        self._log("sort", by=by, ascending=ascending)

    def vet(self):
        problems = []
        if self.data.empty:
            problems.append("sheet has no rows")
        for column in self.data.columns[self.data.isna().any()]:
            problems.append(f"{column}: missing values")
        for column in self.data.columns:
            values = self.data[column].dropna()
            if column.startswith("Amount"):
                bad = values[pd.to_numeric(values, errors="coerce").isna()]
            elif column == "Date":
                bad = values[D_dates(values).isna()]
            else:
                continue
            if not bad.empty:
                problems.append(f"{column}: unreadable values {bad.tolist()}")
        self._log("vet", problems=len(problems))
        return problems

    def move_cell(self, source, target):
        #source and target are (row, column).
        self._check(*source)
        self._check(*target)
        self.data.loc[target[0], target[1]] = self.data.loc[source[0], source[1]]
        self.data.loc[source[0], source[1]] = None
        self._log("move_cell", source=source, target=target)

    def delete_cell(self, row, column=None):
        if column is None:
            self._check(row, self.data.columns[0])
            self.data = self.data.drop(index=row)
        else:
            self._check(row, column)
            self.data.loc[row, column] = None
        self._log("delete_cell", row=row, column=column)



"""
Functions
"""