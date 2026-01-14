#!/usr/bin/env python3
"""
aircraft_map_audit.py

Audit + trace + backup for the aircraft mapping pipeline.

Usage:
  python aircraft_map_audit.py audit --root ./exports
  python aircraft_map_audit.py trace --root ./exports --uid "5HY03205-111A|5PTE0158-3"
  python aircraft_map_audit.py backup --root ./exports --out ./backups
"""

from __future__ import annotations
import argparse, json, os, re, sys, time, zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

UID_RE = re.compile(r"^[^|]+\|[^|]+$")  # dash|matl

def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def find_first(root: Path, names: List[str]) -> Optional[Path]:
    for n in names:
        p = root / n
        if p.exists():
            return p
    # fallback: search
    for p in root.rglob("*.json"):
        if p.name in names:
            return p
    return None

def as_list(x) -> List[Any]:
    return x if isinstance(x, list) else []

def now_stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")

@dataclass
class Issue:
    level: str  # "ERROR" | "WARN" | "INFO"
    code: str
    message: str
    context: Dict[str, Any]

def add_issue(issues: List[Issue], level: str, code: str, message: str, **ctx):
    issues.append(Issue(level=level, code=code, message=message, context=ctx))

def validate_uid(uid: str) -> bool:
    return bool(uid) and bool(UID_RE.match(uid.strip()))

def load_master_parts(root: Path) -> Tuple[str, Any]:
    p = find_first(root, ["master_parts_v2.json", "master_parts.json"])
    if not p:
        return ("missing", None)
    data = read_json(p)
    schema = data.get("schema")
    if schema == "master_parts_v2":
        return ("v2", data)
    # legacy heuristic
    if isinstance(data, dict) and "all_rows" in data and "slides" in data:
        return ("legacy", data)
    return ("unknown", data)

def iter_master_parts_uids(kind: str, data: Any) -> List[Dict[str, Any]]:
    out = []
    if not data:
        return out
    if kind == "v2":
        for p in as_list(data.get("parts")):
            uid = p.get("uid", "")
            out.append({"uid": uid, "part": p})
    elif kind in ("legacy", "unknown"):
        # legacy has all_rows with dash/material
        for r in as_list(data.get("all_rows")):
            dash = str(r.get("dash", "")).strip()
            matl = str(r.get("material", "")).strip()
            uid = f"{dash}|{matl}" if dash or matl else ""
            out.append({"uid": uid, "row": r})
    return out

def load_master_inventory(root: Path) -> Optional[Dict[str, Any]]:
    p = find_first(root, ["master_inventory_v2.json"])
    if not p:
        return None
    data = read_json(p)
    return data if isinstance(data, dict) else None

def load_blueprint_map(root: Path) -> Tuple[str, Any]:
    p = find_first(root, ["blueprint_map_v2.json", "blueprint_regions.json"])
    if not p:
        return ("missing", None)
    data = read_json(p)
    if isinstance(data, dict) and data.get("schema") == "blueprint_map_v2":
        return ("v2", data)
    # legacy mapper export shape
    if isinstance(data, dict) and ("regions" in data and "zones" in data and "groups" in data):
        return ("legacy", data)
    return ("unknown", data)

def collect_mapper_uid_refs(kind: str, data: Any) -> List[Dict[str, Any]]:
    refs = []
    if not data:
        return refs
    regions = as_list(data.get("regions"))
    zones = data.get("zones") or {}
    groups = data.get("groups") or {}

    # regions
    for r in regions:
        for uid in as_list(r.get("uids")):
            refs.append({"uid": uid, "where": "region", "region_id": r.get("id") or r.get("region_id"), "label": r.get("label")})

    # zones
    if isinstance(zones, dict):
        for zid, z in zones.items():
            for uid in as_list(z.get("required_uids")):
                refs.append({"uid": uid, "where": "zone", "zone_id": zid, "label": z.get("label") or z.get("name")})

    # groups
    if isinstance(groups, dict):
        for gid, g in groups.items():
            for uid in as_list(g.get("required_uids")):
                refs.append({"uid": uid, "where": "group", "group_id": gid, "label": g.get("label") or g.get("name")})

    return refs

