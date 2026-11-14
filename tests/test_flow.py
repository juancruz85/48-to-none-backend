import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import main, managerdaemon as MD, model, msm

BANK = (
    "Description,Date,Amount,Transaction_Type\n"
    "Apple,2026-10-31,-7.99,Payment\n"
    "Claude,2026-10-12,-20.00,Payment\n"
)
STORE = (
    "Date,Item,Amount (USD)\n"
    "2026-11-03,Premium Individual (Spotify),12.99\n"
    "2026-10-03,Premium Individual (Spotify),12.99\n"
    "2026-09-03,Premium Individual (Spotify),12.99\n"
    "2026-09-22,$2 Google Play Credit,0.00\n"
)


def fake_model(sheet):
    return f"model saw {sheet.sheet_id} with {len(sheet.data)} rows"


class TestFlow(unittest.TestCase):
    def setUp(self):
        msm.state = msm.State.STOPPED
        msm.last_error = None
        MD.sheets = {}
        MD.dashboard = {}
        mock.patch("src.model.load").start()
        self.addCleanup(mock.patch.stopall)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        MD.LOG_DIR = Path(self.tmp.name) / "logs"
        (self.data_dir / "bank.csv").write_text(BANK)
        (self.data_dir / "store.csv").write_text(STORE)

    def test_analysis_is_returned_as_text_for_both_layouts(self):
        sheets = MD.D_load(self.data_dir)

        bank = MD.D_analyze(sheets["bank.csv"]).results["analysis"]
        store = MD.D_analyze(sheets["store.csv"]).results["analysis"]

        self.assertIn("Rows: 2 | paid: 2 | $0: 0 | total spent: $27.99", bank)
        self.assertIn("Rows: 4 | paid: 3 | $0: 1 | total spent: $38.97", store)
        self.assertIn("Spotify", store)

    def test_run_routes_each_result_back_to_its_sheet(self):
        main.initialize(self.data_dir)

        payloads = MD.D_run(fake_model)

        self.assertEqual(sorted(payloads), ["bank.csv", "store.csv"])
        for sheet_id, payload in payloads.items():
            rows = len(MD.sheets[sheet_id].data)
            expected = f"model saw {sheet_id} with {rows} rows"
            self.assertEqual(payload["sheet_id"], sheet_id)
            self.assertEqual(payload["fraud"], expected)
            self.assertEqual(MD.sheets[sheet_id].results["fraud"], expected)
            self.assertIs(MD.dashboard[sheet_id], payload)
        self.assertEqual(payloads["bank.csv"]["places"], ["Apple", "Claude"])

    def test_result_for_unknown_sheet_is_rejected(self):
        MD.D_load(self.data_dir)

        with self.assertRaises(KeyError):
            MD.D_result({"sheet_id": "nope.csv", "response": "x"})

    def test_sheet_that_fails_vetting_is_not_sent(self):
        (self.data_dir / "bank.csv").write_text(BANK + "Apple,Yesterday,-1.00,Payment\n")
        main.initialize(self.data_dir)
        model = mock.Mock(side_effect=fake_model)

        payloads = MD.D_run(model)

        self.assertEqual([call.args[0].sheet_id for call in model.call_args_list], ["store.csv"])
        self.assertIsNone(payloads["bank.csv"]["fraud"])
        self.assertEqual(payloads["bank.csv"]["vet"], ["Date: unreadable values ['Yesterday']"])

    def test_run_needs_an_operational_manager(self):
        MD.D_load(self.data_dir)

        with self.assertRaises(RuntimeError):
            MD.D_run(fake_model)

    def test_default_model_is_the_backend_model(self):
        sheet = MD.D_load(self.data_dir)["bank.csv"]

        with mock.patch("src.model.respond", fake_model):
            result = MD.D_send(sheet)

        self.assertEqual(result, {"sheet_id": "bank.csv", "response": "model saw bank.csv with 2 rows"})


    def test_irregular_shortlists_what_does_not_fit(self):
        (self.data_dir / "store.csv").write_text(
            STORE
            + "2026-10-20,Mystery Box,99.99\n"
            + "2026-10-21,170 Gems,9.99\n"
            + "2026-10-21,170 Gems,9.99\n"
        )
        sheet = MD.D_analyze(MD.D_organize(MD.D_load(self.data_dir)["store.csv"]))

        found = {p["item"]: p for p in sheet.results["irregular"]}

        self.assertEqual(sorted(found), ["170 Gems", "Mystery Box"])
        self.assertEqual(
            found["Mystery Box"]["signals"],
            ["only time this item was bought at this price", "amount is at least 3 times the usual $12.99"],
        )
        self.assertEqual(found["170 Gems"]["signals"], ["charged 2 times for the same thing on the same day"])
        for purchase in sheet.results["irregular"]:
            self.assertEqual(sheet.data.loc[purchase["row"], "Item"], purchase["item"])

    def test_respond_returns_only_what_the_model_calls_fraud(self):
        (self.data_dir / "store.csv").write_text(STORE + "2026-10-20,Mystery Box,99.99\n2026-10-25,Song,1.29\n")
        sheet = MD.D_analyze(MD.D_organize(MD.D_load(self.data_dir)["store.csv"]))

        def pipe(messages, **kwargs):
            question = messages[1]["content"]
            reply = "FRAUD - far above the usual amount\n" if "Mystery Box, $99.99" in question else "OK - small one-off"
            return [{"generated_text": reply}]

        with mock.patch("src.model.load", return_value=pipe):
            fraud = model.respond(sheet)

        self.assertEqual(len(sheet.results["irregular"]), 2)
        self.assertEqual([(p["item"], p["reason"]) for p in fraud], [("Mystery Box", "far above the usual amount")])
        self.assertEqual(sheet.data.loc[fraud[0]["row"], "Item"], "Mystery Box")

    def test_every_ai_reply_is_stored(self):
        (self.data_dir / "store.csv").write_text(STORE + "2026-10-20,Mystery Box,99.99\n2026-10-25,Song,1.29\n")
        sheet = MD.D_analyze(MD.D_organize(MD.D_load(self.data_dir)["store.csv"]))
        replies = iter(["FRAUD - far above the usual amount", "hmm, hard to say"])
        MD.start_logging()

        with mock.patch("src.model.load", return_value=lambda messages, **kwargs: [{"generated_text": next(replies)}]):
            model.respond(sheet)

        stored = (MD.LOG_DIR / "ai_replies.txt").read_text()
        self.assertEqual(stored.count("| store.csv | row "), 2)
        self.assertIn("ASKED: 2026-10-20, Mystery Box, $99.99.", stored)
        self.assertIn("AI REPLIED: FRAUD - far above the usual amount\nCOUNTED AS: FRAUD\n", stored)
        self.assertIn("AI REPLIED: hmm, hard to say\nCOUNTED AS: UNCLEAR (not counted as fraud)\n", stored)

    def test_respond_skips_the_model_when_nothing_is_irregular(self):
        sheet = MD.D_analyze(MD.D_load(self.data_dir)["store.csv"])
        pipe = mock.Mock()

        with mock.patch("src.model.load", return_value=pipe):
            self.assertEqual(model.respond(sheet), [])

        pipe.assert_not_called()


    def test_program_run_checks_every_sheet_for_fraud(self):
        with mock.patch("src.model.respond", return_value=[]) as respond:
            results = main.run(self.data_dir)

        self.assertEqual(sorted(results), ["bank.csv", "store.csv"])
        self.assertEqual(respond.call_count, 2)
        self.assertEqual(results["store.csv"]["fraud"], [])

    def test_program_run_stops_when_startup_fails(self):
        self.assertIsNone(main.run(self.data_dir / "missing"))
        self.assertEqual(msm.state, msm.State.ERROR)


if __name__ == "__main__":
    unittest.main()
