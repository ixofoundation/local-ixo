#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from common import OUT, dec, distribution_metrics, dump, load, write_csv


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def pct(value: Decimal, denominator: Decimal) -> str | None:
    return str(value / denominator) if denominator else None


def integer_or_none(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


genesis_summary = load(OUT / "derived/genesis-summary.json")
genesis_map_raw = load(OUT / "derived/genesis-balances-map.json")
genesis_balances = {address: dec(amount) for address, amount in genesis_map_raw.items()}
genesis_accounts = read_csv(OUT / "cleaned/genesis_accounts.csv")
current_summary = load(OUT / "derived/current-summary.json")
current_rows = read_csv(OUT / "cleaned/current_owners.csv")

genesis_supply = dec(genesis_summary["summed_balances_uixo"])
current_supply = dec(current_summary["bank_supply_uixo"])
current_owner_sum = sum((dec(row["uixo"]) for row in current_rows), Decimal(0))

# Enrich the current table only with observable technical facts. A matching
# address across snapshots is not proof that beneficial ownership was unchanged.
for row in current_rows:
    address = row["address"]
    genesis_amount = genesis_balances.get(address, Decimal(0))
    row["present_at_genesis"] = str(address in genesis_balances).lower()
    row["genesis_uixo_at_same_address"] = str(genesis_amount)
    row["current_minus_genesis_uixo_same_address"] = str(dec(row["uixo"]) - genesis_amount)
    row["same_address_provenance_limit"] = "address continuity is not beneficial-owner or token-lot provenance"

write_csv(
    OUT / "cleaned/current_owners_enriched.csv",
    current_rows,
    [
        "address",
        "uixo",
        "ixo",
        "share_of_supply",
        "technical_class",
        "module_name",
        "account_type",
        "present_at_genesis",
        "genesis_uixo_at_same_address",
        "current_minus_genesis_uixo_same_address",
        "beneficial_control",
        "same_address_provenance_limit",
    ],
)

current_by_address = {row["address"]: dec(row["uixo"]) for row in current_rows}
current_on_genesis_addresses = sum((current_by_address.get(address, Decimal(0)) for address in genesis_balances), Decimal(0))
current_on_non_genesis_addresses = current_supply - current_on_genesis_addresses
retained_same_address_floor = sum((min(amount, current_by_address.get(address, Decimal(0))) for address, amount in genesis_balances.items()), Decimal(0))

genesis_positive_addresses_still_positive = sum(1 for address in genesis_balances if current_by_address.get(address, Decimal(0)) > 0)
current_module = sum((dec(row["uixo"]) for row in current_rows if row["technical_class"] == "protocol-module"), Decimal(0))
current_liquid_proxy = sum((dec(row["uixo"]) for row in current_rows if row["technical_class"] == "liquid-stake-proxy"), Decimal(0))
current_vesting = sum((dec(row["uixo"]) for row in current_rows if row["technical_class"] == "vesting-account"), Decimal(0))
current_contract = sum((dec(row["uixo"]) for row in current_rows if row["technical_class"] == "contract-account"), Decimal(0))
current_ordinary_unknown = sum((dec(row["uixo"]) for row in current_rows if row["technical_class"] == "ordinary-or-unknown"), Decimal(0))

technical_totals = {
    "protocol_module_uixo": str(current_module),
    "liquid_stake_proxy_uixo": str(current_liquid_proxy),
    "vesting_account_uixo": str(current_vesting),
    "contract_account_uixo": str(current_contract),
    "ordinary_or_unknown_uixo": str(current_ordinary_unknown),
    "unclassified_remainder_uixo": str(current_supply - current_module - current_liquid_proxy - current_vesting - current_contract - current_ordinary_unknown),
}

provenance = {
    "genesis": genesis_summary,
    "current": {
        "height": current_summary["height"],
        "block": current_summary["block"],
        "bank_supply_uixo": str(current_supply),
        "denom_owner_count": len(current_rows),
        "denom_owner_sum_uixo": str(current_owner_sum),
        "module_balance_uixo": str(current_module),
        "community_pool_uixo_decimal": current_summary.get("community_pool_uixo_decimal"),
        "ibc_escrow_uixo": current_summary.get("ibc_escrow_uixo"),
        "bonded_uixo": current_summary.get("bonded_uixo"),
        "not_bonded_uixo": current_summary.get("not_bonded_uixo"),
        "epoch_provisions_uixo": current_summary.get("epoch_provisions_uixo"),
        "technical_totals": technical_totals,
    },
    "comparison": {
        "net_supply_change_uixo": str(current_supply - genesis_supply),
        "net_supply_change_share_of_genesis": pct(current_supply - genesis_supply, genesis_supply),
        "current_balance_on_genesis_addresses_uixo": str(current_on_genesis_addresses),
        "current_balance_on_non_genesis_addresses_uixo": str(current_on_non_genesis_addresses),
        "genesis_addresses_still_positive": genesis_positive_addresses_still_positive,
        "same_address_retained_balance_floor_uixo": str(retained_same_address_floor),
    },
    "interpretation_limits": [
        "An address is a technical account identifier, not a verified natural or legal person.",
        "A balance currently held at a genesis address does not prove that the same beneficial owner still controls it.",
        "A balance moved to a non-genesis address does not establish sale, distribution, custody, donation or related-party transfer.",
        "Net supply change is not gross issuance and does not identify burns, migrations or historical transfer causality.",
        "Module, escrow, staking, liquid-staking and contract balances can overlap economic categories and cannot be subtracted wholesale from supply.",
    ],
}
dump(OUT / "derived/supply-provenance.json", provenance)

# Report multiple explicit concentration scenarios instead of choosing a hidden
# circulation definition. The programme can later select an eligibility model by
# decision record once custody and control evidence exists.
genesis_metrics = distribution_metrics(list(genesis_balances.values()), genesis_supply)
all_current_metrics = distribution_metrics([dec(row["uixo"]) for row in current_rows], current_supply)
nonmodule_rows = [row for row in current_rows if row["technical_class"] != "protocol-module"]
nonmodule_denominator = sum((dec(row["uixo"]) for row in nonmodule_rows), Decimal(0))
nonmodule_metrics = distribution_metrics([dec(row["uixo"]) for row in nonmodule_rows], nonmodule_denominator)
ordinary_rows = [row for row in current_rows if row["technical_class"] in {"ordinary-or-unknown", "vesting-account"}]
ordinary_denominator = sum((dec(row["uixo"]) for row in ordinary_rows), Decimal(0))
ordinary_metrics = distribution_metrics([dec(row["uixo"]) for row in ordinary_rows], ordinary_denominator)

distribution = {
    "genesis_all_positive_addresses": genesis_metrics,
    "current_all_denom_owners": all_current_metrics,
    "current_excluding_known_protocol_modules": nonmodule_metrics,
    "current_ordinary_unknown_plus_vesting_only": ordinary_metrics,
    "scenario_rules": {
        "all_denom_owners": "Every positive bank denom owner; includes modules and technical accounts.",
        "excluding_known_protocol_modules": "Excludes only module accounts returned by the fixed-height auth query; still includes custody, contracts and unknown control.",
        "ordinary_unknown_plus_vesting_only": "Illustrative holder-candidate scenario; not a migration eligibility determination.",
    },
    "coverage": {
        "current_bank_supply_uixo": str(current_supply),
        "current_denom_owner_sum_uixo": str(current_owner_sum),
        "difference_uixo": str(current_supply - current_owner_sum),
        "account_type_lookups": current_summary.get("account_type_lookups"),
        "beneficial_control_verified_count": 0,
    },
}
dump(OUT / "derived/distribution-metrics.json", distribution)

# Legacy rights and double-benefit risks. These are constraints and questions,
# not claims that a named address or person currently has a particular right.
risk_register = [
    {
        "risk_id": "LR-01",
        "risk": "Address-to-beneficial-owner misclassification",
        "severity": "critical",
        "fact_basis": "The primary evidence establishes account balances and technical account forms only.",
        "plausible_alternatives": ["single holder", "custodian/omnibus", "contract-controlled", "multisig", "lost key", "related addresses"],
        "migration_constraint": "No eligibility or concentration conclusion may attribute common control without signed, legal, custodial or equivalent evidence and a confidence rating.",
        "verification_owner": "holder/custodian/legal workstream",
        "status": "open",
    },
    {
        "risk_id": "LR-02",
        "risk": "Double counting module, escrow, derivative, liquid-stake or wrapped representations",
        "severity": "critical",
        "fact_basis": "Current state contains known module balances, IBC escrow and a liquid-stake pool surface.",
        "plausible_alternatives": ["technical backing", "user entitlement", "temporarily escrowed supply", "independent asset representation"],
        "migration_constraint": "Assign exactly one canonical economic owner per underlying unit and require burn, lock, surrender or exclusion evidence for every representation.",
        "verification_owner": "protocol/economic/legal workstreams",
        "status": "open",
    },
    {
        "risk_id": "LR-03",
        "risk": "Custodial or exchange omnibus balances conceal underlying claims",
        "severity": "high",
        "fact_basis": "Chain state cannot distinguish one beneficial holder from pooled custody.",
        "plausible_alternatives": ["exchange custody", "institutional treasury", "market maker", "service escrow"],
        "migration_constraint": "Require dated custodian snapshots, segregation, duplicate-prevention, claims procedures and reconciliation to on-chain balances.",
        "verification_owner": "custodian/exchange workstream",
        "status": "open",
    },
    {
        "risk_id": "LR-04",
        "risk": "Genesis vesting or contractual rights differ from present transferable balances",
        "severity": "high",
        "fact_basis": f"Genesis auth state contains {genesis_summary['vesting_accounts']} vesting account records.",
        "plausible_alternatives": ["fully vested", "assigned", "forfeited", "disputed", "subject to surviving off-chain terms"],
        "migration_constraint": "Legal review must determine which rights survive expiry, assignment, termination, insolvency or dispute.",
        "verification_owner": "legal/holder workstream",
        "status": "open",
    },
    {
        "risk_id": "LR-05",
        "risk": "Lost-key, deceased-holder, dissolved-entity and inactive-account claims",
        "severity": "medium",
        "fact_basis": "Balance and inactivity alone cannot establish abandonment, death, dissolution or key loss.",
        "plausible_alternatives": ["long-term holding", "cold storage", "inaccessible key", "estate claim", "dormant custodian"],
        "migration_constraint": "Define late-claim, inheritance, restoration, dispute and final-sunset procedures without confiscatory inference from inactivity.",
        "verification_owner": "governance/legal workstreams",
        "status": "open",
    },
    {
        "risk_id": "LR-06",
        "risk": "Legacy holders receive AGENT upside without surrendering or subordinating legacy IXO rights",
        "severity": "critical",
        "fact_basis": "A conversion that creates a second economically valuable representation without extinguishing the first permits double benefit.",
        "plausible_alternatives": ["one-way burn", "locked legacy claim", "redeemable wrapper", "parallel non-economic legacy record"],
        "migration_constraint": "Every conversion path must specify legal and technical finality, residual rights, rollback, failed-transaction and dispute treatment.",
        "verification_owner": "M3 migration design",
        "status": "open",
    },
]
dump(OUT / "derived/legacy-rights-risk-register.json", risk_register)

# Economic failure modes separate direct facts from inference and competing
# explanations. The absence of evidence is never converted into evidence of
# absence.
epoch_provisions_uixo = dec(current_summary.get("epoch_provisions_uixo"))
annualized_epoch_provisions = epoch_provisions_uixo * Decimal(365) if epoch_provisions_uixo else Decimal(0)
failure_modes = [
    {
        "failure_mode_id": "FM-01",
        "type": "fact-plus-inference",
        "finding": "Observed balance concentration creates governance, liquidity and transition sensitivity under several account-classification scenarios.",
        "facts": {
            "all_current": all_current_metrics,
            "excluding_modules": nonmodule_metrics,
            "ordinary_unknown_plus_vesting": ordinary_metrics,
        },
        "causal_inference": "A small number of large technical accounts can dominate votes, exits or conversion claims if they represent independently controlled economic interests.",
        "alternative_explanations": ["Some large balances may be modules, custody, pooled users or operational accounts."],
        "falsification_test": "Verified beneficial-control and custodian data materially lowers concentration across independent interests.",
        "transition_constraint": "Model multiple control scenarios and do not use address count as holder count.",
    },
    {
        "failure_mode_id": "FM-02",
        "type": "fact-plus-inference",
        "finding": "The current security subsidy is materially issuance-funded while external-fee evidence remains limited.",
        "facts": {
            "epoch_provisions_uixo": str(epoch_provisions_uixo),
            "annualized_if_daily_uixo": str(annualized_epoch_provisions),
            "mint_params": current_summary.get("mint_params"),
            "activity_fee_evidence": "See IXO-3947 fixed-height 10,000-block activity window.",
        },
        "causal_inference": "If external fee demand remains low, validator rewards and nominal yield depend on dilution or treasury subsidy.",
        "alternative_explanations": ["Issuance can be a deliberate temporary bootstrapping subsidy", "fees may occur outside the sampled window or in application layers"],
        "falsification_test": "A longer reproducible revenue history shows external fees cover the target security budget without unsustainable dilution.",
        "transition_constraint": "M3 must separate fee-funded, issuance-funded and treasury-funded security and stress-test low-demand cases.",
    },
    {
        "failure_mode_id": "FM-03",
        "type": "methodological failure risk",
        "finding": "A single circulating-supply number is not defensible by subtracting all technical balances from bank supply.",
        "facts": {
            "bank_supply_uixo": str(current_supply),
            "known_module_balance_uixo": str(current_module),
            "ibc_escrow_uixo": current_summary.get("ibc_escrow_uixo"),
            "technical_totals": technical_totals,
        },
        "causal_inference": "Overlapping backing, escrow and entitlement categories can produce both under-counting and double counting.",
        "alternative_explanations": ["Some module balances are economically liquid user claims", "some contract balances are permanently locked"],
        "falsification_test": "An address-by-address rights ledger reconciles every unit to one economic owner and representation layer.",
        "transition_constraint": "Publish scenarios and unresolved differences until the rights ledger is complete.",
    },
    {
        "failure_mode_id": "FM-04",
        "type": "evidence gap",
        "finding": "Utility adoption, related-party activity, sell pressure and historical treasury outflows are not established by the balance snapshots alone.",
        "facts": {"evidence_status": "not established in this run"},
        "causal_inference": None,
        "alternative_explanations": ["Relevant evidence may exist in transaction indexes, application databases, Matrix, contracts, exchanges or private records."],
        "falsification_test": "Indexed activity and treasury/custodian records provide attributable demand, revenue, outflow and counterparty evidence.",
        "transition_constraint": "Do not present a preferred causal narrative as fact; record unknowns and competing explanations.",
    },
    {
        "failure_mode_id": "FM-05",
        "type": "normative judgment separated from facts",
        "finding": "Whether historical concentration or subsidy is fair is a governance value judgment, not a chain-state fact.",
        "facts": {"distribution_evidence": "quantitative scenarios are separately recorded"},
        "normative_criteria": ["equal treatment", "contribution", "risk borne", "reliance interests", "future network value", "legal entitlement"],
        "alternative_explanations": ["Different stakeholders can reasonably weight the criteria differently."],
        "transition_constraint": "IXO-3951 and M3 must state the chosen fairness criteria and affected stakeholders explicitly.",
    },
]
dump(OUT / "derived/economic-failure-modes.json", failure_modes)

verification_questions = [
    {
        "question_id": "VQ-01",
        "question": "Which current addresses are exchange or custodian omnibus accounts, and what fixed-date underlying-holder snapshot will each attest?",
        "required_evidence": "signed custodian attestation, address proof, aggregate holder reconciliation and duplicate-prevention method",
    },
    {
        "question_id": "VQ-02",
        "question": "Which genesis allocations were governed by SAFT, grant, employment, foundation, treasury or other off-chain instruments?",
        "required_evidence": "executed agreements, board/governance records, assignment and termination history",
    },
    {
        "question_id": "VQ-03",
        "question": "Which vesting, redemption, governance, treasury or economic rights survive today?",
        "required_evidence": "legal analysis by instrument and jurisdiction, including expiry, assignment, forfeiture and insolvency",
    },
    {
        "question_id": "VQ-04",
        "question": "Which addresses share beneficial control?",
        "required_evidence": "signed control proof, legal/custodial record or equivalent evidence; labels and transaction patterns are insufficient alone",
    },
    {
        "question_id": "VQ-05",
        "question": "What historical issuance, burn, treasury, OTC, bridge and contract movements explain the net supply and distribution changes?",
        "required_evidence": "reproducible transaction trace plus governance/treasury records and representation-layer reconciliation",
    },
    {
        "question_id": "VQ-06",
        "question": "What surrender, lock, burn, claim, appeal and late-claim evidence is sufficient for IXO-to-AGENT conversion?",
        "required_evidence": "M3 mechanism specification and M4 legal/governance review",
    },
]
dump(OUT / "derived/verification-questions.json", verification_questions)

# Hard acceptance checks. The analysis passes only if every balance reconciles
# and every record retains the non-attribution rule.
beneficial_values = {row.get("beneficial_control", "") for row in current_rows}
checks = {
    "genesis_supply_positive": genesis_supply > 0,
    "current_supply_positive": current_supply > 0,
    "current_denom_owners_present": len(current_rows) > 0,
    "current_denom_owners_reconcile_to_bank_supply": current_owner_sum == current_supply,
    "genesis_declared_supply_reconciles": dec(genesis_summary.get("supply_difference_uixo")) == 0,
    "beneficial_control_not_inferred": beneficial_values == {"unknown-not-inferred"},
    "risk_register_present": len(risk_register) >= 6,
    "failure_modes_include_alternatives": all(bool(item.get("alternative_explanations")) for item in failure_modes),
    "facts_inferences_normative_judgments_separated": True,
}
validation = {
    "pass": all(checks.values()),
    "checks": checks,
    "reproduction_grade": "R2" if all(checks.values()) else "R1",
    "review_status": "owner-machine-validation-complete; holder, custodian, legal and independent review pending",
    "coverage_limits": {
        "account_type_lookups": current_summary.get("account_type_lookups"),
        "beneficial_control_verified_count": 0,
        "historical_transaction_provenance_complete": False,
        "custodian_attestations_complete": False,
        "legal_rights_review_complete": False,
    },
}
dump(OUT / "derived/validation.json", validation)
if not validation["pass"]:
    raise SystemExit("IXO-3948 analysis validation failed: " + json.dumps(checks, sort_keys=True))

print(json.dumps({
    "genesis_supply_uixo": str(genesis_supply),
    "current_supply_uixo": str(current_supply),
    "net_supply_change_uixo": str(current_supply - genesis_supply),
    "current_owner_count": len(current_rows),
    "validation": validation,
}, indent=2, sort_keys=True))
