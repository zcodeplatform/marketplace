import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    # Relative sqlite paths resolve to the instance/ folder (Flask-SQLAlchemy 3).
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or "sqlite:///marketplace.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
    IMAGE_STORAGE_BACKEND = os.environ.get("IMAGE_STORAGE_BACKEND", "r2").lower()
    CLOUDFLARE_R2_ACCOUNT_ID = os.environ.get("CLOUDFLARE_R2_ACCOUNT_ID", "")
    CLOUDFLARE_R2_ACCESS_KEY_ID = os.environ.get("CLOUDFLARE_R2_ACCESS_KEY_ID", "")
    CLOUDFLARE_R2_SECRET_ACCESS_KEY = os.environ.get("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "")
    CLOUDFLARE_R2_BUCKET = os.environ.get("CLOUDFLARE_R2_BUCKET", "")
    CLOUDFLARE_R2_PUBLIC_URL = os.environ.get("CLOUDFLARE_R2_PUBLIC_URL", "").rstrip("/")

    CURRENCY_SYMBOL = "KES "

    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    MPESA_BASE_URL = os.environ.get("MPESA_BASE_URL", "https://sandbox.safaricom.co.ke").rstrip("/")
    MPESA_CONSUMER_KEY = os.environ.get("MPESA_CONSUMER_KEY", "")
    MPESA_CONSUMER_SECRET = os.environ.get("MPESA_CONSUMER_SECRET", "")
    MPESA_PASSKEY = os.environ.get("MPESA_PASSKEY", "")
    MPESA_SHORTCODE = os.environ.get("MPESA_SHORTCODE", "")
    MPESA_TRANSACTION_TYPE = os.environ.get("MPESA_TRANSACTION_TYPE", "CustomerPayBillOnline")
    MPESA_CALLBACK_URL = os.environ.get("MPESA_CALLBACK_URL", "")
