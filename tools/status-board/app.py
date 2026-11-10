"""Status board: one page that shows whether each internal service is up."""

import json
import os
from collections.abc import Callable
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from flask import Flask, jsonify, render_template_string

HERE = Path(__file__).parent

PAGE = """<!doctype html>
<title>Status board</title>
<h1>Status board</h1>
<ul>
{% for row in rows %}  <li>{{ row.name }}: {{ "up" if row.up else "DOWN" }}</li>
{% endfor %}</ul>
<p><small>version {{ version }}</small></p>
"""


def read_version() -> str:
    """The version this process serves: set by the release build, never guessed."""
    if os.environ.get("APP_VERSION"):
        return os.environ["APP_VERSION"]
    stamp = HERE / "VERSION"
    return stamp.read_text().strip() if stamp.exists() else "dev"


def check(url: str, timeout: float = 2.0) -> bool:
    """True when the URL answers with a 2xx. Only http(s) is ever opened."""
    if not url.startswith(("http://", "https://")):
        return False
    try:
        with urlopen(url, timeout=timeout) as resp:  # noqa: S310 - scheme checked above
            return 200 <= resp.status < 300
    except (URLError, OSError, ValueError):
        return False


def create_app(
    services: list[dict] | None = None,
    checker: Callable[[str], bool] = check,
) -> Flask:
    app = Flask(__name__)
    if services is None:
        services = json.loads((HERE / "services.json").read_text())
    version = read_version()

    def statuses() -> list[dict]:
        return [{"name": s["name"], "up": checker(s["url"])} for s in services]

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok", version=version)

    @app.get("/api/status")
    def api_status():
        return jsonify(statuses())

    @app.get("/")
    def index():
        return render_template_string(PAGE, rows=statuses(), version=version)

    return app


app = create_app()
