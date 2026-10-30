import hashlib
import hmac
import secrets

from flask import Blueprint, current_app, make_response, redirect, render_template, request, url_for
from flask_login import current_user
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

from extensions import db
from models import CATEGORIES, HomepageAd, Product, ProductView, STATUS_ACTIVE, public_listing_filter
from utils import require_admin

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    latest = Product.query.filter(
        Product.status == STATUS_ACTIVE,
        public_listing_filter(),
    ).order_by(Product.created_at.desc()).limit(6).all()
    ads = HomepageAd.query.filter_by(is_active=True).order_by(
        HomepageAd.created_at.desc(),
        HomepageAd.id.desc(),
    ).limit(3).all()
    return render_template("index.html", products=latest, categories=CATEGORIES, ads=ads)


@bp.route("/browse")
def browse():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "")
    show_sold = request.args.get("sold") == "1"

    query = Product.query.filter(public_listing_filter())
    if not show_sold:
        query = query.filter_by(status=STATUS_ACTIVE)
    if category in CATEGORIES:
        query = query.filter_by(category=category)
    if q:
        like = f"%{q}%"
        query = query.filter(Product.title.ilike(like) | Product.description.ilike(like))
    products = query.order_by(Product.created_at.desc()).all()
    if request.args.get("_partial") == "1":
        return render_template("_browse_results.html", products=products)
    return render_template("browse.html", products=products, q=q, category=category,
                           categories=CATEGORIES, show_sold=show_sold)


@bp.route("/cart")
def cart():
    return render_template("cart.html")


@bp.route("/p/<slug>")
def product_detail(slug):
    product = Product.query.filter(
        Product.slug == slug,
        public_listing_filter(),
    ).first_or_404()
    anonymous_cookie = _record_unique_view(product)
    response = make_response(render_template("products/detail.html", product=product))
    if anonymous_cookie:
        response.set_cookie(
            current_app.config["PRODUCT_VIEW_COOKIE_NAME"],
            anonymous_cookie,
            max_age=current_app.config["PRODUCT_VIEW_COOKIE_MAX_AGE"],
            path="/",
            httponly=True,
            secure=current_app.config.get("SESSION_COOKIE_SECURE", False),
            samesite="Lax",
        )
    return response


def _record_unique_view(product):
    signed_cookie = None
    if current_user.is_authenticated:
        if current_user.id == product.seller_id:
            return None
        viewer_key = f"user:{current_user.id}"
        viewer_id = current_user.id
    else:
        cookie_name = current_app.config["PRODUCT_VIEW_COOKIE_NAME"]
        signed_cookie = request.cookies.get(cookie_name, "")
        secret_key = current_app.secret_key
        if not secret_key:
            raise RuntimeError("SECRET_KEY must be configured to record product views.")
        serializer = URLSafeTimedSerializer(secret_key, salt="product-viewer")
        try:
            viewer_key = serializer.loads(
                signed_cookie,
                max_age=current_app.config["PRODUCT_VIEW_COOKIE_MAX_AGE"],
            ) if signed_cookie and len(signed_cookie) <= 512 else None
        except BadSignature:
            viewer_key = None
        if not isinstance(viewer_key, str):
            viewer_key = secrets.token_urlsafe(32)
            signed_cookie = serializer.dumps(viewer_key)
        else:
            signed_cookie = None
        viewer_id = None

    secret_key = current_app.secret_key
    if not secret_key:
        raise RuntimeError("SECRET_KEY must be configured to record product views.")
    key = secret_key.encode() if isinstance(secret_key, str) else secret_key
    viewer_hash = hmac.new(key, viewer_key.encode(), hashlib.sha256).hexdigest()
    exists = ProductView.query.filter_by(product_id=product.id, viewer_hash=viewer_hash).first()
    if not exists:
        product_view = ProductView()
        product_view.product_id = product.id
        product_view.viewer_id = viewer_id
        product_view.viewer_hash = viewer_hash
        db.session.add(product_view)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

    return signed_cookie if not current_user.is_authenticated else None


@bp.get("/admin/analytics")
def admin_analytics():
    require_admin()
    rows = db.session.query(
        Product,
        func.count(ProductView.id).label("unique_views"),
    ).outerjoin(ProductView, ProductView.product_id == Product.id).group_by(
        Product.id,
    ).order_by(
        func.count(ProductView.id).desc(),
        Product.created_at.desc(),
    ).all()
    return render_template("admin/analytics.html", product_views=rows)


@bp.route("/product/<int:product_id>")
def product_by_id(product_id):
    """Alternate link form: /product/<id> redirects to the canonical /p/<slug>."""
    product = Product.query.filter(
        Product.id == product_id,
        public_listing_filter(),
    ).first_or_404()
    return redirect(url_for("main.product_detail", slug=product.slug), code=301)
