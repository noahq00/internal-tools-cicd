import subprocess
import tarfile
from pathlib import Path

import pytest

BUILD = Path(__file__).resolve().parent.parent / "build_release.sh"
SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def repo(tmp_path):
    tool = tmp_path / "tools" / "demo"
    (tool / "tests").mkdir(parents=True)
    (tool / ".venv" / "bin").mkdir(parents=True)
    (tool / "__pycache__").mkdir()
    (tool / "app.py").write_text("# app\n")
    (tool / "requirements.txt").write_text("flask\n")
    (tool / "tests" / "test_app.py").write_text("# test\n")
    (tool / ".venv" / "bin" / "python").write_text("")
    (tool / "__pycache__" / "app.pyc").write_text("")
    (tool / "VERSION").write_text("stale\n")
    return tmp_path


def build(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(BUILD), *args], cwd=repo, capture_output=True, text=True, check=False
    )


def test_artifact_contains_runtime_files_and_a_fresh_version(repo):
    result = build(repo, "demo", SHA, "dist")
    assert result.returncode == 0, result.stderr
    artifact = repo / result.stdout.strip()
    assert artifact.name == "demo-0123456789ab.tar.gz"
    with tarfile.open(artifact) as tar:
        names = {Path(n).as_posix().removeprefix("./") for n in tar.getnames()}
        version = tar.extractfile("./VERSION").read().decode().strip()
    assert {"app.py", "requirements.txt", "VERSION"} <= names
    assert not any(n.startswith(("tests", ".venv", "__pycache__")) for n in names)
    assert version == "0123456789ab"


@pytest.mark.parametrize(
    "args",
    [
        ("-rf", SHA, "dist"),
        ("demo", "not-a-sha", "dist"),
        ("missing", SHA, "dist"),
        ("demo", SHA),
    ],
)
def test_rejects_bad_input(repo, args):
    assert build(repo, *args).returncode == 64
    assert not (repo / "dist").exists()
