import unittest
from unittest.mock import patch

from app import create_app
from extensions import db, oauth
from models import User


class AuthTestConfig:
    SECRET_KEY = "auth-test-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    TESTING = True
    CURRENCY_SYMBOL = "KES "
    GOOGLE_CLIENT_ID = "google-client-id"
    GOOGLE_CLIENT_SECRET = "google-client-secret"
    ADMIN_EMAILS = ""
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
    PRODUCT_VIEW_COOKIE_NAME = "marketplace_viewer"
    PRODUCT_VIEW_COOKIE_MAX_AGE = 10 * 365 * 24 * 60 * 60
    UPLOAD_FOLDER = ""


class SignupConsentTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(AuthTestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def test_signup_page_shows_required_terms_and_age_confirmations(self):
        response = self.client.get("/signup")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('name="agree_terms" required', page)
        self.assertIn('name="confirm_age" required', page)
        self.assertIn("at least 13 years old", page)
        self.assertIn('href="/terms"', page)

    def test_terms_page_is_public_and_contains_marketplace_terms(self):
        response = self.client.get("/terms")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Terms &amp; Conditions", page)
        self.assertIn("at least 13 years old", page)
        self.assertIn("Orders, payments, and delivery", page)

    def test_signup_rejects_missing_consent(self):
        response = self.client.post(
            "/signup",
            data={"name": "New User", "email": "new@example.test", "password": "password123"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIsNone(User.query.filter_by(email="new@example.test").first())

    def test_signup_creates_user_when_both_confirmations_are_submitted(self):
        response = self.client.post(
            "/signup",
            data={
                "name": "New User",
                "email": "new@example.test",
                "password": "password123",
                "agree_terms": "on",
                "confirm_age": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(User.query.filter_by(email="new@example.test").first())

    def test_google_callback_does_not_create_account_without_signup_consent(self):
        userinfo = {
            "sub": "google-user-id",
            "email": "google@example.test",
            "email_verified": True,
            "name": "Google User",
        }
        with patch.object(oauth.google, "authorize_access_token", return_value={"userinfo": userinfo}):
            response = self.client.get("/auth/google/callback")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/signup")
        self.assertIsNone(User.query.filter_by(email="google@example.test").first())


if __name__ == "__main__":
    unittest.main()
