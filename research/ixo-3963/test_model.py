from __future__ import annotations

import unittest

from economic_metrics import (
    effective_security_capital,
    external_protocol_revenue,
    migration_gates_pass,
    target_security_budget,
)
from economic_simulation import simulate_alternative


class EconomicMetricsTest(unittest.TestCase):
    def test_external_revenue_excludes_related_party_fraction(self) -> None:
        self.assertAlmostEqual(external_protocol_revenue(100.0, 0.8, 0.25), 60.0)

    def test_security_budget_is_stable_cost_based(self) -> None:
        value = target_security_budget(10.0, 5, 0.2, 20.0, 10.0, 0.1)
        self.assertAlmostEqual(value, 99.0)

    def test_effective_security_applies_all_haircuts_and_concentration(self) -> None:
        effective, haircut = effective_security_capital(
            1000.0,
            2.0,
            {"a": 0.5, "b": 0.8},
            0.4,
            1 / 3,
            4,
            5,
            10,
            20,
        )
        expected_haircut = 0.5 * 0.8 * ((1 / 3) / 0.4) * (4 / 5) * (10 / 20)
        self.assertAlmostEqual(haircut, expected_haircut)
        self.assertAlmostEqual(effective, 1000.0 * 2.0 * expected_haircut)

    def test_open_migration_gates_block_launch(self) -> None:
        self.assertFalse(
            migration_gates_pass(
                {
                    "custodian_reconciliation_gate": False,
                    "legal_rights_gate": False,
                    "one_unit_one_claim_gate": False,
                    "related_party_no_double_benefit_gate": False,
                }
            )
        )


class SimulationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.inputs = {
            "meta": {"horizon_months": 2},
            "alternatives": {
                "native_agent": {
                    "implementation_cost_multiplier": 1.0,
                    "initial_capital_multiplier": 1.0,
                    "native_asset": True,
                    "protocol_fee_multiplier": 1.0,
                    "security_mode": "native",
                    "transition_cost": 0,
                },
                "tokenless_service": {
                    "implementation_cost_multiplier": 1.0,
                    "initial_capital_multiplier": 1.0,
                    "native_asset": False,
                    "protocol_fee_multiplier": 1.0,
                    "security_mode": "shared",
                    "shared_security_cost_multiplier": 1.0,
                    "transition_cost": 0,
                },
            },
            "capital": {
                "initial_external_stable_capital": 1000000,
                "monthly_protocol_operations_cost": 1000,
                "monthly_implementation_cost_first_18_months": 100,
                "proceeds_allocation": {
                    "operations": 0.45,
                    "implementation": 0.1,
                    "contingency": 0.05,
                    "security_transition": 0.1,
                    "protocol_owned_liquidity_stable": 0.2,
                    "assurance": 0.1,
                },
                "stable_assurance_target": 100,
            },
            "demand": {
                "initial_active_external_domains": 3.0,
                "active_twins_per_domain": 10,
                "service_value_per_active_twin_month": 10,
                "protocol_fee_per_active_twin_month": 2,
                "monthly_domain_growth_rate": 0.01,
                "monthly_domain_churn_rate": 0.0,
                "initial_external_payer_share": 0.8,
                "external_payer_share_monthly_improvement": 0.0,
                "maximum_external_payer_share": 0.9,
                "related_party_fee_fraction": 0.1,
                "security_fee_allocation_fraction": 0.55,
                "assurance_fee_allocation_fraction": 0.1,
                "treasury_fee_allocation_fraction": 0.25,
                "pol_fee_allocation_fraction": 0.1,
                "largest_domain_revenue_share": 0.3,
            },
            "liquidity": {
                "illustrative_initial_price": 0.1,
                "monthly_executable_depth_at_5pct": 1000000,
                "stressed_depth_multiplier": 0.5,
                "maximum_monthly_sell_pressure_to_stressed_depth": 0.25,
                "legacy_immediate_sell_fraction": 0.1,
                "legacy_vested_sell_fraction": 0.1,
                "public_follow_on_sell_fraction": 0.1,
                "contributor_sell_fraction": 0.1,
                "strategic_sell_fraction": 0.1,
                "security_release_sell_fraction": 0.1,
                "stress_price_multiplier": 0.3,
            },
            "security": {
                "validator_count": 20,
                "independent_controller_count": 20,
                "largest_controller_share": 0.1,
                "controllers_to_two_thirds": 6,
                "maximum_largest_controller_share": 0.3333333333,
                "minimum_controllers_to_two_thirds": 5,
                "minimum_independent_controllers": 20,
                "monthly_cost_per_validator": 10,
                "validator_margin_fraction": 0.2,
                "monthly_common_infrastructure_cost": 20,
                "monthly_audit_upgrade_incident_cost": 10,
                "decentralisation_premium_fraction": 0.1,
                "native_activation_month": 1,
                "shared_security_monthly_cost": 100,
                "shared_security_provider_concentration_pass": True,
                "initial_open_critical_exposure_per_domain": 10,
                "shared_infrastructure_mnvar": 10,
                "bridge_custody_mnvar": 10,
                "reserve_price_haircut_fraction": 0.6,
                "security_release_pause_if_depth_below_usd": 1,
                "bonded_fraction_of_transferable_supply": 0.5,
                "minimum_effective_security_to_mnvar_ratio": 0.1,
                "effective_security_haircuts": {
                    "controller": 1.0,
                    "liquidity": 1.0,
                    "slashability": 1.0,
                    "lock_finality": 1.0,
                    "control_confidence": 1.0,
                    "infrastructure_correlation": 1.0,
                },
            },
            "supply": {
                "maximum": 1000000,
                "allocation": {
                    "legacy_claims": 200000,
                    "public_capital": 200000,
                    "protocol_owned_liquidity": 100000,
                    "security_reserve": 200000,
                    "adoption_reserve": 120000,
                    "treasury": 80000,
                    "contributors": 70000,
                    "strategic_domains": 30000,
                },
                "launch_public": 150000,
                "launch_pol": 100000,
                "legacy_immediate_fraction": 0.25,
                "legacy_claim_start_month": 1,
                "legacy_vesting_months": 30,
                "public_follow_on_start_month": 7,
                "public_follow_on_months": 12,
                "contributor_cliff_months": 12,
                "contributor_vesting_months": 36,
                "strategic_cliff_months": 12,
                "strategic_vesting_months": 36,
                "adoption_release_per_new_external_domain": 100,
                "adoption_monthly_cap": 1000,
                "security_reserve_annual_caps_fraction_of_max": [0.1],
                "max_nonpublic_unlock_fraction_of_stressed_monthly_depth": 0.2,
            },
            "migration": {
                "baseline_claim_rate": 0.5,
                "custodian_reconciliation_gate": False,
                "legal_rights_gate": False,
                "one_unit_one_claim_gate": False,
                "related_party_no_double_benefit_gate": False,
            },
            "scenarios": {"base": {}},
        }

    def test_tokenless_supply_stays_zero(self) -> None:
        rows = simulate_alternative(self.inputs, "tokenless_service", "base")
        self.assertTrue(all(row["minted_supply"] == 0 for row in rows))

    def test_native_is_capped_and_launch_blocked(self) -> None:
        rows = simulate_alternative(self.inputs, "native_agent", "base")
        self.assertTrue(all(row["minted_supply"] <= self.inputs["supply"]["maximum"] for row in rows))
        self.assertTrue(all(row["irreversible_launch_allowed"] is False for row in rows))


if __name__ == "__main__":
    unittest.main()
