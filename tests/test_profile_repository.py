import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from src.profile_repository import DynamoDBProfileRepository


class _TransactionCanceled(Exception):
    response = {
        "Error": {"Code": "TransactionCanceledException"},
        "CancellationReasons": [
            {"Code": "ConditionalCheckFailed"},
            {"Code": "None"},
        ],
    }


class _FakeClient:
    def __init__(self):
        self.items = {}

    def transact_write_items(self, *, TransactItems):
        puts = [operation["Put"] for operation in TransactItems if "Put" in operation]
        for put in puts:
            # Only the profile record is written with a not-exists condition.
            item = put["Item"]
            key = (item["owner_id"], item["record_key"])
            if "ConditionExpression" in put and key in self.items:
                raise _TransactionCanceled()

        # Apply the writes only after checking the conditions, like one
        # atomic transaction for the behavior covered by these tests.
        for operation in TransactItems:
            if "Put" in operation:
                item = operation["Put"]["Item"]
                self.items[(item["owner_id"], item["record_key"])] = dict(item)
            else:
                key = operation["Delete"]["Key"]
                self.items.pop((key["owner_id"], key["record_key"]), None)


class _FakeTable:
    def __init__(self):
        self.name = "Profiles"
        client = _FakeClient()
        self.meta = SimpleNamespace(client=client)

    def put_item(self, *, Item):
        self.meta.client.items[(Item["owner_id"], Item["record_key"])] = dict(Item)

    def delete_item(self, *, Key):
        self.meta.client.items.pop((Key["owner_id"], Key["record_key"]), None)

    def query(self, *, KeyConditionExpression, ConsistentRead, **kwargs):
        self.last_consistent_read = ConsistentRead
        owner_attribute, owner_id = KeyConditionExpression
        self.last_query_options = kwargs
        items = [
            dict(item)
            for (item_owner, _), item in self.meta.client.items.items()
            if item_owner == owner_id and owner_attribute == "owner_id"
        ]
        return {"Items": items}


class _FakeKey:
    def __init__(self, name):
        self.name = name

    def eq(self, value):
        return self.name, value


class _IdentitySerializer:
    def serialize(self, value):
        return value


def _fake_boto3_modules():
    boto3_module = ModuleType("boto3")
    dynamodb_module = ModuleType("boto3.dynamodb")
    conditions_module = ModuleType("boto3.dynamodb.conditions")
    types_module = ModuleType("boto3.dynamodb.types")
    conditions_module.Key = _FakeKey
    types_module.TypeSerializer = _IdentitySerializer
    dynamodb_module.conditions = conditions_module
    dynamodb_module.types = types_module
    boto3_module.dynamodb = dynamodb_module
    return {
        "boto3": boto3_module,
        "boto3.dynamodb": dynamodb_module,
        "boto3.dynamodb.conditions": conditions_module,
        "boto3.dynamodb.types": types_module,
    }


