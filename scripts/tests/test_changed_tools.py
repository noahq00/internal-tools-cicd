import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import changed_tools  # noqa: E402

TOOLS = ["invoice-check", "status-board"]


@pytest.mark.parametrize(
    "paths, expected",
    [
        (["tools/invoice-check/invoice.py"], ["invoice-check"]),
        (["tools/status-board/app.py", "tools/invoice-check/app.py"], TOOLS),
        (["tools/status-board/tests/test_app.py"], ["status-board"]),
        ([".github/workflows/ci.yml"], TOOLS),
        (["scripts/deploy.sh"], TOOLS),
        (["ruff.toml"], TOOLS),
        (["README.md", "docs/pipeline.md"], []),
        (["tools/ghost/app.py"], []),
        (["tools/README.md"], []),
        ([], []),
    ],
)
def test_affected(paths, expected):
    assert changed_tools.affected(paths, TOOLS) == expected


def make_repo(tmp_path: Path) -> Path:
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    for tool in TOOLS:
        (tmp_path / "tools" / tool).mkdir(parents=True)
        (tmp_path / "tools" / tool / "requirements.txt").write_text("flask\n")
    (tmp_path / "tools" / "not-a-tool").mkdir()  # no requirements.txt
    (tmp_path / "tools" / "Bad_Name").mkdir()
    (tmp_path / "tools" / "Bad_Name" / "requirements.txt").write_text("\n")
    (tmp_path / "README.md").write_text("demo\n")
    git("init", "-q", "-b", "main")
    git("-c", "user.name=t", "-c", "user.email=t@example.test", "add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-qm", "base")
    return tmp_path


def commit(repo: Path, path: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed\n")
    env = ["-c", "user.name=t", "-c", "user.email=t@example.test"]
    subprocess.run(["git", *env, "add", "."], cwd=repo, check=True)
    subprocess.run(["git", *env, "commit", "-qm", path], cwd=repo, check=True)
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True)
    return out.stdout.decode().strip()


def run_main(repo: Path, argv: list[str], capsys) -> tuple[int, list[str] | None]:
    code = changed_tools.main(argv, root=repo)
    out = capsys.readouterr().out
    return code, json.loads(out) if out else None


def test_all_tools_needs_requirements_and_a_plain_name(tmp_path):
    assert changed_tools.all_tools(make_repo(tmp_path)) == TOOLS


def test_diff_between_two_commits_selects_the_changed_tool(tmp_path, capsys):
    repo = make_repo(tmp_path)
    base = commit(repo, "README.md")
    head = commit(repo, "tools/status-board/app.py")
    assert run_main(repo, [base, head], capsys) == (0, ["status-board"])


def test_docs_only_change_selects_nothing(tmp_path, capsys):
    repo = make_repo(tmp_path)
    base = commit(repo, "tools/status-board/app.py")
    head = commit(repo, "README.md")
    assert run_main(repo, [base, head], capsys) == (0, [])


def test_first_push_of_a_branch_selects_every_tool(tmp_path, capsys):
    repo = make_repo(tmp_path)
    head = commit(repo, "README.md")
    assert run_main(repo, ["0" * 40, head], capsys) == (0, TOOLS)


def test_unknown_base_commit_selects_every_tool(tmp_path, capsys):
    repo = make_repo(tmp_path)
    head = commit(repo, "README.md")
    assert run_main(repo, ["deadbeef" * 5, head], capsys) == (0, TOOLS)


def test_all_flag_selects_every_tool(tmp_path, capsys):
    assert run_main(make_repo(tmp_path), ["--all"], capsys) == (0, TOOLS)


def test_wrong_arguments_print_usage(tmp_path, capsys):
    assert changed_tools.main(["only-one"], root=make_repo(tmp_path)) == 64
    assert "usage" in capsys.readouterr().err


def test_runs_against_this_repository():
    # The real repo layout: both demo tools are found.
    assert changed_tools.all_tools() == TOOLS
