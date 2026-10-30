import json
import re
import secrets
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from extensions import csrf, db
from models import STATUS_ACTIVE, Payment, PaymentSeller, Product
from mpesa import MpesaError, stk_push, stk_query

bp = Blueprint("payments", __name__)


def _normalize_phone(value):
    phone = re.sub(r"[\s-]", "", str(value or ""))
    if phone.startswith("+"):
        phone = phone[1:]
    if phone.startswith("0"):
        phone = "254" + phone[1:]
    if not re.fullmatch(r"254[17]\d{8}", phone):
        return None
    return phone


def _parse_cart(data):
    entries = data.get("items") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries or len(entries) > 100:
        return None, "Your cart is empty or invalid."

    quantities = {}
    for entry in entries:
        if not isinstance(entry, dict):
            return None, "Your cart contains an invalid item."
        raw_id = entry.get("id")
        if isinstance(raw_id, bool) or not isinstance(raw_id, (int, str)) or not str(raw_id).isdecimal():
            return None, "Your cart contains an invalid item."
        try:
            product_id = int(raw_id)
        except (TypeError, ValueError):
            return None, "Your cart contains an invalid item."
        quantity = entry.get("qty")
        if product_id < 1 or isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            return None, "Your cart contains an invalid quantity."
        if product_id in quantities:
            return None, "Your cart contains a duplicate item."
        quantities[product_id] = quantity
    return quantities, None


def _cart_snapshot(quantities):
    products = Product.query.filter(
        Product.id.in_(quantities),
        Product.status == STATUS_ACTIVE,
    ).all()
    if len(products) != len(quantities):
        return None, None, "One or more items are no longer available. Please update your cart."

    total = Decimal("0.00")
    items = []
    for product in products:
        quantity = quantities[product.id]
        total += product.price * quantity
        items.append({
            "id": product.id,
            "name": product.title,
            "price": format(product.price, ".2f"),
            "image": product.image_url,
            "qty": quantity,
            "seller_id": product.seller_id,
        })

    items.sort(key=lambda item: item["id"])
    return items, total, None


@bp.post("/api/checkout/stk")
def start_stk_push():
    data = request.get_json(silent=True)
    quantities, error = _parse_cart(data)
    if error:
        return jsonify(error=error), 400

    phone_number = _normalize_phone(data.get("phone"))
    if not phone_number:
        return jsonify(error="Enter a valid Kenyan M-Pesa number, such as 0712345678."), 400

    items, total, error = _cart_snapshot(quantities)
    if error or items is None or total is None:
        return jsonify(error=error or "Could not calculate your cart total."), 409

    seller_items = defaultdict(list)
    seller_amounts = defaultdict(lambda: Decimal("0.00"))
    for item in items:
        seller_id = item["seller_id"]
        seller_items[seller_id].append({key: value for key, value in item.items() if key != "seller_id"})
        seller_amounts[seller_id] += Decimal(item["price"]) * item["qty"]

    expected_total = data.get("expected_total")
    try:
        if Decimal(str(expected_total)) != total:
            return jsonify(
                error="Product prices changed. Review the updated total and try again.",
                items=[{key: value for key, value in item.items() if key != "seller_id"} for item in items],
                total=format(total, ".2f"),
            ), 409
    except (InvalidOperation, TypeError, ValueError):
        return jsonify(error="Your cart total is invalid. Refresh the cart and try again."), 400

    if total < 1 or total != total.to_integral_value():
        return jsonify(error="M-Pesa checkout requires a whole-shilling total of at least KES 1."), 400

    reference = f"MP{secrets.token_hex(4).upper()}"
    payment = Payment(
        reference=reference,
        phone_number=phone_number,
        amount=int(total),
        items_json=json.dumps(items),
        status="pending",
    )
    payment.seller_shares = [
        PaymentSeller(
            seller_id=seller_id,
            amount=amount,
            items_json=json.dumps(seller_items[seller_id]),
        )
        for seller_id, amount in seller_amounts.items()
    ]
    db.session.add(payment)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not create M-Pesa payment record")
        return jsonify(error="Could not start checkout. Please try again."), 500

    try:
        response = stk_push(phone_number, int(total), reference)
    except MpesaError as error:
        payment.status = "failed"
        payment.mpesa_response = json.dumps({"message": str(error)})
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("Could not record M-Pesa request failure: %s", reference)
            return jsonify(error="M-Pesa checkout failed and could not be recorded. Please contact support."), 500
        return jsonify(error=str(error)), 502

    payment.checkout_request_id = response["CheckoutRequestID"]
    payment.merchant_request_id = response.get("MerchantRequestID")
    payment.mpesa_response = json.dumps(response)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not save accepted M-Pesa request: %s", reference)
        return jsonify(
            error="M-Pesa accepted the payment prompt, but checkout could not save it. "
                  f"Please contact support with reference {reference}.",
        ), 500

    return jsonify(
        status="pending",
        message="Payment prompt sent. Enter your M-Pesa PIN on your phone.",
        checkout_id=payment.checkout_request_id,
        reference=reference,
        amount=int(total),
    ), 202


