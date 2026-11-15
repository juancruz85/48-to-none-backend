import unittest

from src.profiles import DEFAULT_TAG_NAME, ProfileStore


class TestProfileStore(unittest.TestCase):
    def setUp(self):
        self.store = ProfileStore()
        self.profile = self.store.create_profile("auth-user-1")

    def test_profile_has_unique_id_and_general_default_tag(self):
        other = self.store.create_profile("auth-user-2")

        self.assertNotEqual(self.profile.profile_id, other.profile_id)
        general = self.profile.tags[self.profile.default_tag_id]
        self.assertEqual(general.name, DEFAULT_TAG_NAME)
        self.assertTrue(general.is_default)

    def test_owner_can_only_have_one_profile(self):
        with self.assertRaisesRegex(ValueError, "already has a profile"):
            self.store.create_profile("auth-user-1")
        self.assertEqual(self.store.get_profile_for_owner("auth-user-1").profile_id, self.profile.profile_id)

    def test_account_without_tag_defaults_to_general(self):
        account = self.store.create_account(self.profile.profile_id, "Everyday checking")

        self.assertEqual(account.tag_id, self.profile.default_tag_id)
        self.assertEqual(account.profile_id, self.profile.profile_id)

    def test_account_can_be_imported_directly_into_a_custom_tag(self):
        food = self.store.create_tag(self.profile.profile_id, "Food")
        account = self.store.create_account(self.profile.profile_id, "Food account", tag_id=food.tag_id)

        self.assertEqual(account.tag_id, food.tag_id)

    def test_moving_account_preserves_its_baseline_and_sheet_links(self):
        account = self.store.create_account(self.profile.profile_id, "Travel checking")
        original = {"schema_version": 1, "items": [{"median_amount": 10.0}]}
        self.store.set_account_baseline(self.profile.profile_id, account.account_id, original)
        self.store.attach_sheet(self.profile.profile_id, account.account_id, "jan.csv")
        travel = self.store.create_tag(self.profile.profile_id, "Travel")

        self.store.assign_account_tag(self.profile.profile_id, account.account_id, travel.tag_id)
        self.store.assign_account_tag(self.profile.profile_id, account.account_id, None)

        self.assertEqual(account.tag_id, self.profile.default_tag_id)
        self.assertEqual(account.baseline, original)
        self.assertEqual(account.sheet_ids, ["jan.csv"])
        original["items"][0]["median_amount"] = 99.0
        self.assertEqual(account.baseline["items"][0]["median_amount"], 10.0)

    def test_unknown_tag_does_not_mutate_account(self):
        account = self.store.create_account(self.profile.profile_id, "Checking")
        original_tag = account.tag_id

        with self.assertRaisesRegex(KeyError, "does not belong"):
            self.store.assign_account_tag(self.profile.profile_id, account.account_id, "not-a-tag")

        self.assertEqual(account.tag_id, original_tag)

    def test_deleting_custom_tag_moves_accounts_to_general(self):
        travel = self.store.create_tag(self.profile.profile_id, "Travel")
        account = self.store.create_account(self.profile.profile_id, "Travel checking", travel.tag_id)

        self.store.delete_tag(self.profile.profile_id, travel.tag_id)

        self.assertEqual(account.tag_id, self.profile.default_tag_id)
        self.assertNotIn(travel.tag_id, self.profile.tags)

    def test_default_tag_cannot_be_deleted(self):
        with self.assertRaisesRegex(ValueError, "cannot be deleted"):
            self.store.delete_tag(self.profile.profile_id, self.profile.default_tag_id)
        self.assertIn(self.profile.default_tag_id, self.profile.tags)

    def test_rename_keeps_tag_id_and_tag_names_are_case_insensitively_unique(self):
        tag = self.store.create_tag(self.profile.profile_id, "Everyday")
        tag_id = tag.tag_id

        self.store.rename_tag(self.profile.profile_id, tag_id, "Daily spending")
        self.assertEqual(tag.tag_id, tag_id)
        self.assertEqual(tag.name, "Daily spending")

        with self.assertRaisesRegex(ValueError, "already exists"):
            self.store.create_tag(self.profile.profile_id, "daily SPENDING")

    def test_sheet_can_attach_to_one_account_and_repeated_attach_is_idempotent(self):
        first = self.store.create_account(self.profile.profile_id, "Checking")
        second = self.store.create_account(self.profile.profile_id, "Savings")
        self.store.attach_sheet(self.profile.profile_id, first.account_id, "jan.csv")
        self.store.attach_sheet(self.profile.profile_id, first.account_id, "jan.csv")

        with self.assertRaisesRegex(ValueError, "only one account"):
            self.store.attach_sheet(self.profile.profile_id, second.account_id, "jan.csv")

        self.assertEqual(first.sheet_ids, ["jan.csv"])
        self.assertEqual(second.sheet_ids, [])


if __name__ == "__main__":
    unittest.main()