def audit(root: Path) -> Dict[str, Any]:
    issues: List[Issue] = []
    summary: Dict[str, Any] = {"root": str(root), "timestamp": time.time()}

    mp_kind, mp = load_master_parts(root)
    inv = load_master_inventory(root)
    bm_kind, bm = load_blueprint_map(root)

    summary["master_parts"] = mp_kind
    summary["has_master_inventory_v2"] = bool(inv and inv.get("schema") == "master_inventory_v2")
    summary["blueprint_map"] = bm_kind

    # Master parts UID sanity
    mp_uids = iter_master_parts_uids(mp_kind, mp)
    bad_mp = [x for x in mp_uids if x["uid"] and not validate_uid(x["uid"])]
    if bad_mp:
        add_issue(issues, "ERROR", "MP_BAD_UID", f"{len(bad_mp)} invalid UIDs in master_parts", sample=bad_mp[:5])

    # Inventory sanity
    inv_items = as_list(inv.get("items")) if inv else []
    uid_to_id = {}
    id_to_uid = {}
    for it in inv_items:
        uid = str(it.get("uid", "")).strip()
        iid = it.get("item_id")
        if not validate_uid(uid):
            add_issue(issues, "ERROR", "INV_BAD_UID", "Invalid UID in inventory item", uid=uid, item_id=iid)
            continue
        if uid in uid_to_id and uid_to_id[uid] != iid:
            add_issue(issues, "ERROR", "INV_UID_ID_CONFLICT", "Same UID has multiple item_id values", uid=uid, ids=[uid_to_id[uid], iid])
        uid_to_id[uid] = iid
        if iid in id_to_uid and id_to_uid[iid] != uid:
            add_issue(issues, "ERROR", "INV_ID_UID_CONFLICT", "Same item_id maps to multiple UIDs", item_id=iid, uids=[id_to_uid[iid], uid])
        id_to_uid[iid] = uid

    # Cross-check: requirements UIDs should exist in inventory
    if mp_uids and inv_items:
        missing = []
        for rec in mp_uids:
            uid = rec["uid"]
            if uid and validate_uid(uid) and uid not in uid_to_id:
                missing.append(uid)
        if missing:
            add_issue(issues, "WARN", "REQ_NOT_IN_INV", f"{len(missing)} requirement UIDs not present in inventory", sample=list(set(missing))[:25])

    # Mapper refs should exist in inventory
    mapper_refs = collect_mapper_uid_refs(bm_kind, bm)
    if mapper_refs and inv_items:
        missing = [r for r in mapper_refs if validate_uid(r["uid"]) and r["uid"] not in uid_to_id]
        if missing:
            add_issue(issues, "ERROR", "MAP_UID_MISSING_IN_INV", f"{len(missing)} mapper UID refs missing in inventory", sample=missing[:25])

    # Zone/sequence consistency check (best-effort)
    if mp_kind == "v2" and mp:
        bad_seq = []
        for p in as_list(mp.get("parts")):
            ctx = p.get("context") or {}
            zone = ctx.get("zone")
            zs = ctx.get("zone_sequence")
            seq = str(ctx.get("sequence_label") or "").strip()
            if zone is not None and zs is not None:
                expected = f"z{zone} s{zs}"
                if seq and seq.lower() != expected.lower():
                    bad_seq.append({"uid": p.get("uid"), "expected": expected, "got": seq})
        if bad_seq:
            add_issue(issues, "WARN", "SEQ_LABEL_MISMATCH", f"{len(bad_seq)} parts have mismatched sequence_label", sample=bad_seq[:10])

    summary["counts"] = {
        "master_parts_rows_or_parts": len(as_list(mp.get("parts")) if mp_kind == "v2" else as_list(mp.get("all_rows")) if mp else []),
        "inventory_items": len(inv_items),
        "mapper_uid_refs": len(mapper_refs),
        "issues": len(issues)
    }

    return {
        "summary": summary,
        "issues": [{"level": i.level, "code": i.code, "message": i.message, "context": i.context} for i in issues]
    }

