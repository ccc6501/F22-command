#!/usr/bin/env python3
"""
F-22 Data System Manager
========================
Central orchestrator for all F-22 Raptor data operations.

Core responsibilities:
- Data ingest, validation, and versioning
- Master registry with UID tracking and lineage
- Local HTTP server for app hosting and API
- 3D measurement data management (UV coords, touch masks, spatial)
- Self-monitoring with health checks and auto-recovery
- Build pipeline for derived data regeneration

No external dependencies beyond Python 3.10+ standard library.
"""

from __future__ import annotations

import os
import sys
import json
import hashlib
import shutil
import sqlite3
import threading
import time
import mimetypes
import traceback
import urllib.parse
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum, auto
from functools import wraps
from http.server import HTTPServer, SimpleHTTPRequestHandler
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar, Generic
from collections import defaultdict
import logging
import queue
import signal
import socketserver

# =============================================================================
# CHECKS / VALIDATION
# =============================================================================

class CheckStatus(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"

@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    summary: str
    details: dict = field(default_factory=dict)
    checked_at: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "summary": self.summary,
            "details": self.details,
            "checked_at": self.checked_at,
        }

# =============================================================================
# CONFIGURATION
# =============================================================================

APP_NAME = "F-22 Data System Manager"
APP_VERSION = "2.0.0"
DEFAULT_PORT = 8022  # F-22 themed port

DEFAULT_CONFIG = {
    "root_folder": "",
    "port": DEFAULT_PORT,
    "host": "127.0.0.1",
    
    # Folder structure
    # In this repo, browser apps live under `web/`
    "apps_folder": "web",
    "data_folder": "data",
    "sources_folder": "data/sources",
    # Keep "derived" aligned with exports for a simple mental model.
    "derived_folder": "data/exports",
    "models_folder": "data/models",
    "measurements_folder": "data/measurements",
    "touch_masks_folder": "data/touch_masks",
    # Generated artifacts (PNGs/JSON exports written by tools)
    "outputs_folder": "outputs",
    "exports_folder": "data/exports",
    "inbox_folder": "data/inbox",
    "schemas_folder": "schemas",
    "manager_folder": "manager",
    "reports_folder": "manager/reports",
    "backups_folder": "manager/backups",
    "logs_folder": "manager/logs",
    "db_path": "manager/f22_registry.db",
    
    # Behavior
    "scan_interval_seconds": 10,
    "health_check_interval_seconds": 30,
    "hash_max_mb": 50,
    "auto_rebuild_derived": True,
    "enable_spatial_index": True,
    
    # File handling
    "source_extensions": [".json", ".csv", ".yaml", ".yml", ".xml", ".glb", ".gltf", ".obj", ".fbx"],
    "text_extensions": [".json", ".csv", ".txt", ".md", ".html", ".js", ".ts", ".css", ".yaml", ".yml", ".xml"],
    "model_extensions": [".glb", ".gltf", ".obj", ".fbx", ".stl"],
    "image_extensions": [".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"],
    "exclude_folders": ["node_modules", ".git", "__pycache__", "manager/backups"],
}

# =============================================================================
# LOGGING SETUP
# =============================================================================

class LogLevel(Enum):
    DEBUG = auto()
    INFO = auto()
    WARNING = auto()
    ERROR = auto()
    CRITICAL = auto()

@dataclass
class LogEntry:
    timestamp: str
    level: LogLevel
    component: str
    message: str
    data: Optional[dict] = None

class SystemLogger:
    """Thread-safe logging with multiple outputs."""
    
    def __init__(self, log_dir: Optional[Path] = None):
        self.log_dir = log_dir
        self.entries: list[LogEntry] = []
        self.subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._file_handle = None
        
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"f22_manager_{datetime.now().strftime('%Y%m%d')}.log"
            self._file_handle = open(log_file, "a", encoding="utf-8")
    
    def _emit(self, level: LogLevel, component: str, message: str, data: Optional[dict] = None):
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = LogEntry(timestamp=timestamp, level=level, component=component, message=message, data=data)
        
        with self._lock:
            self.entries.append(entry)
            # Keep last 10000 entries in memory
            if len(self.entries) > 10000:
                self.entries = self.entries[-5000:]
            
            # Write to file
            if self._file_handle:
                line = f"[{timestamp}] [{level.name}] [{component}] {message}"
                if data:
                    line += f" | {json.dumps(data)}"
                self._file_handle.write(line + "\n")
                self._file_handle.flush()
            
            # Notify subscribers
            for q in self.subscribers:
                try:
                    q.put_nowait(entry)
                except queue.Full:
                    pass
        
        # Console output (be careful: Windows consoles may use cp1252 and choke on emoji)
        level_icons = {
            LogLevel.DEBUG: "🔍",
            LogLevel.INFO: "ℹ️ ",
            LogLevel.WARNING: "⚠️ ",
            LogLevel.ERROR: "❌",
            LogLevel.CRITICAL: "🔥",
        }
        icon = level_icons.get(level, "")
        try:
            enc = (getattr(sys.stdout, "encoding", None) or "").lower()
            if "utf" not in enc:
                icon = ""
            print(f"{icon} [{component}] {message}".strip())
        except UnicodeEncodeError:
            # Last resort: no icon
            print(f"[{component}] {message}")
    
    def debug(self, component: str, message: str, data: Optional[dict] = None):
        self._emit(LogLevel.DEBUG, component, message, data)
    
    def info(self, component: str, message: str, data: Optional[dict] = None):
        self._emit(LogLevel.INFO, component, message, data)
    
    def warning(self, component: str, message: str, data: Optional[dict] = None):
        self._emit(LogLevel.WARNING, component, message, data)
    
    def error(self, component: str, message: str, data: Optional[dict] = None):
        self._emit(LogLevel.ERROR, component, message, data)
    
    def critical(self, component: str, message: str, data: Optional[dict] = None):
        self._emit(LogLevel.CRITICAL, component, message, data)
    
    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self.subscribers.append(q)
        return q
    
    def get_recent(self, count: int = 100, level: Optional[LogLevel] = None) -> list[LogEntry]:
        with self._lock:
            entries = self.entries[-count:] if not level else [e for e in self.entries if e.level == level][-count:]
            return list(entries)
    
    def close(self):
        if self._file_handle:
            self._file_handle.close()

# Global logger instance
logger = SystemLogger()

# =============================================================================
# DATA TYPES
# =============================================================================

class DataStatus(Enum):
    VALID = "valid"
    STALE = "stale"
    INVALID = "invalid"
    MISSING = "missing"
    PROCESSING = "processing"

class DataCategory(Enum):
    SOURCE = "source"
    DERIVED = "derived"
    MODEL = "model"
    MEASUREMENT = "measurement"
    TOUCH_MASK = "touch_mask"
    EXPORT = "export"
    OUTPUT = "output"
    APP = "app"
    SCHEMA = "schema"

@dataclass
class DataRecord:
    """A tracked piece of data in the system."""
    uid: str
    path: str
    category: DataCategory
    status: DataStatus
    size: int
    hash_sha256: str
    created_at: str
    modified_at: str
    version: int = 1
    parent_uids: list[str] = field(default_factory=list)  # Lineage - what this was derived from
    child_uids: list[str] = field(default_factory=list)   # What depends on this
    metadata: dict = field(default_factory=dict)
    schema_uid: Optional[str] = None
    
    def to_dict(self) -> dict:
        d = asdict(self)
        d['category'] = self.category.value
        d['status'] = self.status.value
        return d
    
    @classmethod
    def from_dict(cls, d: dict) -> 'DataRecord':
        d = d.copy()
        d['category'] = DataCategory(d['category'])
        d['status'] = DataStatus(d['status'])
        return cls(**d)

@dataclass
class MeasurementPoint:
    """A 3D measurement point with UV mapping."""
    uid: str
    component_uid: str
    label: str
    x: float
    y: float
    z: float
    u: Optional[float] = None  # UV coordinate
    v: Optional[float] = None
    normal_x: Optional[float] = None
    normal_y: Optional[float] = None
    normal_z: Optional[float] = None
    metadata: dict = field(default_factory=dict)

@dataclass
class TouchZone:
    """A touchable region mapped to a component."""
    uid: str
    component_uid: str
    label: str
    color_hex: str  # Color code for identification
    vertices: list[tuple[float, float]]  # 2D polygon in UV/screen space
    center_x: float
    center_y: float
    area: float
    metadata: dict = field(default_factory=dict)

