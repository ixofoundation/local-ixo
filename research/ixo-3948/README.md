# IXO-3948 — Legacy IXO distribution, rights and failure-mode audit

This directory implements the reproducible evidence package for Linear issue **IXO-3948**. Linear remains the programme source of truth; GitHub holds executable methods and immutable workflow artifacts.

## Research boundary

The audit distinguishes:

- directly observed chain and genesis facts;
- technical account classifications;
- causal inferences with alternative explanations;
- open assumptions and unavailable evidence; and
- normative judgments that require an explicit governance criterion.

It **does not** identify wallet owners, infer common control from names or transaction patterns, or treat an address as a person. Every address-level row carries `beneficial_control = unknown-not-inferred` unless a later Linear evidence record adds independently reviewed proof.

## Sources

1. Immutable `ixo-5` genesis archive pinned to IXO Foundation genesis commit `bc042e1223d551b22d55c155de06e662ca24d2f2`.
2. Current `ixo-5` state at a fixed height agreed by at least two independent RPC providers.
3. Fixed-height Cosmos/IXO REST queries for bank supply, all `uixo` denom owners, module accounts, staking pools, community pool, IBC escrow, liquid-stake pools and mint state.
4. IXO-3947 for the separate fixed-height activity, fee, validator and market baseline.

## Reproduction

Requirements: Python 3.11+ and outbound HTTPS access.

```bash
python3 research/ixo-3948/run.py
cat artifacts/ixo-3948/run-result.json
```

Optional controls:

```bash
TOP_ACCOUNT_LOOKUPS=100 HTTP_TIMEOUT=20 \
  python3 research/ixo-3948/run.py
```

`TOP_ACCOUNT_LOOKUPS` controls only how many of the largest balances receive an additional auth-account-type lookup. Every denom owner remains in the distribution table, and no unqueried account is assigned an identity or control class.

## Outputs

```text
artifacts/ixo-3948/
  run-manifest.json
  run-result.json
  raw/
    genesis/
    current/
  cleaned/
    genesis_accounts.csv
    genesis_balances.csv
    current_owners.csv
    current_owners_enriched.csv
  derived/
    genesis-summary.json
    current-summary.json
    supply-provenance.json
    distribution-metrics.json
    legacy-rights-risk-register.json
    economic-failure-modes.json
    verification-questions.json
    validation.json
  hashes/sha256sums.txt
  logs/commands.log
  query-status.jsonl
```

## Classification rules

| Technical class | Meaning | What it does not prove |
|---|---|---|
| `protocol-module` | Address is returned by the fixed-height auth module-account query. | Whether its balance is excluded from circulation or belongs economically to users. |
| `vesting-account` | Auth account type is a Cosmos vesting account. | Whether vesting or off-chain contractual rights survive today. |
| `liquid-stake-proxy` | Address is a configured liquid-stake pool proxy. | Whether an LST holder, admin or validator is the beneficial owner of backing. |
| `contract-account` | Auth account type is a contract account where the endpoint exposes it. | Contract purpose, recoverability or ultimate beneficiary. |
| `ordinary-or-unknown` | No stronger technical class was established. | A natural person, independent holder, unrelated party or freely transferable balance. |

## Concentration scenarios

The audit reports three explicit denominators rather than publishing one hidden “circulating supply” definition:

1. every positive `uixo` denom owner;
2. all denom owners except known protocol modules; and
3. ordinary/unknown plus vesting accounts as an illustrative holder-candidate scenario.

The third scenario is **not** migration eligibility. Custody, contracts, escrow, lost keys and common control remain unresolved.

## Completion gate

A machine-valid R2 run requires:

- exact reconciliation of genesis declared supply to genesis balance sum;
- exact reconciliation of current bank supply to all current denom owners;
- two-provider agreement on the current block and app hash;
- zero unsupported beneficial-control attributions;
- explicit alternative explanations for causal findings; and
- complete risk, verification-question and integrity manifests.

Holder, custodian, legal and independent review remain required before IXO-3948 moves to Done or informs final conversion entitlements.
