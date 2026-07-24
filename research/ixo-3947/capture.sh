#!/usr/bin/env bash
set -Eeuo pipefail

OUT_DIR="${1:-artifacts/ixo-3947}"
CHAIN_ID="${CHAIN_ID:-ixo-5}"
ACTIVITY_BLOCKS="${ACTIVITY_BLOCKS:-10000}"
MAX_TX_PAGES="${MAX_TX_PAGES:-100}"
CURL_TIMEOUT="${CURL_TIMEOUT:-30}"

mkdir -p "$OUT_DIR"/{raw/rpc,raw/rest,raw/market,cleaned,derived,hashes,logs}
: > "$OUT_DIR/logs/commands.log"
: > "$OUT_DIR/endpoint-health.jsonl"
: > "$OUT_DIR/query-status.jsonl"

RPC_NAMES=(first_party ibs bluestake stavr lavenderfive whenmoon sifchain)
RPC_URLS=(
  "https://impacthub.ixo.world/rpc"
  "https://ixo.ibs.team/rpc"
  "https://ixo-rpc.bluestake.net:443"
  "https://ixo.rpc.m.stavr.tech:443"
  "https://rpc.lavenderfive.com:443/impacthub"
  "https://impacthub_mainnet_rpc.chain.whenmoonwhenlambo.money"
  "https://proxies.sifchain.finance/api/impacthub-3/rpc"
)
REST_URLS=(
  "https://impacthub.ixo.world/rest"
  "https://ixo.ibs.team/api"
  "https://ixo-api.bluestake.net"
  "https://ixo.api.m.stavr.tech"
  "https://rest.lavenderfive.com:443/impacthub"
  "https://impacthub_mainnet_api.chain.whenmoonwhenlambo.money"
  "https://proxies.sifchain.finance/api/impacthub-3/rest"
)

log_cmd() {
  printf '%q ' "$@" >> "$OUT_DIR/logs/commands.log"
  printf '\n' >> "$OUT_DIR/logs/commands.log"
}

safe_name() {
  printf '%s' "$1" | sed 's#https\?://##; s#[/:?&=]#_#g'
}

record_query() {
  local name="$1" endpoint="$2" ok="$3" detail="${4:-}"
  jq -nc \
    --arg name "$name" \
    --arg endpoint "$endpoint" \
    --argjson ok "$ok" \
    --arg detail "$detail" \
    '{name:$name,endpoint:$endpoint,ok:$ok,detail:$detail}' \
    >> "$OUT_DIR/query-status.jsonl"
}

curl_body() {
  local url="$1" body="$2"
  shift 2
  log_cmd curl -fsS --retry 2 --retry-all-errors --connect-timeout 10 --max-time "$CURL_TIMEOUT" "$@" "$url"
  curl -fsS --retry 2 --retry-all-errors --connect-timeout 10 --max-time "$CURL_TIMEOUT" "$@" "$url" > "$body"
}

# 1. Endpoint health capture.
for i in "${!RPC_URLS[@]}"; do
  name="${RPC_NAMES[$i]}"
  rpc="${RPC_URLS[$i]%/}"
  body="$OUT_DIR/raw/rpc/status_${name}.json"
  if curl_body "$rpc/status" "$body"; then
    if jq -e --arg chain "$CHAIN_ID" '.result.node_info.network == $chain' "$body" >/dev/null 2>&1; then
      jq -c --arg provider "$name" --arg endpoint "$rpc" '{provider:$provider,endpoint:$endpoint,ok:true,chain_id:.result.node_info.network,height:(.result.sync_info.latest_block_height|tonumber),block_hash:.result.sync_info.latest_block_hash,catching_up:(.result.sync_info.catching_up|tostring)}' "$body" >> "$OUT_DIR/endpoint-health.jsonl"
    else
      jq -nc --arg provider "$name" --arg endpoint "$rpc" '{provider:$provider,endpoint:$endpoint,ok:false,reason:"wrong-chain-or-invalid-status"}' >> "$OUT_DIR/endpoint-health.jsonl"
    fi
  else
    jq -nc --arg provider "$name" --arg endpoint "$rpc" '{provider:$provider,endpoint:$endpoint,ok:false,reason:"unreachable"}' >> "$OUT_DIR/endpoint-health.jsonl"
  fi
