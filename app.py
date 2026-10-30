import click
from dotenv import load_dotenv
from flask import Flask, render_template
from flask_login import current_user

from extensions import csrf, db, login_manager, oauth

load_dotenv()


def create_app(config_object=None):
    if config_object is None:
        from config import Config

        config_object = Config
    app = Flask(__name__)
    app.config.from_object(config_object)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    oauth.init_app(app)

    # Google OAuth (OpenID Connect). Authlib reads GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET from config.
    oauth.register(
        name="google",
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

    from auth import bp as auth_bp
    from ads import bp as ads_bp
    from main import bp as main_bp
    from account import bp as profile_bp
    from payments import bp as payments_bp
    from seller import bp as seller_bp

    for bp in (main_bp, auth_bp, ads_bp, seller_bp, profile_bp, payments_bp):
        app.register_blueprint(bp)

    @app.context_processor
    def inject_globals():
        admin_emails = app.config.get("ADMIN_EMAILS", "")
        if isinstance(admin_emails, str):
            admin_emails = {email.strip().lower() for email in admin_emails.split(",") if email.strip()}
        else:
            admin_emails = {str(email).strip().lower() for email in admin_emails}
        return {
            "google_enabled": bool(app.config["GOOGLE_CLIENT_ID"] and app.config["GOOGLE_CLIENT_SECRET"]),
            "currency": app.config["CURRENCY_SYMBOL"],
            "is_admin": bool(current_user.is_authenticated and current_user.email.lower() in admin_emails),
        }

    @app.template_filter("money")
    def money(value):
        text = f"{value:,.2f}"
        return app.config["CURRENCY_SYMBOL"] + (text[:-3] if text.endswith(".00") else text)

    @app.errorhandler(403)
    def forbidden(_):
        return render_template("error.html", code=403, message="You don't have permission to do that."), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404, message="We couldn't find that page."), 404

    @app.errorhandler(413)
    def too_large(_):
        return render_template("error.html", code=413, message="That file is too large (5 MB max)."), 413

    register_cli(app)

    with app.app_context():
        db.create_all()
        _migrate_payment_buyer_id()
        _migrate_product_categories()
    return app


def _migrate_product_categories():
    """Move products using the original narrow categories into the new taxonomy."""
    from models import Product

    legacy_categories = {
        "Home": "Home & Furniture",
        "Table": "Home & Furniture",
        "Light": "Home & Furniture",
        "Wear": "Clothing & Shoes",
        "Scent": "Beauty & Personal Care",
        "Books": "Books & Stationery",
    }
    changed = False
    for old_category, new_category in legacy_categories.items():
        updated = Product.query.filter_by(category=old_category).update(
            {"category": new_category},
            synchronize_session=False,
        )
        changed = changed or updated > 0
    if changed:
        db.session.commit()


def _migrate_payment_buyer_id():
    """Add buyer ownership to existing payment tables without losing payment history."""
    from sqlalchemy import inspect
    from models import Payment

    inspector = inspect(db.engine)
    if "payments" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("payments")}
    if "buyer_id" not in columns:
        with db.engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE payments ADD COLUMN buyer_id INTEGER REFERENCES users(id)"
            )
    buyer_index = next(
        index for index in Payment.__table__.indexes
        if any(column.name == "buyer_id" for column in index.columns)
    )
    buyer_index.create(db.engine, checkfirst=True)


def register_cli(app):
    @app.cli.command("seed-demo")
    def seed_demo():
        """Load the original six storefront products under a demo seller."""
        from models import Product, User

        seller = User.query.filter_by(email="demo@marketplace.local").first()
        if not seller:
            seller = User(name="Comrade Market", email="demo@marketplace.local")  # no password: cannot log in
            db.session.add(seller)
            db.session.flush()
        items = [
            ("Pour-over carafe", 68, "Home & Furniture", "carafe", "Cream stoneware, one pour."),
            ("Charcoal throw", 140, "Home & Furniture", "throw", "Heavy wool, finished edges."),
            ("Brass desk lamp", 210, "Home & Furniture", "lamp", "Linen shade, warm metal."),
            ("Dinner plates", 96, "Home & Furniture", "plates", "Matte black, set of four."),
            ("Tan loafers", 248, "Clothing & Shoes", "loafers", "Unlined leather, everyday."),
            ("Amber bottle", 54, "Beauty & Personal Care", "amber", "Cedar, resin, quiet citrus."),
        ]
        added = 0
        for title, price, cat, img, note in items:
            if Product.query.filter_by(title=title, seller_id=seller.id).first():
                continue
            db.session.add(Product(
                title=title, slug=Product.make_slug(title), description=note, price=price,
                category=cat, image_path=f"products/{img}.jpg", seller_id=seller.id,
            ))
            db.session.flush()
            added += 1
        db.session.commit()
        click.echo(f"Seeded {added} product(s).")


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
