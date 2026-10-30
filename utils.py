import io
import warnings
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from flask import current_app, request
from PIL import Image, ImageOps, UnidentifiedImageError


class ImageUploadError(ValueError):
    """Raised when an uploaded file is not a supported, decodable image."""


class ImageStorageError(RuntimeError):
    """Raised when image storage is missing configuration or unavailable."""


def is_safe_next(target):
    """Allow only same-site relative redirects (prevents open redirects)."""
    if not target:
        return False
    ref, test = urlparse(request.host_url), urlparse(urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc


def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]


def _webp_bytes(file_storage):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(file_storage.stream) as source:
                image = ImageOps.exif_transpose(source)
                image.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
                has_alpha = "A" in image.getbands() or "transparency" in image.info
                image = image.convert("RGBA" if has_alpha else "RGB")
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=80, method=6)
            return output.getvalue()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, UnidentifiedImageError) as error:
        raise ImageUploadError("The uploaded file is not a valid, supported image.") from error


def _r2_settings():
    keys = {
        "CLOUDFLARE_R2_ACCOUNT_ID": current_app.config.get("CLOUDFLARE_R2_ACCOUNT_ID"),
        "CLOUDFLARE_R2_ACCESS_KEY_ID": current_app.config.get("CLOUDFLARE_R2_ACCESS_KEY_ID"),
        "CLOUDFLARE_R2_SECRET_ACCESS_KEY": current_app.config.get("CLOUDFLARE_R2_SECRET_ACCESS_KEY"),
        "CLOUDFLARE_R2_BUCKET": current_app.config.get("CLOUDFLARE_R2_BUCKET"),
        "CLOUDFLARE_R2_PUBLIC_URL": current_app.config.get("CLOUDFLARE_R2_PUBLIC_URL"),
    }
    missing = [key for key, value in keys.items() if not value]
    if missing:
        raise ImageStorageError(
            "Cloudflare R2 is selected but these settings are missing: " + ", ".join(missing)
        )
    return keys


def _r2_client(settings):
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings['CLOUDFLARE_R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        region_name="auto",
        aws_access_key_id=settings["CLOUDFLARE_R2_ACCESS_KEY_ID"],
        aws_secret_access_key=settings["CLOUDFLARE_R2_SECRET_ACCESS_KEY"],
    )


def save_image(file_storage):
    """Convert an upload to WebP and store it locally or in the configured R2 bucket."""
    data = _webp_bytes(file_storage)
    key = f"uploads/{uuid.uuid4().hex}.webp"
    backend = current_app.config.get("IMAGE_STORAGE_BACKEND", "local")

    if backend == "r2":
        settings = _r2_settings()
        try:
            _r2_client(settings).put_object(
                Bucket=settings["CLOUDFLARE_R2_BUCKET"],
                Key=key,
                Body=data,
                ContentType="image/webp",
                CacheControl="public, max-age=31536000, immutable",
            )
        except (BotoCoreError, ClientError) as error:
            current_app.logger.exception("Cloudflare R2 image upload failed")
            raise ImageStorageError("Could not save the image to Cloudflare R2. Please try again.") from error
        return f"r2:{key}"

    if backend != "local":
        raise ImageStorageError(f"Unsupported image storage backend: {backend}")

    folder = Path(current_app.config["UPLOAD_FOLDER"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / key.split("/", 1)[1]).write_bytes(data)
    return key


def delete_image(image_path):
    """Delete an uploaded image from its configured backend; leave bundled files alone."""
    if not image_path:
        return
    if image_path.startswith("r2:"):
        settings = _r2_settings()
        try:
            _r2_client(settings).delete_object(
                Bucket=settings["CLOUDFLARE_R2_BUCKET"],
                Key=image_path[3:],
            )
        except (BotoCoreError, ClientError) as error:
            current_app.logger.exception("Cloudflare R2 image deletion failed")
            raise ImageStorageError("Could not delete the old image from Cloudflare R2.") from error
    elif image_path.startswith("uploads/"):
        target = Path(current_app.config["UPLOAD_FOLDER"]) / image_path.split("/", 1)[1]
        target.unlink(missing_ok=True)
