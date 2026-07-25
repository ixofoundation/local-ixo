from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from economic_types import REQUIRED_ALTERNATIVES, REQUIRED_SCENARIOS


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_model(
    inputs: dict[str, Any],
    monthly_records: list[dict[str, Any]],
    scenario_summary: list[dict[str, Any]],
    monte_carlo: dict[str, Any],
) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    maximum = float(inputs["supply"]["maximum"])
    allocation_total = sum(float(v) for v in inputs["supply"]["allocation"].values())
    proceeds_total = sum(float(v) for v in inputs["capital"]["proceeds_allocation"].values())

    checks["allocation_reconciles_to_maximum"] = abs(allocation_total - maximum) < 1e-6
    checks["proceeds_allocation_reconciles"] = abs(proceeds_total - 1.0) < 1e-9
    checks["required_alternatives_present"] = set(REQUIRED_ALTERNATIVES) == set(inputs["alternatives"])
    checks["required_scenarios_present"] = set(REQUIRED_SCENARIOS) == set(inputs["scenarios"])
    checks["monthly_record_count"] = len(monthly_records) == (
        len(REQUIRED_ALTERNATIVES) * len(REQUIRED_SCENARIOS) * int(inputs["meta"]["horizon_months"])
    )
    checks["summary_count"] = len(scenario_summary) == len(REQUIRED_ALTERNATIVES) * len(REQUIRED_SCENARIOS)
    checks["tokenless_has_zero_supply"] = all(
        abs(float(row["minted_supply"])) < 1e-9
        for row in monthly_records
        if row["alternative"] == "tokenless_service"
    )
    checks["agent_hard_cap_respected"] = all(
        float(row["minted_supply"]) <= maximum + 1e-6
        for row in monthly_records
        if row["alternative"] in {"native_agent", "shared_security_agent"}
    )
    checks["external_revenue_not_above_gross_fees"] = all(
        float(row["external_protocol_revenue"]) <= float(row["gross_protocol_fees"]) + 1e-9
        for row in monthly_records
    )
    checks["issuance_not_counted_as_external_revenue"] = all(
        not (
            float(row["issuance_tokens"]) > 0
            and abs(float(row["external_protocol_revenue"]) - float(row["issuance_value"])) < 1e-9
        )
        for row in monthly_records
    )
    checks["all_adverse_scenarios_executed"] = {
        row["scenario"] for row in scenario_summary
    } == set(REQUIRED_SCENARIOS)
    checks["residual_decisions_preserved"] = len(inputs.get("residual_decisions", [])) >= 10
    checks["irreversible_launch_blocked_by_open_migration_gates"] = all(
        row["irreversible_launch_allowed"] is False
        for row in monthly_records
        if row["alternative"] in {"native_agent", "shared_security_agent"}
    )
    checks["monte_carlo_run_count"] = int(monte_carlo["run_count"]) == int(inputs["meta"]["monte_carlo_runs"])
    checks["monte_carlo_seed_pinned"] = int(monte_carlo["seed"]) == int(inputs["meta"]["random_seed"])

    return {
        "pass": all(checks.values()),
        "reproduction_grade": "R2",
        "checks": checks,
        "limitations": [
            "decision-support assumptions are not forecasts",
            "price appreciation is not a solvency input",
            "R2 M1 data remains subject to independent review",
            "legal, custody, beneficial-control and migration gates remain residual decisions",
        ],
    }


def write_hash_manifest(root: Path) -> str:
    target = root / "hashes" / "sha256sums.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p != target):
        lines.append(f"{sha256_file(path)}  {path.relative_to(root).as_posix()}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return hashlib.sha256(target.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
