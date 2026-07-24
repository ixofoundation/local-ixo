#!/usr/bin/env python3
"""Normalize deployed IXO v8 response shapes after the generic derivation pass."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

root = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/ixo-3947")
raw = root / "raw" / "rest"
cleaned = root / "cleaned"
derived = root / "derived"


def load(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

pools_payload = load(raw / "liquidstake_pools.json") or {}
pools = pools_payload.get("pools", []) if isinstance(pools_payload, dict) else []
states_payload = load(raw / "liquidstake_states.json") or {}
state = states_payload.get("net_amount_state") if isinstance(states_payload, dict) else None

rows: list[dict[str, Any]] = []
if isinstance(state, dict):
    pool_id = pools[0].get("pool_id", "zero") if pools and isinstance(pools[0], dict) else "zero"
    row = {"pool_id": pool_id}
    for key in [
        "stake_rate", "unstake_rate", "stkixo_total_supply", "net_amount",
        "total_del_shares", "total_liquid_tokens", "total_remaining_rewards",
        "total_unbonding_balance", "proxy_acc_balance",
    ]:
        row[key] = state.get(key, "")
    rows.append(row)

fields = [
    "pool_id", "stake_rate", "unstake_rate", "stkixo_total_supply", "net_amount",
    "total_del_shares", "total_liquid_tokens", "total_remaining_rewards",
    "total_unbonding_balance", "proxy_acc_balance",
]
with (cleaned / "liquid_staking.csv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)

summary = load(derived / "summary.json") or {}
summary["liquid_staking_pool_count"] = len(pools)
summary["liquid_staking_state_count"] = len(rows)
summary["liquid_staking_pools"] = [
    {
        "pool_id": pool.get("pool_id"),
        "liquid_bond_denom": pool.get("liquid_bond_denom"),
        "paused": pool.get("paused"),
        "validator_count": len(pool.get("whitelisted_validators", []) or []),
    }
    for pool in pools if isinstance(pool, dict)
]
save(derived / "summary.json", summary)

reconciliation = load(derived / "reconciliation.json") or {}
reconciliation["liquid_staking_pool_count"] = len(pools)
reconciliation["liquid_staking_state_count"] = len(rows)
if isinstance(state, dict):
    reconciliation["liquid_staking_net_amount_uixo"] = state.get("net_amount")
    reconciliation["liquid_staking_token_supply"] = state.get("stkixo_total_supply")
save(derived / "reconciliation.json", reconciliation)

validation = load(derived / "validation.json") or {}
checks = validation.setdefault("extended_checks", {})
checks["liquid_staking_pool_configuration_captured"] = len(pools) > 0
checks["liquid_staking_live_state_captured"] = len(rows) > 0
save(derived / "validation.json", validation)
