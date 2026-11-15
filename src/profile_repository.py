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