def trace(root: Path, uid: str) -> Dict[str, Any]:
    uid = uid.strip()
    out = {"uid": uid, "found": []}
    mp_kind, mp = load_master_parts(root)
    inv = load_master_inventory(root)
    bm_kind, bm = load_blueprint_map(root)

    # master parts
    for rec in iter_master_parts_uids(mp_kind, mp):
        if rec["uid"] == uid:
            out["found"].append({"source": f"master_parts({mp_kind})", "record": rec.get("part") or rec.get("row")})

    # inventory
    if inv:
        for it in as_list(inv.get("items")):
            if str(it.get("uid", "")).strip() == uid:
                out["found"].append({"source": "master_inventory_v2", "record": it})

    # mapper refs
    for r in collect_mapper_uid_refs(bm_kind, bm):
        if r["uid"] == uid:
            out["found"].append({"source": f"blueprint_map({bm_kind})", "record": r})

    return out

def backup(root: Path, outdir: Path) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    zpath = outdir / f"aircraft_mapping_backup_{now_stamp()}.zip"
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in root.rglob("*"):
            if p.is_file():
                rel = p.relative_to(root)
                z.write(p, rel.as_posix())
    return zpath

def write_report(root: Path, report: Dict[str, Any]) -> Tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / f"audit_report_{now_stamp()}.json"
    md_path = root / f"audit_report_{now_stamp()}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # basic markdown
    issues = report.get("issues", [])
    summary = report.get("summary", {})
    counts = summary.get("counts", {})
    lines = []
    lines.append(f"# Aircraft Mapping QA Report\n")
    lines.append(f"- Root: `{summary.get('root')}`")
    lines.append(f"- Master Parts: `{summary.get('master_parts')}`")
    lines.append(f"- Master Inventory v2: `{summary.get('has_master_inventory_v2')}`")
    lines.append(f"- Blueprint Map: `{summary.get('blueprint_map')}`")
    lines.append("")
    lines.append("## Counts")
    for k, v in (counts or {}).items():
        lines.append(f"- **{k}**: {v}")
    lines.append("")
    lines.append("## Issues")
    if not issues:
        lines.append("✅ No issues found.")
    else:
        for it in issues:
            lines.append(f"- **{it['level']}** `{it['code']}` — {it['message']}")
            ctx = it.get("context") or {}
            if ctx:
                lines.append(f"  - Context: `{json.dumps(ctx)[:500]}`")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path

def main():
    ap = argparse.ArgumentParser(description="Aircraft mapping audit, trace, and backup tool")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_a = sub.add_parser("audit", help="Audit all artifacts for consistency")
    ap_a.add_argument("--root", required=True, help="Root folder containing JSON artifacts")

    ap_t = sub.add_parser("trace", help="Trace a UID across all artifacts")
    ap_t.add_argument("--root", required=True, help="Root folder containing JSON artifacts")
    ap_t.add_argument("--uid", required=True, help="UID to trace (format: dash|material)")

    ap_b = sub.add_parser("backup", help="Create a ZIP backup of all artifacts")
    ap_b.add_argument("--root", required=True, help="Root folder to backup")
    ap_b.add_argument("--out", required=True, help="Output folder for backup ZIP")

    args = ap.parse_args()
    root = Path(args.root).expanduser().resolve()

    if args.cmd == "audit":
        rep = audit(root)
        outdir = root / "reports"
        outdir.mkdir(parents=True, exist_ok=True)
        j, m = write_report(outdir, rep)
        print(f"Wrote:\n- {j}\n- {m}")
        if rep.get("issues"):
            print(f"\n⚠️  Found {len(rep['issues'])} issues. Check report for details.")
            sys.exit(2)
        else:
            print("\n✅ No issues found.")
        return

    if args.cmd == "trace":
        rep = trace(root, args.uid)
        print(json.dumps(rep, indent=2))
        if not rep["found"]:
            print(f"\n❌ UID '{args.uid}' not found in any artifact.")
        else:
            print(f"\n✅ Found {len(rep['found'])} occurrences.")
        return

    if args.cmd == "backup":
        outdir = Path(args.out).expanduser().resolve()
        z = backup(root, outdir)
        print(f"✅ Backup created: {z}")
        return

if __name__ == "__main__":
    main()
