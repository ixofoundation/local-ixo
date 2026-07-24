#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/ixo-3947")
CHAIN_ID = os.getenv("CHAIN_ID", "ixo-5")
TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "12"))
GOV_DETAIL_LIMIT = int(os.getenv("GOV_DETAIL_LIMIT", "10"))
ACTIVITY_BLOCKS = int(os.getenv("ACTIVITY_BLOCKS", "10000"))
MAX_TX_PAGES = int(os.getenv("MAX_TX_PAGES", "30"))

for rel in ["raw/rpc", "raw/rest", "raw/market", "cleaned", "derived", "hashes", "logs"]:
    (OUT / rel).mkdir(parents=True, exist_ok=True)
(OUT / "endpoint-health.jsonl").write_text("", encoding="utf-8")
(OUT / "block-observations.jsonl").write_text("", encoding="utf-8")
(OUT / "query-status.jsonl").write_text("", encoding="utf-8")
(OUT / "logs/commands.log").write_text("", encoding="utf-8")

PROVIDERS = [
    ("first_party", "https://impacthub.ixo.world/rpc", "https://impacthub.ixo.world/rest"),
    ("ibs", "https://ixo.ibs.team/rpc", "https://ixo.ibs.team/api"),
    ("bluestake", "https://ixo-rpc.bluestake.net:443", "https://ixo-api.bluestake.net"),
    ("stavr", "https://ixo.rpc.m.stavr.tech:443", "https://ixo.api.m.stavr.tech"),
    ("lavenderfive", "https://rpc.lavenderfive.com:443/impacthub", "https://rest.lavenderfive.com:443/impacthub"),
    ("whenmoon", "https://impacthub_mainnet_rpc.chain.whenmoonwhenlambo.money", "https://impacthub_mainnet_api.chain.whenmoonwhenlambo.money"),
    ("sifchain", "https://proxies.sifchain.finance/api/impacthub-3/rpc", "https://proxies.sifchain.finance/api/impacthub-3/rest"),
]

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "IXO-M1-Research/1.0 (+https://linear.app/ixo-world/issue/IXO-3947)",
}


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def command(url: str, headers: dict[str, str] | None = None) -> None:
    parts = ["GET", url]
    for key, value in sorted((headers or {}).items()):
        parts.append(f"{key}: {value}")
    with (OUT / "logs/commands.log").open("a", encoding="utf-8") as f:
        f.write(" | ".join(parts) + "\n")


def request(url: str, *, headers: dict[str, str] | None = None, retries: int = 1) -> tuple[bytes, dict[str, str], int]:
    merged = dict(DEFAULT_HEADERS)
    merged.update(headers or {})
    command(url, headers)
    error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=merged, method="GET")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                return response.read(), {k.lower(): v for k, v in response.headers.items()}, response.status
        except Exception as exc:
            error = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    assert error is not None
    raise error


def request_json(url: str, **kwargs: Any) -> tuple[Any, dict[str, str], int, bytes]:
    body, headers, status = request(url, **kwargs)
    return json.loads(body), headers, status, body


def save_response(base: Path, body: bytes, headers: dict[str, str]) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_bytes(body)
    base.with_suffix(".headers").write_text("".join(f"{k}: {v}\n" for k, v in sorted(headers.items())), encoding="utf-8")


def record_query(name: str, endpoint: str, ok: bool, detail: str = "") -> None:
    append_jsonl(OUT / "query-status.jsonl", {"name": name, "endpoint": endpoint, "ok": ok, "detail": detail})


