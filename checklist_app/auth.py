from functools import wraps
from urllib.parse import quote

from firebase_admin import auth as firebase_auth
from flask import g, jsonify, redirect, request, url_for

from .config import settings
from .firebase_client import initialize_firebase


def current_user():
    session_cookie = request.cookies.get("firebase_session")
    if not session_cookie:
        return None

    try:
        initialize_firebase()
        claims = firebase_auth.verify_session_cookie(
            session_cookie,
            check_revoked=True,
            clock_skew_seconds=10,
        )
    except Exception:
        return None

    email = (claims.get("email") or "").lower()
    claims["email"] = email
    claims["uid"] = claims.get("uid") or claims.get("user_id") or claims.get("sub")
    claims["is_admin"] = bool(claims.get("admin")) or email in settings.admin_emails
    claims["all_projects"] = bool(claims.get("all_projects")) or claims["is_admin"]
    claims["projects"] = [
        str(project).strip().upper().replace(" ", "-")
        for project in claims.get("projects", [])
        if str(project).strip()
    ]
    return claims


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.get("user"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Login required."}), 401
            next_url = quote(request.full_path if request.query_string else request.path)
            return redirect(f"{url_for('login')}?next={next_url}")
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not g.user.get("is_admin"):
            return ("Admin access required.", 403)
        return view(*args, **kwargs)

    return wrapped
