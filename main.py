from flask import Blueprint, redirect, render_template, request, url_for

from models import CATEGORIES, STATUS_ACTIVE, Product

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    latest = Product.query.filter_by(status=STATUS_ACTIVE).order_by(Product.created_at.desc()).limit(6).all()
    return render_template("index.html", products=latest)


@bp.route("/browse")
def browse():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "")
    show_sold = request.args.get("sold") == "1"

    query = Product.query
    if not show_sold:
        query = query.filter_by(status=STATUS_ACTIVE)
    if category in CATEGORIES:
        query = query.filter_by(category=category)
    if q:
        like = f"%{q}%"
        query = query.filter(Product.title.ilike(like) | Product.description.ilike(like))
    products = query.order_by(Product.created_at.desc()).all()
    return render_template("browse.html", products=products, q=q, category=category,
                           categories=CATEGORIES, show_sold=show_sold)


@bp.route("/p/<slug>")
def product_detail(slug):
    product = Product.query.filter_by(slug=slug).first_or_404()
    return render_template("products/detail.html", product=product)


@bp.route("/product/<int:product_id>")
def product_by_id(product_id):
    """Alternate link form: /product/<id> redirects to the canonical /p/<slug>."""
    product = Product.query.get_or_404(product_id)
    return redirect(url_for("main.product_detail", slug=product.slug), code=301)
