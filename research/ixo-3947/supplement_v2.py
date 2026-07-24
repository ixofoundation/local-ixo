#!/usr/bin/env python3
"""Bounded governance and activity fallback capture for IXO-3947."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("IXO_CAPTURE_ROOT", "artifacts/ixo-3947"))
TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "12"))
GOV_DETAIL_LIMIT = int(os.environ.get("GOV_DETAIL_LIMIT", "10"))
ACTIVITY_BLOCKS = int(os.environ.get("ACTIVITY_BLOCKS", "10000"))
ACTIVITY_SAMPLE_BLOCKS = int(os.environ.get("ACTIVITY_SAMPLE_BLOCKS", "200"))
MAX_TX_PAGES = int(os.environ.get("MAX_TX_PAGES", "30"))

manifest = json.loads((ROOT / "run-manifest.json").read_text(encoding="utf-8"))
selected = json.loads((ROOT / "selected-block.json").read_text(encoding="utf-8"))
height = int(manifest["height"])

RESTS = [
    ("first_party", "https://impacthub.ixo.world/rest"),
    ("ibs", "https://ixo.ibs.team/api"),
    ("stavr", "https://ixo.api.m.stavr.tech"),
    ("bluestake", "https://ixo-api.bluestake.net"),
    ("lavenderfive", "https://rest.lavenderfive.com:443/impacthub"),
]
RPCS = list(zip(selected["providers"], selected["rpc_endpoints"]))
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "IXO-M1-Research/1.0 (+https://linear.app/ixo-world/issue/IXO-3947)",
}
write_lock = threading.Lock()


def append_line(path: Path, text: str) -> None:
    with write_lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def status_record(name: str, endpoint: str, ok: bool, detail: str = "") -> None:
    append_line(ROOT / "query-status.jsonl", json.dumps({"name": name, "endpoint": endpoint, "ok": ok, "detail": detail}, sort_keys=True))


def fetch(url: str, *, headers: dict[str, str] | None = None, method: str = "GET", data: bytes | None = None) -> tuple[int, dict[str, str], bytes]:
    merged = dict(HEADERS)
    merged.update(headers or {})
    append_line(ROOT / "logs/commands.log", " | ".join([method, url] + [f"{k}: {v}" for k, v in sorted((headers or {}).items())]))
    request = urllib.request.Request(url, headers=merged, method=method, data=data)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()
    except Exception as exc:
        return 0, {}, f"{type(exc).__name__}: {exc}".encode()


def save(path: Path, body: bytes, headers: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    path.with_suffix(".headers").write_text("".join(f"{k}: {v}\n" for k, v in sorted(headers.items())), encoding="utf-8")


def decode(body: bytes) -> Any:
    return json.loads(body.decode("utf-8"))


def fixed_height_get(provider: str, rest: str, name: str, path: str) -> tuple[bool, Any | None]:
    url = rest.rstrip("/") + path
    code, headers, body = fetch(url, headers={"x-cosmos-block-height": str(height)})
    save(ROOT / f"raw/rest/{name}_{provider}.json", body, headers)
    if code != 200:
        status_record(f"{name}_{provider}", url, False, f"HTTP {code}: {body[:300].decode('utf-8', 'replace')}")
        return False, None
    response_height = headers.get("x-cosmos-block-height") or headers.get("grpc-metadata-x-cosmos-block-height")
    if response_height and response_height != str(height):
        status_record(f"{name}_{provider}", url, False, f"response height {response_height} != {height}")
        return False, None
    try:
        payload = decode(body)
    except Exception as exc:
        status_record(f"{name}_{provider}", url, False, f"invalid JSON: {exc}")
        return False, None
    status_record(f"{name}_{provider}", url, True)
    return True, payload


# Governance route implementations return an oversized response when unfiltered.
# First split by lifecycle status; if any provider still cannot serve the set,
# capture the recent proposal-ID range individually and disclose that sampling.
GOV_STATUSES = [
    "PROPOSAL_STATUS_DEPOSIT_PERIOD",
    "PROPOSAL_STATUS_VOTING_PERIOD",
    "PROPOSAL_STATUS_PASSED",
    "PROPOSAL_STATUS_REJECTED",
    "PROPOSAL_STATUS_FAILED",
]
gov_proposals: list[dict[str, Any]] = []
gov_provider = ""
gov_sampled = False
for provider, rest in RESTS:
    candidate: list[dict[str, Any]] = []
    ok_all = True
    for lifecycle in GOV_STATUSES:
        params = urllib.parse.urlencode({"proposal_status": lifecycle, "pagination.limit": "100"})
        ok, payload = fixed_height_get(provider, rest, f"gov_status_{lifecycle.lower()}", f"/cosmos/gov/v1/proposals?{params}")
        if not ok:
            ok_all = False
            break
        candidate.extend((payload or {}).get("proposals", []) or [])
    if ok_all and candidate:
        gov_proposals = candidate
        gov_provider = provider
        break

if not gov_proposals:
    scan_low = int(os.environ.get("GOV_SCAN_LOW", "430"))
    scan_high = int(os.environ.get("GOV_SCAN_HIGH", "550"))

    def one_proposal(proposal_id: int) -> dict[str, Any] | None:
        for provider, rest in RESTS[:3]:
            ok, payload = fixed_height_get(provider, rest, f"gov_proposal_scan_{proposal_id}", f"/cosmos/gov/v1/proposals/{proposal_id}")
            if ok and isinstance(payload, dict) and isinstance(payload.get("proposal"), dict):
                proposal = payload["proposal"]
                proposal["_capture_provider"] = provider
                return proposal
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        found = list(pool.map(one_proposal, range(scan_low, scan_high + 1)))
    gov_proposals = [proposal for proposal in found if proposal]
    gov_provider = "multi-provider-direct-id-scan"
    gov_sampled = True
    if len(gov_proposals) < 10:
        raise SystemExit(f"governance capture insufficient: {len(gov_proposals)} proposals")

# Deduplicate and write the generic shape consumed by derive.py.
unique: dict[str, dict[str, Any]] = {}
for proposal in gov_proposals:
    proposal_id = str(proposal.get("id") or proposal.get("proposal_id") or "")
    if proposal_id:
        unique[proposal_id] = proposal
gov_proposals = sorted(unique.values(), key=lambda proposal: int(proposal.get("id") or proposal.get("proposal_id") or 0))
combined = {
    "proposals": gov_proposals,
    "pagination": {"next_key": None, "total": str(len(gov_proposals))},
    "capture_provider": gov_provider,
    "capture_height": str(height),
    "capture_sampled": gov_sampled,
}
(ROOT / "raw/rest/gov_proposals.json").write_text(json.dumps(combined, sort_keys=True) + "\n", encoding="utf-8")
status_record("gov_proposals_fallback", gov_provider, True, f"captured {len(gov_proposals)} proposals; sampled={gov_sampled}")

latest_ids = sorted(unique, key=int, reverse=True)[:GOV_DETAIL_LIMIT]
for proposal_id in latest_ids:
    for suffix, path in [
        ("proposal", f"/cosmos/gov/v1/proposals/{proposal_id}"),
        ("deposits", f"/cosmos/gov/v1/proposals/{proposal_id}/deposits?pagination.limit=100"),
        ("votes", f"/cosmos/gov/v1/proposals/{proposal_id}/votes?pagination.limit=100"),
        ("tally", f"/cosmos/gov/v1/proposals/{proposal_id}/tally"),
    ]:
        for provider, rest in RESTS[:3]:
            ok, payload = fixed_height_get(provider, rest, f"gov_{suffix}_{proposal_id}", path)
            if ok:
                source = ROOT / f"raw/rest/gov_{suffix}_{proposal_id}_{provider}.json"
                target = ROOT / f"raw/rest/gov_{suffix}_{proposal_id}.json"
                target.write_bytes(source.read_bytes())
                header_source = source.with_suffix(".headers")
                if header_source.exists():
                    target.with_suffix(".headers").write_bytes(header_source.read_bytes())
                break

(ROOT / "derived/governance-capture-method.json").write_text(json.dumps({
    "provider": gov_provider,
    "height": height,
    "proposal_count": len(gov_proposals),
    "sampled": gov_sampled,
    "sample_range": [430, 550] if gov_sampled else None,
    "limitation": "Direct ID scan covers only the disclosed recent range." if gov_sampled else None,
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")

# Try indexed transaction search across confirmed providers and methods.
low = max(1, height - ACTIVITY_BLOCKS + 1)
tx_search_success = False
for provider, rpc in RPCS:
    rpc = rpc.rstrip("/")
    for mode in ("get", "post"):
        captured: list[dict[str, Any]] = []
        total = 0
        failed = False
        for page in range(1, MAX_TX_PAGES + 1):
            expression = f"tx.height >= {low} AND tx.height <= {height}"
            if mode == "get":
                query = urllib.parse.urlencode({"query": f'"{expression}"', "prove": "false", "page": str(page), "per_page": "100", "order_by": "asc"}, quote_via=urllib.parse.quote)
                url = f"{rpc}/tx_search?{query}"
                code, headers, body = fetch(url)
            else:
                url = rpc + "/"
                payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tx_search", "params": {"query": expression, "prove": False, "page": str(page), "per_page": "100", "order_by": "asc"}}).encode()
                code, headers, body = fetch(url, method="POST", data=payload, headers={"Content-Type": "application/json"})
            save(ROOT / f"raw/rpc/tx_search_{provider}_{mode}_{page}.json", body, headers)
            if code != 200:
                status_record(f"tx_search_{provider}_{mode}_{page}", url, False, f"HTTP {code}: {body[:300].decode('utf-8', 'replace')}")
                failed = True
                break
            try:
                response = decode(body)
            except Exception as exc:
                status_record(f"tx_search_{provider}_{mode}_{page}", url, False, f"invalid JSON: {exc}")
                failed = True
                break
            if response.get("error"):
                status_record(f"tx_search_{provider}_{mode}_{page}", url, False, json.dumps(response["error"])[:500])
                failed = True
                break
            result = response.get("result") or {}
            txs = result.get("txs") or []
            captured.extend(txs)
            total = int(result.get("total_count") or len(captured))
            status_record(f"tx_search_{provider}_{mode}_{page}", url, True, f"{len(txs)} transactions")
            if not txs or page * 100 >= total:
                break
        if not failed:
            (ROOT / "raw/rpc/tx_search_1.json").write_text(json.dumps({"result": {"txs": captured, "total_count": str(total)}, "capture_provider": provider, "capture_method": f"tx_search_{mode}", "capture_low_height": low, "capture_high_height": height}, sort_keys=True) + "\n", encoding="utf-8")
            tx_search_success = True
            break
    if tx_search_success:
        break

activity_low = low
activity_method = "tx_search" if tx_search_success else "block_results_sample"
if not tx_search_success:
    activity_low = max(1, height - ACTIVITY_SAMPLE_BLOCKS + 1)

    def block_results(block_height: int) -> tuple[int, Any | None, str | None]:
        for provider, rpc in RPCS:
            url = f"{rpc.rstrip('/')}/block_results?height={block_height}"
            code, headers, body = fetch(url)
            save(ROOT / f"raw/rpc/block_results_{block_height}_{provider}.json", body, headers)
            if code == 200:
                try:
                    response = decode(body)
                    if response.get("result") is not None:
                        return block_height, response["result"], provider
                except Exception:
                    pass
        return block_height, None, None

    heights = list(range(activity_low, height + 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        blocks = list(pool.map(block_results, heights))
    synthetic: list[dict[str, Any]] = []
    successful_blocks = 0
    for block_height, result, provider in blocks:
        if result is None:
            continue
        successful_blocks += 1
        for index, tx_result in enumerate(result.get("txs_results") or []):
            synthetic.append({
                "height": str(block_height),
                "hash": hashlib.sha256(f"{block_height}:{index}".encode()).hexdigest().upper(),
                "index": index,
                "tx_result": tx_result,
                "source_provider": provider,
                "hash_limitation": "deterministic block/index surrogate; block_results does not return raw transaction bytes",
            })
    (ROOT / "raw/rpc/tx_search_1.json").write_text(json.dumps({"result": {"txs": synthetic, "total_count": str(len(synthetic))}, "capture_method": "block_results_sample", "capture_low_height": activity_low, "capture_high_height": height, "successful_blocks": successful_blocks, "requested_blocks": len(heights)}, sort_keys=True) + "\n", encoding="utf-8")
    status_record("activity_block_results_sample", "confirmed-rpc-provider-set", successful_blocks == len(heights), f"{successful_blocks}/{len(heights)} blocks; {len(synthetic)} transactions")

(ROOT / "derived/activity-capture-method.json").write_text(json.dumps({
    "method": activity_method,
    "requested_low_height": low,
    "captured_low_height": activity_low,
    "high_height": height,
    "sampled": not tx_search_success,
    "limitation": None if tx_search_success else f"tx_search failed across confirmed providers; direct block_results events cover the most recent {height - activity_low + 1} blocks.",
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
