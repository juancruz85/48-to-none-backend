import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from src import api, main, managerdaemon as MD, msm

STORE = (
    "Date,Item,Amount (USD)\n"
    "2026-09-03,Premium Individual (Spotify),12.99\n"
    "2026-10-03,Premium Individual (Spotify),12.99\n"
    "2026-11-03,Gems,4.99\n"
    "2026-11-03,Gems,4.99\n"
    "2026-11-04,$2 Google Play Credit,0.00\n"
)
BANK = (
    "Description,Date,Amount,Transaction_Type\n"
    "Apple,2026-10-31,-7.99,Payment\n"
    "Refund,2026-11-01,5.00,Refund\n"
)
BROKEN = "Date,Item,Amount (USD)\n2026-11-03,Gems,not-a-number\n"


def flag_everything(sheet):
    return [{**purchase, "reason": "looks wrong"} for purchase in sheet.results["irregular"]]


def clear_everything(sheet):
    return []


class TestApi(unittest.TestCase):
    def setUp(self):
        msm.state = msm.State.STOPPED
        msm.last_error = None
        MD.sheets = {}
        MD.dashboard = {}
        MD.abandoned.clear()
        api.gave_up = None
        api.data_dir = None
        api._wake.clear()
        mock.patch("src.model.load").start()
        self.addCleanup(mock.patch.stopall)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(MD.stop_logging)
        self.addCleanup(MD.stop_requests)
        self.data_dir = Path(self.tmp.name)
        MD.LOG_DIR = Path(self.tmp.name) / "logs"
        (self.data_dir / "store.csv").write_text(STORE)
        (self.data_dir / "bank.csv").write_text(BANK)

    def sheet(self, report, sheet_id):
        return next(sheet for sheet in report["sheets"] if sheet["sheet_id"] == sheet_id)

    def test_sheets_are_checking_until_the_model_has_answered(self):
        main.initialize(self.data_dir)

        report = api.report()

        self.assertEqual(report["state"], "operational")
        self.assertTrue(report["busy"])
        store = self.sheet(report, "store.csv")
        self.assertEqual(store["status"], "checking")
        self.assertEqual(store["totals"]["transactions"], 5)
        self.assertEqual({t["status"] for t in store["transactions"]}, {"ok"})

    def test_flagged_purchase_carries_reason_and_signals(self):
        main.initialize(self.data_dir)
        MD.D_run(flag_everything)

        report = api.report()

        self.assertFalse(report["busy"])
        store = self.sheet(report, "store.csv")
        self.assertEqual(store["status"], "done")
        flagged = [t for t in store["transactions"] if t["status"] == "fraud"]
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["item"], "Gems")
        self.assertEqual(flagged[0]["reason"], "looks wrong")
        self.assertIn("duplicate charge", flagged[0]["signals"][0])
        self.assertEqual(store["totals"]["fraud"], 1)
        self.assertEqual(store["totals"]["at_risk"], 4.99)
        self.assertEqual(store["totals"]["paid"], 4)
        self.assertEqual(store["totals"]["spent"], 35.96)
        self.assertIn("total spent", store["analysis"])

    def test_irregular_purchase_the_model_passed_is_cleared(self):
        main.initialize(self.data_dir)
        MD.D_run(clear_everything)

        store = self.sheet(api.report(), "store.csv")

        self.assertEqual([t["status"] for t in store["transactions"]].count("cleared"), 1)
        self.assertEqual(store["totals"]["fraud"], 0)
        self.assertEqual(store["totals"]["irregular"], 1)

    def test_bank_layout_counts_spending_as_positive_and_money_in_as_negative(self):
        main.initialize(self.data_dir)
        MD.D_run(clear_everything)

        bank = self.sheet(api.report(), "bank.csv")

        self.assertEqual([t["amount"] for t in bank["transactions"]], [7.99, -5.0])
        self.assertEqual(bank["totals"]["spent"], 7.99)

    def test_sheet_that_fails_vetting_is_reported_not_checked(self):
        (self.data_dir / "broken.csv").write_text(BROKEN)
        main.initialize(self.data_dir)
        MD.D_run(flag_everything)

        broken = self.sheet(api.report(), "broken.csv")

        self.assertEqual(broken["status"], "needs_fixing")
        self.assertTrue(broken["vet"])

    def test_report_is_valid_json_without_nan(self):
        main.initialize(self.data_dir)
        MD.D_run(flag_everything)

        text = json.dumps(api.report(), allow_nan=False)

        self.assertIn("store.csv", text)

    def test_http_routes(self):
        main.initialize(self.data_dir)
        MD.D_run(flag_everything)
        server = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"

        with urllib.request.urlopen(f"{base}/report") as response:
            report = json.load(response)
        with urllib.request.urlopen(f"{base}/health") as response:
            health = json.load(response)
        with self.assertRaises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(f"{base}/nope")

        self.assertEqual(len(report["sheets"]), 2)
        self.assertEqual(health, {"ok": True, "state": "operational"})
        self.assertEqual(missing.exception.code, 404)
        missing.exception.close()


