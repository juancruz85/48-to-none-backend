import unittest

import pandas as pd

from scripts.benchmark_accuracy import _metrics, _target_purchase


class TestAccuracyBenchmark(unittest.TestCase):
    def test_metrics_include_each_confusion_matrix_cell(self):
        result = _metrics([1, 1, 0, 0], [1, 0, 1, 0])

        self.assertEqual((result["tp"], result["fp"], result["tn"], result["fn"]), (1, 1, 1, 1))
        self.assertEqual(result["accuracy"], 0.5)
        self.assertEqual(result["precision"], 0.5)
        self.assertEqual(result["recall"], 0.5)
        self.assertEqual(result["specificity"], 0.5)
        self.assertEqual(result["f1"], 0.5)

    def test_target_context_uses_only_prior_same_item_history(self):
        prepared = pd.DataFrame({
            "Date": pd.to_datetime(["2026-01-01", "2026-01-15", "2026-02-01"]),
            "Item": ["Shop", "Other", "Shop"],
            "Amount": [10.0, 5.0, 25.0],
        })

        purchase = _target_purchase(prepared, 2, {})

        self.assertEqual(purchase["times_seen"], 1)
        self.assertEqual(purchase["baseline"]["history_count"], 1)
        self.assertFalse(purchase["baseline"]["ready"])
        self.assertEqual(purchase["signals"], [])

    def test_metrics_reject_different_input_lengths(self):
        with self.assertRaises(ValueError):
            _metrics([1], [])


if __name__ == "__main__":
    unittest.main()