def status_probe(provider: tuple[str, str, str]) -> dict[str, Any]:
    name, rpc, _ = provider
    url = rpc.rstrip("/") + "/status"
    path = OUT / f"raw/rpc/status_{name}.json"
    try:
        payload, headers, _, body = request_json(url)
        save_response(path, body, headers)
        result = payload["result"]
        row = {
            "provider": name,
            "endpoint": rpc.rstrip("/"),
            "ok": result["node_info"]["network"] == CHAIN_ID,
            "chain_id": result["node_info"]["network"],
            "height": int(result["sync_info"]["latest_block_height"]),
            "block_hash": result["sync_info"]["latest_block_hash"],
            "catching_up": str(result["sync_info"]["catching_up"]).lower(),
        }
    except Exception as exc:
        row = {"provider": name, "endpoint": rpc.rstrip("/"), "ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    append_jsonl(OUT / "endpoint-health.jsonl", row)
    return row


with concurrent.futures.ThreadPoolExecutor(max_workers=len(PROVIDERS)) as pool:
    health = list(pool.map(status_probe, PROVIDERS))
healthy = [r for r in health if r.get("ok") and r.get("chain_id") == CHAIN_ID and r.get("catching_up") == "false"]
if len(healthy) < 2:
    raise SystemExit("fewer than two healthy independent RPC endpoints")
heights = sorted((r["height"] for r in healthy), reverse=True)
height = heights[1]
(OUT / "height.txt").write_text(f"{height}\n", encoding="utf-8")


def block_probe(row: dict[str, Any]) -> dict[str, Any]:
    name, rpc = row["provider"], row["endpoint"]
    url = f"{rpc}/block?height={height}"
    path = OUT / f"raw/rpc/block_{name}_{height}.json"
    try:
        payload, headers, _, body = request_json(url)
        save_response(path, body, headers)
        result = payload["result"]
        block = result["block"]
        obs = {
            "provider": name,
            "endpoint": rpc,
            "ok": block["header"]["chain_id"] == CHAIN_ID,
            "height": int(block["header"]["height"]),
            "block_hash": result["block_id"]["hash"],
            "app_hash": block["header"]["app_hash"],
            "time": block["header"]["time"],
        }
    except Exception as exc:
        obs = {"provider": name, "endpoint": rpc, "ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    append_jsonl(OUT / "block-observations.jsonl", obs)
    return obs


with concurrent.futures.ThreadPoolExecutor(max_workers=len(healthy)) as pool:
    observations = list(pool.map(block_probe, healthy))
groups: defaultdict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
for obs in observations:
    if obs.get("ok"):
        groups[(obs["height"], obs["block_hash"], obs["app_hash"])].append(obs)
valid_groups = [(key, rows) for key, rows in groups.items() if len(rows) >= 2]
if not valid_groups:
    raise SystemExit("no block/app-hash agreement from two independent providers")
valid_groups.sort(key=lambda item: (len(item[1]), item[0][0]), reverse=True)
(key, winning) = valid_groups[0]
selected = {
    "height": key[0],
    "block_hash": key[1],
    "app_hash": key[2],
    "time": winning[0]["time"],
    "providers": [row["provider"] for row in winning],
    "rpc_endpoints": [row["endpoint"] for row in winning],
}
(OUT / "selected-block.json").write_text(json.dumps(selected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
primary_rpc = winning[0]["endpoint"]
primary_rpc_provider = winning[0]["provider"]


def historical_rest_probe(provider: tuple[str, str, str]) -> dict[str, Any]:
    name, _, rest = provider
    url = rest.rstrip("/") + "/cosmos/bank/v1beta1/supply/uixo"
    headers = {"x-cosmos-block-height": str(height)}
    path = OUT / f"raw/rest/probe_bank_supply_{name}.json"
    try:
        payload, response_headers, _, body = request_json(url, headers=headers)
        save_response(path, body, response_headers)
        response_height = response_headers.get("x-cosmos-block-height") or response_headers.get("grpc-metadata-x-cosmos-block-height")
        amount = (payload.get("amount") or {}).get("amount") if isinstance(payload, dict) else None
        return {"provider": name, "rest": rest.rstrip("/"), "ok": response_height == str(height) and bool(amount), "response_height": response_height}
    except Exception as exc:
        return {"provider": name, "rest": rest.rstrip("/"), "ok": False, "reason": f"{type(exc).__name__}: {exc}"}


with concurrent.futures.ThreadPoolExecutor(max_workers=len(PROVIDERS)) as pool:
    rest_probes = list(pool.map(historical_rest_probe, PROVIDERS))
valid_rest = [r for r in rest_probes if r.get("ok")]
if not valid_rest:
    raise SystemExit("no REST endpoint proved historical state at the selected height")
preferred = next((r for r in valid_rest if r["provider"] == primary_rpc_provider), valid_rest[0])
primary_rest, primary_rest_provider = preferred["rest"], preferred["provider"]
manifest = {
    "chain_id": CHAIN_ID,
    "height": height,
    "selected_block": selected,
    "primary_rpc_provider": primary_rpc_provider,
    "primary_rpc": primary_rpc,
    "primary_rest_provider": primary_rest_provider,
    "primary_rest": primary_rest,
    "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "tool": "research/ixo-3947/capture_ci.py",
}
(OUT / "run-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def capture_rpc(name: str, path: str) -> bool:
    url = primary_rpc.rstrip("/") + path
    target = OUT / f"raw/rpc/{name}.json"
    try:
        _, headers, _, body = request_json(url)
        save_response(target, body, headers)
        record_query(name, url, True)
        return True
    except Exception as exc:
        record_query(name, url, False, f"{type(exc).__name__}: {exc}")
        return False


def capture_rest(name: str, path: str) -> bool:
    url = primary_rest.rstrip("/") + path
    req_headers = {"x-cosmos-block-height": str(height)}
    target = OUT / f"raw/rest/{name}.json"
    try:
        _, headers, _, body = request_json(url, headers=req_headers)
        response_height = headers.get("x-cosmos-block-height") or headers.get("grpc-metadata-x-cosmos-block-height")
        if response_height and response_height != str(height):
            raise RuntimeError(f"response height {response_height} != selected {height}")
        save_response(target, body, headers)
        record_query(name, url, True)
        return True
    except Exception as exc:
        record_query(name, url, False, f"{type(exc).__name__}: {exc}")
        return False


for name, path in [
    ("status_primary", "/status"),
    (f"block_{height}", f"/block?height={height}"),
    (f"commit_{height}", f"/commit?height={height}"),
    (f"consensus_params_{height}", f"/consensus_params?height={height}"),
    ("consensus_validators_1", f"/validators?height={height}&page=1&per_page=100"),
]:
    capture_rpc(name, path)

rest_queries = [
    ("node_info", "/cosmos/base/tendermint/v1beta1/node_info"),
    ("module_versions", "/cosmos/upgrade/v1beta1/module_versions"),
    ("current_upgrade_plan", "/cosmos/upgrade/v1beta1/current_plan"),
    ("bank_supply_all", "/cosmos/bank/v1beta1/supply?pagination.limit=10000"),
    ("bank_supply_uixo", "/cosmos/bank/v1beta1/supply/uixo"),
    ("bank_params", "/cosmos/bank/v1beta1/params"),
    ("auth_module_accounts", "/cosmos/auth/v1beta1/module_accounts?pagination.limit=1000"),
    ("staking_pool", "/cosmos/staking/v1beta1/pool"),
    ("staking_params", "/cosmos/staking/v1beta1/params"),
    ("distribution_community_pool", "/cosmos/distribution/v1beta1/community_pool"),
    ("distribution_params", "/cosmos/distribution/v1beta1/params"),
    ("cosmos_mint_params", "/cosmos/mint/v1beta1/params"),
    ("cosmos_mint_inflation", "/cosmos/mint/v1beta1/inflation"),
    ("cosmos_mint_annual_provisions", "/cosmos/mint/v1beta1/annual_provisions"),
    ("ixo_mint_params", "/ixo/mint/v1beta1/params"),
    ("ixo_mint_epoch_provisions", "/ixo/mint/v1beta1/epoch_provisions"),
    ("validators_bonded", "/cosmos/staking/v1beta1/validators?status=BOND_STATUS_BONDED&pagination.limit=1000"),
    ("validators_unbonding", "/cosmos/staking/v1beta1/validators?status=BOND_STATUS_UNBONDING&pagination.limit=1000"),
    ("validators_unbonded", "/cosmos/staking/v1beta1/validators?status=BOND_STATUS_UNBONDED&pagination.limit=1000"),
    ("slashing_params", "/cosmos/slashing/v1beta1/params"),
    ("gov_params_deposit", "/cosmos/gov/v1/params/deposit"),
    ("gov_params_voting", "/cosmos/gov/v1/params/voting"),
    ("gov_params_tallying", "/cosmos/gov/v1/params/tallying"),
    ("gov_proposals", "/cosmos/gov/v1/proposals?pagination.limit=1000"),
    ("ibc_channels", "/ibc/core/channel/v1/channels?pagination.limit=1000"),
    ("ibc_connections", "/ibc/core/connection/v1/connections?pagination.limit=1000"),
    ("ibc_clients", "/ibc/core/client/v1/client_states?pagination.limit=1000"),
    ("ibc_denom_traces", "/ibc/apps/transfer/v1/denom_traces?pagination.limit=1000"),
    ("ibc_transfer_params", "/ibc/apps/transfer/v1/params"),
    ("ibc_total_escrow_uixo", "/ibc/apps/transfer/v1/denoms/uixo/total_escrow"),
    ("liquidstake_module_params", "/ixo/liquidstake/v1beta1/module_params"),
    ("liquidstake_pools", "/ixo/liquidstake/v1beta1/pools?pagination.limit=1000"),
    ("liquidstake_states", "/ixo/liquidstake/v1beta1/states?pagination.limit=1000"),
]
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    list(pool.map(lambda item: capture_rest(*item), rest_queries))

module_payload_path = OUT / "raw/rest/auth_module_accounts.json"
if module_payload_path.exists():
    module_payload = json.loads(module_payload_path.read_text(encoding="utf-8"))
    addresses: set[str] = set()
    stack: list[Any] = [module_payload]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            address = item.get("address")
            if isinstance(address, str) and address.startswith("ixo1"):
                addresses.add(address)
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    (OUT / "module-addresses.txt").write_text("\n".join(sorted(addresses)) + ("\n" if addresses else ""), encoding="utf-8")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda addr: capture_rest(f"module_balance_{addr}", f"/cosmos/bank/v1beta1/balances/{addr}?pagination.limit=10000"), sorted(addresses)))

gov_path = OUT / "raw/rest/gov_proposals.json"
if gov_path.exists():
    payload = json.loads(gov_path.read_text(encoding="utf-8"))
    ids = sorted({int(p.get("id") or p.get("proposal_id")) for p in payload.get("proposals", []) if p.get("id") or p.get("proposal_id")}, reverse=True)[:GOV_DETAIL_LIMIT]
    (OUT / "proposal-ids.txt").write_text("\n".join(map(str, ids)) + ("\n" if ids else ""), encoding="utf-8")
    details = []
    for pid in ids:
        details.extend([
            (f"gov_proposal_{pid}", f"/cosmos/gov/v1/proposals/{pid}"),
            (f"gov_deposits_{pid}", f"/cosmos/gov/v1/proposals/{pid}/deposits?pagination.limit=1000"),
            (f"gov_votes_{pid}", f"/cosmos/gov/v1/proposals/{pid}/votes?pagination.limit=1000"),
            (f"gov_tally_{pid}", f"/cosmos/gov/v1/proposals/{pid}/tally"),
        ])
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda item: capture_rest(*item), details))

low = max(1, height - ACTIVITY_BLOCKS + 1)
(OUT / "activity-low-height.txt").write_text(f"{low}\n", encoding="utf-8")
for page in range(1, MAX_TX_PAGES + 1):
    query = urllib.parse.urlencode({
        "query": f"tx.height >= {low} AND tx.height <= {height}",
        "prove": "false",
        "page": str(page),
        "per_page": "100",
        "order_by": "asc",
    })
    url = f"{primary_rpc}/tx_search?{query}"
    target = OUT / f"raw/rpc/tx_search_{page}.json"
    try:
        payload, headers, _, body = request_json(url)
        save_response(target, body, headers)
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        record_query(f"tx_search_{page}", url, True)
        txs = (payload.get("result") or {}).get("txs") or []
        total = int((payload.get("result") or {}).get("total_count") or 0)
        if not txs or page * 100 >= total:
            break
    except Exception as exc:
        record_query(f"tx_search_{page}", url, False, f"{type(exc).__name__}: {exc}")
        break

market_urls = {
    "coingecko_market_chart": "https://api.coingecko.com/api/v3/coins/ixo/market_chart?vs_currency=usd&days=1&interval=hourly",
    "coingecko_tickers": "https://api.coingecko.com/api/v3/coins/ixo/tickers?include_exchange_logo=false&depth=true",
}
for name, url in market_urls.items():
    try:
        _, headers, _, body = request_json(url)
        save_response(OUT / f"raw/market/{name}.json", body, headers)
        record_query(name, url, True)
    except Exception as exc:
        record_query(name, url, False, f"{type(exc).__name__}: {exc}")

subprocess.run([sys.executable, str(Path(__file__).with_name("derive.py")), str(OUT)], check=True)

hash_lines = []
for path in sorted(p for p in OUT.rglob("*") if p.is_file() and p != OUT / "hashes/sha256sums.txt"):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    hash_lines.append(f"{digest}  {path.relative_to(OUT).as_posix()}")
(OUT / "hashes/sha256sums.txt").write_text("\n".join(hash_lines) + "\n", encoding="utf-8")

query_rows = [json.loads(line) for line in (OUT / "query-status.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
result = {
    "completed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "successful_queries": sum(bool(row.get("ok")) for row in query_rows),
    "failed_queries": sum(not bool(row.get("ok")) for row in query_rows),
}
(OUT / "run-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2, sort_keys=True))
