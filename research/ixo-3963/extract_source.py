#!/usr/bin/env python3
"""Verify and extract the canonical IXO-3963 Python source bundle."""
from __future__ import annotations
import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = json.loads((HERE / "source_manifest.json").read_text(encoding="utf-8"))
PARTS = sorted(HERE.glob("source.part*.b64"))

def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())

if not PARTS:
    raise SystemExit("no source.part*.b64 files found")
encoded = "".join(part.read_text(encoding="ascii").strip() for part in PARTS)
try:
    bundle = base64.b64decode(encoded, validate=True)
except Exception as exc:
    raise SystemExit(f"invalid source bundle base64: {exc}") from exc
if sha_bytes(bundle) != MANIFEST["bundle_sha256"]:
    raise SystemExit(f"source bundle digest mismatch: {sha_bytes(bundle)}")
with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:gz") as archive:
    for member in archive.getmembers():
        target = (ROOT / member.name).resolve()
        if ROOT.resolve() not in target.parents and target != ROOT.resolve():
            raise SystemExit(f"unsafe archive path: {member.name}")
    archive.extractall(ROOT, filter="data")
for rel, expected in MANIFEST.items():
    if rel == "bundle_sha256":
        continue
    actual = sha_file(ROOT / rel)
    if actual != expected:
        raise SystemExit(f"source digest mismatch for {rel}: {actual}")
print(f"verified {len(PARTS)} source parts and extracted {len(MANIFEST)-1} source files")
