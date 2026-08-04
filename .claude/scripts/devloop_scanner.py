#!/usr/bin/env python3
"""Dev Loop state scanner for the /loop architecture.

Reads BUG_INDEX.md and REQ_INDEX.md files, extracts state counts and item
lists, and produces compact JSON for consumption by loop_runner.md.

Usage:
    python devloop_scanner.py --status    # Current state snapshot
    python devloop_scanner.py --delta     # Delta vs last snapshot + update snapshot
"""

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BUG_INDEX = REPO_ROOT / "etf-strategies" / "automation" / "bugs" / "BUG_INDEX.md"
REQ_INDEX_ETF = (
    REPO_ROOT / "etf-strategies" / "automation" / "steering" / "REQ_INDEX.md"
)
REQ_INDEX_DAILY = (
    REPO_ROOT / "my_doc" / "每日复盘" / "harness" / "automation" / "steering" / "REQ_INDEX.md"
)
SNAPSHOT_PATH = Path(__file__).resolve().parent / "devloop_snapshot.json"

BUG_STATES = {
    "OPEN", "IN_PROGRESS", "FIXED", "MANUAL_REVIEW", "VERIFIED", "WONT_FIX"
}
REQ_STATES = {
    "OPEN", "IN_PROGRESS", "IMPLEMENTED", "CLOSED", "ADOPTED", "REJECTED"
}


def parse_markdown_tables(content):
    """Parse all pipe-delimited tables from markdown content."""
    tables = []
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and line.count("|") >= 2:
            header_line = line
            if i + 1 < len(lines):
                sep_line = lines[i + 1].strip()
                if re.match(r"^\|[\s\-:|]+\|$", sep_line):
                    headers = [h.strip() for h in header_line.split("|")[1:-1]]
                    rows = []
                    j = i + 2
                    while j < len(lines):
                        row_line = lines[j].strip()
                        if not row_line.startswith("|"):
                            break
                        parts = [p.strip() for p in row_line.split("|")[1:-1]]
                        if len(parts) >= len(headers):
                            parts = parts[:len(headers)]
                            while len(parts) < len(headers):
                                parts.append("")
                            rows.append(dict(zip(headers, parts)))
                        j += 1
                    if rows:
                        tables.append({"headers": headers, "rows": rows})
                    i = j
                    continue
        i += 1
    return tables


def scan_bugs(path):
    """Parse BUG_INDEX.md and return state summary plus item list."""
    result = {"states": {s: 0 for s in BUG_STATES}, "items": []}
    if not path.exists():
        return result
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    tables = parse_markdown_tables(content)
    for table in tables:
        headers = table["headers"]
        if "状态" in headers and "数量" in headers:
            for row in table["rows"]:
                state = row.get("状态", "").strip()
                if state in BUG_STATES:
                    try:
                        result["states"][state] = int(
                            row.get("数量", "0")
                        )
                    except ValueError:
                        pass
        bug_id_col = status_col = date_col = title_col = None
        for col in headers:
            c = col.strip()
            if c in ("BUG-ID", "BUG ID"):
                bug_id_col = col
            elif c == "状态":
                status_col = col
            elif c in ("日期", "创建日期", "发现日期"):
                date_col = col
            elif c in ("标题", "描述"):
                title_col = col
        if bug_id_col and status_col:
            for row in table["rows"]:
                bid = row.get(bug_id_col, "").strip()
                if bid and bid.startswith("BUG-"):
                    result["items"].append({
                        "id": bid,
                        "status": row.get(status_col, "").strip(),
                        "date": row.get(date_col, "").strip() if date_col else "",
                        "title": row.get(title_col, "").strip() if title_col else "",
                    })
    return result


def scan_reqs(path):
    """Parse REQ_INDEX.md and return state summary plus item list."""
    result = {"states": {s: 0 for s in REQ_STATES}, "items": []}
    if not path.exists():
        return result
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    tables = parse_markdown_tables(content)
    for table in tables:
        headers = table["headers"]
        if "状态" in headers and "数量" in headers:
            for row in table["rows"]:
                state = row.get("状态", "").strip()
                if state in REQ_STATES:
                    try:
                        result["states"][state] = int(
                            row.get("数量", "0")
                        )
                    except ValueError:
                        pass
        req_id_col = status_col = date_col = title_col = None
        for col in headers:
            c = col.strip()
            if c in ("ID", "REQ-ID"):
                req_id_col = col
            elif c == "状态":
                status_col = col
            elif c in ("创建日期", "日期"):
                date_col = col
            elif c == "标题":
                title_col = col
        if req_id_col and status_col:
            for row in table["rows"]:
                rid = row.get(req_id_col, "").strip()
                if rid and rid.startswith("REQ-"):
                    result["items"].append({
                        "id": rid,
                        "status": row.get(status_col, "").strip(),
                        "date": row.get(date_col, "").strip() if date_col else "",
                        "title": row.get(title_col, "").strip() if title_col else "",
                    })
    return result


def detect_stuck(items, item_type):
    """Detect items stuck in a state too long."""
    stuck = []
    today = date.today()
    thresholds = {
        "BUG": [
            ("OPEN", 7, "OPEN>7d"),
            ("MANUAL_REVIEW", 3, "REVIEW>3d"),
        ],
        "REQ": [
            ("OPEN", 7, "OPEN>7d"),
            ("IN_PROGRESS", 3, "IN_PROG>3d"),
            ("IMPLEMENTED", 5, "IMPL>5d"),
        ],
    }
    rules = thresholds.get(item_type, [])
    for item in items:
        status = item.get("status", "")
        date_str = item.get("date", "")
        for check_status, max_days, label in rules:
            if status == check_status and date_str:
                try:
                    item_date = date.fromisoformat(date_str[:10])
                    days = (today - item_date).days
                    if days > max_days:
                        stuck.append({
                            "id": item["id"],
                            "type": item_type,
                            "status": status,
                            "days": days,
                            "label": label,
                        })
                except (ValueError, TypeError):
                    pass
    return stuck


