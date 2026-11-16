import unittest
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from src import datasheet as da, model


def frame(rows):
    return da.prepare(pd.DataFrame(rows, columns=["Date", "Item", "Amount (USD)"]))


def days(month, numbers, item="Tiny Store", amount=0.99):
    return [(f"2026-{month:02d}-{day:02d}", item, amount) for day in numbers]


class TestPatterns(unittest.TestCase):
    def test_charges_that_keep_getting_more_frequent_are_a_pattern(self):
        rows = days(6, [5, 20]) + days(7, [5, 20]) + days(8, range(1, 21))

        found = da.patterns(frame(rows))

        self.assertEqual(len(found), 1)
        pattern = found[0]
        self.assertEqual(pattern["item"], "Tiny Store")
        self.assertEqual(pattern["charges"], 24)
        self.assertEqual(pattern["total"], round(24 * 0.99, 2))
        self.assertEqual([m["charges"] for m in pattern["months"]], [2, 2, 20])
        self.assertTrue(pattern["rising_since"].startswith("2026-08"))
        self.assertIn("charges from Tiny Store", pattern["signal"])

    def test_a_steady_habit_is_not_a_pattern(self):
        rows = []
        for month in range(5, 11):
            rows += days(month, [2, 5, 9, 12, 16, 19, 23, 26], item="Coffee", amount=5.25)

        self.assertEqual(da.patterns(frame(rows)), [])

    def test_a_brand_new_seller_has_no_earlier_history_to_rise_from(self):
        self.assertEqual(da.patterns(frame(days(8, range(1, 21)))), [])

    def test_only_charges_in_the_rise_are_listed_and_each_uses_only_earlier_charges(self):
        rows = days(6, [5, 20]) + days(7, [5, 20]) + days(8, range(1, 21))
        prepared = frame(rows)

        pattern = da.patterns(prepared)[0]

        flagged = prepared.loc[pattern["rows"], "Date"]
        self.assertTrue((flagged >= pd.Timestamp("2026-08-01")).all())
        self.assertEqual(pattern["rising_charges"], len(pattern["rows"]))
        #adding later charges must not change what was decided about the earlier ones.
        later = frame(rows + days(9, range(1, 29)))
        self.assertTrue(set(pattern["rows"]) <= set(da.patterns(later)[0]["rows"]))

    def test_money_in_and_other_sellers_are_ignored(self):
        rows = days(6, [5, 20]) + days(7, [5, 20]) + days(8, range(1, 21))
        rows += [("2026-08-10", "Refund", -40.0)] + days(8, [3, 9], item="Grocer", amount=70.0)

        self.assertEqual([p["item"] for p in da.patterns(frame(rows))], ["Tiny Store"])

    def test_bad_settings_are_refused(self):
        for settings in ({"window_days": 0}, {"min_recent": 1}, {"growth": 1}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                da.patterns(frame(days(6, [5])), **settings)


class TestIrregularSignals(unittest.TestCase):
    """What gets a single purchase sent to the model."""

    def quiet_month(self):
        return [(f"2026-05-{day:02d}", "Grocer", 60.0) for day in range(1, 29, 2)]

    def signals(self, rows):
        return {(p["date"], p["item"]): p["signals"] for p in da.irregular(frame(rows))}

    def test_routine_purchase_on_a_busy_day_is_not_irregular(self):
        rows = self.quiet_month() + [
            ("2026-06-01", "Tiny Store", 0.99), ("2026-06-01", "Other Shop", 4.0),
            ("2026-06-01", "Third Shop", 9.0), ("2026-06-01", "Grocer", 62.0),
        ]

        found = self.signals(rows)

        self.assertNotIn(("2026-06-01", "Grocer"), found)

    def test_unfamiliar_purchases_on_an_unusually_busy_day_are_a_burst(self):
        rows = self.quiet_month() + [(f"2026-06-01", f"Unknown {n}", 60.0 + n) for n in range(5)]

        found = self.signals(rows)

        self.assertEqual(sorted(item for _, item in found), ["Unknown 2", "Unknown 3", "Unknown 4"])
        self.assertIn("burst of unfamiliar purchases", found[("2026-06-01", "Unknown 2")][0])

    def test_many_small_unfamiliar_purchases_that_cost_a_normal_day_are_not_a_burst(self):
        # a day out: five new sellers, $110 in all against a usual $60 day. busy, but not expensive.
        rows = self.quiet_month() + [(f"2026-06-01", f"Unknown {n}", 20.0 + n) for n in range(5)]

        self.assertEqual(da.irregular(frame(rows)), [])

    def test_a_burst_starts_once_the_unfamiliar_spending_passes_double_a_usual_day(self):
        # usual day $60, so the day is expensive past $120: 50, 100, 150 -> the third purchase onwards.
        rows = self.quiet_month() + [(f"2026-06-01", f"Unknown {n}", 50.0) for n in range(4)]

        found = self.signals(rows)

        self.assertEqual(sorted(item for _, item in found), ["Unknown 2", "Unknown 3"])
        self.assertIn("$150.00 of unfamiliar spending today against $60.00 on a usual day",
                      found[("2026-06-01", "Unknown 2")][0])

    def test_a_person_who_always_buys_a_lot_in_a_day_is_not_bursting(self):
        rows = [(f"2026-05-{day:02d}", f"Shop {day}-{n}", 5.0 + n) for day in range(1, 29) for n in range(4)]

        self.assertEqual(da.irregular(frame(rows)), [])

    def test_no_burst_before_there_is_enough_history(self):
        rows = [("2026-05-01", f"Unknown {n}", 20.0 + n) for n in range(6)]

        self.assertEqual(da.irregular(frame(rows)), [])

    def test_a_few_busy_days_do_not_become_the_new_normal(self):
        rows = self.quiet_month()
        for day in (1, 2, 3):
            rows += [(f"2026-06-{day:02d}", f"Unknown {day}-{n}", 60.0 + n) for n in range(5)]

        flagged_days = {date for date, _ in self.signals(rows)}

        self.assertEqual(flagged_days, {"2026-06-01", "2026-06-02", "2026-06-03"})

    def test_duplicate_charge_is_still_flagged_even_for_a_routine_item(self):
        rows = self.quiet_month() + [("2026-06-01", "Grocer", 60.0), ("2026-06-01", "Grocer", 60.0)]

        found = self.signals(rows)

        self.assertIn("duplicate charge", found[("2026-06-01", "Grocer")][0])

    def test_amount_far_above_normal_is_flagged(self):
        rows = self.quiet_month() + [("2026-06-01", "Grocer", 400.0)]

        self.assertIn("exceeds the prior", self.signals(rows)[("2026-06-01", "Grocer")][0])

    def test_ordinary_variation_in_what_an_item_costs_is_not_flagged(self):
        rows = [("2026-01-05", "Diner", 18.0), ("2026-02-05", "Diner", 20.29), ("2026-03-05", "Diner", 24.0),
                ("2026-04-05", "Diner", 33.94)]

        self.assertEqual(da.irregular(frame(rows)), [])

    def test_routine_purchases_do_not_count_towards_a_burst(self):
        rows = self.quiet_month() + [(f"2026-05-{day:02d}", "Tiny Store", 0.99) for day in (3, 9, 15)] + [
            ("2026-06-01", "Grocer", 61.0), ("2026-06-01", "Tiny Store", 0.99), ("2026-06-01", "New Shop", 18.4),
        ]

        self.assertEqual(da.irregular(frame(rows)), [])

    def test_a_bill_charged_the_same_amount_before_is_routine(self):
        rows = self.quiet_month() + [("2026-05-18", "Phone Bill", 65.0)] + [
            ("2026-06-18", "New A", 5.0), ("2026-06-18", "New B", 6.0), ("2026-06-18", "Phone Bill", 65.0),
        ]

        self.assertEqual(da.irregular(frame(rows)), [])


class TestPatternReview(unittest.TestCase):
    def setUp(self):
        rows = days(6, [5, 20]) + days(7, [5, 20]) + days(8, range(1, 21))
        self.sheet = SimpleNamespace(sheet_id="s.csv", results={"patterns": da.patterns(frame(rows))}, touch=lambda: None)

    def review(self, reply):
        pipe = mock.Mock(return_value=[{"generated_text": reply}])
        with mock.patch("src.model.load", return_value=pipe):
            return model.review_patterns(self.sheet), pipe

    def test_suspicious_reply_is_kept_with_its_reason(self):
        found, pipe = self.review("SUSPICIOUS - charges keep increasing")

        self.assertEqual([(p["item"], p["reason"]) for p in found], [("Tiny Store", "charges keep increasing")])
        question = pipe.call_args[0][0][1]["content"]
        self.assertIn("2026-06: 2 charges ($1.98)", question)
        self.assertIn("2026-08: 20 charges", question)
        self.assertIn("Typical charge: $0.99", question)

    def test_ok_and_unclear_replies_are_not_counted(self):
        for reply in ("OK - a normal habit", "This is NOT SUSPICIOUS", "maybe?"):
            with self.subTest(reply=reply):
                self.assertEqual(self.review(reply)[0], [])

    def test_no_patterns_means_no_question(self):
        self.sheet.results["patterns"] = []

        found, pipe = self.review("SUSPICIOUS - x")

        self.assertEqual(found, [])
        pipe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
