from urllib.parse import urlsplit

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import HomepageAd
from utils import (
    ImageStorageError,
    ImageUploadError,
    allowed_image,
    delete_image,
    parse_admin_emails,
    require_admin,
    save_image,
)

bp = Blueprint("ads", __name__, url_prefix="/admin/ads")


def _valid_destination(value):
    if not value:
        return None
    if len(value) > 500:
        return False
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            return False
        parsed.port
    except ValueError:
        return False
    return value


@bp.route("/", methods=["GET", "POST"])
@login_required
def manage():
    require_admin()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        destination = request.form.get("destination_url", "").strip()
        image = request.files.get("image")
        safe_destination = _valid_destination(destination)
        if not title or len(title) > 160:
            flash("Ad text is required and must be 160 characters or fewer.", "error")
            return redirect(url_for("ads.manage"))
        if safe_destination is False:
            flash("Ad link must be a complete http or https URL.", "error")
            return redirect(url_for("ads.manage"))
        if not image or not image.filename or not allowed_image(image.filename):
            flash("Choose a PNG, JPG, WEBP or GIF banner image.", "error")
            return redirect(url_for("ads.manage"))

        try:
            image_path = save_image(image)
        except ImageUploadError as error:
            flash(str(error), "error")
            return redirect(url_for("ads.manage"))
        except ImageStorageError as error:
            flash(str(error), "error")
            return redirect(url_for("ads.manage"))

        ad = HomepageAd(
            title=title,
            image_path=image_path,
            destination_url=safe_destination,
            created_by_id=current_user.id,
        )
        db.session.add(ad)
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("Could not save homepage ad")
            try:
                delete_image(image_path)
            except ImageStorageError:
                current_app.logger.exception("Could not clean up uploaded homepage ad image")
            flash("Could not save the ad. Please try again.", "error")
            return redirect(url_for("ads.manage"))
        flash("Homepage ad added.", "success")
        return redirect(url_for("ads.manage"))

    ads = HomepageAd.query.order_by(HomepageAd.created_at.desc(), HomepageAd.id.desc()).all()
    return render_template("admin/ads.html", ads=ads)


@bp.post("/<int:ad_id>/toggle")
@login_required
def toggle(ad_id):
    require_admin()
    ad = db.get_or_404(HomepageAd, ad_id)
    ad.is_active = not ad.is_active
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not update homepage ad status: %s", ad_id)
        flash("Could not update the ad. Please try again.", "error")
        return redirect(url_for("ads.manage"))
    flash("Homepage ad " + ("published." if ad.is_active else "hidden."), "success")
    return redirect(url_for("ads.manage"))


@bp.route("/<int:ad_id>/edit", methods=["GET", "POST"])
@login_required
def edit(ad_id):
    require_admin()
    ad = db.get_or_404(HomepageAd, ad_id)

    if request.method == "GET":
        return render_template("admin/edit_ad.html", ad=ad)

    title = request.form.get("title", "").strip()
    destination = request.form.get("destination_url", "").strip()
    image = request.files.get("image")
    safe_destination = _valid_destination(destination)
    if not title or len(title) > 160:
        flash("Ad text is required and must be 160 characters or fewer.", "error")
        return redirect(url_for("ads.edit", ad_id=ad.id))
    if safe_destination is False:
        flash("Ad link must be a complete http or https URL.", "error")
        return redirect(url_for("ads.edit", ad_id=ad.id))
    if image and image.filename and not allowed_image(image.filename):
        flash("Choose a PNG, JPG, WEBP or GIF banner image.", "error")
        return redirect(url_for("ads.edit", ad_id=ad.id))

    new_image_path = None
    if image and image.filename:
        try:
            new_image_path = save_image(image)
        except (ImageUploadError, ImageStorageError) as error:
            flash(str(error), "error")
            return redirect(url_for("ads.edit", ad_id=ad.id))

    old_image_path = ad.image_path
    ad.title = title
    ad.destination_url = safe_destination
    if new_image_path:
        ad.image_path = new_image_path
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not update homepage ad: %s", ad_id)
        if new_image_path:
            try:
                delete_image(new_image_path)
            except ImageStorageError:
                current_app.logger.exception("Could not clean up replacement homepage ad image")
        flash("Could not update the ad. Please try again.", "error")
        return redirect(url_for("ads.edit", ad_id=ad_id))

    if new_image_path:
        try:
            delete_image(old_image_path)
        except ImageStorageError:
            current_app.logger.exception("Ad updated but old image cleanup failed: %s", ad_id)
            flash("Ad updated, but its previous image could not be removed from storage.", "error")
            return redirect(url_for("ads.manage"))
    flash("Homepage ad updated.", "success")
    return redirect(url_for("ads.manage"))


@bp.post("/<int:ad_id>/delete")
@login_required
def delete(ad_id):
    require_admin()
    ad = db.get_or_404(HomepageAd, ad_id)
    image_path = ad.image_path
    db.session.delete(ad)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Could not delete homepage ad: %s", ad_id)
        flash("Could not delete the ad. Please try again.", "error")
        return redirect(url_for("ads.manage"))
    try:
        delete_image(image_path)
    except ImageStorageError as error:
        current_app.logger.exception("Homepage ad deleted but image cleanup failed: %s", ad_id)
        flash("Ad deleted, but its image could not be removed from storage.", "error")
    else:
        flash("Homepage ad deleted.", "success")
    return redirect(url_for("ads.manage"))
