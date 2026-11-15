import json
from typing import Protocol

from dataclasses import asdict

from src.profiles import UserProfile

_aws_handler = None


class ProfileRepository(Protocol):
    def create_profile(self, owner_id: str) -> UserProfile: ...

    def get_profile_for_owner(self, owner_id: str) -> UserProfile: ...


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
                body = event.get("body") or "{}"
                payload = json.loads(body)
            except (TypeError, json.JSONDecodeError):
                return error(400, "INVALID_REQUEST", "Request body must be valid JSON.")

            if not isinstance(payload, dict) or payload:
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

        return error(404, "NOT_FOUND", "Route not found.")

    return handle


def handler(event, context):
    """AWS Lambda entry point; keep the DynamoDB client warm between calls."""
    global _aws_handler
    if _aws_handler is None:
        from src.profile_repository import DynamoDBProfileRepository

        _aws_handler = make_handler(DynamoDBProfileRepository.from_environment())
    return _aws_handler(event, context)