done

healthy_count=$(jq -s --arg chain "$CHAIN_ID" '[.[] | select(.ok == true and .chain_id == $chain and (.catching_up == "false"))] | length' "$OUT_DIR/endpoint-health.jsonl")
if (( healthy_count < 2 )); then
  echo "FATAL: fewer than two healthy independent RPC endpoints" >&2
  exit 20
fi

# Choose the second-highest latest height, guaranteeing at least two healthy endpoints are at or above H.
H=$(jq -sr --arg chain "$CHAIN_ID" '[.[] | select(.ok == true and .chain_id == $chain and (.catching_up == "false")) | .height] | sort | reverse | .[1]' "$OUT_DIR/endpoint-health.jsonl")
if [[ -z "$H" || "$H" == "null" ]]; then
  echo "FATAL: could not select a candidate height" >&2
  exit 21
fi
printf '%s\n' "$H" > "$OUT_DIR/height.txt"

# 2. Confirm identical block hash and app hash from at least two independent providers.
: > "$OUT_DIR/block-observations.jsonl"
for i in "${!RPC_URLS[@]}"; do
  name="${RPC_NAMES[$i]}"
  rpc="${RPC_URLS[$i]%/}"
  body="$OUT_DIR/raw/rpc/block_${name}_${H}.json"
  if curl_body "$rpc/block?height=$H" "$body"; then
    if jq -e --arg chain "$CHAIN_ID" '.result.block.header.chain_id == $chain' "$body" >/dev/null 2>&1; then
      jq -c --arg provider "$name" --arg endpoint "$rpc" '{provider:$provider,endpoint:$endpoint,ok:true,height:(.result.block.header.height|tonumber),block_hash:.result.block_id.hash,app_hash:.result.block.header.app_hash,time:.result.block.header.time}' "$body" >> "$OUT_DIR/block-observations.jsonl"
    else
      jq -nc --arg provider "$name" --arg endpoint "$rpc" '{provider:$provider,endpoint:$endpoint,ok:false,reason:"wrong-chain-or-invalid-block"}' >> "$OUT_DIR/block-observations.jsonl"
    fi
  else
    jq -nc --arg provider "$name" --arg endpoint "$rpc" '{provider:$provider,endpoint:$endpoint,ok:false,reason:"height-unavailable"}' >> "$OUT_DIR/block-observations.jsonl"
  fi
done

python3 - "$OUT_DIR/block-observations.jsonl" "$OUT_DIR/selected-block.json" <<'PY'
import json, sys
from collections import defaultdict
src, dst = sys.argv[1:]
groups = defaultdict(list)
for line in open(src, encoding='utf-8'):
    row = json.loads(line)
    if row.get('ok'):
        groups[(row['height'], row['block_hash'], row['app_hash'])].append(row)
valid = [(key, rows) for key, rows in groups.items() if len(rows) >= 2]
if not valid:
    raise SystemExit('no block/app-hash agreement from two providers')
valid.sort(key=lambda item: (len(item[1]), item[0][0]), reverse=True)
(key, rows) = valid[0]
json.dump({
    'height': key[0],
    'block_hash': key[1],
    'app_hash': key[2],
    'time': rows[0]['time'],
    'providers': [r['provider'] for r in rows],
    'rpc_endpoints': [r['endpoint'] for r in rows],
}, open(dst, 'w', encoding='utf-8'), indent=2, sort_keys=True)
PY

PRIMARY_PROVIDER=$(jq -r '.providers[0]' "$OUT_DIR/selected-block.json")
PRIMARY_INDEX=-1
for i in "${!RPC_NAMES[@]}"; do
  if [[ "${RPC_NAMES[$i]}" == "$PRIMARY_PROVIDER" ]]; then PRIMARY_INDEX="$i"; break; fi
done
if (( PRIMARY_INDEX < 0 )); then
  echo "FATAL: selected provider mapping failed" >&2
  exit 22
fi
PRIMARY_RPC="${RPC_URLS[$PRIMARY_INDEX]%/}"

