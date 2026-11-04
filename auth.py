from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from extensions import db, oauth
from models import User
from utils import is_safe_next

bp = Blueprint("auth", __name__)


def _after_login():
    target = request.args.get("next") or request.form.get("next")
    return redirect(target if is_safe_next(target) else url_for("main.index"))


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        terms_accepted = request.form.get("agree_terms") == "on"
        age_confirmed = request.form.get("confirm_age") == "on"
        error = None
        if not terms_accepted or not age_confirmed:
            error = "You must agree to the terms and confirm that you are at least 13 years old."
        elif not name or not email or "@" not in email:
            error = "Please enter your name and a valid email."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif User.query.filter_by(email=email).first():
            error = "An account with that email already exists. Try logging in."
        if error:
            flash(error, "error")
            return render_template(
                "auth/signup.html",
                name=name,
                email=email,
                terms_accepted=terms_accepted,
                age_confirmed=age_confirmed,
            ), 400
        user = User(name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("Welcome! Your account is ready.", "success")
        return _after_login()
    return render_template("auth/signup.html")


@bp.route("/signup/google", methods=["POST"])
def google_signup():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    if request.form.get("agree_terms") != "on" or request.form.get("confirm_age") != "on":
        flash("You must agree to the terms and confirm that you are at least 13 years old.", "error")
        return redirect(url_for("auth.signup", next=request.form.get("next") or None))
    if not current_app.config["GOOGLE_CLIENT_ID"]:
        flash("Google sign-in isn't configured yet.", "error")
        return redirect(url_for("auth.signup", next=request.form.get("next") or None))

    session["google_signup_consent"] = True
    session["google_signup_next"] = request.form.get("next", "")
    return redirect(url_for("auth.google_login"))


@bp.route("/terms")
def terms():
    return render_template("auth/terms.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user, remember=bool(request.form.get("remember")))
            return _after_login()
        if user and not user.password_hash:
            flash("This account uses Google sign-in. Please use the Google button.", "error")
        else:
            flash("Incorrect email or password.", "error")
        return render_template("auth/login.html", email=email), 401
    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You've been logged out.", "info")
    return redirect(url_for("main.index"))


# ---- Google OAuth -----------------------------------------------------------

@bp.route("/login/google")
def google_login():
    if not current_app.config["GOOGLE_CLIENT_ID"]:
        flash("Google sign-in isn't configured yet.", "error")
        return redirect(url_for("auth.login"))
    redirect_uri = url_for("auth.google_callback", _external=True)
    try:
        return oauth.google.authorize_redirect(redirect_uri)
    except Exception:  # Google unreachable / misconfigured
        session.pop("google_signup_consent", None)
        session.pop("google_signup_next", None)
        current_app.logger.exception("Google OAuth redirect failed")
        flash("Couldn't reach Google right now. Please try again or use email and password.", "error")
        return redirect(url_for("auth.login"))


@bp.route("/auth/google/callback")
def google_callback():
    signup_consent = session.pop("google_signup_consent", False)
    signup_next = session.pop("google_signup_next", None)
    try:
        token = oauth.google.authorize_access_token()
    except Exception:  # denied consent, expired state, etc.
        flash("Google sign-in was cancelled or failed. Please try again.", "error")
        return redirect(url_for("auth.login"))

    info = token.get("userinfo") or {}
    google_id, email = info.get("sub"), (info.get("email") or "").lower()
    if not google_id or not email or not info.get("email_verified"):
        flash("Your Google account must have a verified email.", "error")
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(google_id=google_id).first()
    if not user:
        # Link to an existing email/password account, or create a new one.
        user = User.query.filter_by(email=email).first()
        if user:
            user.google_id = google_id
        else:
            if not signup_consent:
                flash("Please agree to the terms and confirm your age before creating an account.", "error")
                return redirect(url_for("auth.signup", next=signup_next or None))
            user = User(name=info.get("name") or email.split("@")[0], email=email, google_id=google_id)
            db.session.add(user)
    user.picture_url = info.get("picture") or user.picture_url
    db.session.commit()

    login_user(user, remember=True)
    if is_safe_next(signup_next):
        return redirect(signup_next)
    return _after_login()
