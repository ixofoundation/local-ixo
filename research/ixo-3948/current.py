#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures
import json
import os
import time
import urllib.parse
from collections import defaultdict
from decimal import Decimal
from typing import Any

from common import CHAIN_ID, OUT, account_address, dec, dump, fetch, save, status, technical_class, uixo, write_csv

RPCS = [
    ("first_party", "https://impacthub.ixo.world/rpc"),
    ("ibs", "https://ixo.ibs.team/rpc"),
    ("stavr", "https://ixo.rpc.m.stavr.tech:443"),
    ("bluestake", "https://ixo-rpc.bluestake.net:443"),
]
RESTS = [
    ("first_party", "https://impacthub.ixo.world/rest"),
    ("ibs", "https://ixo.ibs.team/api"),
    ("stavr", "https://ixo.api.m.stavr.tech"),
    ("bluestake", "https://ixo-api.bluestake.net"),
]
TOP_ACCOUNT_LOOKUPS = int(os.environ.get("TOP_ACCOUNT_LOOKUPS", "100"))


def rpc_status(item: tuple[str, str]) -> dict[str, Any]:
    provider, rpc = item
    url = rpc.rstrip("/") + "/status"
    code, headers, body = fetch(url)
    save(OUT / f"raw/current/rpc/status_{provider}.json", body, headers)
    if code != 200:
        return {"provider": provider, "endpoint": rpc, "ok": False, "reason": f"HTTP {code}"}
    try:
        result = json.loads(body)["result"]
        return {
            "provider": provider,
            "endpoint": rpc.rstrip("/"),
            "ok": result["node_info"]["network"] == CHAIN_ID and not result["sync_info"]["catching_up"],
            "height": int(result["sync_info"]["latest_block_height"]),
        }
    except Exception as exc:
        return {"provider": provider, "endpoint": rpc, "ok": False, "reason": str(exc)}


with concurrent.futures.ThreadPoolExecutor(max_workers=len(RPCS)) as pool:
    health = list(pool.map(rpc_status, RPCS))
healthy = [row for row in health if row.get("ok")]
if len(healthy) < 2:
    raise SystemExit("fewer than two healthy current RPC providers")
height = sorted((row["height"] for row in healthy), reverse=True)[1]


def rpc_block(row: dict[str, Any]) -> dict[str, Any]:
    url = f"{row['endpoint']}/block?height={height}"
    code, headers, body = fetch(url)
    save(OUT / f"raw/current/rpc/block_{row['provider']}_{height}.json", body, headers)
    if code != 200:
        return {"ok": False, "provider": row["provider"]}
    result = json.loads(body)["result"]
    header = result["block"]["header"]
    return {
        "ok": header["chain_id"] == CHAIN_ID,
        "provider": row["provider"],
        "endpoint": row["endpoint"],
        "height": int(header["height"]),
        "block_hash": result["block_id"]["hash"],
        "app_hash": header["app_hash"],
        "time": header["time"],
    }


with concurrent.futures.ThreadPoolExecutor(max_workers=len(healthy)) as pool:
    blocks = list(pool.map(rpc_block, healthy))
groups: defaultdict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
for row in blocks:
    if row.get("ok"):
        groups[(row["height"], row["block_hash"], row["app_hash"])].append(row)
winners = [(key, rows) for key, rows in groups.items() if len(rows) >= 2]
if not winners:
    raise SystemExit("no two-provider current block agreement")
winners.sort(key=lambda item: len(item[1]), reverse=True)
block_key, agreeing = winners[0]
selected_block = {
    "height": block_key[0],
    "block_hash": block_key[1],
    "app_hash": block_key[2],
    "time": agreeing[0]["time"],
    "providers": [row["provider"] for row in agreeing],
    "rpc_endpoints": [row["endpoint"] for row in agreeing],
}
dump(OUT / "raw/current/selected-block.json", selected_block)

valid_rests: list[tuple[str, str]] = []
for provider, rest in RESTS:
    url = rest.rstrip("/") + "/cosmos/bank/v1beta1/supply/by_denom?denom=uixo"
    code, headers, body = fetch(url, headers={"x-cosmos-block-height": str(height)})
    save(OUT / f"raw/current/rest/probe_supply_{provider}.json", body, headers)
    response_height = headers.get("x-cosmos-block-height") or headers.get("grpc-metadata-x-cosmos-block-height")
    if code == 200 and (not response_height or response_height == str(height)):
        valid_rests.append((provider, rest.rstrip("/")))
if not valid_rests:
    raise SystemExit("no current REST endpoint proved fixed-height state")
rest_provider, rest = next((item for item in valid_rests if item[0] == "ibs"), valid_rests[0])


def rest_get(name: str, path: str, required: bool = False) -> Any | None:
    url = rest + path
    code, headers, body = fetch(url, headers={"x-cosmos-block-height": str(height)})
    save(OUT / f"raw/current/rest/{name}.json", body, headers)
    if code != 200:
        status(name, url, False, f"HTTP {code}: {body[:300].decode('utf-8', 'replace')}")
        if required:
            raise SystemExit(f"required query {name} failed")
        return None
    response_height = headers.get("x-cosmos-block-height") or headers.get("grpc-metadata-x-cosmos-block-height")
    if response_height and response_height != str(height):
        status(name, url, False, f"response height {response_height} != {height}")
        if required:
            raise SystemExit(f"required query {name} returned wrong height")
        return None
    status(name, url, True)
    return json.loads(body)


