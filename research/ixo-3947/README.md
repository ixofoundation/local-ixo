# IXO-3947 — Reproducible Impact Hub current-state capture

This directory implements the fixed-height primary-source run required by Linear issue **IXO-3947**. Linear remains the programme source of truth; GitHub holds the executable capture and immutable workflow artifacts linked back to the issue.

## What the run proves

A successful run:

1. discovers healthy Impact Hub RPC endpoints for chain `ixo-5`;
2. selects a fixed height that at least two independent providers can serve;
3. requires identical block hash and app hash from at least two providers;
4. selects a REST endpoint that serves historical state at that height;
5. captures raw chain, validator, supply, module-account, governance, IBC, liquid-staking and recent-activity responses;
6. records every command, endpoint failure, response body and header;
7. derives cleaned CSV tables and transparent concentration/reconciliation summaries; and
8. produces a SHA-256 manifest for the full artifact tree.

The workflow assigns **R2** only when the core machine-validation checks pass. It does not claim the programme protocol's human-independent **R3** review; a second researcher must replay and review the artifact before load-bearing figures are promoted.

## Run locally

Requirements: Bash 5+, `curl`, `jq`, Python 3.11+ and `sha256sum`.

```bash
chmod +x research/ixo-3947/capture.sh
research/ixo-3947/capture.sh artifacts/ixo-3947
jq . artifacts/ixo-3947/derived/validation.json
```

Optional controls:

```bash
ACTIVITY_BLOCKS=20000 MAX_TX_PAGES=200 \
  research/ixo-3947/capture.sh artifacts/ixo-3947
```

## Key outputs

```text
artifacts/ixo-3947/
  run-manifest.json
  endpoint-health.jsonl
  block-observations.jsonl
  selected-block.json
  query-status.jsonl
  raw/
  cleaned/
  derived/
    summary.json
    validation.json
    reconciliation.json
    concentration.json
    activity-summary.json
    market-summary.json
  hashes/sha256sums.txt
  logs/commands.log
```

## Interpretation rules

- Repository or monitor values are not substituted for fixed-height chain state.
- Module-account balances are reported but not subtracted wholesale from supply because categories overlap.
- Validator names never imply common control or affiliation.
- Market data remains secondary context and is never promoted to valuation without contemporaneous spread, depth, volume, venue and anomaly evidence.
- Missing or unsupported endpoints remain explicit failed-query records.
- IXO-3948 owns historical provenance and beneficial-control classification.

## Linear handoff

After a successful workflow run, attach the artifact and its SHA-256 manifest to IXO-3947, register the run and resulting claim/evidence records in the Agency White Paper Evidence Registry, and request an independent replay. Only then may IXO-3947 move to Done.
