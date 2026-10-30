import re
from datetime import datetime, timezone
from urllib.parse import quote

from flask import current_app, url_for
from flask_login import UserMixin
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
    payment_shares = db.relationship(
        "PaymentSeller", back_populates="seller", lazy="dynamic",
    )

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
    image_path = db.Column(db.String(255), nullable=True)  # local path or r2:<object key>
    category = db.Column(db.String(50), nullable=False, default="Other", index=True)
    status = db.Column(db.String(10), nullable=False, default=STATUS_ACTIVE, index=True)
    created_at = db.Column(db.DateTime, default=_now, nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    @property
    def is_sold(self):
        return self.status == STATUS_SOLD

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