#!/usr/bin/env bash
# PVA-M2.10 contract gate: fail when contracts/openapi.json breaks the base revision, unless the
# pull request carries the label `contract-major`. Usage: contract_breaking.sh <base-ref> [oasdiff]
# Env: PR_LABELS (JSON array of label names, may be empty). Labels are data, never interpolated.
set -euo pipefail

base_ref="${1:?base git ref}"
oasdiff="${2:-oasdiff}"
spec="contracts/openapi.json"
base_spec="$(mktemp)"
trap 'rm -f "$base_spec"' EXIT

if ! git show "$base_ref:$spec" >"$base_spec" 2>/dev/null; then
  echo "::notice title=contract::no $spec at the base revision; nothing to compare"
  exit 0
fi

status=0
"$oasdiff" breaking --fail-on ERR "$base_spec" "$spec" || status=$?
if [ "$status" -ne 0 ]; then
  if jq -e 'index("contract-major")' <<<"${PR_LABELS:-[]}" >/dev/null; then
    echo "::notice title=contract::breaking changes allowed by the contract-major label"
    exit 0
  fi
  echo "::error title=contract::breaking change in $spec; fix it or have the owner add the contract-major label"
  exit "$status"
fi
