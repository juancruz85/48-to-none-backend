import base64
import json
from typing import Protocol

from dataclasses import asdict

from src.profiles import Account, ProfileTag, UserProfile

_aws_handler = None


class ProfileRepository(Protocol):
    def create_profile(self, owner_id: str) -> UserProfile: ...

    def get_profile_for_owner(self, owner_id: str) -> UserProfile: ...

    def create_tag(self, owner_id: str, name: str) -> ProfileTag: ...

    def rename_tag(self, owner_id: str, tag_id: str, name: str) -> ProfileTag: ...

    def delete_tag(self, owner_id: str, tag_id: str) -> None: ...

    def create_account(self, owner_id: str, name: str, tag_id: str | None = None) -> Account: ...

    def update_account(self, owner_id: str, account_id: str, name: str | None = None,
                       tag_id: str | None = None) -> Account: ...

    def delete_account(self, owner_id: str, account_id: str) -> None: ...


class _BadRequest(Exception):
    pass


def make_handler(store: ProfileRepository):
    def response(status_code, body):
        return {
            "statusCode": status_code,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body),
        }

    def error(status_code, code, message):
        return response(
            status_code,
            {"error": {"code": code, "message": message}},
        )

    def profile_json(profile):
        return {
            "profile_id": profile.profile_id,
            "created_at": profile.created_at,
            "default_tag_id": profile.default_tag_id,
            "tags": [asdict(tag) for tag in profile.tags.values()],
            "accounts": [asdict(account) for account in profile.accounts.values()],
        }

    def read_body(event):
        try:
            body = event.get("body") or "{}"
            # API Gateway base64-encodes bodies sent without a text
            # content type (curl and HTML forms default to one).
            if event.get("isBase64Encoded"):
                body = base64.b64decode(body).decode("utf-8")
            payload = json.loads(body)
        except (TypeError, ValueError):
            raise _BadRequest("Request body must be valid JSON.")
        if not isinstance(payload, dict):
            raise _BadRequest("Request body must be a JSON object.")
        return payload

    def text_field(payload, name, required=True):
        """A string field from the body; None when an optional field is absent."""
        if name not in payload or payload[name] is None:
            if required:
                raise _BadRequest(f"{name} is required.")
            return None
        if not isinstance(payload[name], str):
            raise _BadRequest(f"{name} must be text.")
        return payload[name]

    def only(payload, *allowed):
        unknown = sorted(set(payload) - set(allowed))
        if unknown:
            raise _BadRequest(f"Unknown field(s): {', '.join(unknown)}.")

    def tags_and_accounts(owner_id, method, parts, event):
        """Routes under /profiles/me: tags and accounts of the authenticated owner."""
        kind = parts[0]
        item_id = parts[1] if len(parts) == 2 else None

        if kind == "tags":
            if method == "POST" and item_id is None:
                payload = read_body(event)
                only(payload, "name")
                return response(201, asdict(store.create_tag(owner_id, text_field(payload, "name"))))
            if method == "PATCH" and item_id:
                payload = read_body(event)
                only(payload, "name")
                return response(200, asdict(store.rename_tag(owner_id, item_id, text_field(payload, "name"))))
            if method == "DELETE" and item_id:
                store.delete_tag(owner_id, item_id)
                return response(200, profile_json(store.get_profile_for_owner(owner_id)))

        if kind == "accounts":
            if method == "POST" and item_id is None:
                payload = read_body(event)
                only(payload, "name", "tag_id")
                account = store.create_account(
                    owner_id, text_field(payload, "name"), text_field(payload, "tag_id", required=False)
                )
                return response(201, asdict(account))
            if method == "PATCH" and item_id:
                payload = read_body(event)
                only(payload, "name", "tag_id")
                name = text_field(payload, "name", required=False)
                tag_id = text_field(payload, "tag_id", required=False)
                if name is None and tag_id is None:
                    raise _BadRequest("Send a name, a tag_id, or both.")
                return response(200, asdict(store.update_account(owner_id, item_id, name=name, tag_id=tag_id)))
            if method == "DELETE" and item_id:
                store.delete_account(owner_id, item_id)
                return response(200, {"deleted": item_id})

        return error(404, "NOT_FOUND", "Route not found.")

    def handle(event, context):
        event = event or {}
        request_context = event.get("requestContext") or {}
        authorizer = request_context.get("authorizer") or {}
        jwt = authorizer.get("jwt") or {}
        claims = jwt.get("claims") or {}
        owner_id = claims.get("sub")

        if not owner_id:
            return error(401, "UNAUTHENTICATED", "Authentication is required.")

        method = (request_context.get("http") or {}).get("method", "")
        path = event.get("rawPath", "")

        if method == "POST" and path == "/profiles":
            try:
                payload = read_body(event)
            except _BadRequest as bad:
                return error(400, "INVALID_REQUEST", str(bad))

            if payload:
                return error(400, "INVALID_REQUEST", "Request body must be empty or an empty object.")

            try:
                profile = store.create_profile(owner_id)
            except ValueError:
                return error(
                    409,
                    "PROFILE_ALREADY_EXISTS",
                    "This owner already has a profile.",
                )

            return response(201, profile_json(profile))

        if method == "GET" and path == "/profiles/me":
            try:
                profile = store.get_profile_for_owner(owner_id)
            except KeyError:
                return error(
                    404,
                    "PROFILE_NOT_FOUND",
                    "No profile exists for the authenticated owner.",
                )

            return response(200, profile_json(profile))

        parts = [part for part in path.split("/") if part]
        if parts[:2] == ["profiles", "me"] and len(parts) in (3, 4) and parts[2] in ("tags", "accounts"):
            try:
                # Checked first so a missing profile is not mistaken for a missing tag or account.
                store.get_profile_for_owner(owner_id)
            except KeyError:
                return error(404, "PROFILE_NOT_FOUND", "No profile exists for the authenticated owner.")
            try:
                return tags_and_accounts(owner_id, method, parts[2:], event)
            except _BadRequest as bad:
                return error(400, "INVALID_REQUEST", str(bad))
            except KeyError:
                return error(404, "NOT_FOUND", "That tag or account does not exist in your profile.")
            except ValueError as invalid:
                message = str(invalid)
                if "already exists" in message:
                    return error(409, "TAG_ALREADY_EXISTS", "A tag with that name already exists.")
                if "cannot be deleted" in message:
                    return error(409, "DEFAULT_TAG", "The General tag cannot be deleted.")
                return error(400, "INVALID_REQUEST", message[:1].upper() + message[1:] + ".")

        return error(404, "NOT_FOUND", "Route not found.")

    return handle


def handler(event, context):
    """AWS Lambda entry point; keep the DynamoDB client warm between calls."""
    global _aws_handler
    if _aws_handler is None:
        from src.profile_repository import DynamoDBProfileRepository

        _aws_handler = make_handler(DynamoDBProfileRepository.from_environment())
    return _aws_handler(event, context)
