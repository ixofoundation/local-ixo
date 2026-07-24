#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from collections import defaultdict
from decimal import Decimal

from common import CHAIN_ID, OUT, account_address, dec, dump, fetch, save, technical_class, uixo, write_csv

GENESIS_URL = os.environ.get(
    "GENESIS_URL",
    "https://github.com/ixofoundation/genesis/raw/bc042e1223d551b22d55c155de06e662ca24d2f2/ixo-5/genesis.json.tar.gz",
)
GENESIS_COMMIT = "bc042e1223d551b22d55c155de06e662ca24d2f2"

code, headers, archive = fetch(GENESIS_URL, retries=2)
if code != 200:
    raise SystemExit(f"genesis download failed: HTTP {code}: {archive[:300]!r}")
save(OUT / "raw/genesis/genesis.json.tar.gz", archive, headers)

with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
    members = [member for member in tar.getmembers() if member.isfile() and member.name.endswith(".json")]
    if not members:
        raise SystemExit("genesis archive contains no JSON")
    extracted = tar.extractfile(members[0])
    assert extracted is not None
    genesis_bytes = extracted.read()
save(OUT / "raw/genesis/genesis.json", genesis_bytes)
genesis = json.loads(genesis_bytes)
if genesis.get("chain_id") != CHAIN_ID:
    raise SystemExit(f"genesis chain_id {genesis.get('chain_id')} != {CHAIN_ID}")
app_state = genesis.get("app_state") or {}

balances: dict[str, Decimal] = defaultdict(Decimal)
for record in (app_state.get("bank") or {}).get("balances", []) or []:
    address = record.get("address", "")
    if address:
        balances[address] += uixo(record.get("coins", []))
summed_supply = sum(balances.values(), Decimal(0))
declared_supply = uixo((app_state.get("bank") or {}).get("supply", []))

accounts: dict[str, dict] = {}
account_rows = []
for account in (app_state.get("auth") or {}).get("accounts", []) or []:
    if not isinstance(account, dict):
        continue
    address = account_address(account)
    if not address:
        continue
    accounts[address] = account
    account_type = account.get("@type", "")
    base_vesting = account.get("base_vesting_account") or {}
    account_rows.append({
        "address": address,
        "account_type": account_type,
        "technical_class": technical_class(account_type),
        "original_vesting_uixo": str(uixo(base_vesting.get("original_vesting", []) if isinstance(base_vesting, dict) else [])),
        "start_time": account.get("start_time", ""),
        "end_time": base_vesting.get("end_time", "") if isinstance(base_vesting, dict) else "",
        "beneficial_control": "unknown-not-inferred",
    })

balance_rows = []
for address, amount in sorted(balances.items(), key=lambda item: item[1], reverse=True):
    account_type = accounts.get(address, {}).get("@type", "")
    balance_rows.append({
        "address": address,
        "uixo": str(amount),
        "ixo": str(amount / Decimal(1_000_000)),
        "share_of_genesis": str(amount / summed_supply) if summed_supply else "0",
        "account_type": account_type,
        "technical_class": technical_class(account_type),
        "beneficial_control": "unknown-not-inferred",
    })

write_csv(OUT / "cleaned/genesis_balances.csv", balance_rows, [
    "address", "uixo", "ixo", "share_of_genesis", "account_type", "technical_class", "beneficial_control",
])
write_csv(OUT / "cleaned/genesis_accounts.csv", account_rows, [
    "address", "account_type", "technical_class", "original_vesting_uixo", "start_time", "end_time", "beneficial_control",
])

summary = {
    "source_url": GENESIS_URL,
    "source_commit": GENESIS_COMMIT,
    "archive_sha256": hashlib.sha256(archive).hexdigest(),
    "json_sha256": hashlib.sha256(genesis_bytes).hexdigest(),
    "genesis_time": genesis.get("genesis_time"),
    "chain_id": genesis.get("chain_id"),
    "declared_supply_uixo": str(declared_supply),
    "summed_balances_uixo": str(summed_supply),
    "supply_difference_uixo": str(declared_supply - summed_supply),
    "positive_balance_addresses": len(balances),
    "vesting_accounts": sum(1 for row in account_rows if row["technical_class"] == "vesting-account"),
}
dump(OUT / "derived/genesis-summary.json", summary)
dump(OUT / "derived/genesis-balances-map.json", {address: str(amount) for address, amount in balances.items()})
print(json.dumps(summary, indent=2, sort_keys=True))
