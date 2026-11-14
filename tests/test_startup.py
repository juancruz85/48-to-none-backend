import tempfile
import unittest
from pathlib import Path

from src import main, managerdaemon, msm


class TestStartup(unittest.TestCase):
    def setUp(self):
        msm.state = msm.State.STOPPED
        msm.last_error = None
        managerdaemon.sheets = {}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)

    def write_csv(self, name="a.csv"):
        (self.data_dir / name).write_text("Date,Amount\n2026-01-01,5.00\n")

    def test_startup_loads_data_and_goes_operational(self):
        self.write_csv("a.csv")
        self.write_csv("b.csv")

        sheets = main.initialize(self.data_dir)

        self.assertEqual(msm.state, msm.State.OPERATIONAL)
        self.assertEqual(sorted(sheets), ["a.csv", "b.csv"])
        self.assertEqual(len(sheets["a.csv"].data), 1)
        self.assertIs(managerdaemon.sheets, sheets)

    def test_startup_without_data_enters_error(self):
        self.assertIsNone(main.initialize(self.data_dir))

        self.assertEqual(msm.state, msm.State.ERROR)
        self.assertIsInstance(msm.last_error, FileNotFoundError)

    def test_recall_after_error_power_cycles(self):
        main.initialize(self.data_dir)
        self.assertEqual(msm.state, msm.State.ERROR)

        self.write_csv()
        main.initialize(self.data_dir)

        self.assertEqual(msm.state, msm.State.OPERATIONAL)

    def test_real_purchase_data_loads(self):
        sheets = main.initialize()

        self.assertEqual(msm.state, msm.State.OPERATIONAL)
        self.assertIn("data.csv", sheets)


if __name__ == "__main__":
    unittest.main()
