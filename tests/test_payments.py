import html
import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock, patch

from app import _migrate_product_categories, create_app
from extensions import db
from models import (
    CATEGORIES,
    LISTING_PLAN_DAYS,
    LISTING_PLAN_PRICE,
    MAX_SELLER_PRODUCTS,
    ListingPlanPayment,
    Payment,
    PaymentSeller,
    Product,
    User,
)
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
        self.seller = seller
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

    def _checkout(self, phone="0712345678", expected_total="10.00", items=None):
        token = self._csrf_token()
        return self.client.post(
            "/api/checkout/stk",
            json={
                "phone": phone,
                "expected_total": expected_total,
                "items": items or [{"id": self.product.id, "qty": 1}],
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
        self.assertEqual(PaymentSeller.query.one().seller_id, self.seller.id)
        self.assertEqual(PaymentSeller.query.one().amount, Decimal("10.00"))

    @patch("payments.stk_push")
    def test_multi_seller_checkout_records_each_seller_share(self, push):
        second_seller = User(name="Second seller", email="second@example.test")
        db.session.add(second_seller)
        db.session.flush()
        second_product = Product(
            slug="second-item",
            title="Second item",
            description="",
            price=Decimal("5.00"),
            category="Other",
            seller_id=second_seller.id,
        )
        db.session.add(second_product)
        db.session.commit()
        push.return_value = {
            "ResponseCode": "0",
            "CheckoutRequestID": "ws_CO_multi",
            "MerchantRequestID": "merchant_multi",
        }

        response = self._checkout(
            expected_total="15.00",
            items=[
                {"id": self.product.id, "qty": 1},
                {"id": second_product.id, "qty": 1},
            ],
        )

        self.assertEqual(response.status_code, 202)
        shares = PaymentSeller.query.order_by(PaymentSeller.seller_id).all()
        self.assertEqual([share.seller_id for share in shares], [self.seller.id, second_seller.id])
        self.assertEqual([share.amount for share in shares], [Decimal("10.00"), Decimal("5.00")])
        self.assertEqual(json.loads(shares[0].items_json)[0]["name"], "Test item")
        self.assertEqual(json.loads(shares[1].items_json)[0]["name"], "Second item")

    def test_profile_lists_only_current_sellers_payment_history(self):
        other_seller = User(name="Other seller", email="other@example.test")
        db.session.add(other_seller)
        db.session.flush()
        for index, (seller, status) in enumerate((
            (self.seller, "pending"),
            (self.seller, "success"),
            (self.seller, "failed"),
            (other_seller, "success"),
        )):
            payment = Payment(
                reference=f"MPHIST{index}",
                phone_number="254712345678",
                amount=10,
                items_json="[]",
                status=status,
            )
            payment.seller_shares.append(PaymentSeller(
                seller=seller,
                amount=Decimal("10.00"),
                items_json=json.dumps([{"name": f"{seller.name} item", "qty": 1}]),
            ))
            db.session.add(payment)
        db.session.commit()
        with self.client.session_transaction() as session:
            session["_user_id"] = str(self.seller.id)
            session["_fresh"] = True

        response = self.client.get("/profile")
        page = html.unescape(response.get_data(as_text=True))

        self.assertEqual(response.status_code, 200)
        self.assertIn('action="/logout"', page)
        self.assertIn(">Log out</button>", page)
        self.assertIn("Sales payment history", page)
        self.assertIn("(3)", page)
        self.assertIn("pending", page)
        self.assertIn("success", page)
        self.assertIn("failed", page)
        self.assertEqual(page.count("Seller item"), 3)
        self.assertNotIn("Other seller item", page)

    def test_seller_cannot_add_more_than_five_products(self):
        for index in range(MAX_SELLER_PRODUCTS - 1):
            db.session.add(Product(
                slug=f"extra-item-{index}",
                title=f"Extra item {index}",
                description="",
                price=Decimal("1.00"),
                category="Other",
                seller_id=self.seller.id,
            ))
        db.session.commit()
        with self.client.session_transaction() as session:
            session["_user_id"] = str(self.seller.id)
            session["_fresh"] = True
        token = self._csrf_token()

        get_response = self.client.get("/sell")
        post_response = self.client.post(
            "/sell",
            data={
                "csrf_token": token,
                "title": "Over limit product",
                "description": "Should not be created",
                "price": "1.00",
                "category": "Other",
                "status": "active",
            },
            follow_redirects=True,
        )

        self.assertEqual(get_response.status_code, 302)
        self.assertEqual(post_response.status_code, 200)
        self.assertEqual(Product.query.filter_by(seller_id=self.seller.id).count(), MAX_SELLER_PRODUCTS)
        page = html.unescape(post_response.get_data(as_text=True))
        self.assertIn("Product limit reached", page)
        self.assertIn(f"{MAX_SELLER_PRODUCTS}/{MAX_SELLER_PRODUCTS}", page)

    @patch("payments.stk_push")
    def test_listing_plan_requests_fixed_price_and_callback_activates_it(self, push):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(self.seller.id)
            session["_fresh"] = True
        token = self._csrf_token()
        push.return_value = {
            "ResponseCode": "0",
            "CheckoutRequestID": "ws_CO_listing_plan",
            "MerchantRequestID": "merchant_listing_plan",
        }

        response = self.client.post(
            "/seller/listing-plan/stk",
            data={"csrf_token": token, "phone": "0712345678"},
        )

        self.assertEqual(response.status_code, 302)
        payment = ListingPlanPayment.query.one()
        self.assertEqual(payment.amount, LISTING_PLAN_PRICE)
        self.assertEqual(payment.phone_number, "254712345678")
        self.assertEqual(payment.status, "pending")
        push.assert_called_once_with("254712345678", LISTING_PLAN_PRICE, payment.reference)

        callback = {
            "Body": {
                "stkCallback": {
                    "CheckoutRequestID": payment.checkout_request_id,
                    "ResultCode": 0,
                    "CallbackMetadata": {
                        "Item": [{"Name": "Amount", "Value": LISTING_PLAN_PRICE}],
                    },
                },
            },
        }
        callback_response = self.client.post("/mpesa/callback", json=callback)
        self.assertEqual(callback_response.status_code, 200)
        self.assertEqual(payment.status, "success")
        self.assertEqual(payment.expires_at - payment.paid_at, timedelta(days=LISTING_PLAN_DAYS))

        paid_at = payment.paid_at
        self.client.post("/mpesa/callback", json=callback)
        self.assertEqual(payment.paid_at, paid_at)

    def test_listing_plan_callback_rejects_wrong_paid_amount(self):
        payment = ListingPlanPayment(
            seller_id=self.seller.id,
            reference="PLBADAMOUNT",
            checkout_request_id="ws_CO_bad_plan_amount",
            phone_number="254712345678",
            amount=LISTING_PLAN_PRICE,
            status="pending",
        )
        db.session.add(payment)
        db.session.commit()

        response = self.client.post(
            "/mpesa/callback",
            json={
                "Body": {
                    "stkCallback": {
                        "CheckoutRequestID": payment.checkout_request_id,
                        "ResultCode": 0,
                        "CallbackMetadata": {
                            "Item": [{"Name": "Amount", "Value": LISTING_PLAN_PRICE - 1}],
                        },
                    },
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payment.status, "failed")
        self.assertIsNone(payment.expires_at)

    @patch("payments.stk_query")
    def test_seller_can_check_plan_payment_when_callback_is_delayed(self, query):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(self.seller.id)
            session["_fresh"] = True
        payment = ListingPlanPayment(
            seller_id=self.seller.id,
            reference="PLQUERYTEST",
            checkout_request_id="ws_CO_plan_query",
            phone_number="254712345678",
            amount=LISTING_PLAN_PRICE,
            status="pending",
        )
        db.session.add(payment)
        db.session.commit()
        token = self._csrf_token()
        query.return_value = {"ResultCode": "0"}

        response = self.client.post(
            f"/seller/listing-plan/{payment.id}/check",
            data={"csrf_token": token},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(payment.status, "success")
        self.assertEqual(payment.expires_at - payment.paid_at, timedelta(days=LISTING_PLAN_DAYS))
        query.assert_called_once_with(payment.checkout_request_id)

    def test_expired_plan_hides_only_listings_beyond_the_free_five(self):
        for index in range(MAX_SELLER_PRODUCTS):
            db.session.add(Product(
                slug=f"premium-item-{index}",
                title=f"Premium item {index}",
                description="",
                price=Decimal("1.00"),
                category="Other",
                seller_id=self.seller.id,
            ))
        plan = ListingPlanPayment(
            seller_id=self.seller.id,
            reference="PLVISIBLE",
            phone_number="254712345678",
            amount=LISTING_PLAN_PRICE,
            status="success",
            paid_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=LISTING_PLAN_DAYS),
        )
        db.session.add(plan)
        db.session.commit()

        premium_response = self.client.get("/p/premium-item-4")
        self.assertEqual(premium_response.status_code, 200)

        plan.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.commit()
        hidden_response = self.client.get("/p/premium-item-4")
        free_response = self.client.get("/p/test-item")
        browse_response = self.client.get("/browse")
        checkout_response = self._checkout(
            expected_total="1.00",
            items=[{"id": Product.query.filter_by(slug="premium-item-4").one().id, "qty": 1}],
        )

        self.assertEqual(hidden_response.status_code, 404)
        self.assertEqual(free_response.status_code, 200)
        self.assertNotIn(b"Premium item 4", browse_response.data)
        self.assertEqual(checkout_response.status_code, 409)

    def test_active_plan_allows_more_than_five_products(self):
        for index in range(MAX_SELLER_PRODUCTS - 1):
            db.session.add(Product(
                slug=f"existing-extra-{index}",
                title=f"Existing extra {index}",
                description="",
                price=Decimal("1.00"),
                category="Other",
                seller_id=self.seller.id,
            ))
        db.session.add(ListingPlanPayment(
            seller_id=self.seller.id,
            reference="PLACTIVEPLAN",
            phone_number="254712345678",
            amount=LISTING_PLAN_PRICE,
            status="success",
            paid_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=LISTING_PLAN_DAYS),
        ))
        db.session.commit()
        with self.client.session_transaction() as session:
            session["_user_id"] = str(self.seller.id)
            session["_fresh"] = True
        token = self._csrf_token()

        response = self.client.post(
            "/sell",
            data={
                "csrf_token": token,
                "title": "Paid plan product",
                "description": "Visible during the plan",
                "price": "12.00",
                "category": "Other",
                "status": "active",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Product.query.filter_by(seller_id=self.seller.id).count(), MAX_SELLER_PRODUCTS + 1)
        profile_response = self.client.get("/profile")
        self.assertIn(b"Monthly listings", profile_response.data)
        self.assertIn(b"Unlimited listings are visible until", profile_response.data)

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
