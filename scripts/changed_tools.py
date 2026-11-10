"""Decide which tools a change touches, so CI only tests and deploys those.

    python scripts/changed_tools.py BASE HEAD     ->  ["invoice-check"]
    python scripts/changed_tools.py --all         ->  every tool

Rules, in order:
  * a change to anything shared (workflows, scripts/, lint config) affects every tool;
  * a change under tools/<name>/ affects that tool;
  * anything else (docs, the README) affects no tool.

When the change set can't be determined (a branch's first push, history that
wasn't fetched), every tool is affected. Testing too much costs minutes;
testing too little ships a broken tool.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED = (".github/", "scripts/", "ruff.toml")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
NO_COMMIT = re.compile(r"^0+$")


def all_tools(root: Path = ROOT) -> list[str]:
    """A tool is a directory under tools/ with a requirements.txt and a plain name."""
    tools_dir = root / "tools"
    return sorted(
        p.name
        for p in tools_dir.iterdir()
        if p.is_dir() and NAME.match(p.name) and (p / "requirements.txt").exists()
    )


def affected(paths: list[str], tools: list[str]) -> list[str]:
    if any(path.startswith(SHARED) for path in paths):
        return list(tools)
    hit = {
        path.split("/")[1] for path in paths if path.startswith("tools/") and path.count("/") >= 2
    }
    return [tool for tool in tools if tool in hit]


def changed_paths(base: str, head: str, root: Path = ROOT) -> list[str] | None:
    """Paths changed between base and head, or None when that can't be known."""
    if not base or NO_COMMIT.match(base):
        return None
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "diff", "--name-only", f"{base}...{head}"],  # noqa: S607 - git from PATH
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line]


def main(argv: list[str], root: Path = ROOT) -> int:
    tools = all_tools(root)
    if argv == ["--all"]:
        selected = tools
    elif len(argv) == 2:
        paths = changed_paths(argv[0], argv[1], root)
        selected = tools if paths is None else affected(paths, tools)
    else:
        print("usage: changed_tools.py BASE HEAD | --all", file=sys.stderr)
        return 64
    print(json.dumps(selected))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
