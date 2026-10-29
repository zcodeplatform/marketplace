from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import CATEGORIES, STATUS_ACTIVE, STATUS_SOLD, Product
from utils import allowed_image, delete_image, save_image

bp = Blueprint("seller", __name__)


def _own_product_or_404(product_id):
    product = db.get_or_404(Product, product_id)
    if product.seller_id != current_user.id:
        abort(403)
    return product


def _parse_form(form, files):
    """Validate product form input. Returns (values, error)."""
    title = form.get("title", "").strip()
    description = form.get("description", "").strip()
    category = form.get("category", "Other")
    status = form.get("status", STATUS_ACTIVE)
    try:
        price = Decimal(form.get("price", "").strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None, "Please enter a valid price."

    if not title or len(title) > 150:
        return None, "Title is required (150 characters max)."
    if price < 0 or price > Decimal("99999999.99"):
        return None, "Price must be between 0 and 99,999,999.99."
    if category not in CATEGORIES:
        return None, "Please choose a category."
    if status not in (STATUS_ACTIVE, STATUS_SOLD):
        return None, "Invalid status."
    image = files.get("image")
    if image and image.filename and not allowed_image(image.filename):
        return None, "Image must be a PNG, JPG, WEBP or GIF file."
    return dict(title=title, description=description, price=price, category=category,
                status=status, image=image if image and image.filename else None), None


@bp.route("/sell", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        values, error = _parse_form(request.form, request.files)
        if error:
            flash(error, "error")
            return render_template("products/form.html", product=None, form=request.form,
                                   categories=CATEGORIES), 400
        image = values.pop("image")
        product = Product(**values, slug=Product.make_slug(values["title"]), seller_id=current_user.id)
        if image:
            product.image_path = save_image(image)
        db.session.add(product)
        db.session.commit()
        flash("Your product is live! Share the link below.", "success")
        return redirect(url_for("main.product_detail", slug=product.slug))
    return render_template("products/form.html", product=None, form={}, categories=CATEGORIES)


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
def edit(product_id):
    product = _own_product_or_404(product_id)
    if request.method == "POST":
        values, error = _parse_form(request.form, request.files)
        if error:
            flash(error, "error")
            return render_template("products/form.html", product=product, form=request.form,
                                   categories=CATEGORIES), 400
        image = values.pop("image")
        for key, val in values.items():
            setattr(product, key, val)  # slug is intentionally left unchanged
        if image:
            delete_image(product.image_path)
            product.image_path = save_image(image)
        db.session.commit()
        flash("Product updated.", "success")
        return redirect(url_for("main.product_detail", slug=product.slug))
    return render_template("products/form.html", product=product, form={}, categories=CATEGORIES)


@bp.route("/products/<int:product_id>/status", methods=["POST"])
@login_required
def toggle_status(product_id):
    product = _own_product_or_404(product_id)
    product.status = STATUS_ACTIVE if product.is_sold else STATUS_SOLD
    db.session.commit()
    flash(f"Marked as {product.status}.", "success")
    return redirect(request.referrer or url_for("profile.view"))


@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@login_required
def delete(product_id):
    product = _own_product_or_404(product_id)
    delete_image(product.image_path)
    db.session.delete(product)
    db.session.commit()
    flash("Product deleted.", "info")
    return redirect(url_for("profile.view"))
