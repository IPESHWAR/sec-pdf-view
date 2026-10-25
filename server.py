#!/usr/bin/env python3
"""Protected PDF viewer with one access code per student.

Pages are rendered to PNG in memory after a student's code is accepted.
The browser receives those PNG bytes and draws them on a canvas. It never
receives the PDF, a filesystem path, or a page saved on disk.

Run from this folder:

    python app.py
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import socket
import threading
import time
from datetime import timedelta
from functools import wraps
from urllib.parse import urlsplit

from flask import Flask, Response, g, jsonify, request, session
from werkzeug.exceptions import RequestEntityTooLarge

from config import HOST, INDEX_FILE, PDF_PATH, PORT, STUDENTS_FILE, USER_PASSWORD, VIEW_MAX_EDGE, same_secret
from pdfpages import PageLibrary
from students import CODE_PATTERN, load_students

ATTEMPT_LIMIT = 8
ATTEMPT_WINDOW_SECONDS = 60
SESSION_HOURS = 8

log = logging.getLogger("protected-viewer")
library = PageLibrary(PDF_PATH, USER_PASSWORD, VIEW_MAX_EDGE)


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    # One process keeps a random key. Set SECRET_KEY in the host environment
    # when more than one process must share the same login session.
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        SESSION_COOKIE_NAME="protected_doc",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=False,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=SESSION_HOURS),
        MAX_CONTENT_LENGTH=8 * 1024,
    )
    app.extensions["failed_logins"] = {}
    app.extensions["login_lock"] = threading.Lock()

    def current_student() -> dict[str, str] | None:
        token = session.get("student_token")
        if not isinstance(token, str) or token == "":
            return None
        return _match_token(token, load_students(STUDENTS_FILE))

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            student = current_student()
            if student is None:
                return jsonify(error="Authentication required."), 401
            g.student = student
            return view(*args, **kwargs)

        return wrapped

    def origin_allowed() -> bool:
        """Accept the browser that loaded this same host, including an https tunnel."""
        origin = request.headers.get("Origin")
        if not origin:
            return False
        try:
            parts = urlsplit(origin.strip())
        except ValueError:
            return False
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            return False
        host = request.headers.get("X-Forwarded-Host", request.host)
        host = host.split(",")[0].strip()
        return parts.netloc.lower() == host.lower()

    def client_key() -> str:
        return request.remote_addr or "unknown"

    def locked_out() -> bool:
        now = time.monotonic()
        with app.extensions["login_lock"]:
            _prune_failures(app, now)
            return len(app.extensions["failed_logins"].get(client_key(), [])) >= ATTEMPT_LIMIT

    def note_failure() -> None:
        now = time.monotonic()
        with app.extensions["login_lock"]:
            app.extensions["failed_logins"].setdefault(client_key(), []).append(now)
            _prune_failures(app, now)

    def clear_failures() -> None:
        with app.extensions["login_lock"]:
            app.extensions["failed_logins"].pop(client_key(), None)

    @app.after_request
    def protect_response(response):
        nonce = getattr(g, "csp_nonce", None)
        script = f"'nonce-{nonce}'" if nonce else "'none'"
        style = f"'nonce-{nonce}'" if nonce else "'none'"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            f"script-src {script}; "
            f"style-src {style}; "
            "img-src 'none'; "
            "connect-src 'self'; "
            "base-uri 'none'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), display-capture=()"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def home():
        if not INDEX_FILE.is_file():
            return "index.html is missing next to server.py.", 500
        nonce = secrets.token_urlsafe(16)
        g.csp_nonce = nonce
        html = INDEX_FILE.read_text(encoding="utf-8").replace("__CSP_NONCE__", nonce)
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    @app.get("/api/session")
    def session_state():
        student = current_student()
        if student is None:
            return jsonify(authenticated=False)
        return jsonify(authenticated=True, name=student["name"], code=student["code"])

    @app.post("/api/login")
    def login():
        if not origin_allowed():
            return jsonify(error="Open the viewer from this server and try again."), 403
        if locked_out():
            return jsonify(error="Too many attempts. Wait a minute and try again."), 429

        payload = request.get_json(silent=True)
        raw_code = payload.get("code") if isinstance(payload, dict) else None
        code = "".join(raw_code.split()) if isinstance(raw_code, str) else ""
        if CODE_PATTERN.fullmatch(code) is None:
            return jsonify(error="Enter the 6-digit access code."), 400

        student = _match_code(code, load_students(STUDENTS_FILE))
        if student is None:
            note_failure()
            log.warning("Rejected viewer login")
            return jsonify(error="Incorrect access code."), 401

        clear_failures()
        session.clear()
        session["student_token"] = student["token"]
        session.permanent = True
        return jsonify(ok=True, name=student["name"], code=student["code"])

    @app.post("/api/logout")
    def logout():
        if not origin_allowed():
            return jsonify(error="Open the viewer from this server and try again."), 403
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/pages")
    @login_required
    def pages():
        student = g.student
        try:
            described = library.describe()
        except (OSError, RuntimeError) as exc:
            log.error("Could not open the PDF: %s", exc.__class__.__name__)
            return jsonify(error="The document could not be opened."), 500
        return jsonify(
            count=len(described),
            name=student["name"],
            code=student["code"],
            pages=described,
        )

    @app.get("/api/pages/<int:index>")
    @login_required
    def page_image(index: int):
        student = g.student
        try:
            png = library.render_png(index)
        except IndexError:
            return jsonify(error="Page not found."), 404
        except (OSError, RuntimeError) as exc:
            log.error("Could not render a page: %s", exc.__class__.__name__)
            return jsonify(error="This page could not be prepared."), 500
        return Response(
            png,
            mimetype="image/png",
            headers={"Content-Disposition": "inline", "Cache-Control": "no-store, private"},
        )

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_exc):
        return jsonify(error="That request was too large."), 413

    @app.errorhandler(404)
    def missing(_exc):
        if request.path.startswith("/api/"):
            return jsonify(error="Not found."), 404
        return "Not found.", 404

    return app


def _match_code(code: str, students: list[dict[str, str]]) -> dict[str, str] | None:
    """Compare against every code so the match position is not a timing signal."""
    found = None
    for student in students:
        if same_secret(code, student["code"]):
            found = student
    if not students:
        same_secret(code, "000000")
    return found


def _match_token(token: str, students: list[dict[str, str]]) -> dict[str, str] | None:
    found = None
    for student in students:
        if same_secret(token, student["token"]):
            found = student
    return found


def _prune_failures(app: Flask, now: float) -> None:
    """Drop expired failures. Caller holds the login lock."""
    cutoff = now - ATTEMPT_WINDOW_SECONDS
    failures: dict[str, list[float]] = app.extensions["failed_logins"]
    app.extensions["failed_logins"] = {
        key: [stamp for stamp in stamps if stamp >= cutoff]
        for key, stamps in failures.items()
        if any(stamp >= cutoff for stamp in stamps)
    }


app = create_app()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the protected PDF viewer.")
    parser.add_argument("--host", default=HOST, help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=PORT, help="Port (default: 5000)")
    return parser.parse_args()


def lan_addresses() -> list[str]:
    """IPv4 addresses other devices can use to reach this computer."""
    addresses: list[str] = []
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("192.168.0.1", 1))
            address = probe.getsockname()[0]
        finally:
            probe.close()
    except OSError:
        return addresses
    if address and not address.startswith("127."):
        addresses.append(address)
    return addresses


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    host = args.host or "0.0.0.0"
    port = int(os.environ.get("PORT", args.port or 5000))
    print(f"Protected viewer on this computer: http://127.0.0.1:{port}")
    for address in lan_addresses():
        print(f"Protected viewer on the local network: http://{address}:{port}")
    students = load_students(STUDENTS_FILE)
    print(f"Student codes loaded: {len(students)}")
    try:
        print(f"PDF pages: {len(library.describe())}")
    except (OSError, RuntimeError):
        print("The PDF could not be opened. Check protected_document.pdf and USER_PASSWORD in config.py.")
    if host in ("127.0.0.1", "localhost", "::1"):
        print("Listening on this computer only.")
    else:
        print("Listening on all network interfaces. Other devices on this network can open the address above.")

    try:
        from waitress import serve

        serve(app, host=host, port=port, threads=8, ident="protected-viewer")
    except OSError as exc:
        print(f"Could not listen on {host}:{port}: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
