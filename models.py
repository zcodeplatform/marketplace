import re
from datetime import datetime, timezone
from urllib.parse import quote

from flask import current_app, url_for
from flask_login import UserMixin
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db, login_manager

CATEGORIES = [
    "Electronics",
    "Home & Furniture",
    "Clothing & Shoes",
    "Food & Groceries",
    "Beauty & Personal Care",
    "Books & Stationery",
    "Sports & Outdoors",
    "Toys & Games",
    "Other",
]
STATUS_ACTIVE = "active"
STATUS_SOLD = "sold"
MAX_SELLER_PRODUCTS = 5
LISTING_PLAN_PRICE = 100
LISTING_PLAN_DAYS = 30


def _image_url(path, fallback):
    if path and path.startswith("r2:"):
        public_url = current_app.config.get("CLOUDFLARE_R2_PUBLIC_URL", "").rstrip("/")
        if not public_url:
            raise RuntimeError("CLOUDFLARE_R2_PUBLIC_URL must be configured to display R2 images.")
        return f"{public_url}/{quote(path[3:], safe='/')}"
    return url_for("static", filename=path or fallback)


def _now():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    # Nullable: accounts created through Google have no password.
    password_hash = db.Column(db.String(255), nullable=True)
    google_id = db.Column(db.String(64), unique=True, nullable=True, index=True)
    picture_url = db.Column(db.String(500), nullable=True)     # from Google
    avatar_path = db.Column(db.String(255), nullable=True)     # local path or r2:<object key>
    bio = db.Column(db.String(500), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    show_phone = db.Column(db.Boolean, nullable=False, default=False)  # show on product pages
    created_at = db.Column(db.DateTime, default=_now, nullable=False)

    products = db.relationship(
        "Product", backref="seller", lazy="dynamic",
        cascade="all, delete-orphan", order_by="Product.created_at.desc()",
    )
    product_views = db.relationship("ProductView", back_populates="viewer", lazy="dynamic")
    payment_shares = db.relationship(
        "PaymentSeller", back_populates="seller", lazy="dynamic",
    )
    checkout_payments = db.relationship(
        "Payment", back_populates="buyer", lazy="dynamic", foreign_keys="Payment.buyer_id",
    )
    listing_plan_payments = db.relationship(
        "ListingPlanPayment", back_populates="seller", lazy="dynamic",
    )
    homepage_ads = db.relationship("HomepageAd", back_populates="created_by", lazy="dynamic")

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return bool(self.password_hash) and check_password_hash(self.password_hash, raw)

    @property
    def avatar_url(self):
        """Uploaded avatar wins, then the Google picture, otherwise None."""
        if self.avatar_path:
            return _image_url(self.avatar_path, "img/placeholder.svg")
        return self.picture_url or None

    @property
    def initials(self):
        parts = self.name.split()
        return "".join(p[0] for p in parts[:2]).upper() or "?"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(160), unique=True, nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    price = db.Column(db.Numeric(10, 2), nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    image_path = db.Column(db.String(255), nullable=True)  # local path or r2:<object key>
    category = db.Column(db.String(50), nullable=False, default="Other", index=True)
    status = db.Column(db.String(10), nullable=False, default=STATUS_ACTIVE, index=True)
    created_at = db.Column(db.DateTime, default=_now, nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    view_records = db.relationship(
        "ProductView", back_populates="product", cascade="all, delete-orphan",
    )

    @property
    def is_sold(self):
        return self.status == STATUS_SOLD

    @property
    def is_available(self):
        return self.status == STATUS_ACTIVE and self.stock > 0

    @property
    def image_url(self):
        return _image_url(self.image_path, "img/placeholder.svg")

    @property
    def image_external_url(self):
        if self.image_path and self.image_path.startswith("r2:"):
            return self.image_url
        return url_for("static", filename=self.image_path or "img/placeholder.svg", _external=True)

    @property
    def public_url(self):
        return url_for("main.product_detail", slug=self.slug, _external=True)

    @staticmethod
    def make_slug(title):
        """Unique, URL-safe slug. Created once so shared links never change."""
        base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80] or "item"
        slug, n = base, 2
        while Product.query.filter_by(slug=slug).first():
            slug = f"{base}-{n}"
            n += 1
        return slug


class ProductView(db.Model):
    __tablename__ = "product_views"
    __table_args__ = (
        db.UniqueConstraint("product_id", "viewer_hash", name="uq_product_viewer"),
    )

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    viewer_hash = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=_now, nullable=False)

    product = db.relationship("Product", back_populates="view_records")
    viewer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    viewer = db.relationship("User", back_populates="product_views")


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(12), unique=True, nullable=False, index=True)
    checkout_request_id = db.Column(db.String(255), unique=True, nullable=True, index=True)
    merchant_request_id = db.Column(db.String(255), nullable=True)
    phone_number = db.Column(db.String(12), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    items_json = db.Column(db.Text, nullable=False)
    mpesa_response = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(12), nullable=False, default="pending", index=True)
    created_at = db.Column(db.DateTime, default=_now, nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    buyer = db.relationship("User", back_populates="checkout_payments", foreign_keys=[buyer_id])
    seller_shares = db.relationship(
        "PaymentSeller", back_populates="payment", cascade="all, delete-orphan",
    )


class PaymentSeller(db.Model):
    __tablename__ = "payment_sellers"
    __table_args__ = (
        db.UniqueConstraint("payment_id", "seller_id", name="uq_payment_seller"),
    )

    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"), nullable=False, index=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    items_json = db.Column(db.Text, nullable=False)

    payment = db.relationship("Payment", back_populates="seller_shares")
    seller = db.relationship("User", back_populates="payment_shares")


class ListingPlanPayment(db.Model):
    __tablename__ = "listing_plan_payments"

    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    reference = db.Column(db.String(12), unique=True, nullable=False, index=True)
    checkout_request_id = db.Column(db.String(255), unique=True, nullable=True, index=True)
    merchant_request_id = db.Column(db.String(255), nullable=True)
    phone_number = db.Column(db.String(12), nullable=False)
    amount = db.Column(db.Integer, nullable=False, default=LISTING_PLAN_PRICE)
    status = db.Column(db.String(12), nullable=False, default="pending", index=True)
    mpesa_response = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=_now, nullable=False)
    paid_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True, index=True)

    seller = db.relationship("User", back_populates="listing_plan_payments")


