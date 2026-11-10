"""End-to-end tests for deploy.sh against a real (tiny) HTTP service.

The restart command starts fake_service.py from the live release. A release
that contains a BROKEN file crashes on start-up, the way a release with a bad
import or a missing setting would.
"""

import os
import shlex
import socket
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
DEPLOY = SCRIPTS / "deploy.sh"
TOOL = "demo"

FAKE_SERVICE = """
import http.server, json, os, sys
port, current = int(sys.argv[1]), sys.argv[2]
if os.path.exists(os.path.join(current, "BROKEN")):
    sys.exit("this release crashes on start-up")
version = open(os.path.join(current, "VERSION")).read().strip()

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        ok = self.path == "/healthz"
        body = json.dumps({"status": "ok", "version": version} if ok else {}).encode()
        self.send_response(200 if ok else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Target:
    """A deploy target in a temp dir: DEPLOY_ROOT plus a fake service manager."""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.root = tmp_path / "opt"
        self.port = free_port()
        self.pidfile = tmp_path / "service.pid"
        service = tmp_path / "fake_service.py"
        service.write_text(FAKE_SERVICE)
        q = shlex.quote
        pid = q(str(self.pidfile))
        current = q(str(self.root / TOOL / "current"))
        self.restart_cmd = (
            f'if [ -f {pid} ]; then p=$(cat {pid}); kill "$p" 2>/dev/null || true; '
            f'while kill -0 "$p" 2>/dev/null; do sleep 0.05; done; fi; '
            f"nohup {q(sys.executable)} {q(str(service))} {self.port} {current} "
            f">>{q(str(tmp_path / 'service.log'))} 2>&1 & echo $! > {pid}"
        )

    def artifact(self, version: str, broken: bool = False) -> Path:
        src = self.tmp / f"src-{version}"
        src.mkdir()
        (src / "VERSION").write_text(version + "\n")
        (src / "app.py").write_text("# demo\n")
        if broken:
            (src / "BROKEN").write_text("")
        path = self.tmp / f"{TOOL}-{version}.tar.gz"
        with tarfile.open(path, "w:gz") as tar:
            tar.add(src, arcname=".")
        return path

    def deploy(self, artifact: Path, tool: str = TOOL, **env) -> subprocess.CompletedProcess:
        full_env = {
            **os.environ,
            "DEPLOY_ROOT": str(self.root),
            "RESTART_CMD": self.restart_cmd,
            "HEALTH_URL": f"http://127.0.0.1:{self.port}/healthz",
            "HEALTH_RETRIES": "40",
            "HEALTH_DELAY": "0.1",
            "INSTALL_DEPS": "0",
            **env,
        }
        return subprocess.run(
            ["bash", str(DEPLOY), tool, str(artifact)],
            env=full_env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def live(self) -> str:
        return os.readlink(self.root / TOOL / "current")

    def log(self) -> list[list[str]]:
        lines = (self.root / TOOL / "deploys.log").read_text().splitlines()
        return [line.split("\t")[1:] for line in lines]

    def stop(self):
        if self.pidfile.exists():
            subprocess.run(["kill", self.pidfile.read_text().strip()], capture_output=True)


@pytest.fixture
def target(tmp_path):
    t = Target(tmp_path)
    yield t
    t.stop()


def test_first_deploy_goes_live(target):
    result = target.deploy(target.artifact("v1"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert target.live() == "releases/v1"
    assert "health check passed: serving v1" in result.stdout
    assert target.log() == [["v1", "ok"]]


def test_new_release_replaces_the_old_one(target):
    assert target.deploy(target.artifact("v1")).returncode == 0
    result = target.deploy(target.artifact("v2"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert target.live() == "releases/v2"
    assert "live now: v1" in result.stdout


def test_broken_release_is_rolled_back_automatically(target):
    assert target.deploy(target.artifact("v1")).returncode == 0
    result = target.deploy(target.artifact("v2", broken=True))
    assert result.returncode == 1, result.stdout + result.stderr
    assert target.live() == "releases/v1"
    assert "rolled back: demo v1 is live again" in result.stdout
    assert target.log() == [["v1", "ok"], ["v2", "failed"], ["v1", "rolled-back"]]


def test_broken_first_release_has_nothing_to_roll_back_to(target):
    result = target.deploy(target.artifact("v1", broken=True), HEALTH_RETRIES="5")
    assert result.returncode == 2
    assert target.log() == [["v1", "failed"]]


def test_failing_restart_command_also_triggers_rollback(target):
    assert target.deploy(target.artifact("v1")).returncode == 0
    result = target.deploy(
        target.artifact("v2"), RESTART_CMD=f"exit 1; {target.restart_cmd}", HEALTH_RETRIES="10"
    )
    # The restart never happens, so v1 keeps serving: v2 is not live, whatever
    # the restart command claimed. The health check catches it and rolls back.
    assert result.returncode == 1, result.stdout + result.stderr
    assert target.live() == "releases/v1"
    assert "health check gave up" in result.stdout


def test_restart_that_does_nothing_is_not_a_deploy(target):
    assert target.deploy(target.artifact("v1")).returncode == 0
    # `true` reports success, but v1 keeps running: the health check must notice.
    result = target.deploy(target.artifact("v2"), RESTART_CMD="true", HEALTH_RETRIES="10")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "serving 'v1', wanted 'v2'" in result.stdout
    assert target.live() == "releases/v1"


def test_redeploying_the_live_version_only_checks_health(target):
    artifact = target.artifact("v1")
    assert target.deploy(artifact).returncode == 0
    result = target.deploy(artifact)
    assert result.returncode == 0
    assert "already live" in result.stdout
    assert target.log() == [["v1", "ok"]]


def test_old_releases_are_pruned_but_rollback_target_is_kept(target):
    for version in ["v1", "v2", "v3", "v4"]:
        assert target.deploy(target.artifact(version), KEEP_RELEASES="1").returncode == 0
        time.sleep(1.1)  # release directories are ordered by modification time
    releases = sorted(p.name for p in (target.root / TOOL / "releases").iterdir())
    assert releases == ["v2", "v3", "v4"]


def test_second_deploy_waits_for_the_lock(target):
    (target.root / TOOL).mkdir(parents=True)
    (target.root / TOOL / ".deploy.lock").mkdir()
    result = target.deploy(target.artifact("v1"))
    assert result.returncode == 75
    assert "another deploy" in result.stderr


@pytest.mark.parametrize("tool", ["-oProxyCommand=touch pwned", "../etc", "Demo", ""])
def test_rejects_unsafe_tool_names(target, tool):
    result = target.deploy(target.artifact("v1"), tool=tool)
    assert result.returncode == 64
    assert not (target.root / TOOL).exists()


def test_rejects_artifact_without_version(target, tmp_path):
    src = tmp_path / "noversion"
    src.mkdir()
    (src / "app.py").write_text("")
    artifact = tmp_path / "noversion.tar.gz"
    with tarfile.open(artifact, "w:gz") as tar:
        tar.add(src, arcname=".")
    result = target.deploy(artifact)
    assert result.returncode == 64
    assert "no VERSION" in result.stderr
    assert not (target.root / TOOL / "current").exists()


def test_rejects_missing_health_url(target):
    result = target.deploy(target.artifact("v1"), HEALTH_URL="")
    assert result.returncode == 64
