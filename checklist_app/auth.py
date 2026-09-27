import hashlib
from functools import wraps
import threading
import time
from urllib.parse import quote

from firebase_admin import auth as firebase_auth
from flask import g, jsonify, redirect, request, url_for

from .config import settings
from .firebase_client import initialize_firebase


_SESSION_CACHE_TTL_SECONDS = 30
_SESSION_CACHE_MAX_ENTRIES = 256
_session_cache = {}
_session_cache_lock = threading.Lock()


def _cached_session_claims(session_cookie):
    cache_key = hashlib.sha256(session_cookie.encode("utf-8")).hexdigest()
    now = time.monotonic()
    with _session_cache_lock:
        cached = _session_cache.get(cache_key)
        if cached and now - cached["created"] <= _SESSION_CACHE_TTL_SECONDS:
            return dict(cached["claims"])
    return None


def _remember_session_claims(session_cookie, claims):
    cache_key = hashlib.sha256(session_cookie.encode("utf-8")).hexdigest()
    now = time.monotonic()
    with _session_cache_lock:
        if len(_session_cache) >= _SESSION_CACHE_MAX_ENTRIES:
            expired = [
                key
                for key, value in _session_cache.items()
                if now - value["created"] > _SESSION_CACHE_TTL_SECONDS
            ]
            for key in expired:
                _session_cache.pop(key, None)
            if len(_session_cache) >= _SESSION_CACHE_MAX_ENTRIES:
                oldest_key = min(
                    _session_cache,
                    key=lambda key: _session_cache[key]["created"],
                )
                _session_cache.pop(oldest_key, None)
        _session_cache[cache_key] = {
            "created": now,
            "claims": dict(claims),
        }


def current_user():
    session_cookie = request.cookies.get("firebase_session")
    if not session_cookie:
        return None

    cached_claims = _cached_session_claims(session_cookie)
    if cached_claims is not None:
        return cached_claims

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
    _remember_session_claims(session_cookie, claims)
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
