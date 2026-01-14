#!/usr/bin/env python3
"""
BootBro Manager (Windows V1)
Local folder manager + QA + backups + UID finder.
- No cloud
- No external deps (Tkinter)
"""

from __future__ import annotations
import os
import json
import shutil
import hashlib
import time
import threading
import queue
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME = "BootBro Manager"
APP_VERSION = "v1.0 (Windows)"

DEFAULT_CONFIG = {
    "root_folder": "",
    "apps_folder": "apps",
    "data_folder": "data",
    "sources_folder": "data/sources",
    "derived_folder": "data/derived",
    "images_folder": "data/images",
    "exports_folder": "data/exports",
    "reports_folder": "manager/reports",
    "backups_folder": "manager/backups",
    "scan_interval_seconds": 15,
    "hash_max_mb": 8,  # sha1 files <= this size
    "include_exts_for_uid_search": [".json", ".csv", ".txt", ".md", ".html", ".js", ".ts", ".yaml", ".yml"],
    "exclude_folders": ["manager/backups", "node_modules", ".git", "__pycache__"],
}

@dataclass
class FileInfo:
    path: str
    size: int
    mtime: float
    sha1: str | None

def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def utc_stamp_folder() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S_UTC")

def safe_rel(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")

def sha1_of_file(path: Path, max_mb: int) -> str | None:
    try:
        size = path.stat().st_size
        if size > max_mb * 1024 * 1024:
            return None
        h = hashlib.sha1()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

def is_excluded(rel_path: str, exclude_folders: list[str]) -> bool:
    rel_path = rel_path.replace("\\", "/")
    for ex in exclude_folders:
        ex = ex.replace("\\", "/").strip("/")
        if rel_path == ex or rel_path.startswith(ex + "/"):
            return True
    return False

def walk_files(root: Path, exclude_folders: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        rel = safe_rel(root, p)
        if is_excluded(rel, exclude_folders):
            continue
        out.append(p)
    return out

class LogBus:
    def __init__(self, ui_queue: "queue.Queue[str]"):
        self.q = ui_queue
    def log(self, msg: str):
        self.q.put(f"{now_stamp()}  {msg}")

class ManagerCore:
    def __init__(self, config: dict, logger: LogBus):
        self.config = config
        self.log = logger.log
        self.root = Path(config.get("root_folder", "")).expanduser().resolve() if config.get("root_folder") else None
        self.last_index: dict[str, FileInfo] = {}
        self.last_scan_summary: dict = {}

    def set_root(self, root_folder: str):
        self.root = Path(root_folder).expanduser().resolve()
        self.config["root_folder"] = str(self.root)

    def ensure_dirs(self):
        if not self.root:
            return
        for key in ["reports_folder", "backups_folder"]:
            p = self.root / self.config[key]
            p.mkdir(parents=True, exist_ok=True)

    def _collect_index(self) -> dict[str, FileInfo]:
        assert self.root
        files = walk_files(self.root, self.config["exclude_folders"])
        idx: dict[str, FileInfo] = {}
        max_mb = int(self.config.get("hash_max_mb", 8))
        for fp in files:
            rel = safe_rel(self.root, fp)
            try:
                st = fp.stat()
                sha1 = sha1_of_file(fp, max_mb)
                idx[rel] = FileInfo(path=rel, size=int(st.st_size), mtime=float(st.st_mtime), sha1=sha1)
            except Exception:
                continue
        return idx

    def diff_index(self, old: dict[str, FileInfo], new: dict[str, FileInfo]) -> dict:
        old_keys = set(old.keys())
        new_keys = set(new.keys())
        added = sorted(new_keys - old_keys)
        removed = sorted(old_keys - new_keys)
        changed = []
        for k in sorted(old_keys & new_keys):
            a, b = old[k], new[k]
            if a.size != b.size or int(a.mtime) != int(b.mtime) or (a.sha1 and b.sha1 and a.sha1 != b.sha1):
                changed.append(k)
        return {"added": added, "removed": removed, "changed": changed}

    def compute_stale_outputs(self) -> dict:
        assert self.root
        sources = (self.root / self.config["sources_folder"]).resolve()
        derived = (self.root / self.config["derived_folder"]).resolve()
        sources_mtime = 0.0
        if sources.exists():
            for p in sources.rglob("*"):
                if p.is_file():
                    try:
                        sources_mtime = max(sources_mtime, p.stat().st_mtime)
                    except Exception:
                        pass
        stale = []
        missing = []
        if derived.exists():
            for p in derived.rglob("*"):
                if p.is_file():
                    try:
                        if p.stat().st_mtime < sources_mtime:
                            stale.append(safe_rel(self.root, p))
                    except Exception:
                        pass
        else:
            missing.append(self.config["derived_folder"])
        return {"sources_latest_mtime": sources_mtime, "stale_outputs": stale, "missing_folders": missing}

    def uid_search(self, uid: str) -> list[dict]:
        assert self.root
        uid = uid.strip()
        if not uid:
            return []
        exts = set([e.lower() for e in self.config.get("include_exts_for_uid_search", [])])
        hits = []
        files = walk_files(self.root, self.config["exclude_folders"])
        for fp in files:
            if fp.suffix.lower() not in exts:
                continue
            rel = safe_rel(self.root, fp)
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore")
                if uid not in text:
                    continue
                count = 0
                for i, line in enumerate(text.splitlines(), start=1):
                    if uid in line:
                        hits.append({"file": rel, "line": i, "context": line.strip()[:280]})
                        count += 1
                        if count >= 25:
                            hits.append({"file": rel, "line": i, "context": "…(more matches truncated)…"})
                            break
            except Exception:
                continue
        return hits

    def make_report(self, diff: dict, stale: dict) -> dict:
        assert self.root
        report = {
            "app": APP_NAME,
            "version": APP_VERSION,
            "generated_at": now_stamp(),
            "root_folder": str(self.root),
            "changes": diff,
            "staleness": {
                "stale_outputs_count": len(stale.get("stale_outputs", [])),
                "stale_outputs": stale.get("stale_outputs", [])[:500],
                "missing_folders": stale.get("missing_folders", []),
                "sources_latest_mtime": stale.get("sources_latest_mtime", 0.0),
            },
            "counts": {
                "total_files_indexed": len(self.last_index),
                "added": len(diff.get("added", [])),
                "removed": len(diff.get("removed", [])),
                "changed": len(diff.get("changed", [])),
            },
        }
        return report

    def write_report_files(self, report: dict) -> tuple[Path, Path]:
        assert self.root
        self.ensure_dirs()
        reports_dir = (self.root / self.config["reports_folder"]).resolve()
        reports_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = reports_dir / f"report_{ts}.json"
        txt_path = reports_dir / f"report_{ts}.txt"
        json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        lines = []
        lines.append(f"{APP_NAME} — {APP_VERSION}")
        lines.append(f"Generated: {report['generated_at']}")
        lines.append(f"Root: {report['root_folder']}")
        lines.append("")
        lines.append("What changed:")
        lines.append(f"  Added:   {report['counts']['added']}")
        lines.append(f"  Removed: {report['counts']['removed']}")
        lines.append(f"  Changed: {report['counts']['changed']}")
        if report["changes"]["added"]:
            lines.append("    + " + "\n    + ".join(report["changes"]["added"][:100]))
        if report["changes"]["removed"]:
            lines.append("    - " + "\n    - ".join(report["changes"]["removed"][:100]))
        if report["changes"]["changed"]:
            lines.append("    * " + "\n    * ".join(report["changes"]["changed"][:150]))
        lines.append("")
        lines.append("Staleness:")
        lines.append(f"  Stale outputs: {report['staleness']['stale_outputs_count']}")
        for s in report["staleness"]["stale_outputs"][:150]:
            lines.append(f"    ! {s}")
        for m in report["staleness"]["missing_folders"]:
            lines.append(f"    ? missing folder: {m}")
        txt_path.write_text("\n".join(lines), encoding="utf-8")
        return json_path, txt_path

    def scan(self) -> dict:
        if not self.root:
            raise RuntimeError("Root folder not set.")
        self.log("🔎 Scan started…")
        start = time.time()
        new_index = self._collect_index()
        diff = self.diff_index(self.last_index, new_index) if self.last_index else {"added": list(new_index.keys()), "removed": [], "changed": []}
        self.last_index = new_index
        stale = self.compute_stale_outputs()
        report = self.make_report(diff, stale)
        self.last_scan_summary = report
        json_path, txt_path = self.write_report_files(report)

        dt = time.time() - start
        self.log(f"✅ Scan complete in {dt:.2f}s — Added {len(diff['added'])}, Changed {len(diff['changed'])}, Removed {len(diff['removed'])}")
        if stale["missing_folders"]:
            self.log(f"⚠️ Missing folders: {', '.join(stale['missing_folders'])}")
        if stale["stale_outputs"]:
            self.log(f"🕒 Stale outputs: {len(stale['stale_outputs'])} (derived older than sources)")
        self.log(f"📄 Report saved: {safe_rel(self.root, json_path)} and {safe_rel(self.root, txt_path)}")
        return report

    def backup(self) -> Path:
        if not self.root:
            raise RuntimeError("Root folder not set.")
        self.ensure_dirs()
        backup_root = (self.root / self.config["backups_folder"]).resolve()
        backup_root.mkdir(parents=True, exist_ok=True)

        stamp = utc_stamp_folder()
        dest = backup_root / f"snapshot_{stamp}"
        self.log(f"📦 Backup started → {safe_rel(self.root, dest)}")
        dest.mkdir(parents=True, exist_ok=True)

        exclude_folders = set([p.replace("\\","/") for p in self.config["exclude_folders"]])
        exclude_folders.add(self.config["backups_folder"].replace("\\","/"))

        for item in ["apps", "data", "manager"]:
            src = (self.root / item)
            if not src.exists():
                continue
            for p in src.rglob("*"):
                if p.is_dir():
                    continue
                rel = safe_rel(self.root, p)
                if any(rel.startswith(ex + "/") or rel == ex for ex in exclude_folders):
                    continue
                outp = dest / rel
                outp.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(p, outp)
                except Exception:
                    pass

        cfg = self.root / "config.yaml"
        if cfg.exists():
            try:
                (dest / "config.yaml").parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cfg, dest / "config.yaml")
            except Exception:
                pass

        self.log("✅ Backup complete.")
        return dest

class AppUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} — {APP_VERSION}")
        self.geometry("1180x760")
        self.minsize(980, 640)

        self.ui_q: queue.Queue[str] = queue.Queue()
        self.logger = LogBus(self.ui_q)
        self.config_data = self._load_config()
        self.core = ManagerCore(self.config_data, self.logger)

        self._build_style()
        self._build_layout()
        self._start_log_pump()

        self._watch_thread = None
        self._watch_stop = threading.Event()
        self._watch_enabled = tk.BooleanVar(value=False)

        if self.config_data.get("root_folder"):
            self._set_root(self.config_data["root_folder"], announce=False)

    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TButton", padding=(14, 10), font=("Segoe UI", 11))
        style.configure("TLabel", font=("Segoe UI", 11))
        style.configure("Header.TLabel", font=("Segoe UI Semibold", 16))
        style.configure("Sub.TLabel", font=("Segoe UI", 10))
        style.configure("TEntry", padding=(10, 8), font=("Segoe UI", 12))
        style.configure("TNotebook.Tab", padding=(14, 8), font=("Segoe UI", 11))
        style.configure("Stat.TLabel", font=("Consolas", 11))

    def _build_layout(self):
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")

        ttk.Label(top, text=APP_NAME, style="Header.TLabel").pack(side="left")
        self.root_lbl = ttk.Label(top, text="Root: (not set)", style="Sub.TLabel")
        self.root_lbl.pack(side="left", padx=18)

        ttk.Button(top, text="Choose Root Folder", command=self.choose_root).pack(side="right")
        ttk.Button(top, text="Save Config", command=self.save_config).pack(side="right", padx=10)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=(0,12))

        self.tab_dash = ttk.Frame(nb)
        self.tab_uid = ttk.Frame(nb)
        self.tab_reports = ttk.Frame(nb)
        self.tab_settings = ttk.Frame(nb)

        nb.add(self.tab_dash, text="Dashboard")
        nb.add(self.tab_uid, text="Part / UID Finder")
        nb.add(self.tab_reports, text="Reports & Backups")
        nb.add(self.tab_settings, text="Settings")

        self._build_dashboard()
        self._build_uid_finder()
        self._build_reports()
        self._build_settings()

        bottom = ttk.Frame(self, padding=(12,0,12,12))
        bottom.pack(fill="both", expand=False)

        ttk.Label(bottom, text="Activity Log", style="Sub.TLabel").pack(anchor="w")

        self.log_text = tk.Text(bottom, height=10, wrap="word", font=("Consolas", 10))
        self.log_text.pack(fill="both", expand=True, pady=(6,0))
        self.log_text.configure(state="disabled")

    def _build_dashboard(self):
        frame = ttk.Frame(self.tab_dash, padding=14)
        frame.pack(fill="both", expand=True)

        stats = ttk.Frame(frame)
        stats.pack(fill="x")

        self.stat_files = ttk.Label(stats, text="Files: —", style="Stat.TLabel")
        self.stat_files.pack(side="left", padx=(0,18))
        self.stat_changes = ttk.Label(stats, text="Changes: —", style="Stat.TLabel")
        self.stat_changes.pack(side="left", padx=(0,18))
        self.stat_stale = ttk.Label(stats, text="Stale outputs: —", style="Stat.TLabel")
        self.stat_stale.pack(side="left", padx=(0,18))
        self.stat_last = ttk.Label(stats, text="Last scan: —", style="Stat.TLabel")
        self.stat_last.pack(side="left")

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(16, 8))

        ttk.Button(btns, text="Run Scan Now", command=self.run_scan).pack(side="left")
        ttk.Button(btns, text="Backup Now", command=self.run_backup).pack(side="left", padx=10)

        ttk.Checkbutton(btns, text="Auto-scan while app is open", variable=self._watch_enabled, command=self.toggle_watcher)\
            .pack(side="left", padx=20)

        self.reason_box = tk.Text(frame, height=14, wrap="word", font=("Segoe UI", 11))
        self.reason_box.pack(fill="both", expand=True, pady=(12,0))
        self.reason_box.insert("1.0", "Why things happen will show here after scans (ex: source changed → derived stale → report generated).")
        self.reason_box.configure(state="disabled")

    def _build_uid_finder(self):
        frame = ttk.Frame(self.tab_uid, padding=14)
        frame.pack(fill="both", expand=True)

        row = ttk.Frame(frame)
        row.pack(fill="x")

        ttk.Label(row, text="UID / Part ID:").pack(side="left")
        self.uid_entry = ttk.Entry(row, width=40)
        self.uid_entry.pack(side="left", padx=10)
        ttk.Button(row, text="Search", command=self.do_uid_search).pack(side="left")

        ttk.Label(frame, text="Searches JSON/CSV/TXT/HTML/JS/YAML in root (fast). Skips binary formats in V1.", style="Sub.TLabel")\
            .pack(anchor="w", pady=(10,0))

        self.uid_results = tk.Text(frame, wrap="word", font=("Consolas", 10))
        self.uid_results.pack(fill="both", expand=True, pady=(10,0))
        self.uid_results.configure(state="disabled")

    def _build_reports(self):
        frame = ttk.Frame(self.tab_reports, padding=14)
        frame.pack(fill="both", expand=True)

        top = ttk.Frame(frame)
        top.pack(fill="x")

        ttk.Button(top, text="Open Reports Folder", command=lambda: self.open_folder("reports_folder")).pack(side="left")
        ttk.Button(top, text="Open Backups Folder", command=lambda: self.open_folder("backups_folder")).pack(side="left", padx=10)
        ttk.Button(top, text="Copy Last Report Path", command=self.copy_last_report_path).pack(side="left", padx=10)

        self.rep_box = tk.Text(frame, wrap="word", font=("Consolas", 10))
        self.rep_box.pack(fill="both", expand=True, pady=(12,0))
        self.rep_box.configure(state="disabled")

    def _build_settings(self):
        frame = ttk.Frame(self.tab_settings, padding=14)
        frame.pack(fill="both", expand=True)

        self.settings_entries = {}
        def add_row(label, key):
            r = ttk.Frame(frame); r.pack(fill="x", pady=6)
            ttk.Label(r, text=label, width=28).pack(side="left")
            e = ttk.Entry(r, width=60)
            e.insert(0, str(self.config_data.get(key, DEFAULT_CONFIG.get(key, ""))))
            e.pack(side="left", padx=10, fill="x", expand=True)
            self.settings_entries[key] = e

        add_row("Apps folder (relative):", "apps_folder")
        add_row("Sources folder (relative):", "sources_folder")
        add_row("Derived folder (relative):", "derived_folder")
        add_row("Reports folder (relative):", "reports_folder")
        add_row("Backups folder (relative):", "backups_folder")
        add_row("Scan interval (seconds):", "scan_interval_seconds")
        add_row("Hash files up to (MB):", "hash_max_mb")

        ttk.Label(frame, text="V1 watcher runs only while this window is open (not a Windows service).", style="Sub.TLabel")\
            .pack(anchor="w", pady=(14,0))

    def _config_path(self) -> Path:
        try:
            here = Path(__file__).resolve().parent
        except Exception:
            here = Path.cwd()
        return here / "config.yaml"

    def _load_config(self) -> dict:
        cfg = DEFAULT_CONFIG.copy()
        path = self._config_path()
        if not path.exists():
            return cfg
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            for ln in lines:
                ln = ln.strip()
                if not ln or ln.startswith("#") or ":" not in ln:
                    continue
                k, v = ln.split(":", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k in cfg:
                    if isinstance(cfg[k], bool):
                        cfg[k] = v.lower() in ("1","true","yes","on")
                    elif isinstance(cfg[k], int):
                        try: cfg[k] = int(v)
                        except Exception: pass
                    else:
                        cfg[k] = v
            return cfg
        except Exception:
            return cfg

    def save_config(self):
        for k, entry in self.settings_entries.items():
            val = entry.get().strip()
            if k in ("scan_interval_seconds", "hash_max_mb"):
                try: self.config_data[k] = int(val)
                except Exception: pass
            else:
                self.config_data[k] = val
        if self.core.root:
            self.config_data["root_folder"] = str(self.core.root)

        path = self._config_path()
        lines = ["# BootBro Manager config (simple key: value)"]
        for k, v in self.config_data.items():
            if isinstance(v, (list, dict)):  # keep config minimal
                continue
            lines.append(f"{k}: {v}")
        try:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.logger.log(f"💾 Config saved: {path}")
            messagebox.showinfo(APP_NAME, f"Saved config to:\n{path}")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Failed to save config:\n{e}")

    def choose_root(self):
        folder = filedialog.askdirectory(title="Choose your BootBro / MakerApp / DB root folder")
        if folder:
            self._set_root(folder, announce=True)

    def _set_root(self, folder: str, announce: bool = True):
        self.core.set_root(folder)
        self.root_lbl.configure(text=f"Root: {folder}")
        self.core.ensure_dirs()
        if announce:
            self.logger.log(f"📁 Root set: {folder}")

    def run_scan(self):
        if not self.core.root:
            messagebox.showwarning(APP_NAME, "Choose a root folder first.")
            return
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        try:
            prev = self.core.last_scan_summary
            report = self.core.scan()
            self._update_stats(report)
            self._set_reason_text(self._build_reason_text(prev, report))
            self._update_reports_box(report)
        except Exception as e:
            self.logger.log(f"❌ Scan error: {e}")

    def run_backup(self):
        if not self.core.root:
            messagebox.showwarning(APP_NAME, "Choose a root folder first.")
            return
        threading.Thread(target=self._backup_worker, daemon=True).start()

    def _backup_worker(self):
        try:
            dest = self.core.backup()
            self.logger.log(f"📦 Snapshot ready: {dest}")
            self._append_reports(f"\nBackup created: {dest}\n")
        except Exception as e:
            self.logger.log(f"❌ Backup error: {e}")

    def do_uid_search(self):
        if not self.core.root:
            messagebox.showwarning(APP_NAME, "Choose a root folder first.")
            return
        uid = self.uid_entry.get().strip()
        if not uid:
            return
        self._set_uid_results("Searching…")
        threading.Thread(target=self._uid_worker, args=(uid,), daemon=True).start()

    def _uid_worker(self, uid: str):
        try:
            hits = self.core.uid_search(uid)
            if not hits:
                self._set_uid_results(f"No hits found for: {uid}\n\nTip: V1 searches text-based files only (JSON/CSV/TXT/HTML/JS).")
                return
            lines = [f"Hits for: {uid}", ""]
            for h in hits[:500]:
                lines.append(f"{h['file']}  (line {h['line']})")
                lines.append(f"  {h['context']}")
                lines.append("")
            self._set_uid_results("\n".join(lines))
        except Exception as e:
            self._set_uid_results(f"Error: {e}")

    def toggle_watcher(self):
        if self._watch_enabled.get():
            if not self.core.root:
                messagebox.showwarning(APP_NAME, "Choose a root folder first.")
                self._watch_enabled.set(False)
                return
            self._watch_stop.clear()
            self._watch_thread = threading.Thread(target=self._watch_loop, daemon=True)
            self._watch_thread.start()
            self.logger.log("🛰️ Auto-scan enabled (runs while app is open).")
        else:
            self._watch_stop.set()
            self.logger.log("🛑 Auto-scan disabled.")

    def _watch_loop(self):
        interval = int(self.config_data.get("scan_interval_seconds", 15))
        last_state = {}
        while not self._watch_stop.is_set():
            try:
                root = self.core.root
                if not root:
                    break
                files = walk_files(root, self.config_data["exclude_folders"])
                cur = {}
                for p in files:
                    try:
                        rel = safe_rel(root, p)
                        st = p.stat()
                        cur[rel] = (int(st.st_mtime), int(st.st_size))
                    except Exception:
                        pass
                if last_state and cur != last_state:
                    self.logger.log("🔔 Change detected — running scan (reason: file set changed or file updated).")
                    self._scan_worker()
                last_state = cur
            except Exception as e:
                self.logger.log(f"Watcher error: {e}")
            for _ in range(max(1, interval)):
                if self._watch_stop.is_set():
                    break
                time.sleep(1)

    def _start_log_pump(self):
        def pump():
            try:
                while True:
                    msg = self.ui_q.get_nowait()
                    self._append_log(msg + "\n")
            except queue.Empty:
                pass
            self.after(150, pump)
        pump()

    def _append_log(self, text: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_reason_text(self, text: str):
        def do():
            self.reason_box.configure(state="normal")
            self.reason_box.delete("1.0", "end")
            self.reason_box.insert("1.0", text)
            self.reason_box.configure(state="disabled")
        self.after(0, do)

    def _set_uid_results(self, text: str):
        def do():
            self.uid_results.configure(state="normal")
            self.uid_results.delete("1.0", "end")
            self.uid_results.insert("1.0", text)
            self.uid_results.configure(state="disabled")
        self.after(0, do)

    def _append_reports(self, text: str):
        def do():
            self.rep_box.configure(state="normal")
            self.rep_box.insert("end", text)
            self.rep_box.see("end")
            self.rep_box.configure(state="disabled")
        self.after(0, do)

    def _update_reports_box(self, report: dict):
        lines = []
        lines.append(f"{APP_NAME} — {APP_VERSION}")
        lines.append(f"Generated: {report.get('generated_at','—')}")
        lines.append(f"Files indexed: {report.get('counts',{}).get('total_files_indexed','—')}")
        lines.append(f"Added: {report.get('counts',{}).get('added','—')} | Changed: {report.get('counts',{}).get('changed','—')} | Removed: {report.get('counts',{}).get('removed','—')}")
        lines.append(f"Stale outputs: {report.get('staleness',{}).get('stale_outputs_count','—')}")
        lines.append("")
        lines.append("Top stale outputs (first 20):")
        for s in report.get("staleness", {}).get("stale_outputs", [])[:20]:
            lines.append(f"  ! {s}")
        self._append_reports("\n".join(lines) + "\n\n")

    def _update_stats(self, report: dict):
        def do():
            self.stat_files.configure(text=f"Files: {report.get('counts',{}).get('total_files_indexed','—')}")
            self.stat_changes.configure(text=f"Changes: +{report.get('counts',{}).get('added','—')}  *{report.get('counts',{}).get('changed','—')}  -{report.get('counts',{}).get('removed','—')}")
            self.stat_stale.configure(text=f"Stale outputs: {report.get('staleness',{}).get('stale_outputs_count','—')}")
            self.stat_last.configure(text=f"Last scan: {report.get('generated_at','—')}")
        self.after(0, do)

    def _build_reason_text(self, prev: dict, cur: dict) -> str:
        lines = []
        lines.append("What the manager did (and why):\n")
        c = cur.get("changes", {})
        s = cur.get("staleness", {})
        lines.append(f"• Scanned the root folder and indexed {cur.get('counts',{}).get('total_files_indexed','?')} files.")
        if c.get("added") or c.get("removed") or c.get("changed"):
            if c.get("added"): lines.append(f"• Detected {len(c['added'])} new file(s).")
            if c.get("changed"): lines.append(f"• Detected {len(c['changed'])} modified file(s).")
            if c.get("removed"): lines.append(f"• Detected {len(c['removed'])} deleted file(s).")
        else:
            lines.append("• No file changes detected since the last scan.")
        lines.append("")
        stale_count = int(s.get("stale_outputs_count", 0))
        if stale_count > 0:
            lines.append(f"• Found {stale_count} stale derived output(s).")
            lines.append("  Reason: at least one file in data/sources is newer than those derived files.")
            lines.append("  Action taken: report generated listing stale outputs (so you know what needs refresh).")
        else:
            lines.append("• Derived outputs look fresh relative to sources.")
        if s.get("missing_folders"):
            lines.append("\n• Missing expected folders:")
            for m in s["missing_folders"]:
                lines.append(f"  - {m}")
        lines.append("\nWhere things were saved:")
        lines.append(f"• Reports → {self.config_data.get('reports_folder')}")
        lines.append(f"• Backups → {self.config_data.get('backups_folder')}")
        lines.append("\nNotes:")
        lines.append("• V1 does not auto-rebuild derived JSONs (it only flags staleness).")
        lines.append("• V1 UID search scans text-based files only.")
        lines.append("• Auto-scan runs only while this app is open.")
        return "\n".join(lines)

    def open_folder(self, config_key: str):
        if not self.core.root:
            return
        target = (self.core.root / self.config_data.get(config_key, "")).resolve()
        target.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(target))  # Windows
        except Exception:
            messagebox.showinfo(APP_NAME, f"Folder:\n{target}")

    def copy_last_report_path(self):
        if not self.core.root:
            return
        reports_dir = (self.core.root / self.config_data["reports_folder"]).resolve()
        if not reports_dir.exists():
            messagebox.showinfo(APP_NAME, "No reports folder yet.")
            return
        items = sorted(reports_dir.glob("report_*.json"))
        if not items:
            messagebox.showinfo(APP_NAME, "No report files yet.")
            return
        last = items[-1]
        self.clipboard_clear()
        self.clipboard_append(str(last))
        self.logger.log(f"📋 Copied path: {last}")

def main():
    app = AppUI()
    app.mainloop()

if __name__ == "__main__":
    main()
