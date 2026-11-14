import tempfile
import unittest
from pathlib import Path

from src import managerdaemon as MD

DATA_DIR = Path(__file__).resolve().parent.parent / "purchase_data"

CSV = (
    "Description,Date,Amount,Transaction_Type\n"
    "Apple,31/10/26,-7.99,Payment\n"
    "Claude,12/10/26,-20.00,Payment\n"
    "Apple,8/10/26,-39.95,Payment\n"
)


class TestSheet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "bank.csv"
        self.path.write_text(CSV)
        self.sheet = MD.D_createsheet(self.path, person_name="Sam", banks=["Chase"])

    def test_createsheet_attaches_metadata(self):
        self.assertEqual(self.sheet.sheet_id, "bank.csv")
        self.assertEqual(self.sheet.source, str(self.path))
        self.assertEqual(self.sheet.person_name, "Sam")
        self.assertEqual(self.sheet.banks, ["Chase"])
        self.assertEqual(self.sheet.places, ["Apple", "Claude"])
        self.assertEqual(len(self.sheet.data), 3)

    def test_load_creates_one_sheet_per_input(self):
        sheets = MD.D_load(DATA_DIR)

        self.assertEqual(sorted(sheets), ["data.csv", "evildata.csv"])
        for name, sheet in sheets.items():
            self.assertEqual(sheet.sheet_id, name)

    def test_sort_orders_by_real_date(self):
        self.sheet.sort("Date")

        self.assertEqual(self.sheet.data["Date"].tolist(), ["8/10/26", "12/10/26", "31/10/26"])
        self.assertTrue(self.sheet.is_sorted)

    def test_iso_dates_sort_year_first(self):
        self.path.write_text("Date,Amount\n2026-11-03,1\n2026-03-11,2\n2026-10-14,3\n")
        sheet = MD.D_createsheet(self.path)

        sheet.sort("Date")

        self.assertEqual(sheet.data["Amount"].tolist(), [2, 3, 1])

    def test_vet_clean_sheet(self):
        self.assertEqual(self.sheet.vet(), [])

    def test_vet_reports_problems(self):
        self.path.write_text("Date,Amount\nYesterday,5\n1/10/26,abc\n2/10/26,\n")
        problems = MD.D_createsheet(self.path).vet()

        self.assertEqual(
            problems,
            [
                "Amount: missing values",
                "Date: unreadable values ['Yesterday']",
                "Amount: unreadable values ['abc']",
            ],
        )

    def test_move_cell(self):
        self.sheet.move_cell((0, "Description"), (1, "Description"))

        self.assertEqual(self.sheet.data.loc[1, "Description"], "Apple")
        self.assertTrue(self.sheet.data.isna().loc[0, "Description"])

    def test_delete_cell_and_record(self):
        self.sheet.delete_cell(0, "Amount")
        self.assertTrue(self.sheet.data.isna().loc[0, "Amount"])

        self.sheet.delete_cell(1)
        self.assertEqual(self.sheet.data.index.tolist(), [0, 2])

    def test_missing_cell_raises(self):
        with self.assertRaises(KeyError):
            self.sheet.delete_cell(99, "Amount")
        with self.assertRaises(KeyError):
            self.sheet.move_cell((0, "Amount"), (0, "Nope"))

    def test_reset_restores_loaded_data(self):
        self.sheet.sort("Date")
        self.sheet.delete_cell(0)

        self.sheet.reset()

        self.assertEqual(self.sheet.data["Date"].tolist(), ["31/10/26", "12/10/26", "8/10/26"])
        self.assertFalse(self.sheet.is_sorted)

    def test_actions_are_logged(self):
        self.sheet.sort("Date")
        self.sheet.delete_cell(0, "Amount")

        actions = [entry["action"] for entry in self.sheet.transaction_history]
        self.assertEqual(actions, ["sort", "delete_cell"])
        self.assertEqual(len(self.sheet.log_dates), 2)

    def test_organize_keeps_identity(self):
        organized = MD.D_organize(self.sheet)

        self.assertIs(organized, self.sheet)
        self.assertEqual(organized.sheet_id, "bank.csv")
        self.assertTrue(organized.is_sorted)
        self.assertEqual(organized.results["vet"], [])


if __name__ == "__main__":
    unittest.main()
