#!/usr/bin/env python3
"""Compatibility entrypoint for the current Cosmos SDK bank-supply REST route.

The capture implementation retains the legacy route as a documented probe, while CI
executes the same source with the v0.50 `supply/by_denom?denom=` route substituted.
Remove this shim when `capture_ci.py` is next consolidated.
"""
from pathlib import Path

source_path = Path(__file__).with_name("capture_ci.py")
source = source_path.read_text(encoding="utf-8")
source = source.replace(
    "/cosmos/bank/v1beta1/supply/uixo",
    "/cosmos/bank/v1beta1/supply/by_denom?denom=uixo",
)
namespace = {"__name__": "__main__", "__file__": str(source_path)}
exec(compile(source, str(source_path), "exec"), namespace)
