import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

from flask import current_app, request
from werkzeug.utils import secure_filename


def is_safe_next(target):
    """Allow only same-site relative redirects (prevents open redirects)."""
    if not target:
        return False
    ref, test = urlparse(request.host_url), urlparse(urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc


def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]


def save_image(file_storage):
    """Save an upload under static/uploads with a random name. Returns the path relative to /static."""
    ext = secure_filename(file_storage.filename).rsplit(".", 1)[1].lower()
    name = f"{uuid.uuid4().hex}.{ext}"
    folder = Path(current_app.config["UPLOAD_FOLDER"])
    folder.mkdir(parents=True, exist_ok=True)
    file_storage.save(folder / name)
    return f"uploads/{name}"


def delete_image(rel_path):
    """Delete only files we uploaded (never the bundled seed images)."""
    if rel_path and rel_path.startswith("uploads/"):
        target = Path(current_app.config["UPLOAD_FOLDER"]) / rel_path.split("/", 1)[1]
        target.unlink(missing_ok=True)
