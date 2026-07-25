#!/usr/bin/env python3
"""Verify and extract the canonical IXO-3963 Python source bundle."""
from __future__ import annotations
import hashlib, json, tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUNDLE = HERE / "source.tar.gz"
MANIFEST = json.loads((HERE / "source_manifest.json").read_text(encoding="utf-8"))

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

if sha(BUNDLE) != MANIFEST["bundle_sha256"]:
    raise SystemExit("source bundle digest mismatch")
with tarfile.open(BUNDLE, "r:gz") as archive:
    for member in archive.getmembers():
        target = (ROOT / member.name).resolve()
        if ROOT.resolve() not in target.parents and target != ROOT.resolve():
            raise SystemExit(f"unsafe archive path: {member.name}")
    archive.extractall(ROOT, filter="data")
for rel, expected in MANIFEST.items():
    if rel == "bundle_sha256":
        continue
    actual = sha(ROOT / rel)
    if actual != expected:
        raise SystemExit(f"source digest mismatch for {rel}: {actual}")
print(f"verified and extracted {len(MANIFEST)-1} source files")
