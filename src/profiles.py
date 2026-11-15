"""In-memory profile, account, and tag domain model for the future API.

Profiles own accounts and tags. Each account has one tag, its own baseline, and
zero or more imported sheets. Reusable policy belongs on tags, never accounts.
Persistence and encrypted transaction-history storage are intentionally left to
the repository/API layer.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


DEFAULT_TAG_NAME = "General"


def _id() -> str:
    return str(uuid4())


def _name(value: str, kind: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{kind} name must not be blank")
    return value.strip()


@dataclass
class ProfileTag:
    tag_id: str
    profile_id: str
    name: str
    is_default: bool = False


@dataclass
class Account:
    account_id: str
    profile_id: str
    tag_id: str
    name: str
    created_at: str
    baseline: dict | None = None
    sheet_ids: list[str] = field(default_factory=list)


@dataclass
class UserProfile:
    profile_id: str
    owner_id: str
    created_at: str
    default_tag_id: str
    tags: dict[str, ProfileTag] = field(default_factory=dict)
    accounts: dict[str, Account] = field(default_factory=dict)


class ProfileStore:
    """Process-local domain store; replace with an encrypted repository for API use."""

    def __init__(self):
        self.profiles: dict[str, UserProfile] = {}
        self._profile_by_owner: dict[str, str] = {}
        self._sheet_account: dict[tuple[str, str], str] = {}

    def create_profile(self, owner_id: str) -> UserProfile:
        owner_id = _name(owner_id, "owner")
        if owner_id in self._profile_by_owner:
            raise ValueError("this owner already has a profile")

        profile_id = _id()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        default_tag = ProfileTag(
            tag_id=_id(),
            profile_id=profile_id,
            name=DEFAULT_TAG_NAME,
            is_default=True,
        )
        profile = UserProfile(
            profile_id=profile_id,
            owner_id=owner_id,
            created_at=now,
            default_tag_id=default_tag.tag_id,
            tags={default_tag.tag_id: default_tag},
        )
        self.profiles[profile_id] = profile
        self._profile_by_owner[owner_id] = profile_id
        return profile

    def get_profile(self, profile_id: str) -> UserProfile:
        try:
            return self.profiles[profile_id]
        except KeyError as error:
            raise KeyError(f"unknown profile: {profile_id}") from error

    def get_profile_for_owner(self, owner_id: str) -> UserProfile:
        try:
            return self.get_profile(self._profile_by_owner[owner_id])
        except KeyError as error:
            raise KeyError(f"no profile for owner: {owner_id}") from error

    def create_tag(self, profile_id: str, name: str) -> ProfileTag:
        profile = self.get_profile(profile_id)
        name = _name(name, "tag")
        self._ensure_unique_tag_name(profile, name)
        tag = ProfileTag(tag_id=_id(), profile_id=profile_id, name=name)
        profile.tags[tag.tag_id] = tag
        return tag

    def rename_tag(self, profile_id: str, tag_id: str, name: str) -> ProfileTag:
        profile = self.get_profile(profile_id)
        tag = self._tag(profile, tag_id)
        name = _name(name, "tag")
        self._ensure_unique_tag_name(profile, name, excluding=tag_id)
        tag.name = name
        return tag

    def create_account(self, profile_id: str, name: str, tag_id: str | None = None) -> Account:
        profile = self.get_profile(profile_id)
        name = _name(name, "account")
        selected_tag_id = tag_id or profile.default_tag_id
        self._tag(profile, selected_tag_id)
        account = Account(
            account_id=_id(),
            profile_id=profile_id,
            tag_id=selected_tag_id,
            name=name,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        profile.accounts[account.account_id] = account
        return account

    def assign_account_tag(self, profile_id: str, account_id: str, tag_id: str | None) -> Account:
        """Move an account to one tag; None explicitly returns it to General."""
        profile = self.get_profile(profile_id)
        account = self._account(profile, account_id)
        new_tag_id = tag_id or profile.default_tag_id
        self._tag(profile, new_tag_id)
        account.tag_id = new_tag_id
        return account

    def rename_account(self, profile_id: str, account_id: str, name: str) -> Account:
        profile = self.get_profile(profile_id)
        account = self._account(profile, account_id)
        account.name = _name(name, "account")
        return account

    def delete_account(self, profile_id: str, account_id: str) -> Account:
        """Remove an account and release its sheets so they can be attached elsewhere."""
        profile = self.get_profile(profile_id)
        account = self._account(profile, account_id)
        for sheet_id in account.sheet_ids:
            self._sheet_account.pop((profile_id, sheet_id), None)
        del profile.accounts[account_id]
        return account

    def delete_tag(self, profile_id: str, tag_id: str) -> None:
        profile = self.get_profile(profile_id)
        tag = self._tag(profile, tag_id)
        if tag.is_default:
            raise ValueError("the General default tag cannot be deleted")
        for account in profile.accounts.values():
            if account.tag_id == tag_id:
                account.tag_id = profile.default_tag_id
        del profile.tags[tag_id]

    def attach_sheet(self, profile_id: str, account_id: str, sheet_id: str) -> Account:
        """Associate an imported CSV sheet with one account without merging histories."""
        profile = self.get_profile(profile_id)
        account = self._account(profile, account_id)
        sheet_id = _name(sheet_id, "sheet")
        key = (profile_id, sheet_id)
        assigned = self._sheet_account.get(key)
        if assigned is not None and assigned != account_id:
            raise ValueError("a sheet can belong to only one account")
        if sheet_id not in account.sheet_ids:
            account.sheet_ids.append(sheet_id)
        self._sheet_account[key] = account_id
        return account

    def set_account_baseline(self, profile_id: str, account_id: str, baseline: dict) -> Account:
        """Store a calculated baseline on its account, never on the tag/profile."""
        if not isinstance(baseline, dict):
            raise TypeError("baseline must be a dictionary")
        profile = self.get_profile(profile_id)
        account = self._account(profile, account_id)
        account.baseline = deepcopy(baseline)
        return account

    @staticmethod
    def _tag(profile: UserProfile, tag_id: str) -> ProfileTag:
        try:
            return profile.tags[tag_id]
        except KeyError as error:
            raise KeyError(f"tag {tag_id} does not belong to profile {profile.profile_id}") from error

    @staticmethod
    def _account(profile: UserProfile, account_id: str) -> Account:
        try:
            return profile.accounts[account_id]
        except KeyError as error:
            raise KeyError(f"account {account_id} does not belong to profile {profile.profile_id}") from error

    @staticmethod
    def _ensure_unique_tag_name(profile: UserProfile, name: str, excluding: str | None = None) -> None:
        normalized = name.casefold()
        if any(tag_id != excluding and tag.name.casefold() == normalized for tag_id, tag in profile.tags.items()):
            raise ValueError(f"tag already exists: {name}")