@bp.post("/mpesa/callback")
@csrf.exempt
def mpesa_callback():
    data = request.get_json(silent=True)
    body = data.get("Body") if isinstance(data, dict) else None
    callback = body.get("stkCallback") if isinstance(body, dict) else None
    if not isinstance(callback, dict):
        return jsonify(ResultCode=1, ResultDesc="Invalid callback data"), 400
    checkout_id = callback.get("CheckoutRequestID")
    result_code = callback.get("ResultCode")
    if not checkout_id or isinstance(result_code, bool) or not isinstance(result_code, int):
        return jsonify(ResultCode=1, ResultDesc="Invalid callback data"), 400

    payment = Payment.query.filter_by(checkout_request_id=checkout_id).first()
    if not payment:
        current_app.logger.warning("Received M-Pesa callback for unknown checkout request")
        return jsonify(ResultCode=1, ResultDesc="Payment not found"), 404

    if result_code == 0:
        payment.status = "success"
    elif result_code == 1032:
        payment.status = "cancelled"
    else:
        payment.status = "failed"
    payment.mpesa_response = json.dumps(data)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not save M-Pesa callback")
        return jsonify(ResultCode=1, ResultDesc="Could not record payment result"), 500
    return jsonify(ResultCode=0, ResultDesc="Success")


@bp.post("/api/payments/<checkout_id>/query")
def query_payment(checkout_id):
    payment = Payment.query.filter_by(checkout_request_id=checkout_id).first()
    if not payment:
        return jsonify(error="Payment not found."), 404
    if payment.status != "pending":
        return _payment_status_response(payment)

    try:
        data = stk_query(checkout_id)
    except MpesaError as error:
        return jsonify(status="pending", message=str(error)), 502

    raw_result_code = data.get("ResultCode")
    if raw_result_code is None:
        return jsonify(
            status="pending",
            message="M-Pesa has not confirmed the payment yet. Check your phone for the prompt.",
        )
    try:
        result_code = int(raw_result_code)
    except (TypeError, ValueError):
        return jsonify(status="pending", message="M-Pesa returned an unrecognized status. Try again.")

    if result_code == 0:
        payment.status = "success"
    elif result_code == 1032:
        payment.status = "cancelled"
    else:
        payment.status = "failed"
    payment.mpesa_response = json.dumps(data)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not save M-Pesa query result")
        return jsonify(error="Could not save the M-Pesa result. Please check again."), 500
    return _payment_status_response(payment)


@bp.get("/api/payments/<checkout_id>")
def payment_status(checkout_id):
    payment = Payment.query.filter_by(checkout_request_id=checkout_id).first()
    if not payment:
        return jsonify(error="Payment not found."), 404

    return _payment_status_response(payment)


def _payment_status_response(payment):
    if payment.status == "pending":
        message = "M-Pesa prompt sent. Waiting for you to approve or cancel it on your phone."
    else:
        message = "M-Pesa did not provide a result description."
    if payment.status != "pending" and payment.mpesa_response:
        try:
            data = json.loads(payment.mpesa_response)
        except json.JSONDecodeError:
            current_app.logger.warning("Could not parse M-Pesa response for payment %s", payment.reference)
        else:
            if isinstance(data, dict):
                body = data.get("Body")
                callback = body.get("stkCallback") if isinstance(body, dict) else None
                message = (
                    (callback.get("ResultDesc") if isinstance(callback, dict) else None)
                    or data.get("CustomerMessage")
                    or data.get("message")
                    or message
                )
    return jsonify(status=payment.status, message=message, reference=payment.reference)
