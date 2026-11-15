import json
import sys
import unittest
from unittest.mock import patch

from src.profile_handler import make_handler
from src.profile_repository import DynamoDBProfileRepository
from src.profiles import ProfileStore


class TestProfileHandler(unittest.TestCase):
    def setUp(self):
        self.store = ProfileStore()
        self.handler = make_handler(self.store)

    def event(self, method, path, *, owner_id="test-owner", body=None):
        event = {
            "version": "2.0",
            "rawPath": path,
            "requestContext": {
                "http": {"method": method},
                "authorizer": {
                    "jwt": {"claims": {"sub": owner_id}}
                },
            },
        }
        if body is not None:
            event["body"] = body
        return event

    def call(self, event):
        response = self.handler(event, None)
        return response["statusCode"], json.loads(response["body"])

    def test_create_profile_returns_general_tag(self):
        status, body = self.call(
            self.event("POST", "/profiles", body="{}")
        )

        self.assertEqual(status, 201)
        self.assertTrue(body["profile_id"])
        self.assertEqual(len(body["tags"]), 1)
        self.assertEqual(body["tags"][0]["name"], "General")
        self.assertTrue(body["tags"][0]["is_default"])
        self.assertEqual(body["accounts"], [])

    def test_duplicate_profile_returns_conflict(self):
        self.call(self.event("POST", "/profiles", body="{}"))

        status, body = self.call(
            self.event("POST", "/profiles", body="{}")
        )

        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "PROFILE_ALREADY_EXISTS")

    def test_get_profile_returns_authenticated_owners_profile(self):
        self.call(self.event("POST", "/profiles", body="{}"))

        status, body = self.call(
            self.event("GET", "/profiles/me")
        )

        self.assertEqual(status, 200)
        self.assertTrue(body["profile_id"])
        self.assertEqual(body["tags"][0]["name"], "General")

    def test_get_missing_profile_returns_not_found(self):
        status, body = self.call(
            self.event("GET", "/profiles/me")
        )

        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "PROFILE_NOT_FOUND")

    def test_missing_authentication_returns_unauthorized(self):
        event = self.event("GET", "/profiles/me")
        del event["requestContext"]["authorizer"]

        status, body = self.call(event)

        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "UNAUTHENTICATED")

    def test_invalid_create_body_returns_bad_request(self):
        status, body = self.call(
            self.event("POST", "/profiles", body="{not-json")
        )

        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "INVALID_REQUEST")

    def test_base64_encoded_create_body_is_decoded(self):
        event = self.event("POST", "/profiles", body="e30=")  
        event["isBase64Encoded"] = True

        status, body = self.call(event)

        self.assertEqual(status, 201)
        self.assertTrue(body["profile_id"])

    def test_invalid_base64_create_body_returns_bad_request(self):
        event = self.event("POST", "/profiles", body="!")
        event["isBase64Encoded"] = True

        status, body = self.call(event)

        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "INVALID_REQUEST")


