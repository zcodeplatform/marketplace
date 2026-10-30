import html
import json
import re
import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

from app import _migrate_product_categories, create_app
from extensions import db
from models import CATEGORIES, Payment, Product, User
from mpesa import stk_push, stk_query


class TestConfig:
    SECRET_KEY = "test-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TESTING = True
    CURRENCY_SYMBOL = "KES "
    GOOGLE_CLIENT_ID = ""
    GOOGLE_CLIENT_SECRET = ""
    UPLOAD_FOLDER = ""
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
    MPESA_BASE_URL = "https://sandbox.safaricom.co.ke"
    MPESA_CONSUMER_KEY = "test-key"
    MPESA_CONSUMER_SECRET = "test-secret"
    MPESA_PASSKEY = "test-passkey"
    MPESA_SHORTCODE = "174379"
    MPESA_TRANSACTION_TYPE = "CustomerPayBillOnline"
    MPESA_CALLBACK_URL = "https://example.test/mpesa/callback"


class PaymentCheckoutTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        seller = User(name="Seller", email="seller@example.test")
        db.session.add(seller)
        db.session.flush()
        self.product = Product(
            slug="test-item",
            title="Test item",
            description="",
            price=Decimal("10.00"),
            category="Other",
            seller_id=seller.id,
        )
        db.session.add(self.product)
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _checkout(self, phone="0712345678", expected_total="10.00"):
        token = self._csrf_token()
        return self.client.post(
            "/api/checkout/stk",
            json={
                "phone": phone,
                "expected_total": expected_total,
                "items": [{"id": self.product.id, "qty": 1}],
            },
            headers={"X-CSRFToken": token},
        )

    def _csrf_token(self):
        page = self.client.get("/cart")
        return re.search(rb'data-csrf-token="([^"]+)"', page.data).group(1).decode()

    @patch("payments.stk_push")
    def test_checkout_uses_server_price_and_normalizes_phone(self, push):
        push.return_value = {
            "ResponseCode": "0",
            "CheckoutRequestID": "ws_CO_test",
            "MerchantRequestID": "merchant_test",
        }

        response = self._checkout()

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json["amount"], 10)
        push.assert_called_once_with("254712345678", 10, response.json["reference"])
        self.assertEqual(Payment.query.one().status, "pending")

    @patch("payments.stk_push")
    def test_changed_price_requires_review_before_push(self, push):
        self.product.price = Decimal("12.00")
        db.session.commit()

        response = self._checkout(expected_total="10.00")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["items"][0]["price"], "12.00")
        push.assert_not_called()
        self.assertEqual(Payment.query.count(), 0)

    @patch("payments.stk_push")
    def test_invalid_phone_does_not_start_payment(self, push):
        response = self._checkout(phone="not-a-phone")

        self.assertEqual(response.status_code, 400)
        push.assert_not_called()

    def test_cart_page_renders_checkout_routes(self):
        response = self.client.get("/cart")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"data-checkout-url", response.data)
        self.assertIn(b"data-csrf-token", response.data)

    def test_major_categories_are_visible_on_home_and_browse(self):
        for path in ("/", "/browse"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            page = html.unescape(response.get_data(as_text=True))
            for category in CATEGORIES:
                self.assertIn(category, page)

    def test_existing_narrow_categories_are_migrated(self):
        self.product.category = "Table"
        db.session.commit()

        _migrate_product_categories()

        db.session.refresh(self.product)
        self.assertEqual(self.product.category, "Home & Furniture")
        self.assertIn(self.product.category, CATEGORIES)

    def test_checkout_requires_csrf_token(self):
        response = self.client.post(
            "/api/checkout/stk",
            json={"phone": "0712345678", "expected_total": "10.00", "items": [{"id": self.product.id, "qty": 1}]},
        )

        self.assertEqual(response.status_code, 400)

    def test_stk_push_sends_daraja_request(self):
        token_response = Mock()
        token_response.json.return_value = {"access_token": "access-token"}
        push_response = Mock()
        push_response.json.return_value = {
            "ResponseCode": "0",
            "CheckoutRequestID": "ws_CO_test",
        }

        with patch("mpesa.requests.get", return_value=token_response) as get_token:
            with patch("mpesa.requests.post", return_value=push_response) as send_push:
                result = stk_push("254712345678", 10, "MP12345678")

        self.assertEqual(result["CheckoutRequestID"], "ws_CO_test")
        get_token.assert_called_once_with(
            "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials",
            auth=("test-key", "test-secret"),
            timeout=15,
        )
        payload = send_push.call_args.kwargs["json"]
        self.assertEqual(send_push.call_args.kwargs["headers"]["Authorization"], "Bearer access-token")
        self.assertEqual(payload["Amount"], 10)
        self.assertEqual(payload["PartyA"], "254712345678")
        self.assertEqual(payload["CallBackURL"], TestConfig.MPESA_CALLBACK_URL)
        self.assertEqual(payload["AccountReference"], "MP12345678")

    def test_stk_query_sends_daraja_status_request(self):
        token_response = Mock()
        token_response.json.return_value = {"access_token": "access-token"}
        query_response = Mock()
        query_response.json.return_value = {
            "ResponseCode": "0",
            "ResultCode": "1032",
            "ResultDesc": "The user has cancelled the request.",
        }

        with patch("mpesa.requests.get", return_value=token_response):
            with patch("mpesa.requests.post", return_value=query_response) as send_query:
                result = stk_query("ws_CO_test")

        self.assertEqual(result["ResultCode"], "1032")
        self.assertEqual(
            send_query.call_args.args[0],
            "https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query",
        )
        self.assertEqual(send_query.call_args.kwargs["json"]["CheckoutRequestID"], "ws_CO_test")

    @patch("payments.stk_push")
    def test_callback_updates_payment_status(self, push):
        push.return_value = {
            "ResponseCode": "0",
            "CheckoutRequestID": "ws_CO_test",
            "MerchantRequestID": "merchant_test",
        }
        checkout = self._checkout()
        callback = self.client.post(
            "/mpesa/callback",
            data=json.dumps({
                "Body": {
                    "stkCallback": {
                        "CheckoutRequestID": checkout.json["checkout_id"],
                        "ResultCode": 0,
                        "ResultDesc": "The service request is processed successfully.",
                    },
                },
            }),
            content_type="application/json",
        )

        self.assertEqual(callback.status_code, 200)
        self.assertEqual(Payment.query.one().status, "success")
        status = self.client.get(f"/api/payments/{checkout.json['checkout_id']}")
        self.assertEqual(status.json["status"], "success")

    @patch("payments.stk_push")
    def test_callback_marks_user_cancellation(self, push):
        push.return_value = {
            "ResponseCode": "0",
            "CheckoutRequestID": "ws_CO_cancel",
            "MerchantRequestID": "merchant_cancel",
        }
        checkout = self._checkout()
        callback = self.client.post(
            "/mpesa/callback",
            json={
                "Body": {
                    "stkCallback": {
                        "CheckoutRequestID": checkout.json["checkout_id"],
                        "ResultCode": 1032,
                        "ResultDesc": "Request cancelled by user",
                    },
                },
            },
        )

        self.assertEqual(callback.status_code, 200)
        status = self.client.get(f"/api/payments/{checkout.json['checkout_id']}")
        self.assertEqual(status.json["status"], "cancelled")
        self.assertEqual(status.json["message"], "Request cancelled by user")

    @patch("payments.stk_query")
    @patch("payments.stk_push")
    def test_manual_query_marks_cancellation(self, push, query):
        push.return_value = {
            "ResponseCode": "0",
            "CheckoutRequestID": "ws_CO_query",
            "MerchantRequestID": "merchant_query",
        }
        checkout = self._checkout()
        query.return_value = {
            "ResponseCode": "0",
            "ResultCode": "1032",
            "ResultDesc": "The user has cancelled the request.",
        }

        response = self.client.post(
            f"/api/payments/{checkout.json['checkout_id']}/query",
            headers={"X-CSRFToken": self._csrf_token()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "cancelled")
        self.assertEqual(Payment.query.one().status, "cancelled")
        query.assert_called_once_with(checkout.json["checkout_id"])

    @patch("payments.stk_query")
    @patch("payments.stk_push")
    def test_manual_query_without_result_keeps_payment_pending(self, push, query):
        push.return_value = {
            "ResponseCode": "0",
            "CheckoutRequestID": "ws_CO_pending",
            "MerchantRequestID": "merchant_pending",
        }
        checkout = self._checkout()
        query.return_value = {
            "ResponseCode": "0",
            "ResponseDescription": "The service request has been accepted successfully",
        }

        response = self.client.post(
            f"/api/payments/{checkout.json['checkout_id']}/query",
            headers={"X-CSRFToken": self._csrf_token()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "pending")
        self.assertIn("has not confirmed", response.json["message"])
        self.assertEqual(Payment.query.one().status, "pending")


if __name__ == "__main__":
    unittest.main()
