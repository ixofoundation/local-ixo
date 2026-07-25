# IXO-3963 — Reproducible Agency / AGENT economic model

This directory implements the quantitative model required by Linear issue
**IXO-3963**. Linear remains the programme source of truth. The code and
workflow artifact are reproduction evidence linked back to that issue.

## Purpose

The model tests whether the conditional M3 economic architecture can:

- maintain stable operating runway without relying on AGENT appreciation;
- distinguish Gross Agency Value, provider revenue, gross protocol fees,
  non-related external protocol revenue, security revenue, assurance capital,
  issuance subsidy and token value accrual;
- fund security from genuine fees with only bounded declining reserve releases;
- absorb legacy, public, contributor, strategic, adoption and security unlocks;
- maintain liquidity- and concentration-adjusted effective security coverage;
- prevent token, LST, capacity, performance and assurance capital from being
  counted more than once;
- compare tokenless, shared-security, recapitalised-IXO and native-AGENT paths
  under common assumptions; and
- state conditions under which native AGENT must not launch.

The model is not a price forecast, valuation, fundraising document, legal
opinion or launch authorization. Every exact launch value remains an explicit
residual decision.

## Files

- `inputs.json` — all assumptions, scenarios, alternatives, gates and residual
  decisions.
- `source.part*.b64` — text-encoded parts of the compressed canonical Python source archive.
- `source_manifest.json` — SHA-256 digest for every source file and the bundle.
- `extract_source.py` — path-safe verifier/extractor used by CI and local runs.
- extracted `economic_*.py`, `model.py` and `test_model.py` — model modules, CLI and tests.
- `.github/workflows/ixo-3963-economic-model.yml` — CI run and immutable
  evidence artifact.

## Run locally

```bash
python3 research/ixo-3963/extract_source.py

python3 research/ixo-3963/model.py \
  --inputs research/ixo-3963/inputs.json \
  --output artifacts/ixo-3963

python3 -m unittest -v \
  research/ixo-3963/test_model.py
```

The implementation uses only the Python standard library.

## Alternatives

The same demand and operating assumptions are applied to:

1. `tokenless_service` — stable-value service with shared/external security;
2. `shared_security_agent` — AGENT application economics while consensus
   security is purchased externally;
3. `recapitalized_ixo` — reformed IXO using the R2 current bonded/supply
   baseline and legacy issuance/concentration constraints; and
4. `native_agent` — hard-capped AGENT with fixed-pool legacy claims, security
   reserve, stable Credits, Fee Router, capacity, assurance and conditional
   native staking.

The alternatives are not assumed to be legally or operationally equivalent.
The model compares disclosed economic mechanics while preserving those
differences as decision gates.

## Required scenarios

The model runs every alternative through:

- base;
- conservative;
- failure;
- rapid growth;
- liquidity shock;
- validator exit;
- concentrated sell-off;
- low fee conversion;
- domain churn; and
- governance capture.

The Monte Carlo run uses a fixed seed and declared input distributions. Its
probabilities describe the model distribution, not objective probabilities of
commercial or technical success.

## Core equations

### External protocol revenue

```text
ExternalProtocolRevenue
  = GrossProtocolFees
  × ExternalPayerShare
  × (1 − RelatedPartyFeeFraction)
```

Treasury, programme, grant, issuance-funded, refunded and circular flows are not
counted as external demand.

### Target security budget

```text
TargetSecurityBudget
  = (ValidatorCost × ValidatorCount × SustainableMargin
     + CommonInfrastructure
     + AuditUpgradeIncidentCapacity)
  × (1 + DecentralisationPremium)
```

### Bounded security-reserve release

```text
StableShortfall
  = max(TargetSecurityBudget − ExternalSecurityRevenue, 0)

ReserveReleaseTokens
  = min(
      StableShortfall / ConservativeReleasePrice,
      RemainingAnnualCap,
      RemainingLifetimeSecurityReserve
    )
```

Unused annual authority expires. Issuance is never counted as external revenue.

### Effective security capital

```text
EffectiveSecurityCapital
  = BondedTokens
  × StressedPrice
  × ControllerHaircut
  × LiquidityHaircut
  × SlashabilityHaircut
  × LockFinalityHaircut
  × ControlConfidenceHaircut
  × InfrastructureCorrelationHaircut
```

The underlying AGENT is counted once. `stAGENT`, LP positions, wrappers and
borrowed/reused claims do not create additional security capital.

### Maximum network value at risk

```text
M-NVaR
  = OpenCriticalDomainExposure
  + SharedInfrastructureExposure
  + BridgeAndCustodyExposure
```

The model uses credible loss/control exposure over the response and unbonding
window, not narrative ecosystem volume.

### Liquidity gate

Expected sell pressure includes the declared fractions of legacy, public,
contributor, strategic, adoption and security releases. Non-public unlocks are
delayed when their expected sales exceed the disclosed fraction of stressed
executable depth.

## Outputs

The workflow artifact contains:

- `outputs/monthly_model.csv`;
- `outputs/scenario_summary.csv`;
- `outputs/sensitivity.csv`;
- `outputs/monte_carlo.json`;
- `outputs/residual_decisions.json`;
- `outputs/validation.json`;
- `outputs/model_manifest.json`;
- the exact input file; and
- `hashes/sha256sums.txt`.

The validation gate requires:

- allocation and proceeds reconciliation;
- no native/shared AGENT supply above the hard maximum;
- zero token supply in the tokenless alternative;
- external revenue never exceeding gross fees;
- issuance remaining separate from external revenue;
- all required adverse scenarios;
- deterministic seeded reproduction; and
- irreversible launch remaining blocked while residual legal, custody,
  one-unit/one-claim and no-double-benefit gates are false.

## Interpretation rule

A failed scenario is evidence about the assumed configuration. It is not cured
by adding an assumed token-price increase. The allowed responses are to:

- increase proven stable capital;
- reduce cost or implementation scope;
- improve independently paid demand;
- tighten exposure and unlock limits;
- use shared/external security;
- remain a stablecoin-funded service;
- reform IXO instead of migrating; or
- stop the relevant launch path.

The corresponding selection, fallback and residual-decision disposition is
owned by **IXO-3964** in Linear.
