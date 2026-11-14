import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from src import main, managerdaemon as MD, msm
from src.mattsheet import Sheet

BANK = (
    "Description,Date,Amount,Transaction_Type\n"
    "Apple,2026-10-31,-7.99,Payment\n"
    "Claude,2026-10-12,-20.00,Payment\n"
)


class TestSupervision(unittest.TestCase):
    def setUp(self):
        msm.state = msm.State.STOPPED
        msm.last_error = None
        MD.sheets = {}
        MD.dashboard = {}
        self.load = mock.patch("src.model.load").start()
        self.respond = mock.patch("src.model.respond", return_value=[]).start()
        self.addCleanup(mock.patch.stopall)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name) / "data"
        self.data_dir.mkdir()
        (self.data_dir / "a.csv").write_text(BANK)
        (self.data_dir / "b.csv").write_text(BANK)
        MD.LOG_DIR = Path(self.tmp.name) / "logs"

    def log_text(self):
        return (MD.LOG_DIR / "manager.log").read_text()

    def test_clean_run_logs_activity(self):
        results = main.run(self.data_dir)

        self.assertEqual(sorted(results), ["a.csv", "b.csv"])
        log = self.log_text()
        self.assertIn("state stopped -> starting", log)
        self.assertIn("loaded 2 sheet(s)", log)
        self.assertIn("checking a.csv", log)
        self.assertIn("b.csv done: 2 irregular (2 sent to the model), 0 possible fraud", log)
        self.assertFalse((MD.LOG_DIR / "dev_report.txt").exists())

    def test_failure_of_every_sheet_is_fixed_by_recovery(self):
        self.respond.side_effect = [RuntimeError("model hiccup"), RuntimeError("model hiccup"), [], []]

        results = main.run(self.data_dir)

        self.assertEqual(sorted(results), ["a.csv", "b.csv"])
        self.assertEqual(msm.state, msm.State.OPERATIONAL)
        self.assertEqual(self.load.call_count, 2)  # startup, then the recovery check. no power cycle.
        log = self.log_text()
        self.assertIn("error reported: RuntimeError('model hiccup')", log)
        self.assertIn("Traceback", log)
        self.assertIn("trying recovery", log)
        self.assertNotIn("failsafe 1", log)

    def test_second_failure_of_every_sheet_is_fixed_by_failsafe_1(self):
        self.respond.side_effect = [RuntimeError("one")] * 2 + [RuntimeError("two")] * 2 + [[], []]

        results = main.run(self.data_dir)

        self.assertEqual(sorted(results), ["a.csv", "b.csv"])
        self.assertEqual(msm.state, msm.State.OPERATIONAL)
        self.assertIn("trying failsafe 1 (power cycle)", self.log_text())
        self.assertFalse((MD.LOG_DIR / "dev_report.txt").exists())

    def test_failure_that_never_goes_away_reaches_failsafe_2(self):
        self.respond.side_effect = RuntimeError("model is broken")

        self.assertIsNone(main.run(self.data_dir))

        self.assertEqual(msm.state, msm.State.ERROR)
        self.assertEqual(self.respond.call_count, 6)  # both sheets on the first try, after recovery, after failsafe 1
        report = (MD.LOG_DIR / "dev_report.txt").read_text()
        self.assertIn("FAILSAFE 2", report)
        self.assertIn("RuntimeError('model is broken')", report)
        self.assertIn("Traceback", report)
        self.assertIn("sheets loaded: ['a.csv', 'b.csv']", report)

    def test_startup_that_cannot_work_reaches_failsafe_2(self):
        self.assertIsNone(main.run(Path(self.tmp.name) / "missing"))

        self.assertEqual(msm.state, msm.State.ERROR)
        self.respond.assert_not_called()
        self.assertIn("No csv input found", (MD.LOG_DIR / "dev_report.txt").read_text())

    def test_one_bad_sheet_does_not_stop_the_others(self):
        (self.data_dir / "bad.csv").write_text("When,Item,Amount\n2026-10-31,Thing,5.00\n")

        results = main.run(self.data_dir)

        self.assertEqual(msm.state, msm.State.OPERATIONAL)
        self.assertEqual(sorted(results), ["a.csv", "b.csv", "bad.csv"])
        self.assertEqual(results["bad.csv"]["error"], "KeyError('Date')")
        self.assertIsNone(results["bad.csv"]["fraud"])
        for good in ("a.csv", "b.csv"):
            self.assertIsNone(results[good]["error"])
            self.assertEqual(results[good]["fraud"], [])
        self.assertEqual(self.respond.call_count, 2)
        self.assertIn("bad.csv failed, the other sheets carry on", self.log_text())
        self.assertNotIn("trying recovery", self.log_text())
        self.assertFalse((MD.LOG_DIR / "dev_report.txt").exists())

    def test_sheet_that_failed_is_tried_again_on_the_next_run(self):
        main.initialize(self.data_dir)

        def hiccup_on_a(sheet):
            if sheet.sheet_id == "a.csv":
                raise RuntimeError("hiccup on a")
            return []

        self.respond.side_effect = hiccup_on_a
        self.assertEqual(MD.D_run()["a.csv"]["error"], "RuntimeError('hiccup on a')")

        self.respond.side_effect = None
        results = MD.D_run()

        self.assertIsNone(results["a.csv"]["error"])
        self.assertEqual(results["a.csv"]["fraud"], [])

    def test_work_stops_once_an_error_is_reported(self):
        main.initialize(self.data_dir)
        queued = threading.Event()

        def sees_a_problem(sheet):
            queued.wait(5)
            MD.report_error("something broke elsewhere")

        first = MD.request("a.csv", sees_a_problem)
        second = MD.request("a.csv", Sheet.reset)
        queued.set()
        first.result(5)

        self.assertTrue(second.cancelled())  # it was queued behind the error, so it never ran
        self.assertEqual(MD.sheets["a.csv"].transaction_history, [])
        with self.assertRaises(RuntimeError):
            MD.request("b.csv", Sheet.reset)
        with self.assertRaises(RuntimeError):
            MD.D_run()

    def test_recover_fails_when_the_model_will_not_load(self):
        main.initialize(self.data_dir)
        MD.report_error("boom")
        self.load.side_effect = OSError("model files are gone")

        self.assertEqual(MD.recover(), msm.State.ERROR)
        self.assertIsInstance(msm.last_error, OSError)


if __name__ == "__main__":
    unittest.main()
