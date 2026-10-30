import json
import re

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import (
    LISTING_PLAN_DAYS,
    LISTING_PLAN_PRICE,
    MAX_SELLER_PRODUCTS,
    ListingPlanPayment,
    Payment,
    PaymentSeller,
    Product,
    active_listing_plan,
    latest_successful_listing_plan_payment,
)
from utils import ImageStorageError, ImageUploadError, allowed_image, delete_image, save_image

bp = Blueprint("profile", __name__)

PHONE_RE = re.compile(r"\+?[0-9][0-9\s\-]{6,18}")


@bp.route("/profile")
@login_required
def view():
    seller_payments = (
        PaymentSeller.query.join(Payment)
        .filter(PaymentSeller.seller_id == current_user.id)
        .order_by(Payment.created_at.desc())
        .all()
    )
    history = [
        {"share": share, "line_items": json.loads(share.items_json)}
        for share in seller_payments
    ]
    products = current_user.products.all()
    free_product_ids = {
        product_id
        for (product_id,) in db.session.query(Product.id)
        .filter_by(seller_id=current_user.id)
        .order_by(Product.created_at.asc(), Product.id.asc())
        .limit(MAX_SELLER_PRODUCTS)
        .all()
    }
    active_plan = active_listing_plan(current_user.id)
    last_successful_plan_payment = latest_successful_listing_plan_payment(current_user.id)
    plan_payments = current_user.listing_plan_payments.order_by(
        ListingPlanPayment.created_at.desc(),
        ListingPlanPayment.id.desc(),
    ).all()
    return render_template(
        "profile/view.html",
        products=products,
        free_product_ids=free_product_ids,
        product_limit="Unlimited" if active_plan else MAX_SELLER_PRODUCTS,
        can_add_products=active_plan is not None or len(products) < MAX_SELLER_PRODUCTS,
        active_listing_plan=active_plan,
        last_successful_plan_payment=last_successful_plan_payment,
        listing_plan_payments=plan_payments,
        listing_plan_price=LISTING_PLAN_PRICE,
        listing_plan_days=LISTING_PLAN_DAYS,
        seller_payment_history=history,
    )


@bp.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        bio = request.form.get("bio", "").strip()
        phone = request.form.get("phone", "").strip()
        avatar = request.files.get("avatar")
        error = None
        if not name or len(name) > 120:
            error = "Name is required (120 characters max)."
        elif len(bio) > 500:
            error = "Bio must be 500 characters or fewer."
        elif phone and not PHONE_RE.fullmatch(phone):
            error = "Enter a valid phone number, e.g. +254 712 345 678."
        elif avatar and avatar.filename and not allowed_image(avatar.filename):
            error = "Profile picture must be a PNG, JPG, WEBP or GIF file."
        if error:
            flash(error, "error")
            return render_template("profile/edit.html"), 400

        old_avatar_path = current_user.avatar_path
        new_avatar_path = old_avatar_path
        if request.form.get("remove_avatar"):
            new_avatar_path = None
        if avatar and avatar.filename:
            try:
                new_avatar_path = save_image(avatar)
            except ImageUploadError as error:
                flash(str(error), "error")
                return render_template("profile/edit.html"), 400
            except ImageStorageError as error:
                flash(str(error), "error")
                return render_template("profile/edit.html"), 503

        current_user.name, current_user.bio = name, bio or None
        current_user.phone = phone or None
        current_user.show_phone = bool(phone) and bool(request.form.get("show_phone"))
        current_user.avatar_path = new_avatar_path
        db.session.commit()
        if old_avatar_path != new_avatar_path:
            try:
                delete_image(old_avatar_path)
            except ImageStorageError as error:
                current_app.logger.error("Profile updated but old avatar cleanup failed: %s", error)
                flash("Profile updated, but the previous picture could not be removed from storage.", "error")
        flash("Profile updated.", "success")
        return redirect(url_for("profile.view"))
    return render_template("profile/edit.html")