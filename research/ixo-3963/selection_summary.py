#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def as_bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def as_float(value: Any) -> float:
    return float(value)


def write_hash_manifest(root: Path) -> str:
    target = root / "hashes" / "sha256sums.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p != target):
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return hashlib.sha256(target.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the conservative IXO-3963 decision summary")
    parser.add_argument("--artifact", required=True, type=Path)
    args = parser.parse_args()
    root = args.artifact
    monthly_path = root / "outputs" / "monthly_model.csv"
    rows = list(csv.DictReader(monthly_path.open(encoding="utf-8")))
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[(row["alternative"], row["scenario"])].append(row)

    scenario_results: list[dict[str, Any]] = []
    for (alternative, scenario), group in sorted(groups.items()):
        group.sort(key=lambda row: int(row["month"]))
        final_window = group[-12:]
        minimum_operating_cash = min(as_float(row["operating_cash"]) for row in group)
        minimum_security_cash = min(as_float(row["security_cash"]) for row in group)
        capital_solvent = minimum_operating_cash >= 0.0 and minimum_security_cash >= 0.0
        liquidity_all_months = all(as_bool(row["liquidity_gate_pass"]) for row in group)
        final_year_economic_pass = all(as_bool(row["economic_path_pass"]) for row in final_window)
        final_year_security_pass = all(as_bool(row["security_gate_pass"]) for row in final_window)
        final_year_demand_pass = all(as_bool(row["demand_gate_pass"]) for row in final_window)
        final_year_assurance_pass = all(as_bool(row["assurance_gate_pass"]) for row in final_window)
        migration_gates_pass = all(as_bool(row["migration_gates_pass"]) for row in final_window)
        configuration_viable = (
            capital_solvent
            and liquidity_all_months
            and final_year_economic_pass
            and final_year_security_pass
            and final_year_demand_pass
            and final_year_assurance_pass
        )
        launch_eligible = configuration_viable and migration_gates_pass
        scenario_results.append(
            {
                "alternative": alternative,
                "scenario": scenario,
                "capital_solvent": capital_solvent,
                "minimum_operating_cash": minimum_operating_cash,
                "minimum_security_cash": minimum_security_cash,
                "liquidity_all_months": liquidity_all_months,
                "final_year_economic_pass": final_year_economic_pass,
                "final_year_security_pass": final_year_security_pass,
                "final_year_demand_pass": final_year_demand_pass,
                "final_year_assurance_pass": final_year_assurance_pass,
                "migration_gates_pass": migration_gates_pass,
                "configuration_viable": configuration_viable,
                "launch_eligible": launch_eligible,
                "month_12_external_fee_coverage": as_float(group[11]["external_fee_coverage"]),
                "month_24_external_fee_coverage": as_float(group[23]["external_fee_coverage"]),
                "final_external_fee_coverage": as_float(group[-1]["external_fee_coverage"]),
                "final_operating_cash": as_float(group[-1]["operating_cash"]),
                "final_active_external_domains": as_float(group[-1]["active_external_domains"]),
                "maximum_sell_pressure_to_depth": max(
                    (as_float(row["expected_sell_pressure_usd"]) / as_float(row["stressed_executable_depth_usd"]))
                    if as_float(row["stressed_executable_depth_usd"]) > 0
                    else 0.0
                    for row in group
                ),
            }
        )

    alternatives: dict[str, Any] = {}
    for alternative in sorted({row["alternative"] for row in scenario_results}):
        selected = [row for row in scenario_results if row["alternative"] == alternative]
        alternatives[alternative] = {
            "scenario_count": len(selected),
            "configuration_viable_scenarios": sum(bool(row["configuration_viable"]) for row in selected),
            "launch_eligible_scenarios": sum(bool(row["launch_eligible"]) for row in selected),
            "capital_solvent_scenarios": sum(bool(row["capital_solvent"]) for row in selected),
            "all_month_liquidity_pass_scenarios": sum(bool(row["liquidity_all_months"]) for row in selected),
            "base": next(row for row in selected if row["scenario"] == "base"),
            "rapid_growth": next(row for row in selected if row["scenario"] == "rapid_growth"),
            "failure": next(row for row in selected if row["scenario"] == "failure"),
        }

    result = {
        "model_id": "AGWP-M3-ECON-1",
        "decision_rule": {
            "configuration_viable": "capital solvent for the full horizon AND liquidity gate passes every month AND economic, security, demand and assurance gates pass throughout the final 12 months",
            "launch_eligible": "configuration viable AND all migration/legal/custody/no-double-benefit gates pass",
            "monte_carlo_note": "Monte Carlo economic-path and solvency frequencies are model-distribution diagnostics, not launch probabilities.",
        },
        "alternatives": alternatives,
        "scenarios": scenario_results,
        "programme_conclusion": {
            "any_launch_eligible_scenario": any(row["launch_eligible"] for row in scenario_results),
            "any_configuration_viable_scenario": any(row["configuration_viable"] for row in scenario_results),
            "native_agent_base_viable": next(
                row["configuration_viable"]
                for row in scenario_results
                if row["alternative"] == "native_agent" and row["scenario"] == "base"
            ),
            "selection_boundary": "No irreversible token, migration or native-security launch is authorised. Prove external demand and stable capital through the simpler service/shared-security stages, then re-run the model with determined residual parameters.",
        },
    }
    output = root / "outputs" / "decision_summary.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    source_dir = root / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "selection_summary.py").write_text(Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
    digest = write_hash_manifest(root)
    print(json.dumps({"decision_summary": str(output), "hash_manifest_sha256": digest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
