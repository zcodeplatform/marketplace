import re
from datetime import datetime, timezone

from flask import url_for
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db, login_manager

CATEGORIES = ["Home", "Table", "Light", "Wear", "Scent", "Electronics", "Books", "Other"]
STATUS_ACTIVE = "active"
STATUS_SOLD = "sold"


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
    avatar_path = db.Column(db.String(255), nullable=True)     # user upload, relative to /static
    bio = db.Column(db.String(500), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    show_phone = db.Column(db.Boolean, nullable=False, default=False)  # show on product pages
    created_at = db.Column(db.DateTime, default=_now, nullable=False)

    products = db.relationship(
        "Product", backref="seller", lazy="dynamic",
        cascade="all, delete-orphan", order_by="Product.created_at.desc()",
    )

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return bool(self.password_hash) and check_password_hash(self.password_hash, raw)

    @property
    def avatar_url(self):
        """Uploaded avatar wins, then the Google picture, otherwise None."""
        if self.avatar_path:
            return url_for("static", filename=self.avatar_path)
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
    image_path = db.Column(db.String(255), nullable=True)  # relative to /static
    category = db.Column(db.String(50), nullable=False, default="Other", index=True)
    status = db.Column(db.String(10), nullable=False, default=STATUS_ACTIVE, index=True)
    created_at = db.Column(db.DateTime, default=_now, nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    @property
    def is_sold(self):
        return self.status == STATUS_SOLD

    @property
    def image_url(self):
        return url_for("static", filename=self.image_path or "img/placeholder.svg")

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
    status = db.Column(db.String(10), nullable=False, default="pending", index=True)
    created_at = db.Column(db.DateTime, default=_now, nullable=False)