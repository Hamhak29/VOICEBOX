"""Security regressions: tampering, expiry and private access enforcement."""
import hashlib
import hmac
import json
from urllib.parse import urlencode
import unittest

from backend.telegram_auth import make_session, read_session, validate_init_data

TOKEN = "123456:test-token"
NOW = 1780000000


def signed(uid=42, date=NOW, **extras):
    data = {"user": json.dumps({"id": uid, "first_name": "Test"}), "auth_date": str(date), **extras}
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


class TelegramAuthTests(unittest.TestCase):
    def test_valid_and_signature_field(self):
        self.assertEqual(validate_init_data(signed(signature="telegram-signature"), TOKEN, {42}, NOW)["id"], 42)

    def test_tampering(self):
        with self.assertRaises(ValueError):
            validate_init_data(signed().replace("Test", "Fake"), TOKEN, {42}, NOW)

    def test_expired_or_future(self):
        for date in [NOW - 3601, NOW + 31]:
            with self.assertRaises(ValueError):
                validate_init_data(signed(date=date), TOKEN, {42}, NOW)

    def test_no_allowlist_or_other_user(self):
        for allowed in [set(), {43}]:
            with self.assertRaises(PermissionError):
                validate_init_data(signed(), TOKEN, allowed, NOW)

    def test_duplicate_fields(self):
        with self.assertRaises(ValueError):
            validate_init_data(signed() + "&auth_date=1", TOKEN, {42}, NOW)

    def test_session_expiry_tampering_and_revocation(self):
        session = make_session(42, TOKEN, NOW)
        self.assertEqual(read_session(session, TOKEN, {42}, NOW), 42)
        with self.assertRaises(ValueError):
            read_session(session, TOKEN, {42}, NOW + 86400)
        with self.assertRaises(ValueError):
            read_session(session.replace("42.", "43.", 1), TOKEN, {43}, NOW)
        with self.assertRaises(PermissionError):
            read_session(session, TOKEN, set(), NOW)


if __name__ == "__main__":
    unittest.main()
