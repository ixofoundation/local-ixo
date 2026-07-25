#!/usr/bin/env python3
"""Verify and extract the canonical IXO-3963 Python source bundle."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = json.loads((HERE / "source_manifest.json").read_text(encoding="utf-8"))
PARTS = sorted(HERE.glob("source.part*.b64"))
DEBUG_DIR = ROOT / "artifacts" / "ixo-3963" / "debug"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_FILE = DEBUG_DIR / "source-extraction.json"


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def write_debug(**updates: Any) -> None:
    current: dict[str, Any] = {}
    if DEBUG_FILE.exists():
        try:
            current = json.loads(DEBUG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            current = {}
    current.update(updates)
    DEBUG_FILE.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fail(message: str, **details: Any) -> None:
    write_debug(status="failed", error=message, **details)
    raise SystemExit(message)


write_debug(
    status="started",
    repository_root=str(ROOT),
    source_directory=str(HERE),
    part_names=[part.name for part in PARTS],
    part_sizes={part.name: part.stat().st_size for part in PARTS},
    manifest=MANIFEST,
)

if not PARTS:
    fail("no source.part*.b64 files found")

encoded = "".join(part.read_text(encoding="ascii").strip() for part in PARTS)
write_debug(encoded_character_count=len(encoded))
try:
    bundle = base64.b64decode(encoded, validate=True)
except Exception as exc:
    fail("invalid source bundle base64", exception=f"{type(exc).__name__}: {exc}")

actual_bundle_sha = sha_bytes(bundle)
write_debug(bundle_byte_count=len(bundle), actual_bundle_sha256=actual_bundle_sha)
if actual_bundle_sha != MANIFEST["bundle_sha256"]:
    fail(
        "source bundle digest mismatch",
        expected_bundle_sha256=MANIFEST["bundle_sha256"],
        actual_bundle_sha256=actual_bundle_sha,
    )

try:
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:gz") as archive:
        members = archive.getmembers()
        write_debug(archive_members=[member.name for member in members])
        for member in members:
            target = (ROOT / member.name).resolve()
            if ROOT.resolve() not in target.parents and target != ROOT.resolve():
                fail("unsafe archive path", archive_member=member.name, resolved_target=str(target))
        archive.extractall(ROOT, filter="data")
except (tarfile.TarError, OSError) as exc:
    fail("source archive extraction failed", exception=f"{type(exc).__name__}: {exc}")

file_results: dict[str, Any] = {}
for rel, expected in MANIFEST.items():
    if rel == "bundle_sha256":
        continue
    path = ROOT / rel
    if not path.exists():
        fail("extracted source file missing", missing_file=rel, file_results=file_results)
    actual = sha_file(path)
    file_results[rel] = {"expected": expected, "actual": actual, "match": actual == expected}
    if actual != expected:
        fail("source digest mismatch", source_file=rel, expected=expected, actual=actual, file_results=file_results)

write_debug(status="passed", extracted_file_count=len(MANIFEST) - 1, file_results=file_results)
print(f"verified {len(PARTS)} source parts and extracted {len(MANIFEST)-1} source files")
