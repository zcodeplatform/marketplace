import re

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from utils import allowed_image, delete_image, save_image

bp = Blueprint("profile", __name__)

PHONE_RE = re.compile(r"\+?[0-9][0-9\s\-]{6,18}")


@bp.route("/profile")
@login_required
def view():
    return render_template("profile/view.html", products=current_user.products.all())


@bp.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        bio = request.form.get("bio", "").strip()
        phone = request.form.get("phone", "").strip()
        avatar = request.files.get("avatar")
        error = None
        if not name or len(name) > 120:
            error = "Name is required (120 characters max)."
        elif len(bio) > 500:
            error = "Bio must be 500 characters or fewer."
        elif phone and not PHONE_RE.fullmatch(phone):
            error = "Enter a valid phone number, e.g. +254 712 345 678."
        elif avatar and avatar.filename and not allowed_image(avatar.filename):
            error = "Profile picture must be a PNG, JPG, WEBP or GIF file."
        if error:
            flash(error, "error")
            return render_template("profile/edit.html"), 400

        current_user.name, current_user.bio = name, bio or None
        current_user.phone = phone or None
        current_user.show_phone = bool(phone) and bool(request.form.get("show_phone"))
        if request.form.get("remove_avatar"):
            delete_image(current_user.avatar_path)
            current_user.avatar_path = None
        if avatar and avatar.filename:
            delete_image(current_user.avatar_path)
            current_user.avatar_path = save_image(avatar)
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("profile.view"))
    return render_template("profile/edit.html")