@dataclass 
class HealthStatus:
    """System health snapshot."""
    timestamp: str
    overall: str  # "healthy", "degraded", "critical"
    components: dict[str, dict]
    disk_free_mb: int
    memory_used_percent: float
    active_connections: int
    pending_rebuilds: int
    errors_last_hour: int

# =============================================================================
# DATABASE / REGISTRY
# =============================================================================

class DataRegistry:
    """
    SQLite-backed registry for all data in the system.
    Single source of truth for UIDs, lineage, and relationships.
    """
    
    def __init__(self, db_path: Path, logger: SystemLogger):
        self.db_path = db_path
        self.logger = logger
        self._lock = threading.Lock()
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                -- Main data records
                CREATE TABLE IF NOT EXISTS data_records (
                    uid TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    category TEXT NOT NULL,
                    status TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    hash_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    modified_at TEXT NOT NULL,
                    version INTEGER DEFAULT 1,
                    metadata TEXT DEFAULT '{}',
                    schema_uid TEXT
                );
                
                CREATE INDEX IF NOT EXISTS idx_records_path ON data_records(path);
                CREATE INDEX IF NOT EXISTS idx_records_category ON data_records(category);
                CREATE INDEX IF NOT EXISTS idx_records_status ON data_records(status);
                
                -- Lineage relationships (parent -> child)
                CREATE TABLE IF NOT EXISTS lineage (
                    parent_uid TEXT NOT NULL,
                    child_uid TEXT NOT NULL,
                    relationship TEXT DEFAULT 'derived_from',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (parent_uid, child_uid),
                    FOREIGN KEY (parent_uid) REFERENCES data_records(uid),
                    FOREIGN KEY (child_uid) REFERENCES data_records(uid)
                );
                
                CREATE INDEX IF NOT EXISTS idx_lineage_parent ON lineage(parent_uid);
                CREATE INDEX IF NOT EXISTS idx_lineage_child ON lineage(child_uid);
                
                -- 3D Measurement points
                CREATE TABLE IF NOT EXISTS measurements (
                    uid TEXT PRIMARY KEY,
                    component_uid TEXT NOT NULL,
                    label TEXT NOT NULL,
                    x REAL NOT NULL,
                    y REAL NOT NULL,
                    z REAL NOT NULL,
                    u REAL,
                    v REAL,
                    normal_x REAL,
                    normal_y REAL,
                    normal_z REAL,
                    metadata TEXT DEFAULT '{}'
                );
                
                CREATE INDEX IF NOT EXISTS idx_measurements_component ON measurements(component_uid);
                
                -- Touch zones
                CREATE TABLE IF NOT EXISTS touch_zones (
                    uid TEXT PRIMARY KEY,
                    component_uid TEXT NOT NULL,
                    label TEXT NOT NULL,
                    color_hex TEXT NOT NULL,
                    vertices TEXT NOT NULL,
                    center_x REAL NOT NULL,
                    center_y REAL NOT NULL,
                    area REAL NOT NULL,
                    metadata TEXT DEFAULT '{}'
                );
                
                CREATE INDEX IF NOT EXISTS idx_touch_zones_component ON touch_zones(component_uid);
                CREATE INDEX IF NOT EXISTS idx_touch_zones_color ON touch_zones(color_hex);
                
                -- Schemas for data validation
                CREATE TABLE IF NOT EXISTS schemas (
                    uid TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    schema_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                
                -- Audit log
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_uid TEXT,
                    actor TEXT DEFAULT 'system',
                    details TEXT DEFAULT '{}'
                );
                
                CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
                CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_log(target_uid);
                
                -- Build queue for derived data
                CREATE TABLE IF NOT EXISTS build_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_uid TEXT NOT NULL,
                    target_path TEXT NOT NULL,
                    builder_name TEXT NOT NULL,
                    priority INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    error_message TEXT
                );
                
                CREATE INDEX IF NOT EXISTS idx_build_status ON build_queue(status);
            """)
            conn.commit()
        
        self.logger.info("Registry", "Database initialized", {"path": str(self.db_path)})
    
    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
    
    def generate_uid(self, prefix: str = "data") -> str:
        """Generate a unique identifier."""
        import uuid
        return f"{prefix}_{uuid.uuid4().hex[:12]}"
    
    # --- Data Records ---
    
    def register(self, record: DataRecord) -> DataRecord:
        """Register or update a data record."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO data_records 
                    (uid, path, category, status, size, hash_sha256, created_at, modified_at, version, metadata, schema_uid)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record.uid, record.path, record.category.value, record.status.value,
                    record.size, record.hash_sha256, record.created_at, record.modified_at,
                    record.version, json.dumps(record.metadata), record.schema_uid
                ))
                
                # Update lineage
                conn.execute("DELETE FROM lineage WHERE child_uid = ?", (record.uid,))
                for parent_uid in record.parent_uids:
                    conn.execute("""
                        INSERT OR IGNORE INTO lineage (parent_uid, child_uid, created_at)
                        VALUES (?, ?, ?)
                    """, (parent_uid, record.uid, self._now()))
                
                conn.commit()
        
        self._audit("register", record.uid, {"path": record.path, "category": record.category.value})
        return record
    
    def get(self, uid: str) -> Optional[DataRecord]:
        """Get a data record by UID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM data_records WHERE uid = ?", (uid,)).fetchone()
            if not row:
                return None
            
            # Get lineage
            parents = [r[0] for r in conn.execute(
                "SELECT parent_uid FROM lineage WHERE child_uid = ?", (uid,)
            ).fetchall()]
            children = [r[0] for r in conn.execute(
                "SELECT child_uid FROM lineage WHERE parent_uid = ?", (uid,)
            ).fetchall()]
            
            return DataRecord(
                uid=row['uid'],
                path=row['path'],
                category=DataCategory(row['category']),
                status=DataStatus(row['status']),
                size=row['size'],
                hash_sha256=row['hash_sha256'],
                created_at=row['created_at'],
                modified_at=row['modified_at'],
                version=row['version'],
                parent_uids=parents,
                child_uids=children,
                metadata=json.loads(row['metadata'] or '{}'),
                schema_uid=row['schema_uid']
            )
    
    def get_by_path(self, path: str) -> Optional[DataRecord]:
        """Get a data record by file path."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT uid FROM data_records WHERE path = ?", (path,)).fetchone()
            if row:
                return self.get(row[0])
        return None
    
    def query(self, category: Optional[DataCategory] = None, status: Optional[DataStatus] = None,
              path_prefix: Optional[str] = None, limit: int = 1000) -> list[DataRecord]:
        """Query data records with filters."""
        conditions = []
        params = []
        
        if category:
            conditions.append("category = ?")
            params.append(category.value)
        if status:
            conditions.append("status = ?")
            params.append(status.value)
        if path_prefix:
            conditions.append("path LIKE ?")
            params.append(f"{path_prefix}%")
        
        where = " AND ".join(conditions) if conditions else "1=1"
        
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT uid FROM data_records WHERE {where} LIMIT ?",
                params + [limit]
            ).fetchall()
        
        return [self.get(row[0]) for row in rows if self.get(row[0])]
    
    def get_stale_derived(self) -> list[DataRecord]:
        """Get all derived records that are stale."""
        return self.query(category=DataCategory.DERIVED, status=DataStatus.STALE)
    
    def mark_stale(self, uid: str):
        """Mark a record and all its descendants as stale."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                # Mark this record stale
                conn.execute(
                    "UPDATE data_records SET status = ? WHERE uid = ?",
                    (DataStatus.STALE.value, uid)
                )
                
                # Get all descendants and mark them stale too
                descendants = self._get_descendants(conn, uid)
                for desc_uid in descendants:
                    conn.execute(
                        "UPDATE data_records SET status = ? WHERE uid = ?",
                        (DataStatus.STALE.value, desc_uid)
                    )
                
                conn.commit()
        
        self._audit("mark_stale", uid, {"descendants": len(descendants) if 'descendants' in dir() else 0})
    
    def _get_descendants(self, conn, uid: str) -> list[str]:
        """Recursively get all descendants of a record."""
        descendants = []
        children = [r[0] for r in conn.execute(
            "SELECT child_uid FROM lineage WHERE parent_uid = ?", (uid,)
        ).fetchall()]
        
        for child in children:
            descendants.append(child)
            descendants.extend(self._get_descendants(conn, child))
        
        return descendants
    
    def delete(self, uid: str):
        """Delete a data record."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM lineage WHERE parent_uid = ? OR child_uid = ?", (uid, uid))
                conn.execute("DELETE FROM data_records WHERE uid = ?", (uid,))
                conn.commit()
        
        self._audit("delete", uid)
    
    # --- Measurements ---
    
    def add_measurement(self, point: MeasurementPoint):
        """Add or update a measurement point."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO measurements
                    (uid, component_uid, label, x, y, z, u, v, normal_x, normal_y, normal_z, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    point.uid, point.component_uid, point.label,
                    point.x, point.y, point.z, point.u, point.v,
                    point.normal_x, point.normal_y, point.normal_z,
                    json.dumps(point.metadata)
                ))
                conn.commit()
    
    def get_measurements(self, component_uid: Optional[str] = None) -> list[MeasurementPoint]:
        """Get measurement points, optionally filtered by component."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if component_uid:
                rows = conn.execute(
                    "SELECT * FROM measurements WHERE component_uid = ?", (component_uid,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM measurements").fetchall()
        
        return [MeasurementPoint(
            uid=r['uid'], component_uid=r['component_uid'], label=r['label'],
            x=r['x'], y=r['y'], z=r['z'], u=r['u'], v=r['v'],
            normal_x=r['normal_x'], normal_y=r['normal_y'], normal_z=r['normal_z'],
            metadata=json.loads(r['metadata'] or '{}')
        ) for r in rows]
    
    def query_spatial(self, x: float, y: float, z: float, radius: float) -> list[MeasurementPoint]:
        """Find measurement points within radius of a 3D point."""
        # Simple brute force for now - could be optimized with R-tree
        all_points = self.get_measurements()
        results = []
        for p in all_points:
            dist = ((p.x - x)**2 + (p.y - y)**2 + (p.z - z)**2) ** 0.5
            if dist <= radius:
                results.append(p)
        return results
    
    # --- Touch Zones ---
    
    def add_touch_zone(self, zone: TouchZone):
        """Add or update a touch zone."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO touch_zones
                    (uid, component_uid, label, color_hex, vertices, center_x, center_y, area, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    zone.uid, zone.component_uid, zone.label, zone.color_hex,
                    json.dumps(zone.vertices), zone.center_x, zone.center_y, zone.area,
                    json.dumps(zone.metadata)
                ))
                conn.commit()
    
    def get_touch_zone_by_color(self, color_hex: str) -> Optional[TouchZone]:
        """Look up a touch zone by its color code."""
        color_hex = color_hex.upper().replace("#", "")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM touch_zones WHERE UPPER(REPLACE(color_hex, '#', '')) = ?",
                (color_hex,)
            ).fetchone()
        
        if not row:
            return None
        
        return TouchZone(
            uid=row['uid'], component_uid=row['component_uid'], label=row['label'],
            color_hex=row['color_hex'], vertices=json.loads(row['vertices']),
            center_x=row['center_x'], center_y=row['center_y'], area=row['area'],
            metadata=json.loads(row['metadata'] or '{}')
        )
    
    def get_touch_zones(self, component_uid: Optional[str] = None) -> list[TouchZone]:
        """Get all touch zones, optionally filtered by component."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if component_uid:
                rows = conn.execute(
                    "SELECT * FROM touch_zones WHERE component_uid = ?", (component_uid,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM touch_zones").fetchall()
        
        return [TouchZone(
            uid=r['uid'], component_uid=r['component_uid'], label=r['label'],
            color_hex=r['color_hex'], vertices=json.loads(r['vertices']),
            center_x=r['center_x'], center_y=r['center_y'], area=r['area'],
            metadata=json.loads(r['metadata'] or '{}')
        ) for r in rows]
    
    # --- Build Queue ---
    
    def queue_build(self, source_uid: str, target_path: str, builder_name: str, priority: int = 0):
        """Add a build job to the queue."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO build_queue (source_uid, target_path, builder_name, priority, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (source_uid, target_path, builder_name, priority, self._now()))
                conn.commit()
    
    def get_pending_builds(self) -> list[dict]:
        """Get all pending build jobs."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM build_queue WHERE status = 'pending' ORDER BY priority DESC, created_at ASC"
            ).fetchall()
        return [dict(r) for r in rows]
    
    def update_build_status(self, build_id: int, status: str, error: Optional[str] = None):
        """Update build job status."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                if status == "running":
                    conn.execute(
                        "UPDATE build_queue SET status = ?, started_at = ? WHERE id = ?",
                        (status, self._now(), build_id)
                    )
                elif status in ("completed", "failed"):
                    conn.execute(
                        "UPDATE build_queue SET status = ?, completed_at = ?, error_message = ? WHERE id = ?",
                        (status, self._now(), error, build_id)
                    )
                else:
                    conn.execute(
                        "UPDATE build_queue SET status = ? WHERE id = ?",
                        (status, build_id)
                    )
                conn.commit()
    
    # --- Audit ---
    
    def _audit(self, action: str, target_uid: Optional[str] = None, details: Optional[dict] = None):
        """Log an audit entry."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO audit_log (timestamp, action, target_uid, details)
                VALUES (?, ?, ?, ?)
            """, (self._now(), action, target_uid, json.dumps(details or {})))
            conn.commit()
    
    def get_audit_log(self, limit: int = 100, target_uid: Optional[str] = None) -> list[dict]:
        """Get audit log entries."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if target_uid:
                rows = conn.execute(
                    "SELECT * FROM audit_log WHERE target_uid = ? ORDER BY timestamp DESC LIMIT ?",
                    (target_uid, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?",
                    (limit,)
                ).fetchall()
        return [dict(r) for r in rows]
    
    # --- Stats ---
    
    def get_stats(self) -> dict:
        """Get registry statistics."""
        with sqlite3.connect(self.db_path) as conn:
            stats = {
                "total_records": conn.execute("SELECT COUNT(*) FROM data_records").fetchone()[0],
                "by_category": {},
                "by_status": {},
                "total_measurements": conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0],
                "total_touch_zones": conn.execute("SELECT COUNT(*) FROM touch_zones").fetchone()[0],
                "pending_builds": conn.execute("SELECT COUNT(*) FROM build_queue WHERE status = 'pending'").fetchone()[0],
            }
            
            for row in conn.execute("SELECT category, COUNT(*) FROM data_records GROUP BY category"):
                stats["by_category"][row[0]] = row[1]
            
            for row in conn.execute("SELECT status, COUNT(*) FROM data_records GROUP BY status"):
                stats["by_status"][row[0]] = row[1]
        
        return stats

# =============================================================================
# FILE SYSTEM OPERATIONS
# =============================================================================

class FileSystem:
    """File system operations with hashing and validation."""
    
    def __init__(self, root: Path, config: dict, logger: SystemLogger):
        self.root = root
        self.config = config
        self.logger = logger
    
    def hash_file(self, path: Path) -> Optional[str]:
        """Compute SHA256 hash of a file."""
        max_mb = self.config.get("hash_max_mb", 50)
        try:
            size = path.stat().st_size
            if size > max_mb * 1024 * 1024:
                return None
            
            h = hashlib.sha256()
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception as e:
            self.logger.warning("FileSystem", f"Hash failed: {path}", {"error": str(e)})
            return None
    
    def rel_path(self, path: Path) -> str:
        """Get path relative to root."""
        try:
            return str(path.relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")
    
    def is_excluded(self, rel_path: str) -> bool:
        """Check if path should be excluded."""
        rel_path = rel_path.replace("\\", "/")
        for ex in self.config.get("exclude_folders", []):
            ex = ex.replace("\\", "/").strip("/")
            if rel_path == ex or rel_path.startswith(ex + "/"):
                return True
        return False
    
    def categorize_file(self, path: Path) -> DataCategory:
        """Determine category based on path and extension."""
        rel = self.rel_path(path)
        
        if rel.startswith(self.config.get("apps_folder", "apps") + "/"):
            return DataCategory.APP
        elif rel.startswith(self.config.get("sources_folder", "data/sources") + "/"):
            return DataCategory.SOURCE
        elif rel.startswith(self.config.get("derived_folder", "data/derived") + "/"):
            return DataCategory.DERIVED
        elif rel.startswith(self.config.get("models_folder", "data/models") + "/"):
            return DataCategory.MODEL
        elif rel.startswith(self.config.get("measurements_folder", "data/measurements") + "/"):
            return DataCategory.MEASUREMENT
        elif rel.startswith(self.config.get("touch_masks_folder", "data/touch_masks") + "/"):
            return DataCategory.TOUCH_MASK
        elif rel.startswith(self.config.get("exports_folder", "data/exports") + "/"):
            return DataCategory.EXPORT
        elif rel.startswith(self.config.get("outputs_folder", "outputs") + "/"):
            return DataCategory.OUTPUT
        elif rel.startswith(self.config.get("schemas_folder", "schemas") + "/"):
            return DataCategory.SCHEMA
        else:
            return DataCategory.SOURCE  # Default
    
    def walk_all(self) -> list[Path]:
        """Walk all files in root, excluding configured folders."""
        files = []
        for p in self.root.rglob("*"):
            if p.is_dir():
                continue
            rel = self.rel_path(p)
            if not self.is_excluded(rel):
                files.append(p)
        return files
    
    def ensure_folders(self):
        """Create all required folders."""
        folders = [
            "apps_folder", "sources_folder", "derived_folder", "models_folder",
            "measurements_folder", "touch_masks_folder", "exports_folder",
            "outputs_folder", "inbox_folder", "schemas_folder", "reports_folder", "backups_folder", "logs_folder"
        ]
        for key in folders:
            folder = self.root / self.config.get(key, "")
            folder.mkdir(parents=True, exist_ok=True)
        
        self.logger.info("FileSystem", "Folder structure ensured")
    
    def read_json(self, path: Path) -> Optional[dict]:
        """Safely read a JSON file."""
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            self.logger.warning("FileSystem", f"JSON read failed: {path}", {"error": str(e)})
            return None
    
    def write_json(self, path: Path, data: dict, indent: int = 2):
        """Write data to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=indent), encoding="utf-8")
    
    def backup(self, target_folder: Optional[str] = None) -> Path:
        """Create a backup snapshot."""
        backup_root = self.root / self.config.get("backups_folder", "manager/backups")
        backup_root.mkdir(parents=True, exist_ok=True)
        
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_UTC")
        dest = backup_root / f"snapshot_{stamp}"
        dest.mkdir(parents=True, exist_ok=True)
        
        exclude = set(self.config.get("exclude_folders", []))
        exclude.add(self.config.get("backups_folder", "manager/backups"))
        
        copied = 0
        apps_root = self.config.get("apps_folder", "apps")
        for src_folder in [apps_root, "data", "schemas"]:
            src = self.root / src_folder
            if not src.exists():
                continue
            
            for p in src.rglob("*"):
                if p.is_dir():
                    continue
                rel = self.rel_path(p)
                if any(rel.startswith(ex + "/") or rel == ex for ex in exclude):
                    continue
                
                out = dest / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(p, out)
                    copied += 1
                except Exception:
                    pass
        
        self.logger.info("FileSystem", f"Backup complete: {copied} files", {"dest": str(dest)})
        return dest

# =============================================================================
# DATA SCANNER / INDEXER
# =============================================================================

class DataScanner:
    """Scans file system and updates registry."""
    
    def __init__(self, fs: FileSystem, registry: DataRegistry, logger: SystemLogger):
        self.fs = fs
        self.registry = registry
        self.logger = logger

    def _validate_json_file(self, rel_path: str, path: Path) -> tuple[DataStatus, list[str]]:
        """Lightweight JSON validation for key deliverables.

        Stdlib-only: ensure JSON parses and basic required keys exist.
        Returns (status, messages).
        """
        rel_norm = rel_path.replace("\\", "/")

        # Only validate JSONs we recognize as deliverables/bridge artifacts.
        key_files = {
            "data/sources/master_parts_v2.json": "master_parts_v2",
            "data/exports/master_inventory_v2.json": "master_inventory_v2",
            "data/exports/blueprint_map_v2.json": "blueprint_map_v2",
            "panel_id_map_colors.json": "panel_id_map_colors",
        }

        # Also validate by filename for exports that are copied elsewhere.
        filename = Path(rel_norm).name
        if rel_norm not in key_files and filename not in {
            "master_parts_v2.json",
            "master_inventory_v2.json",
            "blueprint_map_v2.json",
            "panel_id_map_colors.json",
        }:
            return (DataStatus.VALID, [])

        data = self.fs.read_json(path)
        if data is None:
            return (DataStatus.INVALID, ["JSON parse failed"]) 

        msgs: list[str] = []
        kind = key_files.get(rel_norm, filename)

        def require(obj: dict, key: str, t: type | tuple[type, ...]):
            if key not in obj:
                msgs.append(f"Missing key: {key}")
                return
            if not isinstance(obj[key], t):
                msgs.append(f"Key '{key}' wrong type: expected {t}, got {type(obj[key]).__name__}")

        if kind == "master_parts_v2" or kind == "master_parts_v2.json":
            if not isinstance(data, dict):
                msgs.append("Root must be an object")
            else:
                require(data, "schema", str)
                require(data, "parts", list)
        elif kind == "master_inventory_v2" or kind == "master_inventory_v2.json":
            if not isinstance(data, dict):
                msgs.append("Root must be an object")
            else:
                # Keep flexible: some inventory files may use different top-level keys.
                require(data, "schema", str)
        elif kind == "blueprint_map_v2" or kind == "blueprint_map_v2.json":
            if not isinstance(data, dict):
                msgs.append("Root must be an object")
            else:
                require(data, "schema", str)
        elif kind == "panel_id_map_colors" or kind == "panel_id_map_colors.json":
            if not isinstance(data, dict):
                msgs.append("Root must be an object")
            else:
                require(data, "mapping", dict)

        if msgs:
            return (DataStatus.INVALID, msgs)
        return (DataStatus.VALID, [])
    
    def scan(self) -> dict:
        """Full scan of file system, updating registry."""
        start = time.time()
        self.logger.info("Scanner", "Starting full scan")
        
        files = self.fs.walk_all()
        stats = {"added": 0, "updated": 0, "unchanged": 0, "removed": 0, "errors": 0}
        seen_paths = set()
        
        for path in files:
            rel = self.fs.rel_path(path)
            seen_paths.add(rel)
            
            try:
                st = path.stat()
                hash_val = self.fs.hash_file(path)
                category = self.fs.categorize_file(path)
                
                existing = self.registry.get_by_path(rel)

                validation_status, validation_messages = self._validate_json_file(rel, path)
                
                if existing:
                    # Check if changed
                    if existing.hash_sha256 != hash_val or existing.size != st.st_size:
                        # File changed - update and mark dependents stale
                        existing.hash_sha256 = hash_val or ""
                        existing.size = int(st.st_size)
                        existing.modified_at = datetime.now(timezone.utc).isoformat()
                        existing.version += 1
                        existing.status = validation_status
                        if validation_messages:
                            existing.metadata["validation"] = {
                                "status": validation_status.value,
                                "messages": validation_messages,
                                "checked_at": datetime.now(timezone.utc).isoformat(),
                            }
                        self.registry.register(existing)
                        
                        # Mark all descendants stale
                        for child_uid in existing.child_uids:
                            self.registry.mark_stale(child_uid)
                        
                        stats["updated"] += 1
                    else:
                        stats["unchanged"] += 1
                else:
                    # New file
                    uid = self.registry.generate_uid(category.value[:4])
                    now = datetime.now(timezone.utc).isoformat()
                    record = DataRecord(
                        uid=uid,
                        path=rel,
                        category=category,
                        status=validation_status,
                        size=int(st.st_size),
                        hash_sha256=hash_val or "",
                        created_at=now,
                        modified_at=now,
                    )
                    if validation_messages:
                        record.metadata["validation"] = {
                            "status": validation_status.value,
                            "messages": validation_messages,
                            "checked_at": datetime.now(timezone.utc).isoformat(),
                        }
                    self.registry.register(record)
                    stats["added"] += 1
                    
            except Exception as e:
                self.logger.warning("Scanner", f"Error processing {rel}", {"error": str(e)})
                stats["errors"] += 1
        
        # Find removed files
        all_records = self.registry.query(limit=100000)
        for record in all_records:
            if record.path not in seen_paths:
                self.registry.delete(record.uid)
                stats["removed"] += 1
        
        elapsed = time.time() - start
        self.logger.info("Scanner", f"Scan complete in {elapsed:.2f}s", stats)
        
        return stats

# =============================================================================
# HTTP SERVER
# =============================================================================

class F22APIHandler(SimpleHTTPRequestHandler):
    """HTTP request handler with API endpoints."""
    
    # These will be set by the server
    manager: 'F22DataManager' = None
    
    def __init__(self, *args, **kwargs):
        # Set directory to serve static files from apps folder
        self.directory = str(self.manager.fs.root / self.manager.config.get("apps_folder", "apps"))
        super().__init__(*args, directory=self.directory, **kwargs)
    
    def log_message(self, format, *args):
        """Override to use our logger."""
        self.manager.logger.debug("HTTP", f"{self.address_string()} - {format % args}")
    
    def send_json(self, data: Any, status: int = 200):
        """Send JSON response."""
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)
    
    def send_error_json(self, message: str, status: int = 400):
        """Send error as JSON."""
        self.send_json({"error": message, "status": status}, status)
    
    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
    
    def do_GET(self):
        """Handle GET requests."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        
        # API Routes
        if path.startswith("/api/"):
            self.handle_api_get(path[5:], query)
        elif path == "/" or path == "/index.html":
            # Serve the manager UI
            self.serve_manager_ui()
        elif path.startswith("/apps/"):
            # Friendly alias to serve static apps from the configured apps folder.
            # Example: /apps/blueprint_mapper.html -> <root>/<apps_folder>/blueprint_mapper.html
            self.path = path[len("/apps"):]
            super().do_GET()
        else:
            # Serve static files from apps folder
            super().do_GET()
    
    def do_POST(self):
        """Handle POST requests."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        
        if path.startswith("/api/"):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else b""
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError:
                data = {}
            
            self.handle_api_post(path[5:], data)
        else:
            self.send_error_json("Not Found", 404)
    
    def handle_api_get(self, path: str, query: dict):
        """Route API GET requests."""
        try:
            # System
            if path == "status":
                self.send_json(self.manager.get_status())
            elif path == "health":
                self.send_json(self.manager.get_health())
            elif path == "stats":
                self.send_json(self.manager.registry.get_stats())
            elif path == "config":
                self.send_json(self.manager.config)
            
            # Data Records
            elif path == "records":
                category = query.get("category", [None])[0]
                status = query.get("status", [None])[0]
                prefix = query.get("prefix", [None])[0]
                limit = int(query.get("limit", [100])[0])
                
                cat = DataCategory(category) if category else None
                stat = DataStatus(status) if status else None
                
                records = self.manager.registry.query(category=cat, status=stat, path_prefix=prefix, limit=limit)
                self.send_json([r.to_dict() for r in records])
            
            elif path.startswith("records/"):
                uid = path[8:]
                record = self.manager.registry.get(uid)
                if record:
                    self.send_json(record.to_dict())
                else:
                    self.send_error_json("Record not found", 404)
            
            # Measurements
            elif path == "measurements":
                component = query.get("component", [None])[0]
                points = self.manager.registry.get_measurements(component)
                self.send_json([asdict(p) for p in points])
            
            elif path == "measurements/spatial":
                x = float(query.get("x", [0])[0])
                y = float(query.get("y", [0])[0])
                z = float(query.get("z", [0])[0])
                radius = float(query.get("radius", [1])[0])
                points = self.manager.registry.query_spatial(x, y, z, radius)
                self.send_json([asdict(p) for p in points])
            
            # Touch Zones
            elif path == "touch_zones":
                component = query.get("component", [None])[0]
                zones = self.manager.registry.get_touch_zones(component)
                self.send_json([asdict(z) for z in zones])
            
            elif path == "touch_zones/lookup":
                color = query.get("color", [""])[0]
                zone = self.manager.registry.get_touch_zone_by_color(color)
                if zone:
                    self.send_json(asdict(zone))
                else:
                    self.send_error_json("Zone not found", 404)
            
            # Build Queue
            elif path == "builds":
                builds = self.manager.registry.get_pending_builds()
                self.send_json(builds)
            
            # Audit Log
            elif path == "audit":
                limit = int(query.get("limit", [100])[0])
                target = query.get("target", [None])[0]
                log = self.manager.registry.get_audit_log(limit, target)
                self.send_json(log)
            
            # Logs
            elif path == "logs":
                count = int(query.get("count", [100])[0])
                entries = self.manager.logger.get_recent(count)
                # Serialize with enum handling
                self.send_json([{
                    "timestamp": e.timestamp,
                    "level": e.level.name,
                    "component": e.component,
                    "message": e.message,
                    "data": e.data
                } for e in entries])
            
            # Search
            elif path == "search":
                q = query.get("q", [""])[0]
                results = self.manager.search(q)
                self.send_json(results)
            
            # Files
            elif path.startswith("file/"):
                rel_path = urllib.parse.unquote(path[5:])
                self.serve_data_file(rel_path)

            # Inbox
            elif path == "inbox":
                self.send_json(self.manager.get_inbox_status())

            # Checks
            elif path == "checks":
                self.send_json(self.manager.get_checks_status())
            
            else:
                self.send_error_json("Unknown endpoint", 404)
                
        except Exception as e:
            self.manager.logger.error("API", f"GET {path} failed", {"error": str(e)})
            self.send_error_json(str(e), 500)
    
    def handle_api_post(self, path: str, data: dict):
        """Route API POST requests."""
        try:
            if path == "scan":
                stats = self.manager.scan()
                self.send_json({"status": "ok", "stats": stats})
            
            elif path == "backup":
                dest = self.manager.backup()
                self.send_json({"status": "ok", "path": str(dest)})
            
            elif path == "measurements":
                point = MeasurementPoint(**data)
                self.manager.registry.add_measurement(point)
                self.send_json({"status": "ok", "uid": point.uid})
            
            elif path == "touch_zones":
                zone = TouchZone(**data)
                self.manager.registry.add_touch_zone(zone)
                self.send_json({"status": "ok", "uid": zone.uid})
            
            elif path == "records":
                # Register a new data record
                record = DataRecord.from_dict(data)
                self.manager.registry.register(record)
                self.send_json({"status": "ok", "uid": record.uid})
            
            elif path.startswith("records/") and path.endswith("/stale"):
                uid = path[8:-6]
                self.manager.registry.mark_stale(uid)
                self.send_json({"status": "ok"})

            elif path == "inbox/route":
                # Route files from data/inbox into canonical locations
                mode = (data.get("mode") or "copy").lower()  # copy|move
                files = data.get("files")  # optional list of inbox-relative paths to route
                result = self.manager.route_inbox(mode=mode, files=files)
                self.send_json({"status": "ok", "result": result})

            elif path == "checks/run":
                checks = data.get("checks")
                result = self.manager.run_checks(check_names=checks if isinstance(checks, list) else None)
                self.send_json({"status": "ok", "result": result})

            elif path == "server/start":
                started = self.manager.start_http_server()
                state = "started" if started else "already_running"
                self.send_json({"status": "ok", "state": state})

            elif path == "server/stop":
                self.send_json({"status": "ok"})
                self.manager.request_server_stop()

            elif path == "server/restart":
                self.send_json({"status": "ok"})
                self.manager.request_server_restart()
            
            else:
                self.send_error_json("Unknown endpoint", 404)
                
        except Exception as e:
            self.manager.logger.error("API", f"POST {path} failed", {"error": str(e)})
            self.send_error_json(str(e), 500)
    
    def serve_data_file(self, rel_path: str):
        """Serve a file from the data directory."""
        full_path = self.manager.fs.root / rel_path
        
        if not full_path.exists():
            self.send_error_json("File not found", 404)
            return
        
        # Security: ensure path is within root
        try:
            full_path.resolve().relative_to(self.manager.fs.root.resolve())
        except ValueError:
            self.send_error_json("Access denied", 403)
            return
        
        content_type, _ = mimetypes.guess_type(str(full_path))
        content_type = content_type or "application/octet-stream"
        
        try:
            with full_path.open("rb") as f:
                content = f.read()
            
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", len(content))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error_json(f"Read error: {e}", 500)
    
    def serve_manager_ui(self):
        """Serve the embedded manager UI."""
        html = self.manager.get_ui_html()
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """Threaded HTTP server for handling concurrent requests."""
    allow_reuse_address = True
    daemon_threads = True

# =============================================================================
# MAIN MANAGER CLASS
# =============================================================================

class F22DataManager:
    """
    Central orchestrator for the F-22 Data System.
    """
    
    def __init__(self, root_folder: str, config: Optional[dict] = None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.root = Path(root_folder).expanduser().resolve()
        self.config["root_folder"] = str(self.root)
        
        # Initialize logger
        log_dir = self.root / self.config.get("logs_folder", "manager/logs")
        self.logger = SystemLogger(log_dir)
        
        # Initialize components
        self.fs = FileSystem(self.root, self.config, self.logger)
        self.registry = DataRegistry(self.root / self.config.get("db_path", "manager/f22_registry.db"), self.logger)
        self.scanner = DataScanner(self.fs, self.registry, self.logger)
        
        # Server
        self.server: Optional[ThreadedHTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self._server_enabled = True
        self._server_lock = threading.Lock()
        
        # Background workers
        self._stop_event = threading.Event()
        self._watcher_thread: Optional[threading.Thread] = None
        self._health_thread: Optional[threading.Thread] = None
        
        # State
        self.started_at: Optional[str] = None
        self.last_scan: Optional[str] = None
        self.last_health: Optional[HealthStatus] = None

        # Checks
        self.last_checks: Optional[dict] = None
        
        self.logger.info("Manager", f"Initialized F-22 Data Manager", {"root": str(self.root)})
    
    def setup(self):
        """Initial setup - create folders and do initial scan."""
        self.fs.ensure_folders()
        self.scan()
    
    def start(self, blocking: bool = True):
        """Start the manager and HTTP server."""
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.logger.info("Manager", f"Starting {APP_NAME} {APP_VERSION}")
        
        # Setup
        self.logger.debug("Manager", "Running setup (folders + initial scan)...")
        self.setup()
        self.logger.debug("Manager", "Setup complete")
        
        # Start HTTP server (supervised)
        self.logger.debug("Manager", "Starting HTTP server (supervised)...")
        ok = self._start_server_supervised()
        if not ok:
            # Keep the process alive so the user can read the error.
            self.logger.error(
                "Server",
                "HTTP server failed to start (bind error or permissions). "
                "Try a different port: .\\run_manager.ps1 -Port 8023"
            )
            return
        self.logger.debug("Manager", f"Supervisor started, stop_event={self._stop_event.is_set()}")
        
        # Start background workers
        self.logger.debug("Manager", "Starting background workers...")
        if self.config.get("enable_watcher", True):
            self._start_watcher()
        else:
            self.logger.warning("Watcher", "Watcher disabled (enable_watcher=false)")

        if self.config.get("enable_health", True):
            self._start_health_monitor()
        else:
            self.logger.warning("Health", "Health monitor disabled (enable_health=false)")
        self.logger.debug("Manager", "Background workers started")
        
        host = self.config.get("host", "127.0.0.1")
        port = self.config.get("port", DEFAULT_PORT)
        self.logger.info("Manager", f"Server running at http://{host}:{port}")
        
        if blocking:
            self.logger.debug("Manager", "Entering blocking loop...")
            try:
                while not self._stop_event.is_set():
                    time.sleep(1)
            except KeyboardInterrupt:
                self.stop()
            self.logger.debug("Manager", "Exited blocking loop")
    
    def stop(self):
        """Stop the manager and all workers."""
        self.logger.info("Manager", "Shutting down...")
        self._stop_event.set()
        
        if self.server:
            self.server.shutdown()
            try:
                self.server.server_close()
            except Exception:
                pass
            self.server = None
        
        self.logger.close()

    def start_http_server(self) -> bool:
        """Start the HTTP server if it's not already running."""
        self._server_enabled = True
        if self.server_thread and self.server_thread.is_alive():
            return False
        with self._server_lock:
            if self.server_thread and self.server_thread.is_alive():
                return False
            self._start_server()
        return True

    def stop_http_server(self):
        """Stop the HTTP server without shutting down the manager."""
        self._server_enabled = False
        if self.server:
            self.server.shutdown()
            try:
                self.server.server_close()
            except Exception:
                pass
            self.server = None

    def restart_http_server(self):
        """Restart the HTTP server without stopping the manager."""
        self._server_enabled = True
        if self.server:
            self.server.shutdown()
            try:
                self.server.server_close()
            except Exception:
                pass
            self.server = None

    def request_server_stop(self):
        """Async stop for API handlers."""
        def worker():
            self.logger.info("Server", "HTTP server stop requested via API")
            self.stop_http_server()

        threading.Thread(target=worker, daemon=True).start()

    def request_server_restart(self):
        """Async restart for API handlers."""
        def worker():
            self.logger.info("Server", "HTTP server restart requested via API")
            self.restart_http_server()

        threading.Thread(target=worker, daemon=True).start()
    
    def _start_server(self):
        """Start the HTTP server."""
        host = self.config.get("host", "127.0.0.1")
        port = self.config.get("port", DEFAULT_PORT)
        
        # Create handler class with reference to manager
        handler = type("Handler", (F22APIHandler,), {"manager": self})
        
        try:
            self.server = ThreadedHTTPServer((host, port), handler)
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            self.logger.info("Server", f"HTTP server thread started on {host}:{port}")
        except Exception as e:
            self.logger.error("Server", f"Failed to start HTTP server on {host}:{port}: {e}")
            self.server = None
            self.server_thread = None
            raise

    def _start_server_supervised(self) -> bool:
        """Start the HTTP server and keep it alive.

        If the server thread dies unexpectedly, restart it with a short backoff.
        Clean shutdown sets _stop_event which stops the supervisor.
        """

        # Start once immediately
        try:
            with self._server_lock:
                self._start_server()
        except Exception as e:
            self.logger.error("Server", f"Initial server start failed: {e}")
            # Do NOT set stop_event here; it can cause an immediate program exit and hides the real cause.
            return False

        restart_delay = 1.0
        max_delay = 15.0

        def supervisor_loop():
            nonlocal restart_delay
            while not self._stop_event.is_set():
                if not self._server_enabled:
                    time.sleep(0.5)
                    continue
                t = self.server_thread
                if t is None:
                    time.sleep(0.5)
                    continue

                # Poll periodically so Ctrl+C / stop() is responsive.
                t.join(timeout=1.0)

                if self._stop_event.is_set():
                    return

                # If thread is still alive, keep watching.
                if t.is_alive():
                    continue

                # Thread died: restart unless we are shutting down.
                if not self._server_enabled:
                    time.sleep(0.5)
                    continue
                if self.server_thread is not t and self.server_thread and self.server_thread.is_alive():
                    restart_delay = 1.0
                    continue
                self.logger.warning(
                    "Server",
                    f"HTTP server stopped unexpectedly; restarting in {restart_delay:.1f}s"
                )
                time.sleep(restart_delay)
                if self._stop_event.is_set():
                    return

                try:
                    # Best-effort cleanup of any old server object.
                    if self.server:
                        try:
                            self.server.server_close()
                        except Exception:
                            pass
                        self.server = None

                    with self._server_lock:
                        self._start_server()
                    restart_delay = 1.0
                except Exception as e:
                    self.logger.error("Server", f"Restart failed: {e}")
                    restart_delay = min(max_delay, restart_delay * 2)

        # Launch the supervisor loop in the background.
        threading.Thread(target=supervisor_loop, daemon=True).start()
        return True
    
    def _start_watcher(self):
        """Start file watcher thread."""
        def watcher_loop():
            interval = self.config.get("scan_interval_seconds", 10)
            while not self._stop_event.is_set():
                for _ in range(interval):
                    if self._stop_event.is_set():
                        return
                    time.sleep(1)
                
                try:
                    self.scan()
                except Exception as e:
                    self.logger.error("Watcher", f"Scan failed: {e}")
        
        self._watcher_thread = threading.Thread(target=watcher_loop, daemon=True)
        self._watcher_thread.start()
    
    def _start_health_monitor(self):
        """Start health monitoring thread."""
        def health_loop():
            interval = self.config.get("health_check_interval_seconds", 30)
            while not self._stop_event.is_set():
                for _ in range(interval):
                    if self._stop_event.is_set():
                        return
                    time.sleep(1)
                
                try:
                    self.last_health = self._check_health()
                except Exception as e:
                    self.logger.error("Health", f"Check failed: {e}")
        
        self._health_thread = threading.Thread(target=health_loop, daemon=True)
        self._health_thread.start()
    
    def _check_health(self) -> HealthStatus:
        """Run health checks."""
        components = {}
        
        # Database check
        try:
            stats = self.registry.get_stats()
            components["database"] = {"status": "healthy", "records": stats["total_records"]}
        except Exception as e:
            components["database"] = {"status": "error", "error": str(e)}
        
        # Disk space check
        disk_free = 0
        try:
            stat = shutil.disk_usage(self.root)
            disk_free = stat.free // (1024 * 1024)
            components["disk"] = {
                "status": "healthy" if disk_free > 1000 else "warning" if disk_free > 100 else "critical",
                "free_mb": disk_free
            }
        except Exception as e:
            components["disk"] = {"status": "error", "error": str(e)}
        
        # Server check
        components["server"] = {"status": "healthy" if self.server else "error"}
        
        # Overall status
        statuses = [c.get("status") for c in components.values()]
        if "critical" in statuses or "error" in statuses:
            overall = "critical"
        elif "warning" in statuses:
            overall = "degraded"
        else:
            overall = "healthy"
        
        # Error count
        recent_logs = self.logger.get_recent(100, LogLevel.ERROR)
        hour_ago = datetime.now(timezone.utc).timestamp() - 3600
        errors_last_hour = sum(1 for e in recent_logs 
                               if datetime.fromisoformat(e.timestamp.replace("Z", "+00:00")).timestamp() > hour_ago)
        
        return HealthStatus(
            timestamp=datetime.now(timezone.utc).isoformat(),
            overall=overall,
            components=components,
            disk_free_mb=disk_free,
            memory_used_percent=0,  # TODO: implement
            active_connections=0,  # TODO: implement
            pending_rebuilds=self.registry.get_stats().get("pending_builds", 0),
            errors_last_hour=errors_last_hour
        )
    
    def scan(self) -> dict:
        """Run a scan and update registry."""
        stats = self.scanner.scan()
        self.last_scan = datetime.now(timezone.utc).isoformat()
        return stats
    
    def backup(self) -> Path:
        """Create a backup."""
        return self.fs.backup()

    def get_inbox_status(self) -> dict:
        """Return current inbox status (pending files)."""
        inbox = self.root / self.config.get("inbox_folder", "data/inbox")
        inbox.mkdir(parents=True, exist_ok=True)
        pending = []
        for p in inbox.rglob("*"):
            if p.is_dir():
                continue
            pending.append({
                "path": self.fs.rel_path(p),
                "size": p.stat().st_size,
                "modified_at": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
            })
        return {"inbox": self.config.get("inbox_folder", "data/inbox"), "pending": pending, "count": len(pending)}

    def _route_target_for(self, src: Path) -> Optional[Path]:
        """Decide canonical destination path for an inbox file."""
        name = src.name
        name_l = name.lower()
        rel = self.fs.rel_path(src)

        # Canonicalize specific known artifacts
        if name == "panel_id_map_colors.json":
            return self.root / self.config.get("exports_folder", "data/exports") / name

        # Master parts
        if name_l.startswith("master_parts") and name_l.endswith(".json"):
            return self.root / self.config.get("sources_folder", "data/sources") / name
        if name_l.startswith("master_parts") and name_l.endswith(".csv"):
            return self.root / self.config.get("sources_folder", "data/sources") / name
        if name_l.endswith(".sqlite") and "master_parts" in name_l:
            return self.root / self.config.get("sources_folder", "data/sources") / name

        # Inventory / blueprint exports
        if "master_inventory" in name_l and name_l.endswith(".json"):
            return self.root / self.config.get("exports_folder", "data/exports") / name
        if "blueprint_map" in name_l and name_l.endswith(".json"):
            return self.root / self.config.get("exports_folder", "data/exports") / name

        # Default: keep in inbox unless explicitly recognized
        _ = rel
        return None

    def route_inbox(self, mode: str = "copy", files: Optional[list[str]] = None) -> dict:
        """Route recognized files from data/inbox into canonical locations.

        mode:
          - copy: keep original in inbox
          - move: remove original from inbox after routing
        """
        mode = mode.lower().strip()
        if mode not in {"copy", "move"}:
            mode = "copy"

        inbox = self.root / self.config.get("inbox_folder", "data/inbox")
        inbox.mkdir(parents=True, exist_ok=True)

        stamped = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_UTC")
        processed_root = inbox / "processed" / stamped
        processed_root.mkdir(parents=True, exist_ok=True)

        routed = []
        skipped = []
        errors = []

        desired: Optional[set[str]] = None
        if isinstance(files, list):
            desired = {str(f).replace("\\", "/") for f in files if f}

        for src in inbox.rglob("*"):
            if src.is_dir():
                continue
            # Don't re-route already processed files
            if "processed" in src.parts:
                continue

            if desired is not None:
                rel_src = self.fs.rel_path(src)
                if rel_src not in desired:
                    continue

            dest = self._route_target_for(src)
            if dest is None:
                skipped.append(self.fs.rel_path(src))
                continue

            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                # Preserve an archive copy in processed/ always
                archived = processed_root / src.name
                shutil.copy2(src, archived)

                if mode == "move":
                    shutil.move(str(src), str(dest))
                else:
                    shutil.copy2(src, dest)

                routed.append({
                    "from": self.fs.rel_path(archived),
                    "to": self.fs.rel_path(dest),
                    "mode": mode,
                })
            except Exception as e:
                errors.append({"file": self.fs.rel_path(src), "error": str(e)})

        # Update registry view
        try:
            self.scan()
        except Exception as e:
            self.logger.warning("Inbox", "Scan after routing failed", {"error": str(e)})

        return {
            "mode": mode,
            "counts": {
                "routed": len(routed),
                "skipped": len(skipped),
                "errors": len(errors),
            },
            "routed": routed,
            "skipped": skipped,
            "errors": errors,
        }

    def get_checks_status(self) -> dict:
        """Return the most recent checks run (if any)."""
        return self.last_checks or {
            "checked_at": None,
            "counts": {"pass": 0, "warn": 0, "fail": 0},
            "results": [],
        }

    def run_checks(self, check_names: Optional[list[str]] = None) -> dict:
        """Run manager 'checks' and return structured results.

        check_names:
          - None: run all
          - list[str]: run only named checks
        """
        now = datetime.now(timezone.utc).isoformat()

        available = {
            "inbox_pending": self._check_inbox_pending,
            "panel_id_map_colors_location": self._check_panel_id_map_colors_location,
            "invalid_records": self._check_invalid_records,
            "duplicate_master_part_uids": self._check_duplicate_master_part_uids,
        }

        selected = set(available.keys())
        if isinstance(check_names, list) and check_names:
            selected = {c for c in check_names if c in available}

        results: list[CheckResult] = []
        for name in sorted(selected):
            try:
                res = available[name]()
                if not res.checked_at:
                    res.checked_at = now
                results.append(res)
            except Exception as e:
                results.append(
                    CheckResult(
                        name=name,
                        status=CheckStatus.FAIL,
                        summary=f"Check crashed: {e}",
                        details={"error": str(e)},
                        checked_at=now,
                    )
                )

        counts = {"pass": 0, "warn": 0, "fail": 0}
        for r in results:
            if r.status == CheckStatus.PASS:
                counts["pass"] += 1
            elif r.status == CheckStatus.WARN:
                counts["warn"] += 1
            else:
                counts["fail"] += 1

        payload = {
            "checked_at": now,
            "counts": counts,
            "results": [r.to_dict() for r in results],
        }

        self.last_checks = payload
        return payload

    def _check_inbox_pending(self) -> CheckResult:
        inbox = self.get_inbox_status()
        n = int(inbox.get("count", 0))
        if n == 0:
            return CheckResult(
                name="inbox_pending",
                status=CheckStatus.PASS,
                summary="Inbox is empty",
                details={"count": 0},
            )
        return CheckResult(
            name="inbox_pending",
            status=CheckStatus.WARN,
            summary=f"Inbox has {n} pending file(s)",
            details={"count": n, "pending": inbox.get("pending", [])},
        )

    def _check_panel_id_map_colors_location(self) -> CheckResult:
        root_file = self.root / "panel_id_map_colors.json"
        canonical = self.root / self.config.get("exports_folder", "data/exports") / "panel_id_map_colors.json"

        exists_root = root_file.exists()
        exists_canonical = canonical.exists()

        if exists_canonical and not exists_root:
            return CheckResult(
                name="panel_id_map_colors_location",
                status=CheckStatus.PASS,
                summary="panel_id_map_colors.json is in data/exports",
                details={"canonical": self.fs.rel_path(canonical)},
            )

        if exists_root and not exists_canonical:
            return CheckResult(
                name="panel_id_map_colors_location",
                status=CheckStatus.WARN,
                summary="panel_id_map_colors.json is in repo root (not yet canonicalized)",
                details={
                    "root": self.fs.rel_path(root_file),
                    "expected": self.fs.rel_path(canonical),
                    "hint": "Drop it into data/inbox and use Route Inbox, or move it to data/exports.",
                },
            )

        if exists_root and exists_canonical:
            return CheckResult(
                name="panel_id_map_colors_location",
                status=CheckStatus.WARN,
                summary="panel_id_map_colors.json exists in both root and data/exports",
                details={
                    "root": self.fs.rel_path(root_file),
                    "canonical": self.fs.rel_path(canonical),
                    "hint": "Consider removing the root copy after verifying canonical is correct.",
                },
            )

        return CheckResult(
            name="panel_id_map_colors_location",
            status=CheckStatus.WARN,
            summary="panel_id_map_colors.json not found",
            details={"expected": self.fs.rel_path(canonical)},
        )

    def _check_invalid_records(self) -> CheckResult:
        """Summarize INVALID records for quick triage."""
        invalid_records = []
        try:
            invalid_records = self.registry.query(status=DataStatus.INVALID, limit=100000)
        except Exception:
            invalid_records = []

        n = len(invalid_records)
        if n == 0:
            return CheckResult(
                name="invalid_records",
                status=CheckStatus.PASS,
                summary="No INVALID records",
                details={"count": 0},
            )

        sample = [r.to_dict() if hasattr(r, "to_dict") else r for r in invalid_records[:20]]
        return CheckResult(
            name="invalid_records",
            status=CheckStatus.FAIL,
            summary=f"{n} INVALID record(s) in registry",
            details={"count": n, "sample": sample},
        )

    def _check_duplicate_master_part_uids(self) -> CheckResult:
        """Check duplicate UIDs in data/sources/master_parts_v2.json (if present)."""
        p = self.root / self.config.get("sources_folder", "data/sources") / "master_parts_v2.json"
        if not p.exists():
            return CheckResult(
                name="duplicate_master_part_uids",
                status=CheckStatus.WARN,
                summary="master_parts_v2.json not found (skipping UID duplicate check)",
                details={"expected": self.fs.rel_path(p)},
            )

        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            return CheckResult(
                name="duplicate_master_part_uids",
                status=CheckStatus.FAIL,
                summary=f"Failed to parse master_parts_v2.json: {e}",
                details={"file": self.fs.rel_path(p), "error": str(e)},
            )

        items = data.get("parts") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return CheckResult(
                name="duplicate_master_part_uids",
                status=CheckStatus.FAIL,
                summary="master_parts_v2.json missing 'parts' list",
                details={"file": self.fs.rel_path(p)},
            )

        seen: dict[str, int] = {}
        dups: dict[str, int] = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            uid = it.get("uid") or it.get("id")
            if not uid:
                continue
            uid = str(uid)
            seen[uid] = seen.get(uid, 0) + 1

        for uid, c in seen.items():
            if c > 1:
                dups[uid] = c

        if not dups:
            return CheckResult(
                name="duplicate_master_part_uids",
                status=CheckStatus.PASS,
                summary="No duplicate master part UIDs",
                details={"count": 0},
            )

        # Keep details small
        worst = sorted(dups.items(), key=lambda kv: (-kv[1], kv[0]))[:50]
        return CheckResult(
            name="duplicate_master_part_uids",
            status=CheckStatus.FAIL,
            summary=f"Found {len(dups)} duplicate UID(s) in master_parts_v2.json",
            details={"count": len(dups), "top": worst},
        )
    
    def search(self, query: str) -> list[dict]:
        """Search across all text files for a query string."""
        query = query.strip()
        if not query:
            return []
        
        results = []
        text_exts = set(self.config.get("text_extensions", []))
        
        for path in self.fs.walk_all():
            if path.suffix.lower() not in text_exts:
                continue
            
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                if query.lower() not in text.lower():
                    continue
                
                for i, line in enumerate(text.splitlines(), start=1):
                    if query.lower() in line.lower():
                        results.append({
                            "file": self.fs.rel_path(path),
                            "line": i,
                            "context": line.strip()[:300]
                        })
                        if len(results) >= 500:
                            return results
            except Exception:
                continue
        
        return results
    
    def get_status(self) -> dict:
        """Get current system status."""
        return {
            "app": APP_NAME,
            "version": APP_VERSION,
            "root": str(self.root),
            "started_at": self.started_at,
            "last_scan": self.last_scan,
            "uptime_seconds": (datetime.now(timezone.utc) - datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))).total_seconds() if self.started_at else 0,
            "port": self.config.get("port"),
        }
    
    def get_health(self) -> dict:
        """Get health status."""
        if self.last_health:
            return asdict(self.last_health)
        return {"overall": "unknown", "message": "Health check not yet run"}
    
    def get_ui_html(self) -> str:
        """Return the manager UI HTML."""
        return load_ui_html()

# =============================================================================
# EMBEDDED UI (placeholder - will be replaced with NGA design)
# =============================================================================

# The UI HTML will be loaded from f22_control_center.html if present,
# otherwise use a minimal fallback
MANAGER_UI_HTML = None  # Will be loaded dynamically

def load_ui_html() -> str:
    """Load the UI HTML from external file or return fallback."""
    # Try to load from web/ folder (canonical location)
    try:
        script_dir = Path(__file__).parent
        repo_root = script_dir.parent
        ui_path = repo_root / "web" / "f22_control_center.html"
        if ui_path.exists():
            return ui_path.read_text(encoding="utf-8")
    except Exception:
        pass
    
    # Try same directory as script (fallback)
    try:
        script_dir = Path(__file__).parent
        ui_path = script_dir / "f22_control_center.html"
        if ui_path.exists():
            return ui_path.read_text(encoding="utf-8")
    except Exception:
        pass
    
    # Fallback minimal UI
    return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>F-22 Data System Manager</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: system-ui, sans-serif; background: #06080c; color: #f0f4f8; min-height: 100vh; padding: 40px; }
        h1 { color: #ffd700; margin-bottom: 20px; }
        .card { background: rgba(15,25,40,0.75); border: 1px solid rgba(255,215,0,0.15); border-radius: 16px; padding: 24px; margin-bottom: 20px; }
        pre { background: #121824; padding: 16px; border-radius: 8px; overflow-x: auto; font-size: 14px; }
        .stat { display: inline-block; margin-right: 24px; }
        .stat-value { font-size: 2rem; color: #00d4ff; }
        .stat-label { font-size: 0.8rem; color: #64748b; }
        button { background: linear-gradient(135deg, #ffd700, #b8960b); border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-weight: 600; margin-right: 10px; }
        button:hover { box-shadow: 0 0 20px rgba(255,215,0,0.3); }
    </style>
</head>
<body>
    <h1>F-22 Data System Manager</h1>
    <div class="card">
        <div class="stat"><div class="stat-value" id="records">-</div><div class="stat-label">Records</div></div>
        <div class="stat"><div class="stat-value" id="measurements">-</div><div class="stat-label">Measurements</div></div>
        <div class="stat"><div class="stat-value" id="zones">-</div><div class="stat-label">Touch Zones</div></div>
    </div>
    <div class="card">
        <button onclick="scan()">Run Scan</button>
        <button onclick="backup()">Create Backup</button>
    </div>
    <div class="card">
        <h3 style="margin-bottom:12px;color:#ffd700;">API Endpoints</h3>
        <pre>GET  /api/status      - System status
GET  /api/health      - Health check  
GET  /api/stats       - Registry statistics
GET  /api/records     - List data records
GET  /api/search?q=   - Search files
GET  /api/measurements - 3D measurement points
GET  /api/touch_zones  - Touch zone mappings
POST /api/scan        - Trigger file scan
POST /api/backup      - Create backup snapshot</pre>
    </div>
    <script>
        async function api(endpoint, method='GET') {
            try {
                const r = await fetch('/api/' + endpoint, {method});
                return await r.json();
            } catch(e) { return null; }
        }
        async function update() {
            const s = await api('stats');
            if(s) {
                document.getElementById('records').textContent = s.total_records || 0;
                document.getElementById('measurements').textContent = s.total_measurements || 0;
                document.getElementById('zones').textContent = s.total_touch_zones || 0;
            }
        }
        async function scan() { await api('scan','POST'); update(); alert('Scan complete'); }
        async function backup() { const r = await api('backup','POST'); alert(r ? 'Backup: '+r.path : 'Failed'); }
        update(); setInterval(update, 5000);
    </script>
</body>
</html>'''

# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument("root", nargs="?", default=".", help="Root folder for the data system")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"HTTP port (default: {DEFAULT_PORT})")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--scan-only", action="store_true", help="Run a single scan and exit")
    parser.add_argument("--backup", action="store_true", help="Create backup and exit")
    
    args = parser.parse_args()
    
    config = {
        "port": args.port,
        "host": args.host,
    }
    
    manager = F22DataManager(args.root, config)
    
    if args.scan_only:
        manager.setup()
        stats = manager.scan()
        print(json.dumps(stats, indent=2))
        return
    
    if args.backup:
        manager.setup()
        dest = manager.backup()
        print(f"Backup created: {dest}")
        return
    
    # Handle graceful shutdown
    def signal_handler(sig, frame):
        print("\nShutting down...")
        manager.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    # Note: SIGTERM may not work reliably on Windows
    if hasattr(signal, 'SIGTERM'):
        try:
            signal.signal(signal.SIGTERM, signal_handler)
        except (OSError, ValueError):
            pass
    
    # Start the manager
    try:
        manager.start(blocking=True)
    except Exception as e:
        print(f"\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        manager.stop()
        sys.exit(1)

if __name__ == "__main__":
    main()
