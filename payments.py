import json
import re
import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, flash, jsonify, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from extensions import csrf, db
from models import (
    LISTING_PLAN_DAYS,
    LISTING_PLAN_PRICE,
    STATUS_ACTIVE,
    ListingPlanPayment,
    Payment,
    PaymentSeller,
    Product,
    public_listing_filter,
)
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
        public_listing_filter(),
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
    if not current_user.is_authenticated:
        return jsonify(
            error="Sign in to complete checkout.",
            login_url=url_for("auth.login", next=url_for("main.cart")),
        ), 401

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
        buyer_id=current_user.id,
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


@bp.post("/seller/listing-plan/stk")
@login_required
def start_listing_plan():
    phone_number = _normalize_phone(request.form.get("phone"))
    if not phone_number:
        flash("Enter a valid Kenyan M-Pesa number, such as 0712345678.", "error")
        return redirect(url_for("profile.view"))

    reference = f"PL{secrets.token_hex(5).upper()}"
    payment = ListingPlanPayment(
        seller_id=current_user.id,
        reference=reference,
        phone_number=phone_number,
        amount=LISTING_PLAN_PRICE,
        status="pending",
    )
    db.session.add(payment)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not create listing-plan payment record")
        flash("Could not start payment. Please try again.", "error")
        return redirect(url_for("profile.view"))

    try:
        response = stk_push(phone_number, LISTING_PLAN_PRICE, reference)
    except MpesaError as error:
        payment.status = "failed"
        payment.mpesa_response = json.dumps({"message": str(error)})
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("Could not record listing-plan request failure: %s", reference)
            flash("Payment failed and could not be recorded. Please contact support.", "error")
            return redirect(url_for("profile.view"))
        flash(str(error), "error")
        return redirect(url_for("profile.view"))

    payment.checkout_request_id = response["CheckoutRequestID"]
    payment.merchant_request_id = response.get("MerchantRequestID")
    payment.mpesa_response = json.dumps(response)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not save accepted listing-plan request: %s", reference)
        flash(
            "M-Pesa accepted the prompt, but the request could not be saved. "
            f"Contact support with reference {reference}.",
            "error",
        )
        return redirect(url_for("profile.view"))

    flash(f"KES {LISTING_PLAN_PRICE} payment prompt sent. Approve it on your phone.", "info")
    return redirect(url_for("profile.view"))


@bp.post("/seller/listing-plan/<int:payment_id>/check")
@login_required
def check_listing_plan_payment(payment_id):
    payment = ListingPlanPayment.query.filter_by(
        id=payment_id,
        seller_id=current_user.id,
    ).first_or_404()
    if payment.status != "pending":
        flash(f"Listing plan payment is {payment.status}.", "info")
        return redirect(url_for("profile.view"))
    if not payment.checkout_request_id:
        flash("M-Pesa has not returned a checkout reference yet. Please try again shortly.", "info")
        return redirect(url_for("profile.view"))

    try:
        data = stk_query(payment.checkout_request_id)
    except MpesaError as error:
        flash(str(error), "error")
        return redirect(url_for("profile.view"))

    raw_result_code = data.get("ResultCode")
    if raw_result_code is None:
        flash("M-Pesa is still processing the payment. Check again shortly.", "info")
        return redirect(url_for("profile.view"))
    try:
        result_code = int(raw_result_code)
    except (TypeError, ValueError):
        flash("M-Pesa returned an unrecognized status. Please check again.", "error")
        return redirect(url_for("profile.view"))

    _set_listing_plan_payment_result(payment, result_code, data)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not save listing-plan payment query result")
        flash("Could not save the M-Pesa result. Please check again.", "error")
        return redirect(url_for("profile.view"))
    flash(f"Listing plan payment is {payment.status}.", "success" if payment.status == "success" else "info")
    return redirect(url_for("profile.view"))


def _set_listing_plan_payment_result(payment, result_code, data):
    if payment.status != "pending":
        return
    payment.status = "success" if result_code == 0 else "cancelled" if result_code == 1032 else "failed"
    payment.mpesa_response = json.dumps(data)
    if result_code == 0:
        payment.paid_at = datetime.now(timezone.utc)
        payment.expires_at = payment.paid_at + timedelta(days=LISTING_PLAN_DAYS)


def _callback_paid_amount(callback):
    metadata = callback.get("CallbackMetadata")
    items = metadata.get("Item") if isinstance(metadata, dict) else None
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("Name") == "Amount":
            value = item.get("Value")
            if isinstance(value, bool):
                return None
            try:
                amount = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                return None
            return amount if amount.is_finite() else None
    return None


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

    plan_payment = ListingPlanPayment.query.filter_by(checkout_request_id=checkout_id).first()
    if plan_payment:
        if result_code == 0 and _callback_paid_amount(callback) != Decimal(plan_payment.amount):
            current_app.logger.warning(
                "M-Pesa listing-plan callback amount did not match reference %s",
                plan_payment.reference,
            )
            result_code = -1
        _set_listing_plan_payment_result(plan_payment, result_code, data)
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("Could not save M-Pesa listing-plan callback")
            return jsonify(ResultCode=1, ResultDesc="Could not record payment result"), 500
        return jsonify(ResultCode=0, ResultDesc="Success")

    payment = Payment.query.filter_by(checkout_request_id=checkout_id).first()
    if not payment:
        current_app.logger.warning("Received M-Pesa callback for unknown checkout request")
        return jsonify(ResultCode=1, ResultDesc="Payment not found"), 404

    if payment.status == "pending":
        if result_code == 0:
            payment.status = "success"
        elif result_code == 1032:
            payment.status = "cancelled"
        else:
            payment.status = "failed"
        payment.mpesa_response = json.dumps(data)
    else:
        current_app.logger.info("Ignoring duplicate terminal M-Pesa callback for %s", payment.reference)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not save M-Pesa callback")
        return jsonify(ResultCode=1, ResultDesc="Could not record payment result"), 500
    return jsonify(ResultCode=0, ResultDesc="Success")


@bp.post("/api/payments/<checkout_id>/query")
@login_required
def query_payment(checkout_id):
    payment = Payment.query.filter_by(
        checkout_request_id=checkout_id,
        buyer_id=current_user.id,
    ).first()
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

    if payment.status == "pending":
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
@login_required
def payment_status(checkout_id):
    payment = Payment.query.filter_by(
        checkout_request_id=checkout_id,
        buyer_id=current_user.id,
    ).first()
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