class TestDynamoDBProfileRepository(unittest.TestCase):
    def setUp(self):
        self._boto3_modules = patch.dict(sys.modules, _fake_boto3_modules())
        self._boto3_modules.start()
        self.addCleanup(self._boto3_modules.stop)
        self.table = _FakeTable()
        self.repository = DynamoDBProfileRepository(self.table)

    def test_create_and_fetch_profile_round_trip_with_general_tag(self):
        created = self.repository.create_profile("owner-1")

        self.assertEqual(len(self.table.meta.client.items), 2)
        self.assertIn(("owner-1", "PROFILE"), self.table.meta.client.items)
        self.assertIn(
            ("owner-1", f"TAG#{created.default_tag_id}"),
            self.table.meta.client.items,
        )

        loaded = self.repository.get_profile_for_owner("owner-1")

        self.assertEqual(loaded.profile_id, created.profile_id)
        self.assertEqual(loaded.default_tag_id, created.default_tag_id)
        self.assertEqual(len(loaded.tags), 1)
        general = loaded.tags[loaded.default_tag_id]
        self.assertEqual(general.name, "General")
        self.assertTrue(general.is_default)
        self.assertEqual(loaded.accounts, {})
        self.assertTrue(self.table.last_consistent_read)

    def test_duplicate_owner_is_rejected_without_adding_records(self):
        self.repository.create_profile("owner-1")
        original_records = dict(self.table.meta.client.items)

        with self.assertRaisesRegex(ValueError, "already has a profile"):
            self.repository.create_profile("owner-1")

        self.assertEqual(self.table.meta.client.items, original_records)

    def test_missing_owner_raises_key_error(self):
        with self.assertRaisesRegex(KeyError, "no profile for owner"):
            self.repository.get_profile_for_owner("owner-missing")

    def test_tags_and_accounts_round_trip(self):
        profile = self.repository.create_profile("owner-1")
        work = self.repository.create_tag("owner-1", "Work")
        checking = self.repository.create_account("owner-1", "Checking", work.tag_id)
        savings = self.repository.create_account("owner-1", "Savings")

        loaded = self.repository.get_profile_for_owner("owner-1")

        self.assertEqual({tag.name for tag in loaded.tags.values()}, {"General", "Work"})
        self.assertEqual(loaded.accounts[checking.account_id].tag_id, work.tag_id)
        self.assertEqual(loaded.accounts[savings.account_id].tag_id, profile.default_tag_id)

    def test_rename_tag_and_duplicate_name_is_rejected(self):
        self.repository.create_profile("owner-1")
        work = self.repository.create_tag("owner-1", "Work")

        self.repository.rename_tag("owner-1", work.tag_id, "Business")

        loaded = self.repository.get_profile_for_owner("owner-1")
        self.assertEqual(loaded.tags[work.tag_id].name, "Business")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.repository.create_tag("owner-1", "business")

    def test_deleting_a_tag_moves_its_accounts_to_general(self):
        profile = self.repository.create_profile("owner-1")
        work = self.repository.create_tag("owner-1", "Work")
        account = self.repository.create_account("owner-1", "Checking", work.tag_id)

        self.repository.delete_tag("owner-1", work.tag_id)

        loaded = self.repository.get_profile_for_owner("owner-1")
        self.assertNotIn(work.tag_id, loaded.tags)
        self.assertEqual(loaded.accounts[account.account_id].tag_id, profile.default_tag_id)

    def test_general_tag_cannot_be_deleted(self):
        profile = self.repository.create_profile("owner-1")

        with self.assertRaisesRegex(ValueError, "cannot be deleted"):
            self.repository.delete_tag("owner-1", profile.default_tag_id)

        self.assertIn(profile.default_tag_id, self.repository.get_profile_for_owner("owner-1").tags)

    def test_account_can_be_renamed_moved_and_deleted(self):
        self.repository.create_profile("owner-1")
        work = self.repository.create_tag("owner-1", "Work")
        account = self.repository.create_account("owner-1", "Checking")

        self.repository.update_account("owner-1", account.account_id, name="Main", tag_id=work.tag_id)

        loaded = self.repository.get_profile_for_owner("owner-1").accounts[account.account_id]
        self.assertEqual((loaded.name, loaded.tag_id), ("Main", work.tag_id))

        self.repository.delete_account("owner-1", account.account_id)

        self.assertEqual(self.repository.get_profile_for_owner("owner-1").accounts, {})

    def test_one_owner_cannot_touch_another_owners_records(self):
        self.repository.create_profile("owner-1")
        self.repository.create_profile("owner-2")
        tag = self.repository.create_tag("owner-1", "Work")
        account = self.repository.create_account("owner-1", "Checking")

        with self.assertRaises(KeyError):
            self.repository.rename_tag("owner-2", tag.tag_id, "Mine")
        with self.assertRaises(KeyError):
            self.repository.create_account("owner-2", "Sneaky", tag.tag_id)
        with self.assertRaises(KeyError):
            self.repository.delete_account("owner-2", account.account_id)

        self.assertEqual(len(self.repository.get_profile_for_owner("owner-1").accounts), 1)


if __name__ == "__main__":
    unittest.main()
