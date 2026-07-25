from __future__ import annotations

from collections import defaultdict
from typing import Any

from economic_metrics import (
    annual_security_reserve_cap,
    effective_security_capital,
    external_protocol_revenue,
    liquidity_limit_usd,
    maximum_network_value_at_risk,
    migration_gates_pass,
    target_security_budget,
)
from economic_types import clamp, override, safe_div


def _scheduled_linear(total: float, month: int, start_month: int, duration_months: int) -> float:
    if total <= 0 or duration_months <= 0:
        return 0.0
    if month < start_month or month >= start_month + duration_months:
        return 0.0
    return total / duration_months


def _native_release_schedule(
    inputs: dict[str, Any],
    scenario: dict[str, Any],
    month: int,
    domains: float,
    prior_domains: float,
    remaining: dict[str, float],
    security_release: float,
) -> dict[str, float]:
    supply = inputs["supply"]
    migration = inputs["migration"]
    claim_rate = clamp(float(override(scenario, "claim_rate", migration["baseline_claim_rate"])), 0.0, 1.0)
    releases: dict[str, float] = defaultdict(float)

    if month == 1:
        releases["public"] += min(float(supply["launch_public"]), remaining["public_capital"])
        releases["pol"] += min(float(supply["launch_pol"]), remaining["protocol_owned_liquidity"])

    claim_total = float(supply["allocation"]["legacy_claims"]) * claim_rate
    immediate_total = claim_total * float(supply["legacy_immediate_fraction"])
    vested_total = claim_total - immediate_total
    if month == int(supply["legacy_claim_start_month"]):
        releases["legacy_immediate"] += min(immediate_total, remaining["legacy_claims"])
    releases["legacy_vested"] += min(
        _scheduled_linear(
            vested_total,
            month,
            int(supply["legacy_claim_start_month"]),
            int(supply["legacy_vesting_months"]),
        ),
        max(0.0, remaining["legacy_claims"] - releases["legacy_immediate"]),
    )

    public_follow_on_total = max(
        0.0,
        float(supply["allocation"]["public_capital"]) - float(supply["launch_public"]),
    )
    releases["public_follow_on"] += min(
        _scheduled_linear(
            public_follow_on_total,
            month,
            int(supply["public_follow_on_start_month"]),
            int(supply["public_follow_on_months"]),
        ),
        max(0.0, remaining["public_capital"] - releases["public"]),
    )

    releases["contributors"] += min(
        _scheduled_linear(
            float(supply["allocation"]["contributors"]),
            month,
            int(supply["contributor_cliff_months"]) + 1,
            int(supply["contributor_vesting_months"]),
        ),
        remaining["contributors"],
    )
    releases["strategic"] += min(
        _scheduled_linear(
            float(supply["allocation"]["strategic_domains"]),
            month,
            int(supply["strategic_cliff_months"]) + 1,
            int(supply["strategic_vesting_months"]),
        ),
        remaining["strategic_domains"],
    )

    new_domains = max(0.0, domains - prior_domains)
    adoption = min(
        new_domains * float(supply["adoption_release_per_new_external_domain"]),
        float(supply["adoption_monthly_cap"]),
        remaining["adoption_reserve"],
    )
    releases["adoption"] += adoption
    releases["security"] += min(max(0.0, security_release), remaining["security_reserve"])
    return dict(releases)


def _sell_pressure_usd(
    releases: dict[str, float],
    price: float,
    liquidity: dict[str, Any],
    scenario: dict[str, Any],
) -> float:
    multiplier = float(override(scenario, "sell_fraction_multiplier", 1.0))
    fractions = {
        "legacy_immediate": float(liquidity["legacy_immediate_sell_fraction"]),
        "legacy_vested": float(liquidity["legacy_vested_sell_fraction"]),
        "public_follow_on": float(liquidity["public_follow_on_sell_fraction"]),
        "contributors": float(liquidity["contributor_sell_fraction"]),
        "strategic": float(liquidity["strategic_sell_fraction"]),
        "adoption": 0.05,
        "security": float(liquidity["security_release_sell_fraction"]),
    }
    return sum(
        max(0.0, releases.get(bucket, 0.0)) * max(0.0, price) * clamp(fraction * multiplier, 0.0, 1.0)
        for bucket, fraction in fractions.items()
    )


