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
        puts = [operation["Put"] for operation in TransactItems]
        profile_item = puts[0]["Item"]
        profile_key = (profile_item["owner_id"], profile_item["record_key"])
        if profile_key in self.items:
            raise _TransactionCanceled()

        # Apply the writes only after checking the profile condition, like one
        # atomic transaction for the behavior covered by these tests.
        for put in puts:
            item = put["Item"]
            key = (item["owner_id"], item["record_key"])
            self.items[key] = dict(item)


class _FakeTable:
    def __init__(self):
        self.name = "Profiles"
        client = _FakeClient()
        self.meta = SimpleNamespace(client=client)

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


if __name__ == "__main__":
    unittest.main()
