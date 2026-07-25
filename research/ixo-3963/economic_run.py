from __future__ import annotations

import csv
import random
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from economic_simulation import simulate_alternative
from economic_types import REQUIRED_ALTERNATIVES, REQUIRED_SCENARIOS, percentile, safe_div
from economic_validation import sha256_file, validate_model, write_hash_manifest, write_json


def _sum(rows: list[dict[str, Any]], key: str) -> float:
    return sum(float(row[key]) for row in rows)


def _min(rows: list[dict[str, Any]], key: str) -> float:
    return min(float(row[key]) for row in rows)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    final = rows[-1]
    month12 = rows[min(11, len(rows) - 1)]
    month24 = rows[min(23, len(rows) - 1)]
    security_rows = [row for row in rows if row["modeled_native_stage"] or row["legacy_native_stage"]]
    return {
        "alternative": final["alternative"],
        "scenario": final["scenario"],
        "final_active_external_domains": final["active_external_domains"],
        "final_active_twins": final["active_twins"],
        "cumulative_gross_agency_value": _sum(rows, "gross_agency_value"),
        "cumulative_provider_revenue": _sum(rows, "provider_revenue"),
        "cumulative_gross_protocol_fees": _sum(rows, "gross_protocol_fees"),
        "cumulative_external_protocol_revenue": _sum(rows, "external_protocol_revenue"),
        "cumulative_security_revenue": _sum(rows, "security_revenue"),
        "cumulative_issuance_tokens": _sum(rows, "issuance_tokens"),
        "final_minted_supply": final["minted_supply"],
        "final_transferable_supply": final["transferable_supply"],
        "minimum_operating_cash": _min(rows, "operating_cash"),
        "final_operating_cash": final["operating_cash"],
        "minimum_security_cash": _min(rows, "security_cash"),
        "final_stable_assurance": final["stable_assurance"],
        "final_stable_pol": final["stable_pol"],
        "minimum_runway_months": _min(rows, "runway_months"),
        "month_12_external_fee_coverage": month12["external_fee_coverage"],
        "month_24_external_fee_coverage": month24["external_fee_coverage"],
        "final_external_fee_coverage": final["external_fee_coverage"],
        "minimum_security_budget_coverage": _min(rows, "security_budget_coverage"),
        "minimum_effective_security_to_mnvar": _min(
            security_rows or rows,
            "security_to_mnvar_ratio",
        ),
        "maximum_sell_pressure_to_depth": max(
            safe_div(row["expected_sell_pressure_usd"], row["stressed_executable_depth_usd"], 0.0)
            for row in rows
        ),
        "liquidity_gate_pass_all_months": all(bool(row["liquidity_gate_pass"]) for row in rows),
        "security_gate_pass_final": bool(final["security_gate_pass"]),
        "economic_path_pass_final": bool(final["economic_path_pass"]),
        "migration_gates_pass": bool(final["migration_gates_pass"]),
        "irreversible_launch_allowed": bool(final["irreversible_launch_allowed"]),
        "operating_solvent": _min(rows, "operating_cash") >= 0.0,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run_sensitivity(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    tests = {
        "protocol_fee_multiplier": [0.5, 0.75, 1.0, 1.25, 1.5],
        "price_multiplier": [0.3, 0.5, 0.75, 1.0, 1.25],
        "validator_cost_multiplier": [0.75, 1.0, 1.25, 1.5, 2.0],
        "initial_external_capital_multiplier": [0.5, 0.75, 1.0, 1.25, 1.5],
        "depth_multiplier": [0.15, 0.35, 0.6, 1.0, 1.4],
    }
    rows: list[dict[str, Any]] = []
    for alternative in REQUIRED_ALTERNATIVES:
        for parameter, values in tests.items():
            for value in values:
                model_rows = simulate_alternative(
                    inputs,
                    alternative,
                    "base",
                    {parameter: value},
                )
                summary = summarize(model_rows)
                rows.append(
                    {
                        "alternative": alternative,
                        "parameter": parameter,
                        "value": value,
                        "final_operating_cash": summary["final_operating_cash"],
                        "final_external_fee_coverage": summary["final_external_fee_coverage"],
                        "minimum_effective_security_to_mnvar": summary[
                            "minimum_effective_security_to_mnvar"
                        ],
                        "maximum_sell_pressure_to_depth": summary[
                            "maximum_sell_pressure_to_depth"
                        ],
                        "economic_path_pass_final": summary["economic_path_pass_final"],
                    }
                )
    return rows


def run_monte_carlo(inputs: dict[str, Any]) -> dict[str, Any]:
    run_count = int(inputs["meta"]["monte_carlo_runs"])
    seed = int(inputs["meta"]["random_seed"])
    rng = random.Random(seed)
    by_alt: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index in range(run_count):
        alternative = REQUIRED_ALTERNATIVES[index % len(REQUIRED_ALTERNATIVES)]
        shock = {
            "monthly_domain_growth_rate": rng.triangular(-0.01, 0.08, 0.03),
            "monthly_domain_churn_rate": rng.triangular(0.005, 0.07, 0.02),
            "protocol_fee_multiplier": rng.triangular(0.45, 1.35, 0.9),
            "initial_external_capital_multiplier": rng.triangular(0.4, 1.4, 0.9),
            "price_multiplier": rng.triangular(0.25, 1.0, 0.65),
            "validator_cost_multiplier": rng.triangular(0.9, 1.8, 1.15),
            "depth_multiplier": rng.triangular(0.12, 1.5, 0.65),
            "claim_rate": rng.triangular(0.35, 0.9, 0.65),
            "largest_domain_revenue_share": rng.triangular(0.25, 0.75, 0.4),
            "largest_controller_share": rng.triangular(0.1, 0.45, 0.2),
            "controllers_to_two_thirds": rng.randint(3, 8),
            "independent_controller_count": rng.randint(10, 30),
            "sell_fraction_multiplier": rng.triangular(0.7, 3.0, 1.2),
            "open_exposure_multiplier": rng.triangular(0.8, 1.8, 1.1),
        }
        rows = simulate_alternative(inputs, alternative, "base", shock)
        by_alt[alternative].append(summarize(rows))

    result: dict[str, Any] = {"seed": seed, "run_count": run_count, "alternatives": {}}
    for alternative, summaries in by_alt.items():
        final_cash = [float(row["final_operating_cash"]) for row in summaries]
        fee_coverage = [float(row["final_external_fee_coverage"]) for row in summaries]
        security_ratio = [float(row["minimum_effective_security_to_mnvar"]) for row in summaries]
        sell_ratio = [float(row["maximum_sell_pressure_to_depth"]) for row in summaries]
        result["alternatives"][alternative] = {
            "runs": len(summaries),
            "operating_solvency_fraction": sum(bool(row["operating_solvent"]) for row in summaries)
            / len(summaries),
            "economic_path_pass_fraction": sum(
                bool(row["economic_path_pass_final"]) for row in summaries
            )
            / len(summaries),
            "irreversible_launch_fraction": sum(
                bool(row["irreversible_launch_allowed"]) for row in summaries
            )
            / len(summaries),
            "final_cash_p10_p50_p90": [
                percentile(final_cash, 0.1),
                percentile(final_cash, 0.5),
                percentile(final_cash, 0.9),
            ],
            "fee_coverage_p10_p50_p90": [
                percentile(fee_coverage, 0.1),
                percentile(fee_coverage, 0.5),
                percentile(fee_coverage, 0.9),
            ],
            "security_ratio_p10_p50_p90": [
                percentile(security_ratio, 0.1),
                percentile(security_ratio, 0.5),
                percentile(security_ratio, 0.9),
            ],
            "sell_pressure_to_depth_p10_p50_p90": [
                percentile(sell_ratio, 0.1),
                percentile(sell_ratio, 0.5),
                percentile(sell_ratio, 0.9),
            ],
        }
    return result


def run_model(inputs: dict[str, Any], input_path: Path, output_root: Path, source_dir: Path) -> dict[str, Any]:
    outputs = output_root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    monthly_records: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for alternative in REQUIRED_ALTERNATIVES:
        for scenario in REQUIRED_SCENARIOS:
            rows = simulate_alternative(inputs, alternative, scenario)
            monthly_records.extend(rows)
            summaries.append(summarize(rows))

    sensitivity = run_sensitivity(inputs)
    monte_carlo = run_monte_carlo(inputs)
    validation = validate_model(inputs, monthly_records, summaries, monte_carlo)

    _write_csv(outputs / "monthly_model.csv", monthly_records)
    _write_csv(outputs / "scenario_summary.csv", summaries)
    _write_csv(outputs / "sensitivity.csv", sensitivity)
    write_json(outputs / "monte_carlo.json", monte_carlo)
    write_json(outputs / "residual_decisions.json", inputs.get("residual_decisions", []))
    write_json(outputs / "validation.json", validation)

    input_copy = output_root / "inputs" / "inputs.json"
    input_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(input_path, input_copy)
    source_copy = output_root / "source"
    source_copy.mkdir(parents=True, exist_ok=True)
    source_files = [
        "economic_types.py",
        "economic_metrics.py",
        "economic_simulation.py",
        "economic_validation.py",
        "economic_run.py",
        "model.py",
        "test_model.py",
    ]
    for name in source_files:
        shutil.copyfile(source_dir / name, source_copy / name)

    manifest = {
        "model_id": inputs["meta"]["model_id"],
        "version": inputs["meta"]["version"],
        "input_sha256": sha256_file(input_copy),
        "scenario_count": len(REQUIRED_SCENARIOS),
        "alternative_count": len(REQUIRED_ALTERNATIVES),
        "monthly_record_count": len(monthly_records),
        "sensitivity_record_count": len(sensitivity),
        "monte_carlo_runs": int(monte_carlo["run_count"]),
        "validation_pass": bool(validation["pass"]),
        "irreversible_launch_authorized": False,
        "source_sha256": {
            name: sha256_file(source_copy / name) for name in source_files
        },
    }
    write_json(outputs / "model_manifest.json", manifest)
    manifest["artifact_hash_manifest_sha256"] = write_hash_manifest(output_root)
    write_json(outputs / "model_manifest.json", manifest)
    write_hash_manifest(output_root)
    return manifest
