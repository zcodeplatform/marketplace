import unittest
from decimal import Decimal

from app import create_app
from extensions import db
from models import Product, STATUS_ACTIVE, STATUS_SOLD, User


class HomeSearchTestConfig:
    SECRET_KEY = "home-search-test-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TESTING = True
    CURRENCY_SYMBOL = "KES "
    GOOGLE_CLIENT_ID = ""
    GOOGLE_CLIENT_SECRET = ""
    ADMIN_EMAILS = ""
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
    PRODUCT_VIEW_COOKIE_NAME = "marketplace_viewer"
    PRODUCT_VIEW_COOKIE_MAX_AGE = 10 * 365 * 24 * 60 * 60
    UPLOAD_FOLDER = ""


class HomeSearchTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(HomeSearchTestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.sellers = []
        for number in range(2):
            seller = User()
            seller.name = f"Seller {number}"
            seller.email = f"seller{number}@example.test"
            db.session.add(seller)
            self.sellers.append(seller)
        db.session.flush()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _add_product(self, seller, slug, status=STATUS_ACTIVE):
        product = Product()
        product.slug = slug
        product.title = slug
        product.description = "A desk lamp"
        product.price = Decimal("10.00")
        product.stock = 1
        product.category = "Other"
        product.status = status
        product.seller_id = seller.id
        db.session.add(product)
        return product

    def test_homepage_search_has_no_search_button(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'data-home-search', response.data)
        self.assertIn(b'class="hero-search-icon"', response.data)
        self.assertNotIn(b'<button class="btn" type="submit">Search</button>', response.data)

    def test_suggestions_return_up_to_six_active_matching_products(self):
        for number in range(4):
            self._add_product(self.sellers[0], f"lamp-{number}")
        for number in range(3):
            self._add_product(self.sellers[1], f"lamp-{number + 4}")
        self._add_product(self.sellers[1], "lamp-sold", STATUS_SOLD)
        db.session.commit()

        response = self.client.get("/browse?q=lamp&_suggest=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.count(b'role="option"'), 6)
        self.assertNotIn(b"lamp-sold", response.data)
        self.assertIn(b"See all results", response.data)


if __name__ == "__main__":
    unittest.main()
