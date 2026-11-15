import json
import unittest
from types import SimpleNamespace
from unittest import mock

from src import model


def purchase(row):
    return {
        "row": row,
        "date": "2026-11-01",
        "item": f"Purchase {row}",
        "amount": 12.5 + row,
        "times_bought": 1,
        "times_seen": 1,
        "baseline": {
            "ready": True,
            "history_count": 3,
            "median_amount": 12.5,
            "mad_amount": 0.0,
            "upper_threshold": 18.75,
        },
        "signals": ["first purchase at this price"],
    }


class TestBatchedModel(unittest.TestCase):
    def make_sheet(self, count=5):
        return SimpleNamespace(
            sheet_id="fixture.csv",
            results={
                "profile": {"paid_transactions": 80, "median_paid_amount": 12.5},
                "irregular": [purchase(row) for row in range(count)],
            },
            touch=lambda: None,
        )

    def test_batches_keep_row_identity_and_reduce_model_calls(self):
        calls = []

        def fake_pipeline(messages, **kwargs):
            prompt = messages[1]["content"]
            self.assertNotIn('"paid_transactions":80', prompt)
            rows = json.loads(prompt.split("Transactions to review:\n", 1)[1])
            self.assertEqual(rows[0]["prior_baseline"]["history_count"], 3)
            calls.append([row["row"] for row in rows])
            answer = [
                {
                    "row": row["row"],
                    "verdict": "FRAUD" if row["row"] == 1 else "OK",
                    "reason": "unexpected charge" if row["row"] == 1 else "",
                }
                for row in rows
            ]
            return [{"generated_text": json.dumps(answer)}]

        with mock.patch("src.model.load", return_value=fake_pipeline):
            flagged = model.respond(self.make_sheet(), batch_size=2)

        self.assertEqual(calls, [[0, 1], [2, 3], [4]])
        self.assertEqual([entry["row"] for entry in flagged], [1])
        self.assertEqual(flagged[0]["reason"], "unexpected charge")

    def test_rejects_a_batch_reply_that_omits_rows(self):
        def incomplete_pipeline(messages, **kwargs):
            return [{"generated_text": '[{"row":0,"verdict":"OK","reason":""}]'}]

        with mock.patch("src.model.load", return_value=incomplete_pipeline):
            with self.assertRaisesRegex(ValueError, "exactly one verdict"):
                model.respond(self.make_sheet(count=2), batch_size=2)

    def test_requires_a_positive_integer_batch_size(self):
        with self.assertRaises(ValueError):
            model.respond(self.make_sheet(), batch_size=0)


if __name__ == "__main__":
    unittest.main()