def _creeping():
    """A statement where one seller's $0.99 charges go from 2 a month to one every day."""
    lines = ["Description,Date,Amount,Transaction_Type"]
    for month in ("06", "07", "08", "09", "10"):
        lines.append(f"Rent,2026-{month}-01,-900.00,Payment")
        for day in ("05", "12", "19", "26"):
            lines.append(f"Grocer,2026-{month}-{day},-60.00,Payment")
    for day in ("2026-06-10", "2026-06-24", "2026-07-08", "2026-07-22", "2026-08-05", "2026-08-19"):
        lines.append(f"APPLE.COM/BILL,{day},-0.99,Payment")
    for day in range(1, 29):
        lines.append(f"APPLE.COM/BILL,2026-10-{day:02d},-0.99,Payment")
    return "\n".join(lines) + "\n"


def suspicious_patterns(sheet):
    return [{**pattern, "reason": "keeps growing"} for pattern in sheet.results["patterns"]]


def model_with_pattern_review(sheet):
    return []


model_with_pattern_review.review_patterns = suspicious_patterns


class TestSuspiciousPatterns(unittest.TestCase):
    def setUp(self):
        msm.state = msm.State.STOPPED
        msm.last_error = None
        MD.sheets = {}
        MD.dashboard = {}
        MD.abandoned.clear()
        api.gave_up = None
        api.data_dir = None
        mock.patch("src.model.load").start()
        self.addCleanup(mock.patch.stopall)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(MD.stop_logging)
        self.addCleanup(MD.stop_requests)
        self.data_dir = Path(self.tmp.name)
        MD.LOG_DIR = Path(self.tmp.name) / "logs"
        (self.data_dir / "creeping.csv").write_text(_creeping())

    def report(self, model):
        main.initialize(self.data_dir)
        MD.D_run(model)
        return api.report()["sheets"][0]

    def test_rising_small_charges_are_marked_suspicious_not_fraud(self):
        sheet = self.report(model_with_pattern_review)

        marked = [t for t in sheet["transactions"] if t["status"] == "suspicious"]
        self.assertTrue(marked)
        self.assertEqual({t["item"] for t in marked}, {"APPLE.COM/BILL"})
        self.assertTrue(all(t["date"].startswith("2026-10") for t in marked))
        self.assertEqual(marked[0]["reason"], "keeps growing")
        self.assertIn("charges from APPLE.COM/BILL", marked[0]["signals"][-1])
        self.assertEqual(sheet["totals"]["fraud"], 0)
        self.assertEqual(sheet["totals"]["suspicious"], len(marked))
        self.assertEqual(sheet["totals"]["suspicious_amount"], round(0.99 * len(marked), 2))

    def test_pattern_summary_is_reported_with_the_models_reason(self):
        sheet = self.report(model_with_pattern_review)

        self.assertEqual(len(sheet["patterns"]), 1)
        pattern = sheet["patterns"][0]
        self.assertEqual((pattern["item"], pattern["suspicious"], pattern["reason"]), ("APPLE.COM/BILL", True, "keeps growing"))
        self.assertEqual(pattern["charges"], 34)
        self.assertEqual([m["charges"] for m in pattern["months"]], [2, 2, 2, 0, 28])
        self.assertNotIn("rows", pattern)

    def test_pattern_the_model_passes_is_reported_but_nothing_is_marked(self):
        passes = lambda sheet: []
        passes.review_patterns = lambda sheet: []

        sheet = self.report(passes)

        self.assertEqual([p["suspicious"] for p in sheet["patterns"]], [False])
        self.assertEqual(sheet["totals"]["suspicious"], 0)

    def test_steady_sellers_are_not_a_pattern(self):
        sheet = self.report(model_with_pattern_review)

        self.assertNotIn("Grocer", [p["item"] for p in sheet["patterns"]])
        self.assertNotIn("Rent", [p["item"] for p in sheet["patterns"]])

    def test_a_purchase_the_model_calls_fraud_stays_fraud_inside_a_pattern(self):
        def model(sheet):
            return [{**purchase, "reason": "dup"} for purchase in sheet.results["irregular"]][:1]
        model.review_patterns = suspicious_patterns
        (self.data_dir / "creeping.csv").write_text(_creeping() + "APPLE.COM/BILL,2026-10-28,-0.99,Payment\n")

        sheet = self.report(model)

        self.assertEqual(sheet["totals"]["fraud"], 1)
        self.assertEqual([t["reason"] for t in sheet["transactions"] if t["status"] == "fraud"], ["dup"])

    def test_stand_in_model_without_a_reviewer_never_reaches_the_real_model(self):
        with mock.patch("src.model.review_patterns") as real:
            sheet = self.report(clear_everything)

        real.assert_not_called()
        self.assertEqual(len(sheet["patterns"]), 1)
        self.assertEqual(sheet["totals"]["suspicious"], 0)


