#!/usr/bin/env python3
"""Compatibility entrypoint for the deployed Impact Hub API surface.

The core capture remains readable and conservative. CI applies only explicit,
documented compatibility substitutions for Cosmos SDK v0.50 and the deployed
IXO liquid-stake query surface, while preferring independent providers for
queries that the first-party endpoint throttles or does not index.
"""
from pathlib import Path

source_path = Path(__file__).with_name("capture_ci.py")
source = source_path.read_text(encoding="utf-8")

# Cosmos SDK v0.50 bank supply route.
source = source.replace(
    "/cosmos/bank/v1beta1/supply/uixo",
    "/cosmos/bank/v1beta1/supply/by_denom?denom=uixo",
)

# Prefer the independently operated IBS endpoints after they have passed the
# same chain-id, fixed-height and block/app-hash checks. This avoids treating
# first-party rate limiting or tx-index configuration as missing chain state.
source = source.replace(
    'primary_rpc = winning[0]["endpoint"]\nprimary_rpc_provider = winning[0]["provider"]',
    'rpc_choice = next((row for row in winning if row["provider"] == "ibs"), winning[0])\nprimary_rpc = rpc_choice["endpoint"]\nprimary_rpc_provider = rpc_choice["provider"]',
)
source = source.replace(
    'preferred = next((r for r in valid_rest if r["provider"] == primary_rpc_provider), valid_rest[0])',
    'preferred = next((r for r in valid_rest if r["provider"] == "ibs"), next((r for r in valid_rest if r["provider"] == primary_rpc_provider), valid_rest[0]))',
)

# The v8 API exposes net amount state per pool, not as a global paginated list.
source = source.replace(
    '("liquidstake_states", "/ixo/liquidstake/v1beta1/states?pagination.limit=1000"),',
    '("liquidstake_states", "/ixo/liquidstake/v1beta1/pools/zero/states"),',
)

# CometBFT expects the tx_search expression as a quoted query value.
source = source.replace(
    '"query": f"tx.height >= {low} AND tx.height <= {height}",',
    '"query": f\'"tx.height >= {low} AND tx.height <= {height}"\',',
)

namespace = {"__name__": "__main__", "__file__": str(source_path)}
exec(compile(source, str(source_path), "exec"), namespace)
