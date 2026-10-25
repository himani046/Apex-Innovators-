import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.security import require_api_token, security_mode


class SecurityTests(unittest.TestCase):
    def test_local_development_is_open_only_when_no_token_is_configured(self):
        with patch.dict("os.environ", {"ODIN_ENV": "development"}, clear=True):
            self.assertEqual(security_mode(), "local_development_open")
            self.assertIsNone(require_api_token(None))

    def test_production_without_token_fails_closed(self):
        with patch.dict("os.environ", {"ODIN_ENV": "production"}, clear=True):
            self.assertEqual(security_mode(), "misconfigured_production")
            with self.assertRaises(HTTPException) as raised:
                require_api_token(None)
            self.assertEqual(raised.exception.status_code, 503)

    def test_configured_token_requires_valid_bearer_header(self):
        with patch.dict("os.environ", {"ODIN_API_TOKEN": "test-secret"}, clear=True):
            with self.assertRaises(HTTPException) as missing:
                require_api_token(None)
            self.assertEqual(missing.exception.status_code, 401)
            with self.assertRaises(HTTPException) as wrong:
                require_api_token("Bearer incorrect")
            self.assertEqual(wrong.exception.status_code, 401)
            self.assertIsNone(require_api_token("Bearer test-secret"))

    def test_non_bearer_authentication_is_rejected(self):
        with patch.dict("os.environ", {"ODIN_API_TOKEN": "test-secret"}, clear=True):
            with self.assertRaises(HTTPException):
                require_api_token("Basic dXNlcjpwYXNz")


if __name__ == "__main__":
    unittest.main()
