import io
import re
import unittest
from unittest.mock import patch

from app import create_app
from extensions import db
from models import HomepageAd, User


class AdsTestConfig:
    SECRET_KEY = "test-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TESTING = True
    CURRENCY_SYMBOL = "KES "
    GOOGLE_CLIENT_ID = ""
    GOOGLE_CLIENT_SECRET = ""
    ADMIN_EMAILS = ""
    UPLOAD_FOLDER = ""
    IMAGE_STORAGE_BACKEND = "local"
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}


class HomepageAdsTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(AdsTestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.admin = User(name="Admin", email="admin@example.test")
        self.other_user = User(name="Member", email="member@example.test")
        db.session.add_all([self.admin, self.other_user])
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _login(self, user):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user.id)
            session["_fresh"] = True

    def _csrf_token(self, path="/"):
        page = self.client.get(path)
        return re.search(rb'data-csrf-token="([^"]+)"', page.data).group(1).decode()

    def _ad(self, title, *, is_active=True):
        ad = HomepageAd(
            title=title,
            image_path=f"uploads/{title.lower().replace(' ', '-')}.webp",
            is_active=is_active,
            created_by_id=self.admin.id,
        )
        db.session.add(ad)
        db.session.commit()
        return ad

    def test_only_admin_email_can_manage_ads(self):
        self.app.config["ADMIN_EMAILS"] = "admin@example.test"
        self._login(self.other_user)
        response = self.client.get("/admin/ads/")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_manage_ads(self):
        self.app.config["ADMIN_EMAILS"] = "admin@example.test"
        self._login(self.admin)
        response = self.client.get("/admin/ads/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Homepage ads", response.data)

    def test_upload_saves_ad_record_and_optional_destination(self):
        self.app.config["ADMIN_EMAILS"] = "admin@example.test"
        self._login(self.admin)
        token = self._csrf_token("/admin/ads/")
        with patch("ads.save_image", return_value="r2:uploads/banner.webp") as save:
            response = self.client.post(
                "/admin/ads/",
                data={
                    "csrf_token": token,
                    "title": "Summer sale",
                    "destination_url": "https://shop.example.test/sale",
                    "image": (io.BytesIO(b"fake image"), "banner.png"),
                },
            )

        self.assertEqual(response.status_code, 302)
        save.assert_called_once()
        ad = HomepageAd.query.one()
        self.assertEqual(ad.title, "Summer sale")
        self.assertEqual(ad.image_path, "r2:uploads/banner.webp")
        self.assertEqual(ad.destination_url, "https://shop.example.test/sale")
        self.assertTrue(ad.is_active)

    def test_upload_rejects_non_http_destination_before_storage(self):
        self.app.config["ADMIN_EMAILS"] = "admin@example.test"
        self._login(self.admin)
        token = self._csrf_token("/admin/ads/")
        with patch("ads.save_image") as save:
            response = self.client.post(
                "/admin/ads/",
                data={
                    "csrf_token": token,
                    "title": "Bad link",
                    "destination_url": "javascript:alert(1)",
                    "image": (io.BytesIO(b"fake image"), "banner.png"),
                },
                follow_redirects=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"complete http or https URL", response.data)
        save.assert_not_called()
        self.assertEqual(HomepageAd.query.count(), 0)

    def test_homepage_shows_only_three_newest_active_ads(self):
        self._ad("Old banner")
        self._ad("Second newest")
        self._ad("Newest")
        self._ad("Hidden banner", is_active=False)
        self._ad("Third newest")

        response = self.client.get("/")
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Newest", page)
        self.assertIn("Second newest", page)
        self.assertIn("Third newest", page)
        self.assertNotIn("Old banner", page)
        self.assertNotIn("Hidden banner", page)
        self.assertEqual(page.count('data-ad-slide'), 3)

    def test_admin_can_toggle_and_delete_ads_and_remove_their_image(self):
        self.app.config["ADMIN_EMAILS"] = "admin@example.test"
        self._login(self.admin)
        ad = self._ad("Feature banner")
        token = self._csrf_token("/admin/ads/")

        hidden = self.client.post(
            f"/admin/ads/{ad.id}/toggle",
            data={"csrf_token": token},
        )
        self.assertEqual(hidden.status_code, 302)
        self.assertFalse(db.session.get(HomepageAd, ad.id).is_active)

        token = self._csrf_token("/admin/ads/")
        with patch("ads.delete_image") as delete:
            deleted = self.client.post(
                f"/admin/ads/{ad.id}/delete",
                data={"csrf_token": token},
            )
        self.assertEqual(deleted.status_code, 302)
        self.assertIsNone(db.session.get(HomepageAd, ad.id))
        delete.assert_called_once_with("uploads/feature-banner.webp")


if __name__ == "__main__":
    unittest.main()