supply_payload = rest_get("bank_supply_uixo", "/cosmos/bank/v1beta1/supply/by_denom?denom=uixo", True)
current_supply = uixo(supply_payload)
modules_payload = rest_get("module_accounts", "/cosmos/auth/v1beta1/module_accounts?pagination.limit=1000", True) or {}
staking_pool = rest_get("staking_pool", "/cosmos/staking/v1beta1/pool", True) or {}
community_pool = rest_get("community_pool", "/cosmos/distribution/v1beta1/community_pool") or {}
ibc_escrow = rest_get("ibc_total_escrow_uixo", "/ibc/apps/transfer/v1/denoms/uixo/total_escrow") or {}
liquid_pools = rest_get("liquidstake_pools", "/ixo/liquidstake/v1beta1/pools?pagination.limit=1000") or {}
mint_params = rest_get("ixo_mint_params", "/ixo/mint/v1beta1/params") or {}
epoch_provisions = rest_get("ixo_epoch_provisions", "/ixo/mint/v1beta1/epoch_provisions") or {}

module_addresses: dict[str, str] = {}
for account in modules_payload.get("accounts", []) or []:
    if not isinstance(account, dict):
        continue
    address = account_address(account)
    if address:
        module_addresses[address] = account.get("name", "module")
liquid_proxy_addresses = {
    pool.get("proxy_account_address", "")
    for pool in liquid_pools.get("pools", []) or []
    if isinstance(pool, dict) and pool.get("proxy_account_address")
}

owners: list[dict[str, Any]] = []
next_key: str | None = None
page = 1
while page <= 100:
    params = {"pagination.limit": "500"}
    if next_key:
        params["pagination.key"] = next_key
    payload = rest_get(
        f"denom_owners_page_{page}",
        "/cosmos/bank/v1beta1/denom_owners/uixo?" + urllib.parse.urlencode(params),
        required=(page == 1),
    ) or {}
    owners.extend(payload.get("denom_owners", []) or [])
    next_key = (payload.get("pagination") or {}).get("next_key")
    if not next_key:
        break
    page += 1
    time.sleep(0.1)

rows: list[dict[str, Any]] = []
for owner in owners:
    address = owner.get("address", "")
    balance = uixo(owner.get("balance", owner))
    module_name = module_addresses.get(address, "")
    classification = "protocol-module" if module_name else (
        "liquid-stake-proxy" if address in liquid_proxy_addresses else "ordinary-or-unknown"
    )
    rows.append({
        "address": address,
        "uixo": str(balance),
        "ixo": str(balance / Decimal(1_000_000)),
        "share_of_supply": str(balance / current_supply) if current_supply else "0",
        "technical_class": classification,
        "module_name": module_name,
        "account_type": "not-queried",
        "beneficial_control": "unknown-not-inferred",
    })
rows.sort(key=lambda row: dec(row["uixo"]), reverse=True)

# Account-type coverage is limited to the largest balances and never treated as
# complete beneficial-control classification.
for row in rows[:TOP_ACCOUNT_LOOKUPS]:
    payload = rest_get(f"account_{row['address']}", f"/cosmos/auth/v1beta1/accounts/{row['address']}") or {}
    account = payload.get("account", {}) if isinstance(payload, dict) else {}
    row["account_type"] = account.get("@type", "") if isinstance(account, dict) else ""
    if row["technical_class"] == "ordinary-or-unknown":
        inferred = technical_class(row["account_type"])
        if inferred != "ordinary-or-unknown":
            row["technical_class"] = inferred

write_csv(OUT / "cleaned/current_owners.csv", rows, [
    "address", "uixo", "ixo", "share_of_supply", "technical_class", "module_name",
    "account_type", "beneficial_control",
])

pool = staking_pool.get("pool") or {}
summary = {
    "height": height,
    "block": selected_block,
    "rest_provider": rest_provider,
    "rest": rest,
    "bank_supply_uixo": str(current_supply),
    "denom_owner_count": len(rows),
    "denom_owner_sum_uixo": str(sum((dec(row["uixo"]) for row in rows), Decimal(0))),
    "module_addresses": module_addresses,
    "module_balance_uixo": str(sum((dec(row["uixo"]) for row in rows if row["technical_class"] == "protocol-module"), Decimal(0))),
    "community_pool_uixo_decimal": str(uixo(community_pool)),
    "ibc_escrow_uixo": str(uixo(ibc_escrow)),
    "bonded_uixo": str(dec(pool.get("bonded_tokens"))),
    "not_bonded_uixo": str(dec(pool.get("not_bonded_tokens"))),
    "liquid_pools": liquid_pools.get("pools", []) if isinstance(liquid_pools, dict) else [],
    "mint_params": mint_params.get("params") if isinstance(mint_params, dict) else None,
    "epoch_provisions_uixo": str((epoch_provisions.get("epoch_provisions") if isinstance(epoch_provisions, dict) else None) or ""),
    "account_type_lookups": min(TOP_ACCOUNT_LOOKUPS, len(rows)),
}
dump(OUT / "derived/current-summary.json", summary)
print(json.dumps({key: summary[key] for key in ["height", "bank_supply_uixo", "denom_owner_count", "denom_owner_sum_uixo", "module_balance_uixo"]}, indent=2))