def load_snapshot():
    """Load previous snapshot, or None if missing or corrupt."""
    if not SNAPSHOT_PATH.exists():
        return None
    try:
        with open(SNAPSHOT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_snapshot(snap):
    """Save current Dev Loop state as the new snapshot."""
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SNAPSHOT_PATH, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=2, ensure_ascii=False)


def build_snapshot_state(bugs, reqs_daily, reqs_etf):
    """Build a snapshot-compatible state dict keyed by state -> list of IDs."""
    snap = {
        "updated_at": datetime.now().isoformat(),
        "bugs": {},
        "reqs_daily": {},
        "reqs_etf": {},
    }
    for state in BUG_STATES:
        snap["bugs"][state] = sorted(
            [it["id"] for it in bugs["items"] if it["status"] == state]
        )
    for state in REQ_STATES:
        snap["reqs_daily"][state] = sorted(
            [it["id"] for it in reqs_daily["items"] if it["status"] == state]
        )
        snap["reqs_etf"][state] = sorted(
            [it["id"] for it in reqs_etf["items"] if it["status"] == state]
        )
    return snap


def compute_delta(current_snap, previous_snap):
    """Compare current snapshot with previous and return delta."""
    if previous_snap is None:
        return {
            "bugs_new": [], "bugs_moved": [],
            "reqs_daily_new": [], "reqs_daily_moved": [],
            "reqs_etf_new": [], "reqs_etf_moved": [],
            "note": "initial baseline (no previous snapshot)",
        }
    delta = {
        "bugs_new": [], "bugs_moved": [],
        "reqs_daily_new": [], "reqs_daily_moved": [],
        "reqs_etf_new": [], "reqs_etf_moved": [],
    }

    def domain_delta(domain_key, states_set, new_key, moved_key):
        prev_domain = previous_snap.get(domain_key, {})
        curr_domain = current_snap.get(domain_key, {})
        prev_ids, curr_ids = {}, {}
        for state in states_set:
            for iid in prev_domain.get(state, []):
                prev_ids[iid] = state
            for iid in curr_domain.get(state, []):
                curr_ids[iid] = state
        all_ids = set(list(prev_ids.keys()) + list(curr_ids.keys()))
        for iid in all_ids:
            ps = prev_ids.get(iid)
            cs = curr_ids.get(iid)
            if ps is None and cs is not None:
                delta[new_key].append(iid)
            elif ps is not None and cs is not None and ps != cs:
                delta[moved_key].append({"id": iid, "from": ps, "to": cs})

    domain_delta("bugs", BUG_STATES, "bugs_new", "bugs_moved")
    domain_delta("reqs_daily", REQ_STATES, "reqs_daily_new", "reqs_daily_moved")
    domain_delta("reqs_etf", REQ_STATES, "reqs_etf_new", "reqs_etf_moved")
    return delta


def build_status():
    """Build complete Dev Loop status."""
    bugs = scan_bugs(BUG_INDEX)
    reqs_daily = scan_reqs(REQ_INDEX_DAILY)
    reqs_etf = scan_reqs(REQ_INDEX_ETF)
    all_stuck = (
        detect_stuck(bugs["items"], "BUG")
        + detect_stuck(reqs_daily["items"], "REQ")
        + detect_stuck(reqs_etf["items"], "REQ")
    )
    return {
        "bugs": bugs["states"],
        "reqs_daily": reqs_daily["states"],
        "reqs_etf": reqs_etf["states"],
        "stuck": all_stuck,
        "healthy": len(all_stuck) == 0,
        "scanned_at": datetime.now().isoformat(),
    }


def cmd_status():
    """Print current Dev Loop status as JSON."""
    print(json.dumps(build_status(), indent=2, ensure_ascii=False))


def cmd_delta():
    """Print delta vs last snapshot and update snapshot."""
    bugs = scan_bugs(BUG_INDEX)
    reqs_daily = scan_reqs(REQ_INDEX_DAILY)
    reqs_etf = scan_reqs(REQ_INDEX_ETF)
    current_snap = build_snapshot_state(bugs, reqs_daily, reqs_etf)
    previous_snap = load_snapshot()
    delta = compute_delta(current_snap, previous_snap)
    all_stuck = (
        detect_stuck(bugs["items"], "BUG")
        + detect_stuck(reqs_daily["items"], "REQ")
        + detect_stuck(reqs_etf["items"], "REQ")
    )
    current_status = {
        "bugs": bugs["states"],
        "reqs_daily": reqs_daily["states"],
        "reqs_etf": reqs_etf["states"],
        "stuck": all_stuck,
        "healthy": len(all_stuck) == 0,
        "scanned_at": datetime.now().isoformat(),
    }
    output = {"delta": delta, "current": current_status}
    print(json.dumps(output, indent=2, ensure_ascii=False))
    save_snapshot(current_snap)


if __name__ == "__main__":
    if "--status" in sys.argv:
        cmd_status()
    elif "--delta" in sys.argv:
        cmd_delta()
    else:
        print("Usage: devloop_scanner.py --status | --delta", file=sys.stderr)
        sys.exit(1)
