import json
import unittest

from src.profile_handler import make_handler
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


if __name__ == "__main__":
    unittest.main()