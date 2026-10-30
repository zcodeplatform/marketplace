import unittest
from decimal import Decimal

from app import create_app
from extensions import db
from models import Product, ProductView, User


class AnalyticsTestConfig:
    SECRET_KEY = "analytics-test-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TESTING = True
    CURRENCY_SYMBOL = "KES "
    GOOGLE_CLIENT_ID = ""
    GOOGLE_CLIENT_SECRET = ""
    ADMIN_EMAILS = "admin@example.test"
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
    PRODUCT_VIEW_COOKIE_NAME = "marketplace_viewer"
    PRODUCT_VIEW_COOKIE_MAX_AGE = 10 * 365 * 24 * 60 * 60
    UPLOAD_FOLDER = ""


class ProductViewAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(AnalyticsTestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.seller = User()
        self.seller.name = "Seller"
        self.seller.email = "seller@example.test"
        self.viewer = User()
        self.viewer.name = "Viewer"
        self.viewer.email = "viewer@example.test"
        self.admin = User()
        self.admin.name = "Admin"
        self.admin.email = "admin@example.test"
        db.session.add_all([self.seller, self.viewer, self.admin])
        db.session.flush()
        self.product = Product()
        self.product.slug = "analytics-item"
        self.product.title = "Analytics item"
        self.product.description = ""
        self.product.price = Decimal("10.00")
        self.product.category = "Other"
        self.product.seller_id = self.seller.id
        db.session.add(self.product)
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _login(self, client, user):
        with client.session_transaction() as session:
            session["_user_id"] = str(user.id)
            session["_fresh"] = True
        from flask import g

        g.pop("_login_user", None)

    def test_anonymous_browser_counts_once_per_product_and_cookie_is_protected(self):
        first = self.client.get("/p/analytics-item")
        second = self.client.get("/p/analytics-item")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(ProductView.query.filter_by(product_id=self.product.id).count(), 1)
        cookie_header = first.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie_header)
        self.assertIn("SameSite=Lax", cookie_header)
        self.assertNotIn("Secure", cookie_header)

    def test_different_anonymous_browsers_count_as_separate_viewers(self):
        self.client.get("/p/analytics-item")
        other_browser = self.app.test_client()
        other_browser.get("/p/analytics-item")

        self.assertEqual(ProductView.query.filter_by(product_id=self.product.id).count(), 2)

    def test_signed_in_account_counts_once_and_owner_views_are_excluded(self):
        viewer_client = self.app.test_client()
        self._login(viewer_client, self.viewer)
        viewer_client.get("/p/analytics-item")
        viewer_client.get("/p/analytics-item")

        seller_client = self.app.test_client()
        self._login(seller_client, self.seller)
        seller_client.get("/p/analytics-item")

        records = ProductView.query.filter_by(product_id=self.product.id).all()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].viewer_id, self.viewer.id)

    def test_seller_profile_shows_own_product_unique_view_count(self):
        self.client.get("/p/analytics-item")
        self._login(self.client, self.seller)

        response = self.client.get("/profile")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"1 unique view", response.data)

    def test_admin_can_see_all_products_and_view_counts(self):
        self.client.get("/p/analytics-item")
        self._login(self.client, self.admin)

        response = self.client.get("/admin/analytics")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Analytics item", response.data)
        self.assertIn(b"1 unique view", response.data)

    def test_non_admin_cannot_view_global_analytics(self):
        self._login(self.client, self.viewer)

        response = self.client.get("/admin/analytics")

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