# Probe historical REST support and select the first provider that returns bank supply at H.
PRIMARY_REST=""
PRIMARY_REST_PROVIDER=""
for i in "${!REST_URLS[@]}"; do
  rest="${REST_URLS[$i]%/}"
  name="${RPC_NAMES[$i]}"
  probe="$OUT_DIR/raw/rest/probe_bank_supply_${name}.json"
  headers="$OUT_DIR/raw/rest/probe_bank_supply_${name}.headers"
  log_cmd curl -fsS --retry 2 --connect-timeout 10 --max-time "$CURL_TIMEOUT" -D "$headers" -H "Accept: application/json" -H "x-cosmos-block-height: $H" "$rest/cosmos/bank/v1beta1/supply/uixo"
  if curl -fsS --retry 2 --retry-all-errors --connect-timeout 10 --max-time "$CURL_TIMEOUT" -D "$headers" -H "Accept: application/json" -H "x-cosmos-block-height: $H" "$rest/cosmos/bank/v1beta1/supply/uixo" > "$probe"; then
    response_height=$(awk 'BEGIN{IGNORECASE=1} /^x-cosmos-block-height:/ {gsub("\r",""); print $2}' "$headers" | tail -1)
    if [[ -z "$response_height" || "$response_height" == "$H" ]]; then
      PRIMARY_REST="$rest"
      PRIMARY_REST_PROVIDER="$name"
      break
    fi
  fi
done
if [[ -z "$PRIMARY_REST" ]]; then
  echo "FATAL: no REST endpoint served the selected historical height" >&2
  exit 23
fi

jq -n \
  --arg chain_id "$CHAIN_ID" \
  --argjson height "$H" \
  --arg rpc_provider "$PRIMARY_PROVIDER" \
  --arg rpc "$PRIMARY_RPC" \
  --arg rest_provider "$PRIMARY_REST_PROVIDER" \
  --arg rest "$PRIMARY_REST" \
  --arg captured_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --slurpfile selected "$OUT_DIR/selected-block.json" \
  '{chain_id:$chain_id,height:$height,selected_block:$selected[0],primary_rpc_provider:$rpc_provider,primary_rpc:$rpc,primary_rest_provider:$rest_provider,primary_rest:$rest,captured_at_utc:$captured_at}' \
  > "$OUT_DIR/run-manifest.json"

get_rpc() {
  local name="$1" path="$2"
  local file="$OUT_DIR/raw/rpc/${name}.json"
  if curl_body "$PRIMARY_RPC$path" "$file"; then record_query "$name" "$PRIMARY_RPC$path" true; else record_query "$name" "$PRIMARY_RPC$path" false "curl-failed"; fi
}

get_rest() {
  local name="$1" path="$2"
  local file="$OUT_DIR/raw/rest/${name}.json"
  local headers="$OUT_DIR/raw/rest/${name}.headers"
  log_cmd curl -fsS --retry 2 --connect-timeout 10 --max-time "$CURL_TIMEOUT" -D "$headers" -H "Accept: application/json" -H "x-cosmos-block-height: $H" "$PRIMARY_REST$path"
  if curl -fsS --retry 2 --retry-all-errors --connect-timeout 10 --max-time "$CURL_TIMEOUT" -D "$headers" -H "Accept: application/json" -H "x-cosmos-block-height: $H" "$PRIMARY_REST$path" > "$file"; then
    record_query "$name" "$PRIMARY_REST$path" true
  else
    record_query "$name" "$PRIMARY_REST$path" false "curl-failed"
    rm -f "$file"
  fi
}

# 3. Fixed-height primary capture.
get_rpc "status_primary" "/status"
get_rpc "block_${H}" "/block?height=$H"
get_rpc "commit_${H}" "/commit?height=$H"
get_rpc "consensus_params_${H}" "/consensus_params?height=$H"

page=1
while :; do
  file="$OUT_DIR/raw/rpc/consensus_validators_${page}.json"
  if ! curl_body "$PRIMARY_RPC/validators?height=$H&page=$page&per_page=100" "$file"; then
    record_query "consensus_validators_${page}" "$PRIMARY_RPC/validators" false "curl-failed"
    break
  fi
  record_query "consensus_validators_${page}" "$PRIMARY_RPC/validators" true
  count=$(jq -r '.result.count // "0" | tonumber' "$file")
  total=$(jq -r '.result.total // "0" | tonumber' "$file")
  (( count == 0 || page * 100 >= total )) && break
  page=$((page + 1))
