import json
import re
import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP

from flask import Blueprint, current_app, flash, jsonify, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import update
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
        public_listing_filter(),
    ).all()
    if len(products) != len(quantities):
        return None, None, "One or more items are no longer available. Please update your cart."

    total = Decimal("0.00")
    items = []
    products_by_id = {product.id: product for product in products}
    for product_id, quantity in quantities.items():
        product = products_by_id[product_id]
        if product.stock < 1:
            return None, None, f"{product.title} is already out of stock."
        if product.status != STATUS_ACTIVE:
            return None, None, "One or more items are no longer available. Please update your cart."
        if quantity > product.stock:
            return None, None, (
                f"Insufficient stock for {product.title}. "
                f"Only {product.stock} item(s) are available."
            )
        discounted_price = product.discounted_price
        total += discounted_price * quantity
        items.append({
            "id": product.id,
            "name": product.title,
            "price": format(discounted_price, ".2f"),
            "original_price": format(product.price, ".2f"),
            "discount_percent": format(product.discount_percent, ".2f"),
            "image": product.image_url,
            "qty": quantity,
            "seller_id": product.seller_id,
        })

    items.sort(key=lambda item: item["id"])
    return items, total, None


def _allocate_seller_amounts(seller_amounts, total, payable_total):
    allocated = {}
    remainders = []
    for seller_id, amount in seller_amounts.items():
        exact_cents = amount * payable_total / total * 100
        whole_cents = exact_cents.to_integral_value(rounding=ROUND_DOWN)
        allocated[seller_id] = whole_cents / 100
        remainders.append((exact_cents - whole_cents, seller_id))

    remaining_cents = int((payable_total - sum(allocated.values())) * 100)
    for _, seller_id in sorted(remainders, reverse=True)[:remaining_cents]:
        allocated[seller_id] += Decimal("0.01")
    return allocated


def _reserve_inventory(quantities):
    """Atomically reserve each cart line; the caller commits or rolls back the transaction."""
    for product_id, quantity in sorted(quantities.items()):
        result = db.session.execute(
            update(Product)
            .where(
                Product.id == product_id,
                Product.status == STATUS_ACTIVE,
                Product.stock >= quantity,
            )
            .values(stock=Product.stock - quantity)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            return product_id
    return None


def _inventory_error(product_id, quantity):
    product = Product.query.filter(
        Product.id == product_id,
        public_listing_filter(),
    ).first()
    if not product:
        return "One or more items are no longer available. Please update your cart."
    if product.stock < 1:
        return f"{product.title} is already out of stock."
    if product.status == STATUS_ACTIVE and quantity > product.stock:
        return (
            f"Insufficient stock for {product.title}. "
            f"Only {product.stock} item(s) are available."
        )
    return "One or more items are no longer available. Please update your cart."


def _set_checkout_payment_result(payment, result_code, data):
    status = "success" if result_code == 0 else "cancelled" if result_code == 1032 else "failed"
    result = db.session.execute(
        update(Payment)
        .where(Payment.id == payment.id, Payment.status == "pending")
        .values(status=status, mpesa_response=json.dumps(data))
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1 or status == "success":
        return result.rowcount == 1

    items = json.loads(payment.items_json)
    if not isinstance(items, list):
        raise ValueError(f"Invalid inventory reservation for payment {payment.reference}.")
    for item in items:
        product_id = item.get("id") if isinstance(item, dict) else None
        quantity = item.get("qty") if isinstance(item, dict) else None
        if (
            isinstance(product_id, bool)
            or not isinstance(product_id, int)
            or product_id < 1
            or isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity < 1
        ):
            raise ValueError(f"Invalid inventory reservation for payment {payment.reference}.")
        db.session.execute(
            update(Product)
            .where(Product.id == product_id)
            .values(stock=Product.stock + quantity)
            .execution_options(synchronize_session=False)
        )
    return True


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

    payable_total = total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if total > 0 and payable_total > 0:
        seller_amounts = _allocate_seller_amounts(seller_amounts, total, payable_total)

    expected_total = data.get("expected_total")
    try:
        if Decimal(str(expected_total)) != payable_total:
            return jsonify(
                error="Product prices changed. Review the updated total and try again.",
                items=[{key: value for key, value in item.items() if key != "seller_id"} for item in items],
                total=format(total, ".2f"),
                payable_total=format(payable_total, ".2f"),
            ), 409
    except (InvalidOperation, TypeError, ValueError):
        return jsonify(error="Your cart total is invalid. Refresh the cart and try again."), 400

    if payable_total < 1:
        return jsonify(error="M-Pesa checkout requires a whole-shilling total of at least KES 1."), 400

    reference = f"MP{secrets.token_hex(4).upper()}"
    payment = Payment(
        reference=reference,
        phone_number=phone_number,
        amount=int(payable_total),
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
    failed_product_id = _reserve_inventory(quantities)
    if failed_product_id is not None:
        db.session.rollback()
        return jsonify(error=_inventory_error(failed_product_id, quantities[failed_product_id])), 409
    db.session.add(payment)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not create M-Pesa payment record")
        return jsonify(error="Could not start checkout. Please try again."), 500

    try:
        response = stk_push(phone_number, int(payable_total), reference)
    except MpesaError as error:
        try:
            _set_checkout_payment_result(payment, 1, {"message": str(error)})
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("Could not record M-Pesa request failure: %s", reference)
            return jsonify(error="M-Pesa checkout failed and could not be recorded. Please contact support."), 500
        except ValueError:
            db.session.rollback()
            current_app.logger.exception("Could not restore inventory for failed M-Pesa request: %s", reference)
            return jsonify(error="M-Pesa checkout failed and inventory could not be restored. Please contact support."), 500
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
        amount=int(payable_total),
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

    if payment.status != "pending":
        current_app.logger.info("Ignoring duplicate terminal M-Pesa callback for %s", payment.reference)
    try:
        _set_checkout_payment_result(payment, result_code, data)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not save M-Pesa callback")
        return jsonify(ResultCode=1, ResultDesc="Could not record payment result"), 500
    except ValueError:
        db.session.rollback()
        current_app.logger.exception("Could not restore inventory for M-Pesa callback")
        return jsonify(ResultCode=1, ResultDesc="Could not restore inventory"), 500
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

    try:
        _set_checkout_payment_result(payment, result_code, data)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not save M-Pesa query result")
        return jsonify(error="Could not save the M-Pesa result. Please check again."), 500
    except ValueError:
        db.session.rollback()
        current_app.logger.exception("Could not restore inventory for M-Pesa query result")
        return jsonify(error="Could not restore inventory. Please contact support."), 500
    db.session.refresh(payment)
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