P1, P2 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
A1, A2 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class TestUploads(unittest.TestCase):
    def setUp(self):
        msm.state = msm.State.STOPPED
        msm.last_error = None
        MD.sheets = {}
        MD.dashboard = {}
        MD.unreadable.clear()
        MD.abandoned.clear()
        api.gave_up = None
        api._wake.clear()
        mock.patch("src.model.load").start()
        self.addCleanup(mock.patch.stopall)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(MD.stop_logging)
        self.addCleanup(MD.stop_requests)
        api.data_dir = Path(self.tmp.name) / "user_data"
        self.addCleanup(setattr, api, "data_dir", None)
        MD.LOG_DIR = Path(self.tmp.name) / "logs"

    def test_upload_is_saved_under_its_owner_and_wakes_the_manager(self):
        sheet_id = api.save_sheet(P1, A1, "My Bank (Nov).csv", STORE.encode())

        self.assertEqual(sheet_id, f"{P1}__{A1}__My Bank (Nov).csv")
        self.assertEqual((api.data_dir / sheet_id).read_text(), STORE)
        self.assertEqual(api.owner(sheet_id), (P1, A1, "My Bank (Nov).csv"))
        self.assertTrue(api._wake.is_set())
        self.assertEqual(list(api.data_dir.glob("*.part")), [])

    def test_upload_name_cannot_leave_the_folder(self):
        sheet_id = api.save_sheet(P1, A1, "../../etc/passwd.csv", STORE.encode())

        self.assertEqual(sheet_id, f"{P1}__{A1}__passwd.csv")
        self.assertEqual([path.name for path in Path(self.tmp.name).rglob("*.csv")], [sheet_id])

    def test_bad_uploads_are_refused(self):
        cases = [
            (P1, A1, "notes.txt", STORE.encode()),
            (P1, A1, ".csv", STORE.encode()),
            (P1, A1, "empty.csv", b"  "),
            (P1, A1, "no-columns.csv", b"a,b\n1,2\n"),
            (P1, A1, "big.csv", b"Date,Item,Amount\n" + b"x" * (api.MAX_UPLOAD_BYTES + 1)),
            ("../x", A1, "a.csv", STORE.encode()),
            (P1, "not an id", "a.csv", STORE.encode()),
        ]
        for profile_id, account_id, name, content in cases:
            with self.subTest(name=name, profile=profile_id, account=account_id):
                with self.assertRaises(api.BadRequest):
                    api.save_sheet(profile_id, account_id, name, content)
        self.assertEqual(api._files(), [])

    def test_report_only_shows_the_profiles_own_sheets(self):
        api.save_sheet(P1, A1, "mine.csv", STORE.encode())
        api.save_sheet(P2, A2, "theirs.csv", BANK.encode())
        main.initialize(api.data_dir)
        MD.D_run(flag_everything)

        mine = api.report(P1)
        everything = api.report()

        self.assertEqual([(s["account_id"], s["name"], s["status"]) for s in mine["sheets"]], [(A1, "mine.csv", "done")])
        self.assertEqual(mine["sheets"][0]["totals"]["fraud"], 1)
        self.assertEqual(len(everything["sheets"]), 2)
        self.assertNotIn("theirs", json.dumps(mine))

    def test_uploaded_sheet_shows_as_checking_before_the_manager_picks_it_up(self):
        api.save_sheet(P1, A1, "new.csv", STORE.encode())

        report = api.report(P1)

        self.assertEqual(report["state"], "waiting")
        self.assertTrue(report["busy"])
        self.assertEqual([(s["name"], s["status"]) for s in report["sheets"]], [("new.csv", "checking")])

    def test_empty_profile_is_waiting_and_not_busy(self):
        report = api.report(P1)

        self.assertEqual((report["state"], report["busy"], report["sheets"]), ("waiting", False, []))

    def test_delete_one_sheet_or_a_whole_account(self):
        api.save_sheet(P1, A1, "one.csv", STORE.encode())
        api.save_sheet(P1, A1, "two.csv", STORE.encode())
        api.save_sheet(P1, A2, "other-account.csv", STORE.encode())
        api._wake.clear()

        self.assertEqual(api.delete_sheets(P1, A1, "one.csv"), 1)
        self.assertEqual(api.delete_sheets(P1, A1, "one.csv"), 0)
        self.assertTrue(api._wake.is_set())
        self.assertEqual(api.delete_sheets(P1, A1), 1)

        self.assertEqual([path.name for path in api._files()], [f"{P1}__{A2}__other-account.csv"])

    def test_deleted_sheet_leaves_the_report_before_the_next_refresh(self):
        api.save_sheet(P1, A1, "gone.csv", STORE.encode())
        main.initialize(api.data_dir)
        MD.D_run(flag_everything)

        api.delete_sheets(P1, A1, "gone.csv")

        self.assertEqual(api.report(P1)["sheets"], [])

    def test_upload_and_delete_over_http(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"

        def call(method, path, body=None):
            request = urllib.request.Request(f"{base}{path}", data=body, method=method)
            try:
                with urllib.request.urlopen(request) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as error:
                with error:
                    return error.code, json.load(error)

        status, saved = call("PUT", f"/sheets/{P1}/{A1}/my%20bank.csv", STORE.encode())
        self.assertEqual((status, saved["name"]), (201, "my bank.csv"))

        status, body = call("PUT", f"/sheets/{P1}/{A1}/bad.csv", b"a,b\n1,2\n")
        self.assertEqual((status, body["error"]["code"]), (400, "INVALID_REQUEST"))
        self.assertIn("missing the column", body["error"]["message"])

        status, report = call("GET", f"/report?profile={P1}")
        self.assertEqual((status, [s["name"] for s in report["sheets"]]), (200, ["my bank.csv"]))
        self.assertEqual(call("GET", "/report?profile=../etc")[0], 400)

        self.assertEqual(call("DELETE", f"/sheets/{P1}/{A1}/my%20bank.csv"), (200, {"deleted": 1}))
        self.assertEqual(call("GET", f"/report?profile={P1}")[1]["sheets"], [])


if __name__ == "__main__":
    unittest.main()
