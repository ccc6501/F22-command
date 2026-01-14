BootBro Manager (Windows V1)
===========================

What this is
------------
A local, standalone folder manager + QA + backup tool meant to "own" your BootBro/MakerApp/DB folder.
- No cloud calls
- No external dependencies
- Touch-friendly UI (Tkinter)

How to run (Windows)
--------------------
1) Unzip
2) Open PowerShell in the unzipped folder
3) Run:

    python manager.py

(If python isn't found, install Python 3.10+ from python.org and check "Add to PATH".)

Folder expectations (recommended)
---------------------------------
<ROOT>
  apps/
  data/
    sources/
    derived/
    images/
    exports/
  manager/
    reports/
    backups/

What V1 does
------------
- Scans: indexes files (size/mtime + optional sha1 for small files)
- Explains: tells you WHAT changed and WHY it ran the scan
- Staleness check: flags derived outputs older than sources
- Reports: writes JSON + TXT reports into manager/reports
- UID finder: searches UID/part id in text-based files (JSON/CSV/TXT/HTML/JS/YAML)
- Backups: creates timestamped snapshots in manager/backups (no overwrites)

What V1 does NOT do (yet)
-------------------------
- It does not rebuild your derived JSON outputs automatically (it only tells you what is stale).
- It does not scan inside binary formats (PDF/PPTX/XLSX) — planned for V2.

Tip
---
Turn on "Auto-scan" to keep it aware while you're working. It runs ONLY while the window is open.
