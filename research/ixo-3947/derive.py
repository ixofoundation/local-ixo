#!/usr/bin/env python3
from __future__ import annotations

import base64
import csv
import json
import sys
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/ixo-3947")
RAW_REST = ROOT / "raw" / "rest"
RAW_RPC = ROOT / "raw" / "rpc"
CLEANED = ROOT / "cleaned"
DERIVED = ROOT / "derived"
CLEANED.mkdir(parents=True, exist_ok=True)
DERIVED.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def decimal(value: Any, default: Decimal = Decimal(0)) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    if fieldnames is None:
        fieldnames = sorted({key for row in rows for key in row}) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        if not fieldnames:
            handle.write("")
            return
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def coin_amount(payload: Any, denom: str = "uixo") -> Decimal:
    if payload is None:
        return Decimal(0)
    if isinstance(payload, dict):
        if payload.get("denom") == denom and "amount" in payload:
            return decimal(payload.get("amount"))
        for key in ("amount", "balance", "supply", "pool"):
            if key in payload:
                found = coin_amount(payload[key], denom)
                if found:
                    return found
        for value in payload.values():
            found = coin_amount(value, denom)
            if found:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = coin_amount(value, denom)
            if found:
                return found
    return Decimal(0)


def all_coins(payload: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    if isinstance(payload, dict):
        if isinstance(payload.get("denom"), str) and "amount" in payload:
            result.append({"denom": payload["denom"], "amount": str(payload["amount"])})
        else:
            for value in payload.values():
                result.extend(all_coins(value))
    elif isinstance(payload, list):
        for value in payload:
            result.extend(all_coins(value))
    return result


def flatten_accounts(payload: Any) -> list[dict[str, Any]]:
    accounts = []
    if not isinstance(payload, dict):
        return accounts
    for account in payload.get("accounts", []):
        if not isinstance(account, dict):
            continue
        address = account.get("address")
        if not address:
            address = account.get("base_account", {}).get("address") if isinstance(account.get("base_account"), dict) else None
        if not address and isinstance(account.get("base_vesting_account"), dict):
            address = account["base_vesting_account"].get("base_account", {}).get("address")
        accounts.append({
            "address": address or "",
            "name": account.get("name", ""),
            "type": account.get("@type", ""),
            "permissions": ",".join(account.get("permissions", []) or []),
        })
    return accounts


def maybe_b64(value: Any) -> str:
    if not isinstance(value, str):
        return str(value)
    try:
        raw = base64.b64decode(value, validate=True)
        text = raw.decode("utf-8")
        if text and all(ch.isprintable() or ch in "\r\n\t" for ch in text):
            return text
    except Exception:
        pass
    return value


def iter_event_attributes(tx_result: dict[str, Any]) -> Iterable[tuple[str, str, str]]:
    for event in tx_result.get("events", []) or []:
        event_type = maybe_b64(event.get("type", ""))
        for attr in event.get("attributes", []) or []:
            yield event_type, maybe_b64(attr.get("key", "")), maybe_b64(attr.get("value", ""))

manifest = read_json(ROOT / "run-manifest.json") or {}
selected = read_json(ROOT / "selected-block.json") or {}
height = int(manifest.get("height") or selected.get("height") or 0)
block_time = selected.get("time") or ""

supply_all = read_json(RAW_REST / "bank_supply_all.json")
supply_rows: list[dict[str, Any]] = []
if isinstance(supply_all, dict):
    for coin in supply_all.get("supply", []) or []:
        if isinstance(coin, dict):
            supply_rows.append({"denom": coin.get("denom", ""), "amount_base_units": coin.get("amount", "")})
supply_uixo_payload = read_json(RAW_REST / "bank_supply_uixo.json")
bank_supply_uixo = coin_amount(supply_uixo_payload)
if bank_supply_uixo == 0:
    for row in supply_rows:
        if row["denom"] == "uixo":
            bank_supply_uixo = decimal(row["amount_base_units"])
            break
write_csv(CLEANED / "supply.csv", supply_rows, ["denom", "amount_base_units"])

module_accounts = flatten_accounts(read_json(RAW_REST / "auth_module_accounts.json"))
module_balance_total_uixo = Decimal(0)
for account in module_accounts:
    address = account["address"]
    payload = read_json(RAW_REST / f"module_balance_{address}.json") if address else None
    coins = all_coins(payload)
    uixo = sum((decimal(c["amount"]) for c in coins if c["denom"] == "uixo"), Decimal(0))
    module_balance_total_uixo += uixo
    account["uixo_balance"] = str(uixo)
    account["other_balances"] = json.dumps([c for c in coins if c["denom"] != "uixo"], sort_keys=True)
write_csv(CLEANED / "module_accounts.csv", module_accounts, ["name", "type", "address", "permissions", "uixo_balance", "other_balances"])

staking_pool = read_json(RAW_REST / "staking_pool.json") or {}
pool_obj = staking_pool.get("pool", staking_pool) if isinstance(staking_pool, dict) else {}
bonded_uixo = decimal(pool_obj.get("bonded_tokens") if isinstance(pool_obj, dict) else 0)
not_bonded_uixo = decimal(pool_obj.get("not_bonded_tokens") if isinstance(pool_obj, dict) else 0)
validators_payload = read_json(RAW_REST / "validators_bonded.json") or {}
validators = validators_payload.get("validators", []) if isinstance(validators_payload, dict) else []
validator_rows: list[dict[str, Any]] = []
for val in validators:
    if not isinstance(val, dict):
        continue
    commission = val.get("commission", {}) if isinstance(val.get("commission"), dict) else {}
    rates = commission.get("commission_rates", {}) if isinstance(commission.get("commission_rates"), dict) else {}
    validator_rows.append({
        "operator_address": val.get("operator_address", ""),
        "moniker": (val.get("description") or {}).get("moniker", "") if isinstance(val.get("description"), dict) else "",
        "status": val.get("status", ""),
        "tokens_uixo": str(val.get("tokens", "0")),
        "delegator_shares": str(val.get("delegator_shares", "0")),
        "commission_rate": str(rates.get("rate", "")),
        "commission_max_rate": str(rates.get("max_rate", "")),
        "commission_max_change_rate": str(rates.get("max_change_rate", "")),
        "jailed": val.get("jailed", False),
        "unbonding_height": val.get("unbonding_height", ""),
        "affiliation_status": "unverified",
    })
validator_rows.sort(key=lambda row: decimal(row["tokens_uixo"]), reverse=True)
write_csv(CLEANED / "validators.csv", validator_rows, [
    "operator_address", "moniker", "status", "tokens_uixo", "delegator_shares",
    "commission_rate", "commission_max_rate", "commission_max_change_rate",
    "jailed", "unbonding_height", "affiliation_status",
])

weights = [decimal(row["tokens_uixo"]) for row in validator_rows]
total_validator_tokens = sum(weights, Decimal(0))
shares = [(w / total_validator_tokens) if total_validator_tokens else Decimal(0) for w in weights]

def top_share(n: int) -> str:
    return str(sum(shares[:n], Decimal(0)))

def min_for_threshold(threshold: Decimal) -> int | None:
    running = Decimal(0)
    for index, share in enumerate(shares, start=1):
        running += share
        if running >= threshold:
            return index
    return None

concentration = {
    "bonded_validator_count": len(validator_rows),
    "validator_tokens_uixo": str(total_validator_tokens),
    "top_1_share": top_share(1),
    "top_3_share": top_share(3),
    "top_5_share": top_share(5),
    "top_10_share": top_share(10),
    "hhi": str(sum((share * share for share in shares), Decimal(0))),
    "minimum_validators_for_one_third": min_for_threshold(Decimal(1) / Decimal(3)),
    "minimum_validators_for_one_half": min_for_threshold(Decimal(1) / Decimal(2)),
    "minimum_validators_for_two_thirds": min_for_threshold(Decimal(2) / Decimal(3)),
}
write_json(DERIVED / "concentration.json", concentration)

consensus_rows: list[dict[str, Any]] = []
for path in sorted(RAW_RPC.glob("consensus_validators_*.json")):
    payload = read_json(path) or {}
    for val in ((payload.get("result") or {}).get("validators") or []):
        consensus_rows.append({
            "address": val.get("address", ""),
            "pub_key_type": (val.get("pub_key") or {}).get("type", ""),
            "pub_key_value": (val.get("pub_key") or {}).get("value", ""),
            "voting_power": val.get("voting_power", "0"),
            "proposer_priority": val.get("proposer_priority", "0"),
        })
write_csv(CLEANED / "consensus_validators.csv", consensus_rows, ["address", "pub_key_type", "pub_key_value", "voting_power", "proposer_priority"])

community_pool_payload = read_json(RAW_REST / "distribution_community_pool.json")
community_pool_uixo = coin_amount(community_pool_payload)

def first_value(paths: list[Path], keys: list[str]) -> Any:
    for path in paths:
        payload = read_json(path)
        if payload is None:
            continue
        stack = [payload]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                for key in keys:
                    if key in item:
                        return item[key]
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
    return None

inflation = first_value([RAW_REST / "cosmos_mint_inflation.json", RAW_REST / "ixo_mint_params.json"], ["inflation", "inflation_rate"])
annual_provisions = first_value([RAW_REST / "cosmos_mint_annual_provisions.json", RAW_REST / "ixo_mint_epoch_provisions.json"], ["annual_provisions", "epoch_provisions", "provisions"])

gov_payload = read_json(RAW_REST / "gov_proposals.json") or {}
gov_rows: list[dict[str, Any]] = []
for prop in gov_payload.get("proposals", []) if isinstance(gov_payload, dict) else []:
    if not isinstance(prop, dict):
        continue
    pid = str(prop.get("id") or prop.get("proposal_id") or "")
    tally_payload = read_json(RAW_REST / f"gov_tally_{pid}.json") or {}
    tally = tally_payload.get("tally", tally_payload.get("tally_result", {})) if isinstance(tally_payload, dict) else {}
    messages = prop.get("messages", []) or []
    gov_rows.append({
        "proposal_id": pid,
        "status": prop.get("status", ""),
        "title": prop.get("title", "") or (prop.get("metadata", "") if not messages else ""),
        "message_types": ",".join(sorted({m.get("@type", "") for m in messages if isinstance(m, dict)})),
        "submit_time": prop.get("submit_time", ""),
        "deposit_end_time": prop.get("deposit_end_time", ""),
        "voting_start_time": prop.get("voting_start_time", ""),
        "voting_end_time": prop.get("voting_end_time", ""),
        "yes_count": tally.get("yes_count", "") if isinstance(tally, dict) else "",
        "abstain_count": tally.get("abstain_count", "") if isinstance(tally, dict) else "",
        "no_count": tally.get("no_count", "") if isinstance(tally, dict) else "",
        "no_with_veto_count": tally.get("no_with_veto_count", "") if isinstance(tally, dict) else "",
    })
write_csv(CLEANED / "governance.csv", gov_rows, [
    "proposal_id", "status", "title", "message_types", "submit_time", "deposit_end_time",
    "voting_start_time", "voting_end_time", "yes_count", "abstain_count", "no_count", "no_with_veto_count",
])

ibc_payload = read_json(RAW_REST / "ibc_channels.json") or {}
ibc_rows: list[dict[str, Any]] = []
for channel in ibc_payload.get("channels", []) if isinstance(ibc_payload, dict) else []:
    if not isinstance(channel, dict):
        continue
    counterparty = channel.get("counterparty", {}) if isinstance(channel.get("counterparty"), dict) else {}
    ibc_rows.append({
        "port_id": channel.get("port_id", ""),
        "channel_id": channel.get("channel_id", ""),
        "state": channel.get("state", ""),
        "ordering": channel.get("ordering", ""),
        "counterparty_port_id": counterparty.get("port_id", ""),
        "counterparty_channel_id": counterparty.get("channel_id", ""),
        "connection_hops": ",".join(channel.get("connection_hops", []) or []),
        "version": channel.get("version", ""),
    })
write_csv(CLEANED / "ibc_channels.csv", ibc_rows, [
    "port_id", "channel_id", "state", "ordering", "counterparty_port_id",
    "counterparty_channel_id", "connection_hops", "version",
])
ibc_escrow_uixo = coin_amount(read_json(RAW_REST / "ibc_total_escrow_uixo.json"))

liquid_payload = read_json(RAW_REST / "liquidstake_states.json") or {}
liquid_rows: list[dict[str, Any]] = []
for state in liquid_payload.get("states", []) if isinstance(liquid_payload, dict) else []:
    if not isinstance(state, dict):
        continue
    liquid_rows.append({key: state.get(key, "") for key in [
        "pool_id", "stake_rate", "unstake_rate", "stkixo_total_supply", "net_amount",
        "total_del_shares", "total_liquid_tokens", "total_remaining_rewards",
        "total_unbonding_balance", "proxy_acc_balance",
    ]})
write_csv(CLEANED / "liquid_staking.csv", liquid_rows)

tx_count = 0
success_count = 0
failed_count = 0
senders: set[str] = set()
actions: Counter[str] = Counter()
fees_by_denom: defaultdict[str, Decimal] = defaultdict(Decimal)
heights: list[int] = []
activity_rows: list[dict[str, Any]] = []
for path in sorted(RAW_RPC.glob("tx_search_*.json")):
    payload = read_json(path) or {}
    txs = ((payload.get("result") or {}).get("txs") or []) if isinstance(payload, dict) else []
    for tx in txs:
        tx_count += 1
        result = tx.get("tx_result", {}) if isinstance(tx, dict) else {}
        code = int(result.get("code", 0) or 0)
        success_count += int(code == 0)
        failed_count += int(code != 0)
        try:
            heights.append(int(tx.get("height", 0)))
        except Exception:
            pass
        row_actions: list[str] = []
        row_senders: list[str] = []
        for event_type, key, value in iter_event_attributes(result):
            normalized_key = key.lower()
            if normalized_key in {"action", "message.action", "msg_type", "message_type"}:
                actions[value] += 1
                row_actions.append(value)
            if normalized_key in {"sender", "message.sender", "spender", "granter", "delegator"} and value.startswith("ixo1"):
                senders.add(value)
                row_senders.append(value)
            if normalized_key in {"fee", "tx.fee"}:
                for part in value.split(","):
                    digits = "".join(ch for ch in part if ch.isdigit() or ch in ".-")
                    denom = part[len(digits):]
                    if digits and denom:
                        fees_by_denom[denom] += decimal(digits)
        activity_rows.append({
            "height": tx.get("height", ""),
            "hash": tx.get("hash", ""),
            "code": code,
            "gas_wanted": result.get("gas_wanted", ""),
            "gas_used": result.get("gas_used", ""),
            "actions": ",".join(sorted(set(row_actions))),
            "senders": ",".join(sorted(set(row_senders))),
        })
write_csv(CLEANED / "activity.csv", activity_rows, ["height", "hash", "code", "gas_wanted", "gas_used", "actions", "senders"])
activity_summary = {
    "window_low_height": min(heights) if heights else None,
    "window_high_height": max(heights) if heights else None,
    "transactions": tx_count,
    "successful_transactions": success_count,
    "failed_transactions": failed_count,
    "unique_observed_senders": len(senders),
    "module_actions": dict(actions.most_common()),
    "fees_by_denom": {k: str(v) for k, v in sorted(fees_by_denom.items())},
    "limitation": "Active addresses are event-observed senders in the captured tx_search height window, not a proof of unique human users.",
}
write_json(DERIVED / "activity-summary.json", activity_summary)

tickers: list[dict[str, Any]] = []
for path in sorted((ROOT / "raw" / "market").glob("*.json")):
    payload = read_json(path)
    if isinstance(payload, dict) and isinstance(payload.get("tickers"), list):
        for ticker in payload["tickers"]:
            market = ticker.get("market", {}) if isinstance(ticker.get("market"), dict) else {}
            tickers.append({
                "market": market.get("name", ""),
                "base": ticker.get("base", ""),
                "target": ticker.get("target", ""),
                "last": ticker.get("last", ""),
                "volume": ticker.get("volume", ""),
                "bid_ask_spread_percentage": ticker.get("bid_ask_spread_percentage", ""),
                "depth_plus_2": ticker.get("cost_to_move_up_usd", ""),
                "depth_minus_2": ticker.get("cost_to_move_down_usd", ""),
                "last_traded_at": ticker.get("last_traded_at", ""),
                "is_stale": ticker.get("is_stale", ""),
                "is_anomaly": ticker.get("is_anomaly", ""),
            })
write_csv(CLEANED / "market_liquidity.csv", tickers)
market_summary = {
    "ticker_count": len(tickers),
    "non_stale_non_anomalous_tickers": sum(1 for t in tickers if t.get("is_stale") is False and t.get("is_anomaly") is False),
    "tickers_with_spread": sum(1 for t in tickers if t.get("bid_ask_spread_percentage") not in (None, "")),
    "tickers_with_depth": sum(1 for t in tickers if t.get("depth_plus_2") not in (None, "") or t.get("depth_minus_2") not in (None, "")),
    "valuation_eligible": False,
    "reason": "No ticker is promoted to valuation without contemporaneous spread, depth, volume, venue and anomaly checks.",
}
write_json(DERIVED / "market-summary.json", market_summary)

reconciliation = {
    "height": height,
    "block_time_utc": block_time,
    "bank_supply_uixo": str(bank_supply_uixo),
    "staking_bonded_uixo": str(bonded_uixo),
    "staking_not_bonded_uixo": str(not_bonded_uixo),
    "staking_pool_total_uixo": str(bonded_uixo + not_bonded_uixo),
    "staking_pool_share_of_supply": str((bonded_uixo + not_bonded_uixo) / bank_supply_uixo) if bank_supply_uixo else None,
    "community_pool_uixo_decimal": str(community_pool_uixo),
    "module_account_uixo_total": str(module_balance_total_uixo),
    "ibc_total_escrow_uixo": str(ibc_escrow_uixo),
    "liquid_staking_pool_count": len(liquid_rows),
    "unreconciled_supply_uixo": None,
    "note": "Module balances overlap supply and must not be subtracted wholesale. Full circulation classification requires the provenance/control work in IXO-3948.",
}
write_json(DERIVED / "reconciliation.json", reconciliation)

query_status = []
try:
    query_status = [json.loads(line) for line in (ROOT / "query-status.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
except FileNotFoundError:
    pass
failed_queries = [q for q in query_status if not q.get("ok")]
core_checks = {
    "two_provider_block_agreement": len(selected.get("providers", [])) >= 2,
    "chain_id_is_ixo_5": manifest.get("chain_id") == "ixo-5",
    "fixed_height_selected": height > 0,
    "bank_supply_uixo_present": bank_supply_uixo > 0,
    "staking_pool_present": bonded_uixo + not_bonded_uixo > 0,
    "bonded_validator_set_present": len(validator_rows) > 0,
    "raw_hash_and_app_hash_present": bool(selected.get("block_hash") and selected.get("app_hash")),
}
validation = {
    "pass": all(core_checks.values()),
    "core_checks": core_checks,
    "failed_query_count": len(failed_queries),
    "failed_queries": failed_queries,
    "review_status": "owner-machine-validation-complete; independent researcher replay pending",
    "reproduction_grade": "R2" if all(core_checks.values()) else "R1",
}
write_json(DERIVED / "validation.json", validation)

summary = {
    "chain_id": manifest.get("chain_id"),
    "height": height,
    "block_time_utc": block_time,
    "block_hash": selected.get("block_hash"),
    "app_hash": selected.get("app_hash"),
    "confirming_providers": selected.get("providers", []),
    "bank_supply_uixo": str(bank_supply_uixo),
    "bank_supply_ixo": str(bank_supply_uixo / Decimal(1_000_000)) if bank_supply_uixo else None,
    "bonded_uixo": str(bonded_uixo),
    "not_bonded_uixo": str(not_bonded_uixo),
    "bonded_validator_count": len(validator_rows),
    "consensus_validator_count": len(consensus_rows),
    "community_pool_uixo_decimal": str(community_pool_uixo),
    "inflation": str(inflation) if inflation is not None else None,
    "annual_or_epoch_provisions": str(annual_provisions) if annual_provisions is not None else None,
    "ibc_channel_count": len(ibc_rows),
    "ibc_open_channel_count": sum(1 for row in ibc_rows if str(row.get("state", "")).endswith("OPEN")),
    "liquid_staking_pool_count": len(liquid_rows),
    "governance_proposal_count": len(gov_rows),
    "activity": activity_summary,
    "concentration": concentration,
    "market": market_summary,
    "validation": validation,
}
write_json(DERIVED / "summary.json", summary)
print(json.dumps(summary, indent=2, sort_keys=True, default=str))