def simulate_alternative(
    inputs: dict[str, Any],
    alternative_name: str,
    scenario_name: str,
    scenario_override: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    meta = inputs["meta"]
    alt = inputs["alternatives"][alternative_name]
    scenario = dict(inputs["scenarios"][scenario_name])
    if scenario_override:
        scenario.update(scenario_override)
    demand = inputs["demand"]
    capital = inputs["capital"]
    liquidity = inputs["liquidity"]
    security = inputs["security"]
    supply = inputs["supply"]
    migration = inputs["migration"]

    horizon = int(meta["horizon_months"])
    initial_capital = (
        float(capital["initial_external_stable_capital"])
        * float(alt["initial_capital_multiplier"])
        * float(override(scenario, "initial_external_capital_multiplier", 1.0))
    )
    proceeds = capital["proceeds_allocation"]
    operating_cash = initial_capital * (
        float(proceeds["operations"]) + float(proceeds["implementation"]) + float(proceeds["contingency"])
    )
    security_cash = initial_capital * float(proceeds["security_transition"])
    stable_pol = initial_capital * float(proceeds["protocol_owned_liquidity_stable"])
    stable_assurance = initial_capital * float(proceeds["assurance"])
    operating_cash -= float(alt["transition_cost"])

    domains = float(demand["initial_active_external_domains"])
    prior_domains = domains
    external_payer_share = float(demand["initial_external_payer_share"])
    price = float(liquidity["illustrative_initial_price"]) * float(override(scenario, "price_multiplier", 1.0))
    fee_conversion_slippage = clamp(float(override(scenario, "fee_conversion_slippage_fraction", 0.0)), 0.0, 0.95)
    depth_multiplier = float(override(scenario, "depth_multiplier", 1.0))
    open_exposure_multiplier = float(override(scenario, "open_exposure_multiplier", 1.0))
    largest_domain_revenue_share = float(
        override(scenario, "largest_domain_revenue_share", demand["largest_domain_revenue_share"])
    )

    validator_count = int(override(scenario, "validator_count", security["validator_count"]))
    independent_controller_count = int(
        override(scenario, "independent_controller_count", security["independent_controller_count"])
    )
    largest_controller_share = float(
        override(scenario, "largest_controller_share", security["largest_controller_share"])
    )
    controllers_to_two_thirds = int(
        override(scenario, "controllers_to_two_thirds", security["controllers_to_two_thirds"])
    )

    allocation = {key: float(value) for key, value in supply["allocation"].items()}
    remaining = dict(allocation)
    minted_supply = 0.0
    transferable_supply = 0.0
    legacy_supply = float(alt.get("legacy_current_supply", 0.0))
    cumulative_issuance = 0.0
    remaining_security_reserve = float(allocation["security_reserve"])
    year_security_release = 0.0
    current_year = 1
    records: list[dict[str, Any]] = []

    for month in range(1, horizon + 1):
        year = (month - 1) // 12 + 1
        if year != current_year:
            current_year = year
            year_security_release = 0.0

        growth = float(override(scenario, "monthly_domain_growth_rate", demand["monthly_domain_growth_rate"]))
        churn = float(override(scenario, "monthly_domain_churn_rate", demand["monthly_domain_churn_rate"]))
        if month > 1:
            prior_domains = domains
            domains = max(0.0, domains * (1.0 + growth - churn))
        active_twins = domains * float(demand["active_twins_per_domain"])
        service_value = active_twins * float(demand["service_value_per_active_twin_month"])
        fee_multiplier = float(alt["protocol_fee_multiplier"]) * float(
            override(scenario, "protocol_fee_multiplier", 1.0)
        )
        gross_protocol_fees = active_twins * float(demand["protocol_fee_per_active_twin_month"]) * fee_multiplier
        external_payer_share = min(
            float(demand["maximum_external_payer_share"]),
            external_payer_share + (float(demand["external_payer_share_monthly_improvement"]) if month > 1 else 0.0),
        )
        external_revenue = external_protocol_revenue(
            gross_protocol_fees,
            external_payer_share,
            float(demand["related_party_fee_fraction"]),
        )
        provider_revenue = max(0.0, service_value - gross_protocol_fees)
        security_revenue = external_revenue * float(demand["security_fee_allocation_fraction"])
        assurance_revenue = external_revenue * float(demand["assurance_fee_allocation_fraction"])
        treasury_revenue = external_revenue * float(demand["treasury_fee_allocation_fraction"])
        pol_revenue = external_revenue * float(demand["pol_fee_allocation_fraction"])

        monthly_operations_cost = float(capital["monthly_protocol_operations_cost"]) * float(
            alt["implementation_cost_multiplier"]
        )
        monthly_implementation_cost = (
            float(capital["monthly_implementation_cost_first_18_months"])
            * float(alt["implementation_cost_multiplier"])
            if month <= 18
            else 0.0
        )
        operating_cash += treasury_revenue - monthly_operations_cost - monthly_implementation_cost
        stable_assurance += assurance_revenue
        stable_pol += pol_revenue

        target_budget = target_security_budget(
            float(security["monthly_cost_per_validator"])
            * float(override(scenario, "validator_cost_multiplier", 1.0)),
            validator_count,
            float(security["validator_margin_fraction"]),
            float(security["monthly_common_infrastructure_cost"]),
            float(security["monthly_audit_upgrade_incident_cost"]),
            float(security["decentralisation_premium_fraction"]),
        )

        modeled_native_stage = alternative_name == "native_agent" and month >= int(security["native_activation_month"])
        shared_stage = alt["security_mode"] == "shared" or (
            alternative_name == "native_agent" and not modeled_native_stage
        )
        legacy_native_stage = alt["security_mode"] == "legacy_native"
        shared_security_cost = (
            float(security["shared_security_monthly_cost"])
            * float(alt.get("shared_security_cost_multiplier", 1.0))
            if shared_stage
            else 0.0
        )
        if shared_stage:
            security_cash += security_revenue - shared_security_cost

        mnvar = maximum_network_value_at_risk(
            domains,
            float(security["initial_open_critical_exposure_per_domain"]),
            open_exposure_multiplier,
            float(security["shared_infrastructure_mnvar"]),
            float(security["bridge_custody_mnvar"]),
        )

        security_release_tokens = 0.0
        issuance_tokens = 0.0
        issuance_value = 0.0
        if modeled_native_stage:
            annual_cap = annual_security_reserve_cap(
                month,
                float(supply["maximum"]),
                [float(v) for v in supply["security_reserve_annual_caps_fraction_of_max"]],
            )
            monthly_cap_remaining = max(0.0, annual_cap - year_security_release)
            conservative_price = price * float(security["reserve_price_haircut_fraction"])
            shortfall = max(0.0, target_budget - security_revenue)
            depth_for_release = float(liquidity["monthly_executable_depth_at_5pct"]) * depth_multiplier
            if conservative_price > 0 and depth_for_release >= float(security["security_release_pause_if_depth_below_usd"]):
                security_release_tokens = min(
                    shortfall / conservative_price,
                    monthly_cap_remaining,
                    remaining_security_reserve,
                )
            year_security_release += security_release_tokens
            remaining_security_reserve -= security_release_tokens
            issuance_tokens = security_release_tokens
            issuance_value = security_release_tokens * conservative_price
        elif legacy_native_stage:
            issuance_tokens = float(alt["legacy_monthly_issuance_tokens"])
            issuance_value = issuance_tokens * price
            cumulative_issuance += issuance_tokens

        releases: dict[str, float] = {}
        if alt["native_asset"] and alternative_name != "recapitalized_ixo":
            releases = _native_release_schedule(
                inputs,
                scenario,
                month,
                domains,
                prior_domains,
                remaining,
                security_release_tokens,
            )
            for bucket, amount in releases.items():
                allocation_key = {
                    "public": "public_capital",
                    "public_follow_on": "public_capital",
                    "pol": "protocol_owned_liquidity",
                    "legacy_immediate": "legacy_claims",
                    "legacy_vested": "legacy_claims",
                    "contributors": "contributors",
                    "strategic": "strategic_domains",
                    "adoption": "adoption_reserve",
                    "security": "security_reserve",
                }[bucket]
                remaining[allocation_key] = max(0.0, remaining[allocation_key] - amount)
            month_minted = sum(releases.values())
            minted_supply = min(float(supply["maximum"]), minted_supply + month_minted)
            transferable_supply += sum(
                amount for bucket, amount in releases.items() if bucket != "pol"
            )
        elif alternative_name == "recapitalized_ixo":
            legacy_supply += issuance_tokens
            minted_supply = legacy_supply
            transferable_supply = float(alt["legacy_free_supply"]) + cumulative_issuance

        sell_pressure = _sell_pressure_usd(releases, price, liquidity, scenario)
        stressed_depth, sell_limit = liquidity_limit_usd(
            float(liquidity["monthly_executable_depth_at_5pct"]),
            depth_multiplier,
            float(liquidity["stressed_depth_multiplier"]),
            min(
                float(liquidity["maximum_monthly_sell_pressure_to_stressed_depth"]),
                float(supply["max_nonpublic_unlock_fraction_of_stressed_monthly_depth"]),
            ),
        )
        liquidity_gate = sell_pressure <= sell_limit + 1e-9

        if alternative_name == "recapitalized_ixo":
            bonded_tokens = float(alt["legacy_bonded_tokens"])
            alt_largest = float(override(scenario, "largest_controller_share", alt["legacy_largest_controller_share"]))
            alt_two_thirds = int(
                override(scenario, "controllers_to_two_thirds", alt["legacy_controllers_to_two_thirds"])
            )
            esc, total_security_haircut = effective_security_capital(
                bonded_tokens,
                price * float(liquidity["stress_price_multiplier"]),
                security["effective_security_haircuts"],
                alt_largest,
                float(security["maximum_largest_controller_share"]),
                alt_two_thirds,
                int(security["minimum_controllers_to_two_thirds"]),
                independent_controller_count,
                int(security["minimum_independent_controllers"]),
            )
            concentration_gate = (
                alt_largest < float(security["maximum_largest_controller_share"])
                and alt_two_thirds >= int(security["minimum_controllers_to_two_thirds"])
                and independent_controller_count >= int(security["minimum_independent_controllers"])
            )
        elif modeled_native_stage:
            bonded_tokens = transferable_supply * float(security["bonded_fraction_of_transferable_supply"])
            esc, total_security_haircut = effective_security_capital(
                bonded_tokens,
                price * float(liquidity["stress_price_multiplier"]),
                security["effective_security_haircuts"],
                largest_controller_share,
                float(security["maximum_largest_controller_share"]),
                controllers_to_two_thirds,
                int(security["minimum_controllers_to_two_thirds"]),
                independent_controller_count,
                int(security["minimum_independent_controllers"]),
            )
            concentration_gate = (
                largest_controller_share < float(security["maximum_largest_controller_share"])
                and controllers_to_two_thirds >= int(security["minimum_controllers_to_two_thirds"])
                and independent_controller_count >= int(security["minimum_independent_controllers"])
            )
        else:
            bonded_tokens = 0.0
            esc = 0.0
            total_security_haircut = 0.0
            concentration_gate = bool(security["shared_security_provider_concentration_pass"])

        security_to_mnvar = safe_div(esc, mnvar, 0.0) if (modeled_native_stage or legacy_native_stage) else 0.0
        if shared_stage:
            security_budget_coverage = safe_div(security_revenue + max(0.0, security_cash), shared_security_cost, 0.0)
            security_gate = concentration_gate and security_cash >= 0.0
        else:
            security_budget_coverage = safe_div(
                security_revenue + issuance_value,
                target_budget,
                0.0,
            )
            security_gate = (
                concentration_gate
                and security_to_mnvar >= float(security["minimum_effective_security_to_mnvar_ratio"])
                and security_budget_coverage >= 1.0
            )

        recurring_cost = monthly_operations_cost + monthly_implementation_cost
        runway_months = safe_div(max(0.0, operating_cash), recurring_cost, 0.0)
        external_fee_coverage = safe_div(external_revenue, recurring_cost + (shared_security_cost if shared_stage else target_budget), 0.0)
        assurance_gate = stable_assurance >= float(capital["stable_assurance_target"])
        demand_gate = (
            domains >= 3.0
            and external_payer_share >= 0.5
            and largest_domain_revenue_share <= 0.4
        )
        migration_pass = migration_gates_pass(migration)
        economic_path_pass = (
            operating_cash >= 0.0
            and security_gate
            and liquidity_gate
            and assurance_gate
            and demand_gate
        )
        irreversible_launch_allowed = economic_path_pass and migration_pass
        token_settlement_value = (
            gross_protocol_fees * (1.0 - fee_conversion_slippage)
            if alt["native_asset"]
            else 0.0
        )

        record = {
            "alternative": alternative_name,
            "scenario": scenario_name,
            "month": month,
            "active_external_domains": domains,
            "active_twins": active_twins,
            "gross_agency_value": service_value,
            "provider_revenue": provider_revenue,
            "gross_protocol_fees": gross_protocol_fees,
            "external_protocol_revenue": external_revenue,
            "external_payer_share": external_payer_share,
            "largest_domain_revenue_share": largest_domain_revenue_share,
            "security_revenue": security_revenue,
            "assurance_revenue": assurance_revenue,
            "treasury_revenue": treasury_revenue,
            "pol_revenue": pol_revenue,
            "token_settlement_value": token_settlement_value,
            "issuance_tokens": issuance_tokens,
            "issuance_value": issuance_value,
            "minted_supply": minted_supply,
            "transferable_supply": transferable_supply,
            "price_assumption": price,
            "operating_cash": operating_cash,
            "security_cash": security_cash,
            "stable_assurance": stable_assurance,
            "stable_pol": stable_pol,
            "monthly_operations_cost": monthly_operations_cost,
            "monthly_implementation_cost": monthly_implementation_cost,
            "target_security_budget": target_budget,
            "shared_security_cost": shared_security_cost,
            "security_budget_coverage": security_budget_coverage,
            "external_fee_coverage": external_fee_coverage,
            "bonded_tokens": bonded_tokens,
            "effective_security_capital": esc,
            "effective_security_haircut": total_security_haircut,
            "maximum_network_value_at_risk": mnvar,
            "security_to_mnvar_ratio": security_to_mnvar,
            "expected_sell_pressure_usd": sell_pressure,
            "stressed_executable_depth_usd": stressed_depth,
            "sell_pressure_limit_usd": sell_limit,
            "liquidity_gate_pass": liquidity_gate,
            "concentration_gate_pass": concentration_gate,
            "security_gate_pass": security_gate,
            "assurance_gate_pass": assurance_gate,
            "demand_gate_pass": demand_gate,
            "economic_path_pass": economic_path_pass,
            "migration_gates_pass": migration_pass,
            "irreversible_launch_allowed": irreversible_launch_allowed,
            "runway_months": runway_months,
            "modeled_native_stage": modeled_native_stage,
            "shared_security_stage": shared_stage,
            "legacy_native_stage": legacy_native_stage,
        }
        for bucket in (
            "public",
            "public_follow_on",
            "pol",
            "legacy_immediate",
            "legacy_vested",
            "contributors",
            "strategic",
            "adoption",
            "security",
        ):
            record[f"release_{bucket}"] = releases.get(bucket, 0.0)
        records.append(record)

    return records
