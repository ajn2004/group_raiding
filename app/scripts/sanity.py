from __future__ import annotations

import compileall
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]

    ok = compileall.compile_dir(str(repo_root), quiet=1)
    if not ok:
        return 1

    try:
        __import__("discord")
    except ModuleNotFoundError:
        print("Missing dependency: install deps with `uv sync --dev` and rerun with `uv run`.")
        return 1

    try:
        __import__("app.discord_bot.bot")
    except Exception as exc:
        print(f"Sanity import failed: {exc}", file=sys.stderr)
        return 1

    print("Sanity OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
