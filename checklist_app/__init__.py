from datetime import datetime, timedelta
import json
from pathlib import Path
import time
from urllib import error as url_error
from urllib import request as url_request
from zoneinfo import ZoneInfo

from firebase_admin import auth as firebase_auth
from google.api_core.exceptions import ResourceExhausted
from flask import (
    Flask,
    Response,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from .auth import admin_required, current_user, login_required
from .config import settings
from .exports import export_all_xlsx, export_history_csv, export_structures_csv
from .firebase_client import get_db, initialize_firebase
from .qr import generate_qr_bytes, generate_qr_zip
from .services import (
    add_checklist_item,
    create_project,
    create_structure,
    create_structures_bulk,
    deactivate_checklist_item,
    delete_project,
    delete_structure,
    display_project_name,
    display_block,
    extract_structure_number,
    format_structure_id,
    build_project_summary,
    get_active_checklist_items,
    get_history,
    get_project_display_name,
    get_next_structure_id,
    get_structure,
    list_project_records,
    list_projects,
    list_structures,
    normalize_block,
    normalize_project,
    normalize_scope,
    normalize_structure_id,
    update_checklist_remark,
    update_checklist_item_label,
    update_checklist_status,
    update_final_remark,
    update_project_block_count,
    update_project_block_structure_count,
    update_project_display_name,
)


BASE_DIR = Path(__file__).resolve().parent.parent


def create_app():
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.secret_key = settings.session_secret
    dashboard_cache = {}
    dashboard_cache_ttl = 60

    @app.errorhandler(ResourceExhausted)
    def firebase_quota_exceeded(_error):
        if request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
            return jsonify({"error": "Firebase quota exceeded. Please try again after quota reset."}), 429
        return render_template("firebase_quota.html"), 429

    @app.before_request
    def load_user():
        g.user = current_user()

    @app.context_processor
    def inject_globals():
        return {
            "current_user": g.get("user"),
            "firebase_web_config": settings.firebase_web_config,
            "status_options": settings.status_options,
            "settings": settings,
        }

    @app.template_filter("status_label")
    def status_label(value):
        return settings.status_options.get(value, value)

    @app.template_filter("status_badge")
    def status_badge(value):
        classes = {
            "completed": "text-bg-success",
            "pending": "text-bg-warning",
            "na": "text-bg-secondary",
        }
        return classes.get(value, "text-bg-light")

    @app.template_filter("scope_name")
    def scope_name(value):
        return (value or "").replace("-", " ")

    @app.template_filter("block_label")
    def block_label(value):
        return display_block(value)

    def db():
        return get_db()

    def public_base_url():
        configured = settings.app_base_url.strip().rstrip("/")
        if configured:
            return configured
        return request.url_root.rstrip("/")

    def wants_json_response():
        return (
            request.headers.get("X-Requested-With") == "fetch"
            or request.accept_mimetypes.best == "application/json"
        )

    def clear_dashboard_cache():
        dashboard_cache.clear()

    def firebase_auth_request(action, payload):
        if not settings.firebase_api_key:
            raise ValueError("Firebase API key is missing.")

        body = json.dumps(payload).encode("utf-8")
        request_url = (
            f"https://identitytoolkit.googleapis.com/v1/accounts:{action}"
            f"?key={settings.firebase_api_key}"
        )
        request_obj = url_request.Request(
            request_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with url_request.urlopen(request_obj, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except url_error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                message = payload.get("error", {}).get("message", str(exc))
            except Exception:
                message = str(exc)
            raise ValueError(message) from exc

    def auth_error_message(error):
        messages = {
            "EMAIL_EXISTS": "This email is already registered. Please sign in or reset the password.",
            "EMAIL_NOT_FOUND": "No user found for this email.",
            "INVALID_EMAIL": "Please enter a valid email address.",
            "INVALID_LOGIN_CREDENTIALS": "Email or password is incorrect.",
            "INVALID_PASSWORD": "Email or password is incorrect.",
            "MISSING_PASSWORD": "Please enter a password.",
            "OPERATION_NOT_ALLOWED": "Email/password login is not enabled in Firebase Authentication.",
            "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many attempts. Please try again later.",
            "USER_DISABLED": "This user access is disabled. Contact admin.",
            "WEAK_PASSWORD : Password should be at least 6 characters": "Password must be at least 6 characters.",
        }
        return messages.get(str(error), "Request failed. Please try again.")

    def create_session_response(id_token):
        expires_in = timedelta(days=5)
        initialize_firebase()
        firebase_auth.verify_id_token(id_token, clock_skew_seconds=10)
        try:
            session_cookie = firebase_auth.create_session_cookie(
                id_token, expires_in=expires_in
            )
        except Exception as exc:
            if "Token used too early" not in str(exc):
                raise
            time.sleep(3)
            session_cookie = firebase_auth.create_session_cookie(
                id_token, expires_in=expires_in
            )

        response = jsonify({"ok": True})
        response.set_cookie(
            "firebase_session",
            session_cookie,
            max_age=int(expires_in.total_seconds()),
            httponly=True,
            secure=settings.cookie_secure,
            samesite="Lax",
        )
        return response

    def format_auth_timestamp(value):
        if not value:
            return "-"
        try:
            timestamp = int(value) / 1000
            moment = datetime.fromtimestamp(timestamp, ZoneInfo(settings.app_timezone))
            return moment.strftime("%d-%m-%Y %I:%M %p")
        except Exception:
            return "-"

    def user_is_admin(user_record):
        claims = user_record.custom_claims or {}
        email = (user_record.email or "").lower()
        return bool(claims.get("admin")) or email in settings.admin_emails

    def normalize_project_list(projects):
        normalized = []
        for project in projects or []:
            project_id = normalize_project(str(project))
            if project_id and project_id not in normalized:
                normalized.append(project_id)
        return normalized

    def user_claim_payload(is_admin, all_projects=False, projects=None):
        project_ids = normalize_project_list(projects)
        all_access = bool(all_projects) or is_admin
        return {
            "admin": bool(is_admin),
            "role": "admin" if is_admin else "worker",
            "all_projects": all_access,
            "projects": [] if all_access else project_ids,
        }

    def project_access_from_form():
        return (
            request.form.get("all_projects") == "1",
            normalize_project_list(request.form.getlist("projects")),
        )

    def user_project_access(user_record):
        claims = user_record.custom_claims or {}
        is_admin = user_is_admin(user_record)
        all_projects = bool(claims.get("all_projects")) or is_admin
        projects = [] if all_projects else normalize_project_list(claims.get("projects"))
        return all_projects, projects

    def user_can_access_structure(user, structure):
        if not user:
            return False
        if user.get("is_admin") or user.get("all_projects"):
            return True
        project_id = normalize_project(structure.get("project") or "")
        if not project_id:
            return False
        return project_id in set(normalize_project_list(user.get("projects")))

    def structure_access_denied_response(structure=None):
        if request.path.startswith("/api/") or wants_json_response():
            return jsonify({"error": "You do not have access to this project."}), 403
        return render_template("access_denied.html", structure=structure), 403

    def load_allowed_structure(structure_id):
        structure = get_structure(db(), structure_id)
        if not structure:
            return None, jsonify({"error": "Structure not found."}), 404
        if not user_can_access_structure(g.user, structure):
            response, status = structure_access_denied_response(structure)
            return None, response, status
        return structure, None, None

    def can_edit_structure(structure):
        return user_can_access_structure(g.get("user"), structure)

    def public_structure_payload(structure, can_edit=False):
        payload = dict(structure)
        payload["can_edit"] = bool(can_edit)
        if can_edit:
            return payload

        payload["updated_by"] = None
        payload["created_by"] = None
        payload["final_remark"] = ""
        payload["final_remark_updated_by"] = None
        payload["checklist"] = [
            {
                "item_id": item.get("item_id"),
                "label": item.get("label"),
                "status": item.get("status", "pending"),
            }
            for item in structure.get("checklist", [])
        ]
        return payload

    def build_auth_user_rows(search="", project_records=None):
        initialize_firebase()
        project_records = project_records or []
        project_display_names = {
            item["project_id"]: item["display_name"] for item in project_records
        }
        query = (search or "").strip().lower()
        users = []
        for user in firebase_auth.list_users().iterate_all():
            claims = user.custom_claims or {}
            email = user.email or ""
            display_name = user.display_name or ""
            haystack = " ".join([user.uid, email, display_name]).lower()
            if query and query not in haystack:
                continue
            metadata = user.user_metadata
            is_admin = user_is_admin(user)
            all_projects, projects = user_project_access(user)
            project_labels = [
                project_display_names.get(project_id, display_project_name(project_id))
                for project_id in projects
            ]
            users.append(
                {
                    "uid": user.uid,
                    "email": email,
                    "display_name": display_name,
                    "disabled": bool(user.disabled),
                    "email_verified": bool(user.email_verified),
                    "is_admin": is_admin,
                    "role": claims.get("role") or ("admin" if is_admin else "worker"),
                    "all_projects": all_projects,
                    "projects": projects,
                    "project_labels": project_labels,
                    "access_label": "All projects" if all_projects else (
                        ", ".join(project_labels) if project_labels else "No project access"
                    ),
                    "created_at": format_auth_timestamp(
                        metadata.creation_timestamp if metadata else None
                    ),
                    "last_sign_in": format_auth_timestamp(
                        metadata.last_sign_in_timestamp if metadata else None
                    ),
                }
            )
        users.sort(key=lambda item: (item["disabled"], item["email"].lower()))
        summary = {
            "total": len(users),
            "active": sum(1 for user in users if not user["disabled"]),
            "disabled": sum(1 for user in users if user["disabled"]),
            "admins": sum(1 for user in users if user["is_admin"]),
        }
        return users, summary

    def dashboard_project_records_for_user(user, project_records):
        if user.get("is_admin") or user.get("all_projects"):
            return project_records, None
        allowed_ids = set(normalize_project_list(user.get("projects")))
        return (
            [
                project
                for project in project_records
                if project["project_id"] in allowed_ids
            ],
            allowed_ids,
        )

    def user_can_access_project(user, project_id):
        project_id = normalize_project(project_id)
        if not project_id:
            return True
        if user.get("is_admin") or user.get("all_projects"):
            return True
        return project_id in set(normalize_project_list(user.get("projects")))

    def dashboard_access_denied_response(project_id):
        if request.path.startswith("/api/") or wants_json_response():
            return jsonify({"error": "You do not have access to this project."}), 403
        return render_template(
            "access_denied.html",
            structure={
                "project": project_id,
                "project_display_name": get_project_display_name(db(), project_id),
            },
        ), 403

    def project_access_error(project_id):
        if user_can_access_project(g.user, project_id):
            return None
        return dashboard_access_denied_response(project_id)

    def require_project_access(project_id):
        error = project_access_error(project_id)
        if error:
            return error
        return None

    def build_dashboard_payload(search, project_id, block_id, allowed_project_ids=None):
        allowed_set = None
        if allowed_project_ids is not None:
            allowed_set = set(normalize_project_list(allowed_project_ids))
        cache_key = (
            normalize_structure_id(search) if search else "",
            project_id or "",
            block_id or "",
            ",".join(sorted(allowed_set)) if allowed_set is not None else "__ALL__",
        )
        cached = dashboard_cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached["created"] <= dashboard_cache_ttl:
            return cached["payload"]

        database = db()
        project_records = [
            item
            for item in list_project_records(database)
            if allowed_set is None or item["project_id"] in allowed_set
        ]
        project_display_names = {
            item["project_id"]: item["display_name"] for item in project_records
        }
        project_block_counts = {
            item["project_id"]: int(item.get("block_count") or 0)
            for item in project_records
        }
        project_block_structure_counts = {
            item["project_id"]: item.get("block_structure_counts") or {}
            for item in project_records
        }
        project_block_count = project_block_counts.get(project_id, 0)
        project_structures = (
            list_structures(database, project=project_id)
            if project_id and (allowed_set is None or project_id in allowed_set)
            else []
        )
        block_structure_count = 0
        if block_id:
            block_counts = project_block_structure_counts.get(project_id, {})
            if block_id in block_counts:
                try:
                    block_structure_count = int(block_counts.get(block_id) or 0)
                except (TypeError, ValueError):
                    block_structure_count = 0
            else:
                for structure in project_structures:
                    if structure.get("block") != block_id:
                        continue
                    number = extract_structure_number(structure.get("structure_id", ""))
                    if number.isdigit():
                        block_structure_count = max(block_structure_count, int(number))
        normalized_search = normalize_structure_id(search) if search else ""
        structures = []
        for structure in project_structures:
            if block_id and structure.get("block") != block_id:
                continue
            if normalized_search:
                candidates = [
                    structure.get("structure_id", ""),
                    structure.get("structure_number", ""),
                    structure.get("project", ""),
                    structure.get("block", ""),
                    structure.get("block_display", ""),
                ]
                if not any(
                    normalized_search in normalize_structure_id(candidate)
                    for candidate in candidates
                ):
                    continue
            structures.append(structure)
        total = len(structures)
        completed = sum(1 for item in structures if item["counts"]["pending"] == 0)
        pending = total - completed
        payload = {
            "structures": structures,
            "total": total,
            "completed": completed,
            "pending": pending,
            "project_summary": build_project_summary(
                project_structures,
                block_id,
                block_count=project_block_count,
            ),
            "project": project_id,
            "project_display_name": project_display_names.get(
                project_id,
                display_project_name(project_id),
            ),
            "project_block_count": project_block_count,
            "block_structure_count": block_structure_count,
            "block": block_id,
            "search": search,
            "projects": [item["project_id"] for item in project_records],
            "project_records": project_records,
            "project_display_names": project_display_names,
        }
        dashboard_cache[cache_key] = {"created": now, "payload": payload}
        return payload

    @app.get("/")
    def index():
        if g.user:
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("login"))

    @app.get("/login")
    def login():
        if g.user:
            next_url = request.args.get("next") or url_for("admin_dashboard")
            return redirect(next_url)
        return render_template("login.html", next_url=request.args.get("next", ""))

    @app.get("/account")
    @login_required
    def worker_account():
        if g.user.get("is_admin"):
            return redirect(url_for("admin_dashboard"))
        return render_template("account.html")

    @app.get("/scan")
    @login_required
    def scan_qr():
        return render_template("scanner.html")

    @app.get("/service-worker.js")
    def service_worker():
        response = app.send_static_file("service-worker.js")
        response.headers["Content-Type"] = "application/javascript; charset=utf-8"
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    @app.post("/auth/login")
    def auth_login():
        payload = request.get_json(silent=True) or {}
        email = (payload.get("email") or "").strip()
        password = payload.get("password") or ""
        if not email or not password:
            return jsonify({"error": "Please enter email and password."}), 400

        try:
            result = firebase_auth_request(
                "signInWithPassword",
                {"email": email, "password": password, "returnSecureToken": True},
            )
            return create_session_response(result["idToken"])
        except Exception as exc:
            return jsonify({"error": auth_error_message(exc)}), 401

    @app.post("/auth/signup")
    @admin_required
    def auth_signup():
        payload = request.get_json(silent=True) or {}
        name = (payload.get("name") or "").strip()
        email = (payload.get("email") or "").strip().lower()
        password = payload.get("password") or ""
        if not name or not email or not password:
            return jsonify({"error": "Please enter name, email and password."}), 400
        if len(password) < 6:
            return jsonify({"error": "Password must be at least 6 characters."}), 400

        try:
            initialize_firebase()
            user = firebase_auth.create_user(
                email=email,
                password=password,
                display_name=name,
                disabled=False,
            )
            firebase_auth.set_custom_user_claims(
                user.uid, user_claim_payload(False, False, [])
            )
            return jsonify({"ok": True, "uid": user.uid})
        except firebase_auth.EmailAlreadyExistsError:
            return jsonify({"error": auth_error_message("EMAIL_EXISTS")}), 409
        except Exception as exc:
            return jsonify({"error": auth_error_message(exc)}), 400

    @app.post("/auth/reset")
    @admin_required
    def auth_reset():
        payload = request.get_json(silent=True) or {}
        email = (payload.get("email") or "").strip()
        if not email:
            return jsonify({"error": "Please enter email."}), 400

        try:
            firebase_auth_request(
                "sendOobCode",
                {"requestType": "PASSWORD_RESET", "email": email},
            )
        except Exception as exc:
            if str(exc) not in {"EMAIL_NOT_FOUND", "INVALID_EMAIL"}:
                return jsonify({"error": auth_error_message(exc)}), 400
        return jsonify({"ok": True})

    @app.post("/session-login")
    def session_login():
        payload = request.get_json(silent=True) or {}
        id_token = payload.get("idToken")
        if not id_token:
            return jsonify({"error": "Missing Firebase ID token."}), 400

        try:
            return create_session_response(id_token)
        except Exception as exc:
            return jsonify({"error": f"Could not create session: {exc}"}), 401

    @app.get("/logout")
    def logout():
        response = redirect(url_for("login"))
        response.delete_cookie("firebase_session")
        return response

    @app.get("/structure/<structure_id>")
    def structure_page(structure_id):
        structure = get_structure(db(), structure_id)
        if not structure:
            return render_template("not_found.html", structure_id=structure_id), 404
        structure["project_display_name"] = get_project_display_name(
            db(), structure.get("project")
        )
        return render_template(
            "structure.html",
            structure=structure,
            can_edit_structure=can_edit_structure(structure),
        )

    @app.get("/api/structure/<structure_id>")
    def api_structure(structure_id):
        structure = get_structure(db(), structure_id)
        if not structure:
            return jsonify({"error": "Structure not found."}), 404
        editable = can_edit_structure(structure)
        structure["project_display_name"] = get_project_display_name(
            db(), structure.get("project")
        )
        return jsonify(public_structure_payload(structure, editable))

    @app.post("/api/structure/<structure_id>/items/<item_id>")
    @login_required
    def api_update_item(structure_id, item_id):
        payload = request.get_json(silent=True) or {}
        new_status = payload.get("status")
        _structure, error_response, status = load_allowed_structure(structure_id)
        if error_response:
            return error_response, status
        try:
            result = update_checklist_status(db(), structure_id, item_id, new_status, g.user)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception:
            app.logger.exception("Checklist update failed for %s/%s", structure_id, item_id)
            return jsonify({"error": "Could not update checklist. Please try again."}), 500
        if not result:
            return jsonify({"error": "Structure not found."}), 404
        clear_dashboard_cache()
        return jsonify(result)

    @app.post("/api/structure/<structure_id>/items/<item_id>/remark")
    @login_required
    def api_update_item_remark(structure_id, item_id):
        payload = request.get_json(silent=True) or {}
        _structure, error_response, status = load_allowed_structure(structure_id)
        if error_response:
            return error_response, status
        try:
            result = update_checklist_remark(
                db(), structure_id, item_id, payload.get("remark", ""), g.user
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception:
            app.logger.exception("Remark update failed for %s/%s", structure_id, item_id)
            return jsonify({"error": "Could not update remark. Please try again."}), 500
        if not result:
            return jsonify({"error": "Structure not found."}), 404
        clear_dashboard_cache()
        return jsonify(result)

    @app.post("/api/structure/<structure_id>/final-remark")
    @login_required
    def api_update_final_remark(structure_id):
        payload = request.get_json(silent=True) or {}
        _structure, error_response, status = load_allowed_structure(structure_id)
        if error_response:
            return error_response, status
        try:
            result = update_final_remark(
                db(), structure_id, payload.get("remark", ""), g.user
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception:
            app.logger.exception("Final remark update failed for %s", structure_id)
            return jsonify({"error": "Could not update final remark. Please try again."}), 500
        if not result:
            return jsonify({"error": "Structure not found."}), 404
        clear_dashboard_cache()
        return jsonify(result)

    @app.get("/admin/users")
    @admin_required
    def admin_users():
        search = request.args.get("q", "").strip()
        project_records = list_project_records(db())
        users, summary = build_auth_user_rows(search, project_records)
        return render_template(
            "admin/users.html",
            users=users,
            summary=summary,
            search=search,
            project_records=project_records,
        )

    @app.post("/admin/users")
    @admin_required
    def admin_create_user():
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "worker")
        all_projects, projects = project_access_from_form()
        if not name or not email or not password:
            flash("Name, email and password are required.", "danger")
            return redirect(url_for("admin_users"))
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return redirect(url_for("admin_users"))
        if role != "admin" and not all_projects and not projects:
            flash("Select at least one project or All projects for worker access.", "danger")
            return redirect(url_for("admin_users"))

        try:
            initialize_firebase()
            user = firebase_auth.create_user(
                email=email,
                password=password,
                display_name=name,
                disabled=False,
            )
            is_admin = role == "admin"
            firebase_auth.set_custom_user_claims(
                user.uid,
                user_claim_payload(is_admin, all_projects, projects),
            )
        except firebase_auth.EmailAlreadyExistsError:
            flash("This email is already registered.", "danger")
            return redirect(url_for("admin_users", q=email))
        except Exception as exc:
            flash(auth_error_message(exc), "danger")
            return redirect(url_for("admin_users"))

        flash(f"User {email} created.", "success")
        return redirect(url_for("admin_users", q=email))

    @app.post("/admin/users/<uid>/access")
    @admin_required
    def admin_update_user_access(uid):
        action = request.form.get("action", "")
        if uid == g.user.get("uid"):
            flash("You cannot remove access from your own active login.", "danger")
            return redirect(url_for("admin_users"))

        try:
            initialize_firebase()
            user = firebase_auth.get_user(uid)
            if action == "disable":
                firebase_auth.update_user(uid, disabled=True)
                firebase_auth.revoke_refresh_tokens(uid)
                flash(f"Access removed for {user.email}.", "success")
            elif action == "enable":
                firebase_auth.update_user(uid, disabled=False)
                flash(f"Access enabled for {user.email}.", "success")
            else:
                flash("Invalid access action.", "danger")
        except Exception as exc:
            flash(f"Could not update access: {exc}", "danger")
        return redirect(url_for("admin_users"))

    @app.post("/admin/users/<uid>/role")
    @admin_required
    def admin_update_user_role(uid):
        role = request.form.get("role", "worker")
        is_admin = role == "admin"
        if uid == g.user.get("uid") and not is_admin:
            flash("You cannot remove admin access from your own active login.", "danger")
            return redirect(url_for("admin_users"))

        try:
            initialize_firebase()
            user = firebase_auth.get_user(uid)
            claims = user.custom_claims or {}
            firebase_auth.set_custom_user_claims(
                uid,
                user_claim_payload(
                    is_admin,
                    claims.get("all_projects"),
                    claims.get("projects"),
                ),
            )
            firebase_auth.revoke_refresh_tokens(uid)
            flash(f"Role updated for {user.email}.", "success")
        except Exception as exc:
            flash(f"Could not update role: {exc}", "danger")
        return redirect(url_for("admin_users"))

    @app.post("/admin/users/<uid>/projects")
    @admin_required
    def admin_update_user_projects(uid):
        all_projects, projects = project_access_from_form()
        if not all_projects and not projects:
            flash("Select at least one project or All projects.", "danger")
            return redirect(url_for("admin_users"))

        try:
            initialize_firebase()
            user = firebase_auth.get_user(uid)
            if user_is_admin(user):
                firebase_auth.set_custom_user_claims(
                    uid,
                    user_claim_payload(True, True, []),
                )
                flash("Admin users already have all project access.", "info")
            else:
                firebase_auth.set_custom_user_claims(
                    uid,
                    user_claim_payload(False, all_projects, projects),
                )
                firebase_auth.revoke_refresh_tokens(uid)
                flash(f"Project access updated for {user.email}.", "success")
        except Exception as exc:
            flash(f"Could not update project access: {exc}", "danger")
        return redirect(url_for("admin_users"))

    @app.post("/admin/users/<uid>/reset")
    @admin_required
    def admin_reset_user_password(uid):
        try:
            initialize_firebase()
            user = firebase_auth.get_user(uid)
            if not user.email:
                flash("This user does not have an email address.", "danger")
                return redirect(url_for("admin_users"))
            firebase_auth_request(
                "sendOobCode",
                {"requestType": "PASSWORD_RESET", "email": user.email},
            )
            flash(f"Password reset link sent to {user.email}.", "success")
        except Exception as exc:
            flash(auth_error_message(exc), "danger")
        return redirect(url_for("admin_users"))

    @app.get("/admin")
    @login_required
    def admin_dashboard():
        search = request.args.get("q", "").strip()
        project = request.args.get("project", "").strip()
        block = request.args.get("block", "").strip()
        project_id, block_id = normalize_scope(project, block)
        project_records, allowed_project_ids = dashboard_project_records_for_user(
            g.user, list_project_records(db())
        )
        if project_id and not user_can_access_project(g.user, project_id):
            return dashboard_access_denied_response(project_id)
        if not project_id and allowed_project_ids is not None and len(project_records) == 1:
            return redirect(
                url_for("admin_dashboard", project=project_records[0]["project_id"])
            )

        payload = build_dashboard_payload(
            search, project_id, block_id, allowed_project_ids=allowed_project_ids
        )
        create_id = normalize_structure_id(request.args.get("create_id", "").strip())
        if not create_id and project_id and block_id:
            create_id = get_next_structure_id(db(), project=project_id, block=block_id)
        selected_structure = request.args.get("selected_structure", "").strip()
        selected_structure_number = 0
        if selected_structure:
            selected_structure = extract_structure_number(selected_structure)
            if selected_structure.isdigit():
                selected_structure_number = int(selected_structure)
        return render_template(
            "admin/dashboard.html",
            structures=payload["structures"],
            search=payload["search"],
            total=payload["total"],
            completed=payload["completed"],
            pending=payload["pending"],
            project_summary=payload["project_summary"],
            project=project_id,
            project_display_name=payload["project_display_name"],
            project_display_names=payload["project_display_names"],
            project_block_count=payload["project_block_count"],
            block_structure_count=payload["block_structure_count"],
            block=block_id,
            projects=payload["projects"],
            project_records=payload["project_records"],
            user_can_manage_project=bool(project_id and user_can_access_project(g.user, project_id)),
            create_structure_id=extract_structure_number(create_id) if create_id else "",
            bulk_start=request.args.get("bulk_start"),
            bulk_end=request.args.get("bulk_end"),
            bulk_project=request.args.get("bulk_project", ""),
            bulk_block=request.args.get("bulk_block", ""),
            selected_structure_number=selected_structure_number,
        )

    @app.get("/admin/api/structures")
    @login_required
    def admin_structures_api():
        search = request.args.get("q", "").strip()
        project_id, block_id = normalize_scope(
            request.args.get("project", "").strip(),
            request.args.get("block", "").strip(),
        )
        _project_records, allowed_project_ids = dashboard_project_records_for_user(
            g.user, list_project_records(db())
        )
        if project_id and not user_can_access_project(g.user, project_id):
            response, status = dashboard_access_denied_response(project_id)
            return response, status
        return jsonify(
            build_dashboard_payload(
                search, project_id, block_id, allowed_project_ids=allowed_project_ids
            )
        )

    @app.post("/admin/projects")
    @admin_required
    def admin_create_project():
        project = request.form.get("project", "").strip()
        try:
            project_data = create_project(db(), project, g.user["email"])
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("admin_dashboard"))

        clear_dashboard_cache()
        flash(f"Project {project_data['display_name']} is ready.", "success")
        return redirect(
            url_for(
                "admin_dashboard",
                project=project_data["project_id"],
            )
        )

    @app.post("/admin/projects/<project_id>/rename")
    @login_required
    def admin_rename_project(project_id):
        access_error = require_project_access(project_id)
        if access_error:
            return access_error
        display_name = request.form.get("display_name", "").strip()
        try:
            project_data = update_project_display_name(
                db(), project_id, display_name, g.user["email"]
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("admin_dashboard", project=project_id))

        clear_dashboard_cache()
        flash(f"Project renamed to {project_data['display_name']}.", "success")
        return redirect(url_for("admin_dashboard", project=project_data["project_id"]))

    @app.post("/admin/projects/<project_id>/blocks")
    @login_required
    def admin_update_project_blocks(project_id):
        access_error = require_project_access(project_id)
        if access_error:
            return access_error
        try:
            project_data = update_project_block_count(
                db(),
                project_id,
                request.form.get("block_count", "0"),
                g.user["email"],
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("admin_dashboard", project=project_id))

        clear_dashboard_cache()
        flash(f"Saved {project_data['block_count']} blocks for this project.", "success")
        return redirect(url_for("admin_dashboard", project=project_data["project_id"]))

    @app.post("/admin/projects/<project_id>/blocks/<block_id>/structures")
    @login_required
    def admin_update_block_structures(project_id, block_id):
        access_error = require_project_access(project_id)
        if access_error:
            return access_error
        try:
            block_data = update_project_block_structure_count(
                db(),
                project_id,
                block_id,
                request.form.get("structure_count", "0"),
                g.user["email"],
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("admin_dashboard", project=project_id, block=block_id))

        clear_dashboard_cache()
        flash(
            f"Saved {block_data['structure_count']} structures for Block {display_block(block_data['block'])}.",
            "success",
        )
        return redirect(
            url_for(
                "admin_dashboard",
                project=block_data["project_id"],
                block=block_data["block"],
            )
        )

    @app.post("/admin/open-structure-checklist")
    @login_required
    def admin_open_structure_checklist():
        project_id, block_id = normalize_scope(
            request.form.get("project", "").strip(),
            request.form.get("block", "").strip(),
        )
        access_error = require_project_access(project_id)
        if access_error:
            return access_error
        try:
            number = int(request.form.get("structure_number", "0"))
        except ValueError:
            number = 0
        if not project_id or not block_id or number < 1 or number > 999999:
            flash("Select a valid structure number.", "danger")
            return redirect(url_for("admin_dashboard", project=project_id, block=block_id))

        structure = create_structure(
            db(),
            format_structure_id(number, project=project_id, block=block_id),
            g.user["email"],
            base_url=public_base_url(),
            project=project_id,
            block=block_id,
        )
        clear_dashboard_cache()
        return redirect(url_for("structure_page", structure_id=structure["structure_id"]))

    @app.post("/admin/projects/<project_id>/delete")
    @login_required
    def admin_delete_project(project_id):
        access_error = require_project_access(project_id)
        if access_error:
            return access_error
        try:
            deleted = delete_project(db(), project_id)
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("admin_dashboard", project=project_id))

        clear_dashboard_cache()
        flash(f"Project {deleted['project_id']} deleted.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.post("/admin/structures")
    @login_required
    def admin_create_structure():
        project = request.form.get("project", "").strip()
        block = request.form.get("block", "").strip()
        project_id, block_id = normalize_scope(project, block)
        if not project_id:
            flash("Select a project first.", "danger")
            return redirect(url_for("admin_dashboard"))
        access_error = require_project_access(project_id)
        if access_error:
            return access_error
        structure_id = request.form.get("structure_id", "").strip()
        if not structure_id:
            structure_id = get_next_structure_id(
                db(), project=project_id, block=block_id
            )
        structure = create_structure(
            db(),
            structure_id,
            g.user["email"],
            base_url=public_base_url(),
            project=project_id,
            block=block_id,
        )
        clear_dashboard_cache()
        flash(f"Structure {structure['structure_id']} is ready.", "success")
        return redirect(url_for("admin_structure_detail", structure_id=structure["structure_id"]))

    @app.post("/admin/structures/<structure_id>/delete")
    @login_required
    def admin_delete_structure(structure_id):
        structure, error_response, status = load_allowed_structure(structure_id)
        if error_response:
            return error_response, status
        deleted = delete_structure(db(), structure_id)
        if not deleted:
            if wants_json_response():
                return jsonify({"error": "Structure not found or already deleted."}), 404
            flash("Structure not found or already deleted.", "warning")
            return redirect(url_for("admin_dashboard"))

        clear_dashboard_cache()
        if wants_json_response():
            return jsonify({"deleted": deleted})

        flash(
            f"Deleted {deleted['structure_id']}. Same ID is ready in the create box.",
            "success",
        )
        return redirect(
            url_for(
                "admin_dashboard",
                project=deleted.get("project", ""),
                block=deleted.get("block", ""),
                create_id=deleted["structure_id"],
            )
        )

    @app.post("/admin/structures/bulk")
    @login_required
    def admin_create_bulk():
        project = request.form.get("project", "").strip()
        block = request.form.get("block", "").strip()
        project_id, block_id = normalize_scope(project, block)
        if not project_id:
            flash("Select a project first.", "danger")
            return redirect(url_for("admin_dashboard"))
        access_error = require_project_access(project_id)
        if access_error:
            return access_error
        try:
            start = int(request.form.get("start_number", "1"))
            end = int(request.form.get("end_number", "1"))
        except ValueError:
            flash("Start and end must be numbers.", "danger")
            return redirect(url_for("admin_dashboard"))
        if end < start or end - start > 500:
            flash("Bulk range must be ascending and limited to 500 structures.", "danger")
            return redirect(url_for("admin_dashboard"))

        structures = create_structures_bulk(
            db(),
            start,
            end,
            g.user["email"],
            base_url=public_base_url(),
            project=project_id,
            block=block_id,
        )
        scope = " / ".join(item for item in [project_id, block_id] if item)
        label = f" for {scope}" if scope else ""
        clear_dashboard_cache()
        flash(f"Bulk created or verified {len(structures)} structures{label}.", "success")
        return redirect(
            url_for(
                "admin_dashboard",
                project=project_id,
                block=block_id,
                bulk_start=start,
                bulk_end=end,
                bulk_project=project_id,
                bulk_block=block_id,
            )
        )

    @app.get("/admin/structures/<structure_id>")
    @login_required
    def admin_structure_detail(structure_id):
        structure, error_response, status = load_allowed_structure(structure_id)
        if error_response:
            return error_response, status
        structure["project_display_name"] = get_project_display_name(
            db(), structure.get("project")
        )
        history = get_history(db(), structure_id=structure["structure_id"], limit=100)
        return render_template(
            "admin/structure_detail.html",
            structure=structure,
            history=history,
            base_url=public_base_url(),
        )

    @app.get("/admin/structures/<structure_id>/qr.png")
    @login_required
    def admin_structure_qr(structure_id):
        _structure, error_response, status = load_allowed_structure(structure_id)
        if error_response:
            return error_response, status
        png = generate_qr_bytes(normalize_structure_id(structure_id), public_base_url())
        return send_file(
            png,
            mimetype="image/png",
            as_attachment=request.args.get("download") == "1",
            download_name=f"{structure_id}.png",
        )

    @app.get("/admin/qr-codes.zip")
    @login_required
    def admin_qr_zip():
        raw_ids = request.args.get("ids", "").strip()
        if raw_ids:
            structure_ids = [normalize_structure_id(item) for item in raw_ids.split(",") if item]
            for structure_id in structure_ids:
                _structure, error_response, status = load_allowed_structure(structure_id)
                if error_response:
                    return error_response, status
        else:
            project = request.args.get("project", "").strip()
            block = request.args.get("block", "").strip()
            project_id, block_id = normalize_scope(project, block)
            if not project_id and not (g.user.get("is_admin") or g.user.get("all_projects")):
                return dashboard_access_denied_response(project_id)
            access_error = require_project_access(project_id)
            if access_error:
                return access_error
            try:
                start = int(request.args.get("start", "1"))
                end = int(request.args.get("end", "1"))
            except ValueError:
                return Response("Invalid range.", status=400)
            if end < start or end - start > 500:
                return Response("Invalid range.", status=400)
            structure_ids = [
                format_structure_id(number, project=project_id, block=block_id)
                for number in range(start, end + 1)
            ]

        archive = generate_qr_zip(structure_ids, public_base_url())
        return send_file(
            archive,
            mimetype="application/zip",
            as_attachment=True,
            download_name="structure-qr-codes.zip",
        )

    @app.route("/admin/checklist-items", methods=["GET", "POST"])
    @admin_required
    def admin_checklist_items():
        if request.method == "POST":
            label = request.form.get("label", "").strip()
            if not label:
                flash("Checklist item label is required.", "danger")
            else:
                add_checklist_item(db(), label, g.user["email"])
                clear_dashboard_cache()
                flash("Checklist item added.", "success")
            return redirect(url_for("admin_checklist_items"))

        items = get_active_checklist_items(db(), include_inactive=True)
        return render_template("admin/checklist_items.html", items=items)

    @app.post("/admin/checklist-items/<item_id>/remove")
    @admin_required
    def admin_remove_checklist_item(item_id):
        deactivate_checklist_item(db(), item_id, g.user["email"])
        clear_dashboard_cache()
        flash("Checklist item removed from active checklists.", "success")
        return redirect(url_for("admin_checklist_items"))

    @app.post("/admin/checklist-items/<item_id>/rename")
    @admin_required
    def admin_rename_checklist_item(item_id):
        label = request.form.get("label", "").strip()
        try:
            result = update_checklist_item_label(db(), item_id, label, g.user["email"])
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("admin_checklist_items"))

        clear_dashboard_cache()
        flash(
            f"Checklist item renamed. Updated {result['updated_structures']} structures.",
            "success",
        )
        return redirect(url_for("admin_checklist_items"))

    @app.get("/admin/history")
    @login_required
    def admin_history():
        structure_id = request.args.get("structure_id", "").strip()
        project = request.args.get("project", "").strip()
        block = request.args.get("block", "").strip()
        project_id, block_id = normalize_scope(project, block)
        if structure_id:
            _structure, error_response, status = load_allowed_structure(structure_id)
            if error_response:
                return error_response, status
        elif project_id:
            access_error = require_project_access(project_id)
            if access_error:
                return access_error
        elif not (g.user.get("is_admin") or g.user.get("all_projects")):
            return dashboard_access_denied_response(project_id)
        history = get_history(
            db(),
            structure_id=structure_id or None,
            project=project_id,
            block=block_id,
            limit=300,
        )
        return render_template(
            "admin/history.html",
            history=history,
            structure_id=structure_id,
            project=project_id,
            block=block_id,
        )

    @app.get("/admin/export/structures.csv")
    @login_required
    def admin_export_structures_csv():
        project_id, block_id = normalize_scope(
            request.args.get("project", "").strip(),
            request.args.get("block", "").strip(),
        )
        if not project_id and not (g.user.get("is_admin") or g.user.get("all_projects")):
            return dashboard_access_denied_response(project_id)
        access_error = require_project_access(project_id)
        if access_error:
            return access_error
        csv_text = export_structures_csv(db(), project=project_id, block=block_id)
        return Response(
            csv_text,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=structures.csv"},
        )

    @app.get("/admin/export/history.csv")
    @login_required
    def admin_export_history_csv():
        project_id, block_id = normalize_scope(
            request.args.get("project", "").strip(),
            request.args.get("block", "").strip(),
        )
        if not project_id and not (g.user.get("is_admin") or g.user.get("all_projects")):
            return dashboard_access_denied_response(project_id)
        access_error = require_project_access(project_id)
        if access_error:
            return access_error
        csv_text = export_history_csv(db(), project=project_id, block=block_id)
        return Response(
            csv_text,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=history.csv"},
        )

    @app.get("/admin/export/all.xlsx")
    @login_required
    def admin_export_all_xlsx():
        project_id, block_id = normalize_scope(
            request.args.get("project", "").strip(),
            request.args.get("block", "").strip(),
        )
        if not project_id and not (g.user.get("is_admin") or g.user.get("all_projects")):
            return dashboard_access_denied_response(project_id)
        access_error = require_project_access(project_id)
        if access_error:
            return access_error
        workbook = export_all_xlsx(db(), project=project_id, block=block_id)
        return send_file(
            workbook,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="structure-checklist-export.xlsx",
        )

    return app