class HomepageAd(db.Model):
    __tablename__ = "homepage_ads"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    image_path = db.Column(db.String(255), nullable=False)
    destination_url = db.Column(db.String(500), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime, default=_now, nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    created_by = db.relationship("User", back_populates="homepage_ads")

    @property
    def image_url(self):
        return _image_url(self.image_path, "img/placeholder.svg")


def active_listing_plan(seller_id, now=None):
    now = now or _now()
    return ListingPlanPayment.query.filter(
        ListingPlanPayment.seller_id == seller_id,
        ListingPlanPayment.status == "success",
        ListingPlanPayment.expires_at > now,
    ).order_by(ListingPlanPayment.paid_at.desc(), ListingPlanPayment.id.desc()).first()


def latest_successful_listing_plan_payment(seller_id):
    return ListingPlanPayment.query.filter(
        ListingPlanPayment.seller_id == seller_id,
        ListingPlanPayment.status == "success",
        ListingPlanPayment.paid_at.isnot(None),
    ).order_by(
        ListingPlanPayment.paid_at.desc(),
        ListingPlanPayment.id.desc(),
    ).first()


def public_listing_filter(now=None):
    now = now or _now()
    older_product = aliased(Product)
    prior_listing_count = (
        select(func.count(older_product.id))
        .where(
            older_product.seller_id == Product.seller_id,
            or_(
                older_product.created_at < Product.created_at,
                and_(
                    older_product.created_at == Product.created_at,
                    older_product.id < Product.id,
                ),
            ),
        )
        .correlate(Product)
        .scalar_subquery()
    )
    active_sellers = select(ListingPlanPayment.seller_id).where(
        ListingPlanPayment.status == "success",
        ListingPlanPayment.expires_at > now,
    )
    return or_(
        prior_listing_count < MAX_SELLER_PRODUCTS,
        Product.seller_id.in_(active_sellers),
    )