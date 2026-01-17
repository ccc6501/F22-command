#!/usr/bin/env python3
"""Repo-root launcher for the F-22 Data Manager.

Why this exists:
- Avoid remembering that the actual script lives in tools/f22_data_manager.py
- Default to using the repo root as the manager root_folder

Usage:
  python run_manager.py
  python run_manager.py --scan-only

Note: This launcher uses the currently-running Python interpreter.
If you want to ensure the repo venv is used on Windows, prefer:
  .\run_manager.ps1
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    manager_script = repo_root / "tools" / "f22_data_manager.py"

    if not manager_script.exists():
        print(f"Cannot find manager script: {manager_script}", file=sys.stderr)
        return 2

    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("--port", type=int, default=8022)
    p.add_argument("--host", type=str, default="127.0.0.1")
    p.add_argument("--scan-only", action="store_true")
    p.add_argument("--backup", action="store_true")
    args = p.parse_args()

    cmd = [
        sys.executable,
        str(manager_script),
        str(repo_root),
        "--port",
        str(args.port),
        "--host",
        args.host,
    ]

    if args.scan_only:
        cmd.append("--scan-only")
    if args.backup:
        cmd.append("--backup")

    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
