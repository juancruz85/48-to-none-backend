"""DynamoDB persistence for profiles, tags, and accounts.

The DynamoDB table uses ``owner_id`` as its partition key and ``record_key`` as
its sort key. A profile is stored at ``PROFILE``; related records use keys such
as ``TAG#<tag_id>`` and ``ACCOUNT#<account_id>``. This keeps growing account
data out of one profile item.
"""

import os
from decimal import Decimal

from src.profiles import Account, ProfileStore, ProfileTag, UserProfile


class DynamoDBProfileRepository:
    """Persist profile data in a DynamoDB table with owner-scoped records."""

    def __init__(self, table):
        self._table = table
        self._client = table.meta.client
        self._table_name = table.name

    @classmethod
    def from_environment(cls):
        """Build the repository using ``PROFILE_TABLE_NAME`` and Lambda IAM."""
        table_name = os.environ.get("PROFILE_TABLE_NAME")
        if not table_name:
            raise RuntimeError("PROFILE_TABLE_NAME must be configured")

        import boto3

        return cls(boto3.resource("dynamodb").Table(table_name))

    def create_profile(self, owner_id: str) -> UserProfile:
        """Create a profile and its General tag as one conditional transaction."""
        # Reuse the domain model for ID generation and the default-tag rule.
        profile = ProfileStore().create_profile(owner_id)
        default_tag = profile.tags[profile.default_tag_id]

        profile_item = {
            "owner_id": owner_id,
            "record_key": "PROFILE",
            "record_type": "PROFILE",
            "profile_id": profile.profile_id,
            "created_at": profile.created_at,
            "default_tag_id": profile.default_tag_id,
        }
        tag_item = {
            "owner_id": owner_id,
            "record_key": f"TAG#{default_tag.tag_id}",
            "record_type": "TAG",
            "tag_id": default_tag.tag_id,
            "profile_id": default_tag.profile_id,
            "name": default_tag.name,
            "is_default": default_tag.is_default,
        }

        try:
            self._client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self._table_name,
                            "Item": self._to_dynamodb(profile_item),
                            "ConditionExpression": "attribute_not_exists(owner_id)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self._table_name,
                            "Item": self._to_dynamodb(tag_item),
                        }
                    },
                ]
            )
        except Exception as error:
            error_response = getattr(error, "response", {})
            details = error_response.get("Error", {})
            reasons = error_response.get("CancellationReasons", [])
            if (
                details.get("Code") == "TransactionCanceledException"
                and reasons
                and reasons[0].get("Code") == "ConditionalCheckFailed"
            ):
                raise ValueError("this owner already has a profile") from error
            raise

        return profile

    def get_profile_for_owner(self, owner_id: str) -> UserProfile:
        """Load an owner’s profile and all tag/account records from the table."""
        from boto3.dynamodb.conditions import Key

        records = []
        query = {
            "KeyConditionExpression": Key("owner_id").eq(owner_id),
            "ConsistentRead": True,
        }
        while True:
            page = self._table.query(**query)
            records.extend(page.get("Items", []))
            last_key = page.get("LastEvaluatedKey")
            if not last_key:
                break
            query["ExclusiveStartKey"] = last_key

        profile_item = next(
            (item for item in records if item.get("record_type") == "PROFILE"),
            None,
        )
        if profile_item is None:
            raise KeyError(f"no profile for owner: {owner_id}")

        profile_id = profile_item["profile_id"]
        tags = {}
        accounts = {}
        for item in records:
            if item.get("profile_id") != profile_id:
                continue
            if item.get("record_type") == "TAG":
                tag = ProfileTag(
                    tag_id=item["tag_id"],
                    profile_id=item["profile_id"],
                    name=item["name"],
                    is_default=item.get("is_default", False),
                )
                tags[tag.tag_id] = tag
            elif item.get("record_type") == "ACCOUNT":
                account = Account(
                    account_id=item["account_id"],
                    profile_id=item["profile_id"],
                    tag_id=item["tag_id"],
                    name=item["name"],
                    created_at=item["created_at"],
                    baseline=self._from_dynamodb(item.get("baseline")),
                    sheet_ids=item.get("sheet_ids", []),
                )
                accounts[account.account_id] = account

        return UserProfile(
            profile_id=profile_id,
            owner_id=owner_id,
            created_at=profile_item["created_at"],
            default_tag_id=profile_item["default_tag_id"],
            tags=tags,
            accounts=accounts,
        )

    # Tags and accounts. Each change loads the owner's records, applies the
    # domain rule from ``ProfileStore`` (names, ownership, the General tag), then
    # writes only the records that changed.

    def _store_for_owner(self, owner_id: str):
        profile = self.get_profile_for_owner(owner_id)
        store = ProfileStore()
        store.profiles[profile.profile_id] = profile
        store._profile_by_owner[owner_id] = profile.profile_id
        return store, profile

    @staticmethod
    def _tag_key(tag_id: str) -> str:
        return f"TAG#{tag_id}"

    @staticmethod
    def _account_key(account_id: str) -> str:
        return f"ACCOUNT#{account_id}"

    def _tag_item(self, owner_id: str, tag: ProfileTag) -> dict:
        return {
            "owner_id": owner_id,
            "record_key": self._tag_key(tag.tag_id),
            "record_type": "TAG",
            "tag_id": tag.tag_id,
            "profile_id": tag.profile_id,
            "name": tag.name,
            "is_default": tag.is_default,
        }

    def _account_item(self, owner_id: str, account: Account) -> dict:
        return self._to_dynamodb({
            "owner_id": owner_id,
            "record_key": self._account_key(account.account_id),
            "record_type": "ACCOUNT",
            "account_id": account.account_id,
            "profile_id": account.profile_id,
            "tag_id": account.tag_id,
            "name": account.name,
            "created_at": account.created_at,
            "baseline": account.baseline,
            "sheet_ids": list(account.sheet_ids),
        })

    def create_tag(self, owner_id: str, name: str) -> ProfileTag:
        store, profile = self._store_for_owner(owner_id)
        tag = store.create_tag(profile.profile_id, name)
        self._table.put_item(Item=self._tag_item(owner_id, tag))
        return tag

    def rename_tag(self, owner_id: str, tag_id: str, name: str) -> ProfileTag:
        store, profile = self._store_for_owner(owner_id)
        tag = store.rename_tag(profile.profile_id, tag_id, name)
        self._table.put_item(Item=self._tag_item(owner_id, tag))
        return tag

    def delete_tag(self, owner_id: str, tag_id: str) -> None:
        """Delete a custom tag and move its accounts to General in one transaction."""
        store, profile = self._store_for_owner(owner_id)
        moved = [account for account in profile.accounts.values() if account.tag_id == tag_id]
        store.delete_tag(profile.profile_id, tag_id)
        operations = [{
            "Delete": {
                "TableName": self._table_name,
                "Key": {"owner_id": owner_id, "record_key": self._tag_key(tag_id)},
            }
        }]
        operations += [
            {"Put": {"TableName": self._table_name, "Item": self._account_item(owner_id, account)}}
            for account in moved
        ]
        # A transaction holds at most 100 writes; the tag delete goes last so a
        # retry after a partial failure still finds the tag and finishes the move.
        for start in range(1, len(operations), 99):
            self._client.transact_write_items(TransactItems=operations[start:start + 99])
        self._client.transact_write_items(TransactItems=operations[:1])

    def create_account(self, owner_id: str, name: str, tag_id: str | None = None) -> Account:
        store, profile = self._store_for_owner(owner_id)
        account = store.create_account(profile.profile_id, name, tag_id)
        self._table.put_item(Item=self._account_item(owner_id, account))
        return account

    def update_account(self, owner_id: str, account_id: str, name: str | None = None,
                       tag_id: str | None = None) -> Account:
        """Rename an account and/or move it to another tag."""
        store, profile = self._store_for_owner(owner_id)
        account = store._account(profile, account_id)
        if name is not None:
            account = store.rename_account(profile.profile_id, account_id, name)
        if tag_id is not None:
            account = store.assign_account_tag(profile.profile_id, account_id, tag_id)
        self._table.put_item(Item=self._account_item(owner_id, account))
        return account

    def delete_account(self, owner_id: str, account_id: str) -> None:
        store, profile = self._store_for_owner(owner_id)
        store.delete_account(profile.profile_id, account_id)
        self._table.delete_item(Key={"owner_id": owner_id, "record_key": self._account_key(account_id)})

    @classmethod
    def _to_dynamodb(cls, value):
        if isinstance(value, float):
            return Decimal(str(value))
        if isinstance(value, dict):
            return {key: cls._to_dynamodb(nested) for key, nested in value.items()}
        if isinstance(value, list):
            return [cls._to_dynamodb(nested) for nested in value]
        return value

    @classmethod
    def _from_dynamodb(cls, value):
        if isinstance(value, Decimal):
            return int(value) if value == value.to_integral_value() else float(value)
        if isinstance(value, dict):
            return {key: cls._from_dynamodb(nested) for key, nested in value.items()}
        if isinstance(value, list):
            return [cls._from_dynamodb(nested) for nested in value]
        return value