done

# Network/version.
get_rest node_info "/cosmos/base/tendermint/v1beta1/node_info"
get_rest module_versions "/cosmos/upgrade/v1beta1/module_versions"
get_rest current_upgrade_plan "/cosmos/upgrade/v1beta1/current_plan"

# Supply and module accounts.
get_rest bank_supply_all "/cosmos/bank/v1beta1/supply?pagination.limit=10000"
get_rest bank_supply_uixo "/cosmos/bank/v1beta1/supply/uixo"
get_rest bank_params "/cosmos/bank/v1beta1/params"
get_rest auth_module_accounts "/cosmos/auth/v1beta1/module_accounts?pagination.limit=1000"
get_rest staking_pool "/cosmos/staking/v1beta1/pool"
get_rest staking_params "/cosmos/staking/v1beta1/params"
get_rest distribution_community_pool "/cosmos/distribution/v1beta1/community_pool"
get_rest distribution_params "/cosmos/distribution/v1beta1/params"

# Standard and IXO custom mint surfaces; failures are retained as query-status records.
get_rest cosmos_mint_params "/cosmos/mint/v1beta1/params"
get_rest cosmos_mint_inflation "/cosmos/mint/v1beta1/inflation"
get_rest cosmos_mint_annual_provisions "/cosmos/mint/v1beta1/annual_provisions"
get_rest ixo_mint_params "/ixo/mint/v1beta1/params"
get_rest ixo_mint_epoch_provisions "/ixo/mint/v1beta1/epoch_provisions"

# Validator sets.
get_rest validators_bonded "/cosmos/staking/v1beta1/validators?status=BOND_STATUS_BONDED&pagination.limit=1000"
get_rest validators_unbonding "/cosmos/staking/v1beta1/validators?status=BOND_STATUS_UNBONDING&pagination.limit=1000"
get_rest validators_unbonded "/cosmos/staking/v1beta1/validators?status=BOND_STATUS_UNBONDED&pagination.limit=1000"
get_rest slashing_params "/cosmos/slashing/v1beta1/params"

# Governance.
get_rest gov_params_deposit "/cosmos/gov/v1/params/deposit"
get_rest gov_params_voting "/cosmos/gov/v1/params/voting"
get_rest gov_params_tallying "/cosmos/gov/v1/params/tallying"
get_rest gov_proposals "/cosmos/gov/v1/proposals?pagination.limit=1000"

# IBC and representations.
get_rest ibc_channels "/ibc/core/channel/v1/channels?pagination.limit=1000"
get_rest ibc_connections "/ibc/core/connection/v1/connections?pagination.limit=1000"
get_rest ibc_clients "/ibc/core/client/v1/client_states?pagination.limit=1000"
get_rest ibc_denom_traces "/ibc/apps/transfer/v1/denom_traces?pagination.limit=1000"
get_rest ibc_transfer_params "/ibc/apps/transfer/v1/params"
get_rest ibc_total_escrow_uixo "/ibc/apps/transfer/v1/denoms/uixo/total_escrow"

# IXO liquid staking.
get_rest liquidstake_module_params "/ixo/liquidstake/v1beta1/module_params"
get_rest liquidstake_pools "/ixo/liquidstake/v1beta1/pools?pagination.limit=1000"
get_rest liquidstake_states "/ixo/liquidstake/v1beta1/states?pagination.limit=1000"

# Query balances of all module accounts discovered at H.
if [[ -f "$OUT_DIR/raw/rest/auth_module_accounts.json" ]]; then
  jq -r '.. | objects | .address? // empty' "$OUT_DIR/raw/rest/auth_module_accounts.json" | grep '^ixo1' | sort -u > "$OUT_DIR/module-addresses.txt" || true
  while IFS= read -r addr; do
    [[ -z "$addr" ]] && continue
    get_rest "module_balance_${addr}" "/cosmos/bank/v1beta1/balances/${addr}?pagination.limit=10000"
  done < "$OUT_DIR/module-addresses.txt"
fi

