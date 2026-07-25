from __future__ import annotations

from typing import Any

from economic_types import clamp, product, safe_div


def external_protocol_revenue(
    gross_protocol_fees: float,
    external_payer_share: float,
    related_party_fee_fraction: float,
) -> float:
    return max(
        0.0,
        gross_protocol_fees
        * clamp(external_payer_share, 0.0, 1.0)
        * (1.0 - clamp(related_party_fee_fraction, 0.0, 1.0)),
    )


def target_security_budget(
    monthly_cost_per_validator: float,
    validator_count: int,
    validator_margin_fraction: float,
    monthly_common_infrastructure_cost: float,
    monthly_audit_upgrade_incident_cost: float,
    decentralisation_premium_fraction: float,
) -> float:
    validator_budget = (
        monthly_cost_per_validator
        * max(0, validator_count)
        * (1.0 + max(0.0, validator_margin_fraction))
    )
    base = (
        validator_budget
        + max(0.0, monthly_common_infrastructure_cost)
        + max(0.0, monthly_audit_upgrade_incident_cost)
    )
    return base * (1.0 + max(0.0, decentralisation_premium_fraction))


def effective_security_capital(
    bonded_tokens: float,
    stressed_price: float,
    haircuts: dict[str, float],
    largest_controller_share: float,
    maximum_largest_controller_share: float,
    controllers_to_two_thirds: int,
    minimum_controllers_to_two_thirds: int,
    independent_controller_count: int,
    minimum_independent_controllers: int,
) -> tuple[float, float]:
    base_haircut = product([clamp(float(value), 0.0, 1.0) for value in haircuts.values()])
    largest_factor = (
        1.0
        if largest_controller_share <= maximum_largest_controller_share
        else safe_div(maximum_largest_controller_share, largest_controller_share, 0.0)
    )
    two_thirds_factor = clamp(
        safe_div(controllers_to_two_thirds, minimum_controllers_to_two_thirds, 0.0),
        0.0,
        1.0,
    )
    controller_count_factor = clamp(
        safe_div(independent_controller_count, minimum_independent_controllers, 0.0),
        0.0,
        1.0,
    )
    total_haircut = base_haircut * largest_factor * two_thirds_factor * controller_count_factor
    effective = max(0.0, bonded_tokens) * max(0.0, stressed_price) * total_haircut
    return effective, total_haircut


def maximum_network_value_at_risk(
    active_domains: float,
    initial_open_critical_exposure_per_domain: float,
    open_exposure_multiplier: float,
    shared_infrastructure_mnvar: float,
    bridge_custody_mnvar: float,
) -> float:
    return max(0.0, active_domains) * max(0.0, initial_open_critical_exposure_per_domain) * max(
        0.0, open_exposure_multiplier
    ) + max(0.0, shared_infrastructure_mnvar) + max(0.0, bridge_custody_mnvar)


def annual_security_reserve_cap(
    month: int,
    maximum_supply: float,
    annual_cap_fractions: list[float],
) -> float:
    if month <= 0 or not annual_cap_fractions:
        return 0.0
    year_index = min((month - 1) // 12, len(annual_cap_fractions) - 1)
    return max(0.0, maximum_supply) * max(0.0, float(annual_cap_fractions[year_index]))


def liquidity_limit_usd(
    monthly_executable_depth_at_5pct: float,
    depth_multiplier: float,
    stressed_depth_multiplier: float,
    maximum_sell_pressure_fraction: float,
) -> tuple[float, float]:
    stressed_depth = (
        max(0.0, monthly_executable_depth_at_5pct)
        * max(0.0, depth_multiplier)
        * max(0.0, stressed_depth_multiplier)
    )
    return stressed_depth, stressed_depth * clamp(maximum_sell_pressure_fraction, 0.0, 1.0)


def migration_gates_pass(migration: dict[str, Any]) -> bool:
    required = (
        "custodian_reconciliation_gate",
        "legal_rights_gate",
        "one_unit_one_claim_gate",
        "related_party_no_double_benefit_gate",
    )
    return all(bool(migration.get(key, False)) for key in required)