class TestTagAndAccountRoutes(unittest.TestCase):
    """The tag and account routes, run against the DynamoDB repository with a fake table."""

    def setUp(self):
        from tests import test_profile_repository as fakes

        modules = patch.dict(sys.modules, fakes._fake_boto3_modules())
        modules.start()
        self.addCleanup(modules.stop)
        self.handler = make_handler(DynamoDBProfileRepository(fakes._FakeTable()))
        self.profile = self.call("POST", "/profiles")[1]

    def call(self, method, path, body=None, owner_id="owner-1"):
        event = {
            "version": "2.0",
            "rawPath": path,
            "requestContext": {
                "http": {"method": method},
                "authorizer": {"jwt": {"claims": {"sub": owner_id}}},
            },
        }
        if body is not None:
            event["body"] = json.dumps(body)
        response = self.handler(event, None)
        return response["statusCode"], json.loads(response["body"])

    def test_create_rename_and_delete_tag(self):
        status, tag = self.call("POST", "/profiles/me/tags", {"name": "Work"})
        self.assertEqual((status, tag["name"], tag["is_default"]), (201, "Work", False))

        status, renamed = self.call("PATCH", f"/profiles/me/tags/{tag['tag_id']}", {"name": "Business"})
        self.assertEqual((status, renamed["name"]), (200, "Business"))

        status, profile = self.call("DELETE", f"/profiles/me/tags/{tag['tag_id']}")
        self.assertEqual(status, 200)
        self.assertEqual([t["name"] for t in profile["tags"]], ["General"])

    def test_duplicate_tag_name_is_a_conflict(self):
        self.call("POST", "/profiles/me/tags", {"name": "Work"})

        status, body = self.call("POST", "/profiles/me/tags", {"name": "work"})

        self.assertEqual((status, body["error"]["code"]), (409, "TAG_ALREADY_EXISTS"))

    def test_general_tag_cannot_be_deleted(self):
        status, body = self.call("DELETE", f"/profiles/me/tags/{self.profile['default_tag_id']}")

        self.assertEqual((status, body["error"]["code"]), (409, "DEFAULT_TAG"))

    def test_account_defaults_to_general_then_moves_and_renames(self):
        tag = self.call("POST", "/profiles/me/tags", {"name": "Work"})[1]

        status, account = self.call("POST", "/profiles/me/accounts", {"name": "Checking"})
        self.assertEqual((status, account["tag_id"]), (201, self.profile["default_tag_id"]))

        status, moved = self.call(
            "PATCH", f"/profiles/me/accounts/{account['account_id']}", {"name": "Main", "tag_id": tag["tag_id"]}
        )
        self.assertEqual((status, moved["name"], moved["tag_id"]), (200, "Main", tag["tag_id"]))

        profile = self.call("GET", "/profiles/me")[1]
        self.assertEqual(profile["accounts"][0]["name"], "Main")

    def test_deleting_a_tag_returns_its_accounts_to_general(self):
        tag = self.call("POST", "/profiles/me/tags", {"name": "Work"})[1]
        self.call("POST", "/profiles/me/accounts", {"name": "Checking", "tag_id": tag["tag_id"]})

        profile = self.call("DELETE", f"/profiles/me/tags/{tag['tag_id']}")[1]

        self.assertEqual(profile["accounts"][0]["tag_id"], self.profile["default_tag_id"])

    def test_delete_account(self):
        account = self.call("POST", "/profiles/me/accounts", {"name": "Checking"})[1]

        status, body = self.call("DELETE", f"/profiles/me/accounts/{account['account_id']}")

        self.assertEqual((status, body), (200, {"deleted": account["account_id"]}))
        self.assertEqual(self.call("GET", "/profiles/me")[1]["accounts"], [])

    def test_bad_input_is_rejected(self):
        cases = [
            ("POST", "/profiles/me/tags", {}),
            ("POST", "/profiles/me/tags", {"name": "   "}),
            ("POST", "/profiles/me/tags", {"name": 5}),
            ("POST", "/profiles/me/tags", {"name": "Work", "is_default": True}),
            ("POST", "/profiles/me/accounts", {"tag_id": self.profile["default_tag_id"]}),
            ("PATCH", "/profiles/me/accounts/some-id", {}),
        ]
        for method, path, body in cases:
            with self.subTest(path=path, body=body):
                status, response = self.call(method, path, body)
                self.assertEqual((status, response["error"]["code"]), (400, "INVALID_REQUEST"))

    def test_unknown_tag_or_account_is_not_found(self):
        for method, path, body in [
            ("PATCH", "/profiles/me/tags/missing", {"name": "X"}),
            ("DELETE", "/profiles/me/tags/missing", None),
            ("POST", "/profiles/me/accounts", {"name": "Checking", "tag_id": "missing"}),
            ("PATCH", "/profiles/me/accounts/missing", {"name": "X"}),
            ("DELETE", "/profiles/me/accounts/missing", None),
        ]:
            with self.subTest(method=method, path=path):
                self.assertEqual(self.call(method, path, body)[0], 404)

    def test_another_owner_cannot_change_my_tags_or_accounts(self):
        tag = self.call("POST", "/profiles/me/tags", {"name": "Work"})[1]
        account = self.call("POST", "/profiles/me/accounts", {"name": "Checking"})[1]
        self.call("POST", "/profiles", owner_id="owner-2")

        attempts = [
            ("PATCH", f"/profiles/me/tags/{tag['tag_id']}", {"name": "Mine"}),
            ("DELETE", f"/profiles/me/tags/{tag['tag_id']}", None),
            ("POST", "/profiles/me/accounts", {"name": "Sneaky", "tag_id": tag["tag_id"]}),
            ("PATCH", f"/profiles/me/accounts/{account['account_id']}", {"name": "Mine"}),
            ("DELETE", f"/profiles/me/accounts/{account['account_id']}", None),
        ]
        for method, path, body in attempts:
            with self.subTest(method=method, path=path):
                self.assertEqual(self.call(method, path, body, owner_id="owner-2")[0], 404)

        mine = self.call("GET", "/profiles/me")[1]
        self.assertEqual(len(mine["tags"]), 2)
        self.assertEqual(mine["accounts"][0]["name"], "Checking")

    def test_routes_need_a_profile_first(self):
        status, body = self.call("POST", "/profiles/me/tags", {"name": "Work"}, owner_id="nobody")

        self.assertEqual((status, body["error"]["code"]), (404, "PROFILE_NOT_FOUND"))


if __name__ == "__main__":
    unittest.main()