# Per-proposal details.
if [[ -f "$OUT_DIR/raw/rest/gov_proposals.json" ]]; then
  jq -r '.proposals[]? | .id // .proposal_id // empty' "$OUT_DIR/raw/rest/gov_proposals.json" | sort -n -u > "$OUT_DIR/proposal-ids.txt" || true
  while IFS= read -r id; do
    [[ -z "$id" ]] && continue
    get_rest "gov_proposal_${id}" "/cosmos/gov/v1/proposals/${id}"
    get_rest "gov_deposits_${id}" "/cosmos/gov/v1/proposals/${id}/deposits?pagination.limit=1000"
    get_rest "gov_votes_${id}" "/cosmos/gov/v1/proposals/${id}/votes?pagination.limit=1000"
    get_rest "gov_tally_${id}" "/cosmos/gov/v1/proposals/${id}/tally"
  done < "$OUT_DIR/proposal-ids.txt"
fi

# Recent activity window via CometBFT tx_search. Preserve raw pages; cap prevents runaway artifacts.
LOW=$(( H > ACTIVITY_BLOCKS ? H - ACTIVITY_BLOCKS + 1 : 1 ))
printf '%s\n' "$LOW" > "$OUT_DIR/activity-low-height.txt"
page=1
while (( page <= MAX_TX_PAGES )); do
  file="$OUT_DIR/raw/rpc/tx_search_${page}.json"
  url="$PRIMARY_RPC/tx_search"
  log_cmd curl -fsS --get --data-urlencode "query=tx.height >= $LOW AND tx.height <= $H" --data-urlencode "prove=false" --data-urlencode "page=$page" --data-urlencode "per_page=100" --data-urlencode "order_by=asc" "$url"
  if ! curl -fsS --retry 2 --retry-all-errors --connect-timeout 10 --max-time 60 --get \
      --data-urlencode "query=tx.height >= $LOW AND tx.height <= $H" \
      --data-urlencode "prove=false" \
      --data-urlencode "page=$page" \
      --data-urlencode "per_page=100" \
      --data-urlencode "order_by=asc" \
      "$url" > "$file"; then
    record_query "tx_search_${page}" "$url" false "curl-failed-or-index-disabled"
    rm -f "$file"
    break
  fi
  if jq -e '.error != null' "$file" >/dev/null 2>&1; then
    record_query "tx_search_${page}" "$url" false "rpc-error-or-index-disabled"
    break
  fi
  record_query "tx_search_${page}" "$url" true
  count=$(jq -r '.result.txs | length' "$file")
  total=$(jq -r '.result.total_count // "0" | tonumber' "$file")
  (( count == 0 || page * 100 >= total )) && break
  page=$((page + 1))
done

# Secondary market context: raw only; never promoted to valuation without depth/spread evidence.
for market_url in \
  "https://api.coingecko.com/api/v3/coins/ixo/market_chart?vs_currency=usd&days=1&interval=hourly" \
  "https://api.coingecko.com/api/v3/coins/ixo/tickers?include_exchange_logo=false&depth=true"; do
  name=$(safe_name "$market_url")
  if curl_body "$market_url" "$OUT_DIR/raw/market/${name}.json"; then
    record_query "market_${name}" "$market_url" true
  else
    record_query "market_${name}" "$market_url" false "secondary-market-source-unavailable"
    rm -f "$OUT_DIR/raw/market/${name}.json"
  fi
done

# 4. Derive cleaned tables and checks.
python3 "$(dirname "$0")/derive.py" "$OUT_DIR"

# Integrity manifest after all outputs are generated.
(
  cd "$OUT_DIR"
  find . -type f ! -path './hashes/sha256sums.txt' -print0 | sort -z | xargs -0 sha256sum > hashes/sha256sums.txt
)

jq -n \
  --arg completed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --argjson failed_queries "$(jq -s '[.[]|select(.ok==false)]|length' "$OUT_DIR/query-status.jsonl")" \
  --argjson successful_queries "$(jq -s '[.[]|select(.ok==true)]|length' "$OUT_DIR/query-status.jsonl")" \
  '{completed_at_utc:$completed_at,successful_queries:$successful_queries,failed_queries:$failed_queries}' \
  > "$OUT_DIR/run-result.json"

printf 'IXO-3947 capture complete: %s at height %s\n' "$OUT_DIR" "$H"
