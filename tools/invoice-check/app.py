"""Invoice check: an HTTP API around invoice.check_invoice."""

import os
from pathlib import Path

from flask import Flask, jsonify, request

from invoice import InvalidInvoice, check_invoice

HERE = Path(__file__).parent


def read_version() -> str:
    if os.environ.get("APP_VERSION"):
        return os.environ["APP_VERSION"]
    stamp = HERE / "VERSION"
    return stamp.read_text().strip() if stamp.exists() else "dev"


def create_app() -> Flask:
    app = Flask(__name__)
    version = read_version()

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok", version=version)

    @app.post("/api/check")
    def api_check():
        payload = request.get_json(silent=True)
        try:
            findings = check_invoice(payload)
        except InvalidInvoice as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(ok=not findings, findings=[f.as_dict() for f in findings])

    return app


app = create_app()
