"""Convenience wrapper.

This repo's manager lives in `tools/f22_data_manager.py`.
This file exists so that running from repo root works:

    python f22_data_manager.py

On Windows PowerShell, use `run_manager.ps1` for the best experience.
"""

from tools.f22_data_manager import main


if __name__ == "__main__":
    raise SystemExit(main())
