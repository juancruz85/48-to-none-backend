import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from src import main, managerdaemon as MD, model, msm
from src.mattsheet import Sheet

BANK = (
    "Description,Date,Amount,Transaction_Type\n"
    "Apple,2026-10-31,-7.99,Payment\n"
    "Claude,2026-10-12,-20.00,Payment\n"
)


class TestRequests(unittest.TestCase):
    def setUp(self):
        msm.state = msm.State.STOPPED
        msm.last_error = None
        MD.sheets = {}
        MD.dashboard = {}
        mock.patch("src.model.load").start()
        self.respond = mock.patch("src.model.respond", return_value=[]).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(MD.stop_requests)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(MD.stop_logging)
        self.data_dir = Path(self.tmp.name) / "data"
        self.data_dir.mkdir()
        self.write("a.csv")
        self.write("b.csv")
        MD.LOG_DIR = Path(self.tmp.name) / "logs"
        main.initialize(self.data_dir)

    def write(self, name, text=BANK):
        path = self.data_dir / name
        changed = path.exists()
        path.write_text(text)
        if changed:
            # make sure the modified time moves even when the rewrite happens within the same clock tick
            stamp = path.stat().st_mtime_ns + 1_000_000_000
            os.utime(path, ns=(stamp, stamp))

    def test_request_runs_an_action_on_the_sheet(self):
        MD.request("a.csv", Sheet.delete_cell, 0, "Amount").result(5)

        self.assertTrue(MD.sheets["a.csv"].data.isna().loc[0, "Amount"])
        self.assertEqual(MD.sheets["a.csv"].transaction_history[-1]["action"], "delete_cell")

    def test_same_sheet_actions_run_one_at_a_time_in_order(self):
        running, overlaps, order = [], [], []

        def action(sheet, number):
            running.append(number)
            if len(running) > 1:
                overlaps.append(list(running))
            time.sleep(0.02)
            order.append(number)
            running.remove(number)

        futures = [MD.request("a.csv", action, number) for number in range(6)]
        for future in futures:
            future.result(5)

        self.assertEqual(overlaps, [])
        self.assertEqual(order, [0, 1, 2, 3, 4, 5])

    def test_different_sheets_run_at_the_same_time(self):
        both_running = threading.Barrier(2)

        def action(sheet):
            both_running.wait(5)  # only gets past this if the other sheet's action is running too
            return sheet.sheet_id

        a = MD.request("a.csv", action)
        b = MD.request("b.csv", action)

        self.assertEqual((a.result(5), b.result(5)), ("a.csv", "b.csv"))

    def test_request_is_refused_for_unknown_sheet_or_when_not_operational(self):
        with self.assertRaises(KeyError):
            MD.request("nope.csv", Sheet.reset)

        MD.report_error("down")
        with self.assertRaises(RuntimeError):
            MD.request("a.csv", Sheet.reset)

    def test_run_checks_sheets_at_the_same_time(self):
        both_running = threading.Barrier(2)

        def slow_model(sheet):
            both_running.wait(5)
            return []

        results = MD.D_run(slow_model)

        self.assertEqual(sorted(results), ["a.csv", "b.csv"])

    def test_run_does_not_hang_when_work_is_stopped_midway(self):
        def breaks_everything(sheet):
            MD.report_error("something broke elsewhere")
            return []

        with self.assertRaises(RuntimeError):
            MD.D_run(breaks_everything)

        self.assertEqual(msm.state, msm.State.ERROR)

    def test_model_is_only_used_by_one_sheet_at_a_time(self):
        mock.patch.stopall()
        in_model, overlaps = [], []

        def pipe(messages, **kwargs):
            in_model.append(1)
            if len(in_model) > 1:
                overlaps.append(1)
            time.sleep(0.01)
            in_model.pop()
            return [{"generated_text": "OK - fine"}]

        with mock.patch("src.model.load", return_value=pipe):
            results = MD.D_run()

        self.assertEqual(overlaps, [])
        self.assertEqual([entry["fraud"] for entry in results.values()], [[], []])

    def test_refresh_with_nothing_changed_does_nothing(self):
        MD.D_run()
        self.respond.reset_mock()

        self.assertEqual(MD.D_refresh(), {})
        self.respond.assert_not_called()

    def test_refresh_picks_up_new_changed_and_deleted_csvs(self):
        MD.D_run()
        self.respond.reset_mock()
        old_a = MD.sheets["a.csv"]
        self.write("new.csv")
        self.write("a.csv", BANK + "Apple,2026-11-01,-3.00,Payment\n")
        (self.data_dir / "b.csv").unlink()

        results = MD.D_refresh()

        self.assertEqual(sorted(results), ["a.csv", "new.csv"])
        self.assertEqual(sorted(MD.sheets), ["a.csv", "new.csv"])
        self.assertEqual(sorted(MD.dashboard), ["a.csv", "new.csv"])
        self.assertIsNot(MD.sheets["a.csv"], old_a)
        self.assertEqual(len(MD.sheets["a.csv"].data), 3)
        self.assertEqual(self.respond.call_count, 2)
        self.assertEqual(msm.state, msm.State.OPERATIONAL)

    def test_refresh_waits_for_actions_queued_on_the_old_sheet(self):
        release = threading.Event()
        seen = []

        def slow_action(sheet):
            release.wait(5)
            seen.append(len(sheet.data))

        MD.request("a.csv", slow_action)
        self.write("a.csv", BANK + "Apple,2026-11-01,-3.00,Payment\n")
        threading.Timer(0.05, release.set).start()

        MD.D_refresh()
        MD.request("a.csv", lambda sheet: seen.append(len(sheet.data))).result(5)

        self.assertEqual(seen, [2, 3])  # the queued action saw the old sheet, the one after the refresh saw the new one

    def test_refresh_skips_a_csv_it_cannot_read(self):
        self.write("broken.csv", "")

        self.assertEqual(MD.D_refresh(), {})

        self.assertNotIn("broken.csv", MD.sheets)
        self.assertEqual(msm.state, msm.State.OPERATIONAL)

    def test_serve_refreshes_then_shuts_down(self):
        real_sleep = time.sleep

        def add_a_csv(seconds):
            if seconds == 7:
                self.write("late.csv")
            else:
                real_sleep(seconds)

        with mock.patch("time.sleep", side_effect=add_a_csv):
            results = main.serve(self.data_dir, interval=7, cycles=1)

        self.assertEqual(sorted(results), ["a.csv", "b.csv", "late.csv"])
        self.assertEqual(msm.state, msm.State.STOPPED)


if __name__ == "__main__":
    unittest.main()
