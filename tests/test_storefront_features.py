import json
import re
import unittest
from decimal import Decimal
from unittest.mock import patch

from app import create_app
from extensions import db
from models import Payment, PaymentSeller, Product, User


class StorefrontFeatureTestConfig:
    SECRET_KEY = "storefront-feature-test-key"
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


class StorefrontFeatureTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(StorefrontFeatureTestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.seller = User(name="Seller", email="seller@example.test")
        db.session.add(self.seller)
        db.session.flush()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _add_product(self, title, price, discount=5, seller=None):
        product = Product(
            slug=title.lower().replace(" ", "-"),
            title=title,
            description="A product",
            price=Decimal(price),
            discount_percent=Decimal(str(discount)),
            stock=10,
            category="Other",
            seller_id=(seller or self.seller).id,
        )
        db.session.add(product)
        db.session.flush()
        return product

    def _csrf_token(self):
        response = self.client.get("/cart")
        return re.search(rb'data-csrf-token="([^"]+)"', response.data).group(1).decode()

    def _login_seller(self):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(self.seller.id)
            session["_fresh"] = True

    def test_wishlist_toggle_and_listing(self):
        product = self._add_product("Saved item", "20.00")
        db.session.commit()
        headers = {"X-CSRFToken": self._csrf_token()}

        response = self.client.post(
            "/wishlist/toggle",
            json={"product_id": product.id},
            headers=headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"saved": True, "count": 1})
        self.assertIn(b"Saved item", self.client.get("/wishlist").data)

        response = self.client.post(
            "/wishlist/toggle",
            json={"product_id": product.id},
            headers=headers,
        )

        self.assertEqual(response.json, {"saved": False, "count": 0})
        self.assertIn(b"No saved products yet", self.client.get("/wishlist").data)

    def test_wishlist_rejects_invalid_and_unavailable_products(self):
        token = self._csrf_token()

        invalid = self.client.post(
            "/wishlist/toggle",
            json={"product_id": "not-an-id"},
            headers={"X-CSRFToken": token},
        )
        missing = self.client.post(
            "/wishlist/toggle",
            json={"product_id": 9999},
            headers={"X-CSRFToken": token},
        )

        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json["error"], "Choose a valid product to save.")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json["error"], "That product is no longer available.")

    def test_admin_account_has_verified_badge_on_identity_surfaces(self):
        admin = User(name="Marketplace Admin", email="admin@example.test")
        db.session.add(admin)
        db.session.flush()
        product = self._add_product("Admin seller product", "40.00", seller=admin)
        regular_product = self._add_product("Regular seller product", "20.00")
        db.session.commit()
        self.app.config["ADMIN_EMAILS"] = "ADMIN@example.test"

        product_page = self.client.get(f"/p/{product.slug}")
        self.assertIn(b"Verified administrator", product_page.data)
        regular_product_page = self.client.get(f"/p/{regular_product.slug}")
        self.assertNotIn(b"Verified administrator", regular_product_page.data)

        with self.client.session_transaction() as session:
            session["_user_id"] = str(admin.id)
            session["_fresh"] = True
        from flask import g
        g.pop("_login_user", None)
        profile_page = self.client.get("/profile")
        self.assertEqual(profile_page.status_code, 200)
        self.assertIn(b"Marketplace Admin", profile_page.data)
        self.assertIn(b"Verified administrator", profile_page.data)
        analytics_page = self.client.get("/admin/analytics")
        self.assertEqual(analytics_page.status_code, 200)
        self.assertIn(b"Verified administrator", analytics_page.data)

    def test_browse_filters_by_discounted_price_and_sorts(self):
        self._add_product("Ten with discount", "10.00", 5)
        self._add_product("Twenty half price", "20.00", 50)
        self._add_product("Thirty discounted", "30.00", 5)
        db.session.commit()

        response = self.client.get("/browse?sort=price_asc")
        markup = response.data.decode()

        self.assertLess(markup.index("Ten with discount"), markup.index("Twenty half price"))
        self.assertLess(markup.index("Twenty half price"), markup.index("Thirty discounted"))
        filtered = self.client.get("/browse?min_price=20")
        self.assertIn(b"Thirty discounted", filtered.data)
        self.assertNotIn(b"Ten with discount", filtered.data)

    def test_browse_inverted_price_range_returns_empty_results(self):
        self._add_product("Price range item", "95.00")
        db.session.commit()

        for suffix in ("", "&_partial=1"):
            response = self.client.get(f"/browse?min_price=906&max_price=99{suffix}")

            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Minimum price cannot be greater than maximum price.", response.data)
            self.assertNotIn(b"Price range item", response.data)

    def test_bad_request_renders_custom_error_page(self):
        response = self.client.get("/browse?max_price=5237867788")

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"<title>400", response.data)
        self.assertIn(b"Enter a valid max price.", response.data)
        self.assertIn(b"Back home", response.data)

    def test_browse_paginates_and_filters_on_sale_products(self):
        sellers = [self.seller]
        for number in range(2):
            seller = User(name=f"Seller {number + 1}", email=f"seller{number + 1}@example.test")
            db.session.add(seller)
            db.session.flush()
            sellers.append(seller)
        for number in range(15):
            self._add_product(
                f"Product {number:02d}", "20.00", 0 if number == 0 else 5,
                seller=sellers[number // 5],
            )
        db.session.commit()

        first_page = self.client.get("/browse?sale=1")
        second_page = self.client.get("/browse?sale=1&page=2")
        second_markup = second_page.data.decode()

        self.assertIn(b"14 pieces found", first_page.data)
        self.assertIn(b"14 pieces found", second_page.data)
        self.assertIn("Product 02", second_markup)
        self.assertIn("Product 01", second_markup)
        self.assertNotIn("Product 03", second_markup)
        self.assertNotIn("Product 00", second_markup)

    def test_new_listing_discount_defaults_to_five_percent_and_is_editable(self):
        self._login_seller()
        page = self.client.get("/sell")
        self.assertIn(b'name="discount_percent"', page.data)
        self.assertIn(b'value="5"', page.data)
        token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()

        response = self.client.post(
            "/sell",
            data={
                "csrf_token": token,
                "title": "Discounted product",
                "description": "On sale",
                "price": "100",
                "stock": "3",
                "category": "Other",
                "status": "active",
            },
        )

        self.assertEqual(response.status_code, 302)
        product = Product.query.filter_by(title="Discounted product").one()
        self.assertEqual(product.discount_percent, Decimal("5.00"))

        edit_response = self.client.post(
            f"/products/{product.id}/edit",
            data={
                "csrf_token": token,
                "title": product.title,
                "description": product.description,
                "price": "100",
                "discount_percent": "12.5",
                "stock": "3",
                "category": "Other",
                "status": "active",
            },
        )

        self.assertEqual(edit_response.status_code, 302)
        db.session.refresh(product)
        self.assertEqual(product.discount_percent, Decimal("12.50"))
        self.assertEqual(product.discounted_price, Decimal("87.50"))

    @patch("payments.stk_push")
    def test_checkout_charges_discounted_price(self, push):
        product = self._add_product("Sale item", "100.00", 5)
        db.session.commit()
        self._login_seller()
        push.return_value = {
            "ResponseCode": "0",
            "CheckoutRequestID": "ws_CO_sale",
            "MerchantRequestID": "merchant_sale",
        }

        response = self.client.post(
            "/api/checkout/stk",
            json={
                "phone": "0712345678",
                "expected_total": "95.00",
                "items": [{"id": product.id, "qty": 1}],
            },
            headers={"X-CSRFToken": self._csrf_token()},
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json["amount"], 95)
        push.assert_called_once_with("254712345678", 95, response.json["reference"])
        self.assertEqual(Payment.query.one().amount, 95)
        self.assertEqual(PaymentSeller.query.one().amount, Decimal("95.00"))
        self.assertEqual(json.loads(Payment.query.one().items_json)[0]["price"], "95.00")

    @patch("payments.stk_push")
    def test_checkout_rounds_discounted_total_for_mpesa(self, push):
        product = self._add_product("Fractional sale", "10.00", 5)
        db.session.commit()
        self._login_seller()
        push.return_value = {
            "ResponseCode": "0",
            "CheckoutRequestID": "ws_CO_rounding",
            "MerchantRequestID": "merchant_rounding",
        }

        response = self.client.post(
            "/api/checkout/stk",
            json={
                "phone": "0712345678",
                "expected_total": "10.00",
                "items": [{"id": product.id, "qty": 1}],
            },
            headers={"X-CSRFToken": self._csrf_token()},
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json["amount"], 10)
        self.assertEqual(PaymentSeller.query.one().amount, Decimal("10.00"))
        self.assertEqual(json.loads(Payment.query.one().items_json)[0]["price"], "9.50")


if __name__ == "__main__":
    unittest.main()
