"""
One-off / repeatable: read predictions.csv, find (report_id, metric_id) where
M0 vs M1(A0,A1,A2,A5) differ on pred_disclosure_status, pred_value, or pred_page.
Writes prediction_disagreements_m0_m1_a1_a2_a5.json next to this script.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CSV_PATH = Path(__file__).resolve().parent / "predictions.csv"
OUT_PATH = Path(__file__).resolve().parent / "prediction_disagreements_m0_m1_a1_a2_a5.json"

# Canonical comparison keys (method, ablation) -> short label in output
TARGETS: List[Tuple[str, str, str]] = [
    ("M0", "", "M0"),
    ("M1", "A0", "M1_A0"),
    ("M1", "A1", "M1_A1"),
    ("M1", "A2", "M1_A2"),
    ("M1", "A5", "M1_A5"),
]


def _norm(s: Any) -> str:
    if s is None:
        return ""
    t = str(s).strip()
    return t


def _norm_page(s: Any) -> str:
    if s is None or s == "":
        return ""
    try:
        return str(int(float(str(s).strip())))
    except (ValueError, TypeError):
        return _norm(s)


def row_key(r: Dict[str, str]) -> Tuple[str, str, str, str]:
    return (r["report_id"], r["metric_id"], r["method"], (r.get("ablation") or "").strip())


def parse_ts(s: str) -> datetime:
    s = (s or "").strip()
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def main() -> None:
    # (report_id, metric_id, method, ablation) -> best row by timestamp
    best: Dict[Tuple[str, str, str, str], Dict[str, str]] = {}
    best_ts: Dict[Tuple[str, str, str, str], datetime] = {}

    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            k = row_key(r)
            ts = parse_ts(r.get("timestamp") or "")
            if k not in best_ts or ts >= best_ts[k]:
                best_ts[k] = ts
                best[k] = r

    # (report_id, metric_id) -> label -> snapshot
    by_pair: Dict[Tuple[str, str], Dict[str, Dict[str, str]]] = {}

    for (rid, mid, method, abl), r in best.items():
        for m, a, label in TARGETS:
            if method == m and (abl or "") == (a or ""):
                snap = {
                    "pred_disclosure_status": _norm(r.get("pred_disclosure_status")).lower(),
                    "pred_value": _norm(r.get("pred_value")),
                    "pred_page": _norm_page(r.get("pred_page")),
                    "pred_unit": _norm(r.get("pred_unit")),
                    "run_id": _norm(r.get("run_id")),
                    "timestamp": _norm(r.get("timestamp")),
                }
                by_pair.setdefault((rid, mid), {})[label] = snap
                break

    disagreements: List[Dict[str, Any]] = []
    stats = {"pairs_with_all_five": 0, "pairs_with_disagreement": 0, "reports_touched": set()}

    for (rid, mid), snaps in by_pair.items():
        if len(snaps) < 5:
            continue
        if not all(x in snaps for x in ("M0", "M1_A0", "M1_A1", "M1_A2", "M1_A5")):
            continue
        stats["pairs_with_all_five"] += 1

        fields = ("pred_disclosure_status", "pred_value", "pred_page")
        diff_fields: List[str] = []
        for fld in fields:
            vals = {snaps[lb][fld] for lb in ("M0", "M1_A0", "M1_A1", "M1_A2", "M1_A5")}
            if len(vals) > 1:
                diff_fields.append(fld)

        if not diff_fields:
            continue
        stats["pairs_with_disagreement"] += 1
        stats["reports_touched"].add(rid)

        disagreements.append(
            {
                "report_id": rid,
                "metric_id": mid,
                "diff_fields": diff_fields,
                "by_method": {
                    "M0": snaps["M0"],
                    "M1_A0": snaps["M1_A0"],
                    "M1_A1": snaps["M1_A1"],
                    "M1_A2": snaps["M1_A2"],
                    "M1_A5": snaps["M1_A5"],
                },
            }
        )

    disagreements.sort(key=lambda x: (x["report_id"], x["metric_id"]))

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_csv": str(CSV_PATH).replace("\\", "/"),
        "description": (
            "Rows where the same (report_id, metric_id) has all of M0, M1+A0, M1+A1, M1+A2, M1+A5 "
            "and pred_disclosure_status, pred_value, or pred_page are not identical across the five. "
            "When duplicate runs exist for the same key, the latest timestamp row is kept."
        ),
        "summary": {
            "metric_pairs_with_all_five_methods": stats["pairs_with_all_five"],
            "metric_pairs_with_any_field_disagreement": stats["pairs_with_disagreement"],
            "distinct_reports_with_disagreement": len(stats["reports_touched"]),
        },
        "disagreements": disagreements,
    }

    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Wrote", OUT_PATH)
    print(json.dumps(out["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
