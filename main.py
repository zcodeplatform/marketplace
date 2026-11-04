import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

from extensions import db
from models import CATEGORIES, HomepageAd, Product, ProductView, STATUS_ACTIVE, public_listing_filter
from utils import require_admin

bp = Blueprint("main", __name__)
PRODUCTS_PER_PAGE = 12
PRODUCT_SORTS = {
    "newest": "Newest",
    "popular": "Most viewed",
    "price_asc": "Price: low to high",
    "price_desc": "Price: high to low",
}


def _price_bound(name):
    value = request.args.get(name, "").strip()
    if not value:
        return None
    try:
        price = Decimal(value)
    except InvalidOperation:
        abort(400, description=f"Enter a valid {name.replace('_', ' ')}.")
    if not price.is_finite() or price < 0 or price > Decimal("99999999.99"):
        abort(400, description=f"Enter a valid {name.replace('_', ' ')}.")
    return price


def _product_listing(query, empty_message):
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "")
    show_sold = request.args.get("sold") == "1"
    min_price = _price_bound("min_price")
    max_price = _price_bound("max_price")
    if min_price is not None and max_price is not None and min_price > max_price:
        empty_message = "Minimum price cannot be greater than maximum price."

    if not show_sold:
        query = query.filter(Product.status == STATUS_ACTIVE)
    if category in CATEGORIES:
        query = query.filter(Product.category == category)
    if q:
        like = f"%{q}%"
        query = query.filter(Product.title.ilike(like) | Product.description.ilike(like))

    current_price = func.round(Product.price * (100 - Product.discount_percent) / 100, 2)
    if min_price is not None:
        query = query.filter(current_price >= min_price)
    if max_price is not None:
        query = query.filter(current_price <= max_price)
    on_sale = request.args.get("sale") == "1"
    if on_sale:
        query = query.filter(Product.discount_percent > 0)

    sort = request.args.get("sort", "newest")
    if sort not in PRODUCT_SORTS:
        sort = "newest"
    if sort == "price_asc":
        query = query.order_by(current_price.asc(), Product.id.asc())
    elif sort == "price_desc":
        query = query.order_by(current_price.desc(), Product.id.desc())
    elif sort == "popular":
        view_count = db.session.query(func.count(ProductView.id)).filter(
            ProductView.product_id == Product.id,
        ).correlate(Product).scalar_subquery()
        query = query.order_by(view_count.desc(), Product.created_at.desc(), Product.id.desc())
    else:
        query = query.order_by(Product.created_at.desc(), Product.id.desc())

    total = query.count()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    pages = max(1, (total + PRODUCTS_PER_PAGE - 1) // PRODUCTS_PER_PAGE)
    page = min(page, pages)
    products = query.offset((page - 1) * PRODUCTS_PER_PAGE).limit(PRODUCTS_PER_PAGE).all()

    query_args = request.args.to_dict()
    query_args.pop("_partial", None)
    query_args.pop("_suggest", None)
    page_links = []
    for page_number in range(1, pages + 1):
        query_args["page"] = page_number
        page_links.append({
            "number": page_number,
            "url": url_for(request.endpoint, **query_args),
            "current": page_number == page,
        })

    return {
        "products": products,
        "total": total,
        "page": page,
        "pages": pages,
        "page_links": page_links,
        "q": q,
        "category": category,
        "show_sold": show_sold,
        "min_price": request.args.get("min_price", ""),
        "max_price": request.args.get("max_price", ""),
        "sale_only": on_sale,
        "sort": sort,
        "sort_options": PRODUCT_SORTS,
        "empty_message": empty_message,
    }


@bp.get("/sitemap.xml")
def sitemap():
    today = datetime.now(timezone.utc).date().isoformat()
    products = Product.query.filter(
        Product.status == STATUS_ACTIVE,
        public_listing_filter(),
    ).order_by(Product.created_at.desc(), Product.id.desc()).all()
    pages = [
        (url_for("main.index", _external=True), today, "daily", "1.0"),
        (url_for("main.browse", _external=True), today, "daily", "0.9"),
        *(
            (
                url_for("main.product_detail", slug=product.slug, _external=True),
                product.created_at.date().isoformat(),
                "weekly",
                "0.8",
            )
            for product in products
        ),
    ]

    sitemap_namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    root = ElementTree.Element("urlset", {"xmlns": sitemap_namespace})
    for location, last_modified, change_frequency, priority in pages:
        url_element = ElementTree.SubElement(root, "url")
        ElementTree.SubElement(url_element, "loc").text = location
        ElementTree.SubElement(url_element, "lastmod").text = last_modified
        ElementTree.SubElement(url_element, "changefreq").text = change_frequency
        ElementTree.SubElement(url_element, "priority").text = priority

    xml = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(xml, content_type="text/xml; charset=utf-8")


@bp.get("/google1fc7af632ee3cc17.html")
def google_site_verification():
    return Response(
        "google-site-verification: google1fc7af632ee3cc17.html",
        mimetype="text/html",
    )


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
    query = Product.query.filter(public_listing_filter())
    q = request.args.get("q", "").strip()
    if request.args.get("_suggest") == "1":
        products = query.filter_by(status=STATUS_ACTIVE).filter(
            Product.title.ilike(f"%{q}%") | Product.description.ilike(f"%{q}%"),
        ).order_by(Product.created_at.desc()).limit(6).all()
        return render_template("_search_suggestions.html", products=products, q=q)
    listing = _product_listing(query, "No products match your filters.")
    if request.args.get("_partial") == "1":
        return render_template("_browse_results.html", **listing)
    return render_template("browse.html", categories=CATEGORIES, listing_title="Browse",
                           listing_kicker="The collection", **listing)


@bp.get("/wishlist")
def wishlist():
    ids = session.get("wishlist", [])
    if not isinstance(ids, list):
        ids = []
    ids = [
        product_id for product_id in ids
        if isinstance(product_id, int) and not isinstance(product_id, bool) and product_id > 0
    ]
    query = Product.query.filter(public_listing_filter(), Product.id.in_(ids))
    listing = _product_listing(query, "No saved products yet. Tap the heart on a product to save it.")
    if request.args.get("_partial") == "1":
        return render_template("_browse_results.html", **listing)
    return render_template("browse.html", categories=CATEGORIES, listing_title="Your favourites",
                           listing_kicker="Saved for later", **listing)


@bp.post("/wishlist/toggle")
def wishlist_toggle():
    data = request.get_json(silent=True) or request.form
    raw_product_id = data.get("product_id", "")
    if (
        isinstance(raw_product_id, bool)
        or not isinstance(raw_product_id, (int, str))
        or not str(raw_product_id).isdecimal()
    ):
        return jsonify(error="Choose a valid product to save."), 400
    product_id = int(raw_product_id)
    if product_id < 1:
        return jsonify(error="Choose a valid product to save."), 400
    product = Product.query.filter(
        Product.id == product_id,
        public_listing_filter(),
    ).first()
    if product is None:
        return jsonify(error="That product is no longer available."), 404

    ids = session.get("wishlist", [])
    if not isinstance(ids, list):
        ids = []
    saved_ids = {
        item for item in ids
        if isinstance(item, int) and not isinstance(item, bool) and item > 0
    }
    saved = product_id not in saved_ids
    if saved:
        saved_ids.add(product_id)
    else:
        saved_ids.remove(product_id)
    session["wishlist"] = sorted(saved_ids)
    return jsonify(saved=saved, count=len(saved_ids))


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
