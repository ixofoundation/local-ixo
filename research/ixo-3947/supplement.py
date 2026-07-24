#!/usr/bin/env python3
"""Fill index-dependent IXO-3947 evidence with deterministic provider fallbacks.

Governance is captured through fixed-height REST pagination. Transaction activity
first uses CometBFT tx_search (GET then JSON-RPC POST) across independently
confirmed providers. If all indexes reject the range query, a fixed recent block
window is reconstructed from block_results events and clearly marked as a sample.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
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
ACTIVITY_SAMPLE_BLOCKS = int(os.environ.get("ACTIVITY_SAMPLE_BLOCKS", "500"))
MAX_TX_PAGES = int(os.environ.get("MAX_TX_PAGES", "30"))

manifest = json.loads((ROOT / "run-manifest.json").read_text(encoding="utf-8"))
selected = json.loads((ROOT / "selected-block.json").read_text(encoding="utf-8"))
height = int(manifest["height"])
chain_id = manifest["chain_id"]

RESTS = [
    ("first_party", "https://impacthub.ixo.world/rest"),
    ("ibs", "https://ixo.ibs.team/api"),
    ("bluestake", "https://ixo-api.bluestake.net"),
    ("stavr", "https://ixo.api.m.stavr.tech"),
    ("lavenderfive", "https://rest.lavenderfive.com:443/impacthub"),
    ("whenmoon", "https://impacthub_mainnet_api.chain.whenmoonwhenlambo.money"),
    ("sifchain", "https://proxies.sifchain.finance/api/impacthub-3/rest"),
]
RPCS = [(name, endpoint) for name, endpoint in zip(selected["providers"], selected["rpc_endpoints"])]

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "IXO-M1-Research/1.0 (+https://linear.app/ixo-world/issue/IXO-3947)",
}


def append_status(name: str, endpoint: str, ok: bool, detail: str = "") -> None:
    with (ROOT / "query-status.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"name": name, "endpoint": endpoint, "ok": ok, "detail": detail}, sort_keys=True) + "\n")


def log_command(method: str, url: str, headers: dict[str, str] | None = None) -> None:
    with (ROOT / "logs/commands.log").open("a", encoding="utf-8") as handle:
        handle.write(" | ".join([method, url] + [f"{k}: {v}" for k, v in sorted((headers or {}).items())]) + "\n")


def fetch(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    data: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    merged = dict(HEADERS)
    merged.update(headers or {})
    log_command(method, url, headers)
    request = urllib.request.Request(url, headers=merged, method=method, data=data)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()


def save(path: Path, body: bytes, headers: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    path.with_suffix(".headers").write_text("".join(f"{k}: {v}\n" for k, v in sorted(headers.items())), encoding="utf-8")


def json_body(body: bytes) -> Any:
    return json.loads(body.decode("utf-8"))


# ---------------------------------------------------------------------------
# Governance: fixed-height, smaller pages, provider fallback.
# ---------------------------------------------------------------------------
gov_success = False
for provider, rest in RESTS:
    proposals: list[dict[str, Any]] = []
    next_key: str | None = None
    page = 1
    provider_failed = False
    while page <= 20:
        params = {"pagination.limit": "100", "pagination.reverse": "true"}
        if next_key:
            params["pagination.key"] = next_key
        url = f"{rest.rstrip('/')}/cosmos/gov/v1/proposals?{urllib.parse.urlencode(params)}"
        status, headers, body = fetch(url, headers={"x-cosmos-block-height": str(height)})
        save(ROOT / f"raw/rest/gov_proposals_{provider}_page_{page}.json", body, headers)
        if status != 200:
            append_status(f"gov_proposals_{provider}_page_{page}", url, False, f"HTTP {status}: {body[:300].decode('utf-8', 'replace')}")
            provider_failed = True
            break
        try:
            payload = json_body(body)
        except Exception as exc:
            append_status(f"gov_proposals_{provider}_page_{page}", url, False, f"invalid JSON: {exc}")
            provider_failed = True
            break
        response_height = headers.get("x-cosmos-block-height") or headers.get("grpc-metadata-x-cosmos-block-height")
        if response_height and response_height != str(height):
            append_status(f"gov_proposals_{provider}_page_{page}", url, False, f"response height {response_height} != {height}")
            provider_failed = True
            break
        proposals.extend(payload.get("proposals", []) or [])
        next_key = (payload.get("pagination") or {}).get("next_key")
        append_status(f"gov_proposals_{provider}_page_{page}", url, True, f"{len(payload.get('proposals', []) or [])} proposals")
        if not next_key:
            break
        page += 1
        time.sleep(0.25)
    if not provider_failed and proposals:
        combined = {"proposals": proposals, "pagination": {"next_key": None, "total": str(len(proposals))}, "capture_provider": provider, "capture_height": str(height)}
        (ROOT / "raw/rest/gov_proposals.json").write_text(json.dumps(combined, sort_keys=True) + "\n", encoding="utf-8")
        append_status("gov_proposals_fallback", rest, True, f"captured {len(proposals)} proposals at height {height}")
        gov_success = True
        latest_ids = sorted({int(p.get("id") or p.get("proposal_id")) for p in proposals if p.get("id") or p.get("proposal_id")}, reverse=True)[:GOV_DETAIL_LIMIT]
        for proposal_id in latest_ids:
            for suffix, path in [
                ("proposal", f"/cosmos/gov/v1/proposals/{proposal_id}"),
                ("deposits", f"/cosmos/gov/v1/proposals/{proposal_id}/deposits?pagination.limit=100"),
                ("votes", f"/cosmos/gov/v1/proposals/{proposal_id}/votes?pagination.limit=100"),
                ("tally", f"/cosmos/gov/v1/proposals/{proposal_id}/tally"),
            ]:
                url = rest.rstrip("/") + path
                status, headers, body = fetch(url, headers={"x-cosmos-block-height": str(height)})
                save(ROOT / f"raw/rest/gov_{suffix}_{proposal_id}.json", body, headers)
                append_status(f"gov_{suffix}_{proposal_id}", url, status == 200, "" if status == 200 else f"HTTP {status}")
                time.sleep(0.1)
        break
if not gov_success:
    append_status("gov_proposals_fallback", "all-confirmed-rest-providers", False, "all fixed-height pagination attempts failed")


# ---------------------------------------------------------------------------
# Activity: tx_search provider/method fallback, then block_results sample.
# ---------------------------------------------------------------------------
low = max(1, height - ACTIVITY_BLOCKS + 1)
tx_search_success = False
for provider, rpc in RPCS:
    rpc = rpc.rstrip("/")
    for mode in ("get", "post"):
        all_txs: list[dict[str, Any]] = []
        total_count = 0
        mode_failed = False
        for page in range(1, MAX_TX_PAGES + 1):
            query = f"tx.height >= {low} AND tx.height <= {height}"
            if mode == "get":
                params = urllib.parse.urlencode({"query": f'"{query}"', "prove": "false", "page": str(page), "per_page": "100", "order_by": "asc"}, quote_via=urllib.parse.quote)
                url = f"{rpc}/tx_search?{params}"
                status, headers, body = fetch(url)
            else:
                url = rpc + "/"
                request_payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tx_search", "params": {"query": query, "prove": False, "page": str(page), "per_page": "100", "order_by": "asc"}}).encode("utf-8")
                status, headers, body = fetch(url, method="POST", data=request_payload, headers={"Content-Type": "application/json"})
            save(ROOT / f"raw/rpc/tx_search_{provider}_{mode}_{page}.json", body, headers)
            if status != 200:
                append_status(f"tx_search_{provider}_{mode}_{page}", url, False, f"HTTP {status}: {body[:300].decode('utf-8', 'replace')}")
                mode_failed = True
                break
            try:
                payload = json_body(body)
            except Exception as exc:
                append_status(f"tx_search_{provider}_{mode}_{page}", url, False, f"invalid JSON: {exc}")
                mode_failed = True
                break
            if payload.get("error"):
                append_status(f"tx_search_{provider}_{mode}_{page}", url, False, json.dumps(payload["error"])[:500])
                mode_failed = True
                break
            result = payload.get("result") or {}
            txs = result.get("txs") or []
            all_txs.extend(txs)
            total_count = int(result.get("total_count") or len(all_txs))
            append_status(f"tx_search_{provider}_{mode}_{page}", url, True, f"{len(txs)} transactions")
            if not txs or page * 100 >= total_count:
                break
        if not mode_failed:
            combined = {"result": {"txs": all_txs, "total_count": str(total_count)}, "capture_provider": provider, "capture_method": f"tx_search_{mode}", "capture_low_height": low, "capture_high_height": height}
            (ROOT / "raw/rpc/tx_search_1.json").write_text(json.dumps(combined, sort_keys=True) + "\n", encoding="utf-8")
            append_status("tx_search_fallback", rpc, True, f"captured {len(all_txs)} transactions")
            tx_search_success = True
            break
    if tx_search_success:
        break

activity_method = "tx_search" if tx_search_success else "block_results_sample"
activity_sample_low = low
if not tx_search_success:
    activity_sample_low = max(1, height - ACTIVITY_SAMPLE_BLOCKS + 1)

    def capture_block_results(h: int) -> tuple[int, Any | None, str | None]:
        for provider, rpc in RPCS:
            url = f"{rpc.rstrip('/')}/block_results?height={h}"
            status, headers, body = fetch(url)
            save(ROOT / f"raw/rpc/block_results_{h}_{provider}.json", body, headers)
            if status != 200:
                continue
            try:
                payload = json_body(body)
                if payload.get("result") is not None:
                    return h, payload["result"], provider
            except Exception:
                continue
        return h, None, None

    synthetic: list[dict[str, Any]] = []
    heights = list(range(activity_sample_low, height + 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(capture_block_results, heights))
    successful_blocks = 0
    for h, result, provider in results:
        if result is None:
            continue
        successful_blocks += 1
        for index, tx_result in enumerate(result.get("txs_results") or []):
            tx_hash = hashlib.sha256(f"{h}:{index}".encode()).hexdigest().upper()
            synthetic.append({"height": str(h), "hash": tx_hash, "index": index, "tx_result": tx_result, "source_provider": provider, "hash_limitation": "deterministic block/index surrogate; raw tx bytes were not returned by block_results"})
    combined = {"result": {"txs": synthetic, "total_count": str(len(synthetic))}, "capture_method": "block_results_sample", "capture_low_height": activity_sample_low, "capture_high_height": height, "successful_blocks": successful_blocks, "requested_blocks": len(heights)}
    (ROOT / "raw/rpc/tx_search_1.json").write_text(json.dumps(combined, sort_keys=True) + "\n", encoding="utf-8")
    append_status("activity_block_results_sample", "confirmed-rpc-provider-set", successful_blocks == len(heights), f"{successful_blocks}/{len(heights)} blocks; {len(synthetic)} transactions")

activity_meta = {
    "method": activity_method,
    "requested_low_height": low,
    "captured_low_height": activity_sample_low,
    "high_height": height,
    "sampled": not tx_search_success,
    "limitation": None if tx_search_success else f"tx_search range queries failed across confirmed providers; direct block_results events cover only the most recent {height - activity_sample_low + 1} blocks.",
}
(ROOT / "derived/activity-capture-method.json").write_text(json.dumps(activity_meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

if not gov_success:
    raise SystemExit("governance fallback failed")
