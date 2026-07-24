#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OUT = Path(os.environ.get("IXO_3948_OUT", "artifacts/ixo-3948"))

if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True, exist_ok=True)

for script in ("genesis.py", "current.py", "analyze.py"):
    subprocess.run([sys.executable, str(SCRIPT_DIR / script)], check=True, env=os.environ.copy())

current_summary = json.loads((OUT / "derived/current-summary.json").read_text(encoding="utf-8"))
genesis_summary = json.loads((OUT / "derived/genesis-summary.json").read_text(encoding="utf-8"))
validation = json.loads((OUT / "derived/validation.json").read_text(encoding="utf-8"))

manifest = {
    "issue": "IXO-3948",
    "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "code_commit": os.environ.get("GITHUB_SHA", "local-unpinned-run"),
    "method": "research/ixo-3948/run.py",
    "chain_id": current_summary["block"].get("chain_id", "ixo-5") if isinstance(current_summary.get("block"), dict) else "ixo-5",
    "genesis": {
        "source_url": genesis_summary["source_url"],
        "source_commit": genesis_summary["source_commit"],
        "archive_sha256": genesis_summary["archive_sha256"],
        "json_sha256": genesis_summary["json_sha256"],
        "genesis_time": genesis_summary["genesis_time"],
        "summed_balances_uixo": genesis_summary["summed_balances_uixo"],
    },
    "current": {
        "height": current_summary["height"],
        "block": current_summary["block"],
        "rest_provider": current_summary["rest_provider"],
        "bank_supply_uixo": current_summary["bank_supply_uixo"],
        "denom_owner_count": current_summary["denom_owner_count"],
    },
    "validation": validation,
}
(OUT / "run-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

hash_path = OUT / "hashes/sha256sums.txt"
hash_path.parent.mkdir(parents=True, exist_ok=True)
lines: list[str] = []
for path in sorted(p for p in OUT.rglob("*") if p.is_file() and p != hash_path):
    lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(OUT).as_posix()}")
hash_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

result = {
    "pass": validation["pass"],
    "reproduction_grade": validation["reproduction_grade"],
    "current_height": current_summary["height"],
    "genesis_supply_uixo": genesis_summary["summed_balances_uixo"],
    "current_supply_uixo": current_summary["bank_supply_uixo"],
    "denom_owner_count": current_summary["denom_owner_count"],
    "hash_manifest_sha256": hashlib.sha256(hash_path.read_bytes()).hexdigest(),
}
(OUT / "run-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2, sort_keys=True))

if not validation["pass"]:
    raise SystemExit("IXO-3948 validation failed")
