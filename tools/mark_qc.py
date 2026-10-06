#!/usr/bin/env python3
"""导演 QC 裁决：venv/bin/python tools/mark_qc.py <sid> <pass|fail> [note]

pass → verdict=pass（量产跳过该段）；fail → verdict=fail（下次运行换新 seed 重出）。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT = os.path.join(ROOT, "clips", "final", "segments-report.json")

if len(sys.argv) < 3 or sys.argv[2] not in ("pass", "fail"):
    sys.exit(__doc__)
sid, verdict = sys.argv[1], sys.argv[2]
note = sys.argv[3] if len(sys.argv) > 3 else ""
report = json.load(open(REPORT)) if os.path.exists(REPORT) else {}
report.setdefault(sid, {})["verdict"] = verdict
if note:
    report[sid]["qc_note"] = note
json.dump(report, open(REPORT, "w"), ensure_ascii=False, indent=2)
print(f"{sid} -> {verdict}")
