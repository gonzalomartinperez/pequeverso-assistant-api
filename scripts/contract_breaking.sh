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

if ! git cat-file -e "$base_ref^{commit}" 2>/dev/null; then
  echo "::error title=contract::base ref '$base_ref' is not a commit; cannot compare $spec"
  exit 2
fi
# ls-tree prints nothing for a missing path and fails on a repository error (which then fails here).
if [ -z "$(git ls-tree --name-only "$base_ref" -- "$spec")" ]; then
  echo "::notice title=contract::no $spec at the base revision; nothing to compare"
  exit 0
fi
git show "$base_ref:$spec" >"$base_spec"

status=0
"$oasdiff" breaking --fail-on ERR "$base_spec" "$spec" || status=$?
if [ "$status" -eq 0 ]; then
  exit 0
fi
# Only exit 1 means "breaking changes found" (--fail-on ERR). Any other status (102 load failure,
# 127 missing binary, ...) is a tool failure that no label may override.
if [ "$status" -eq 1 ] && jq -e 'index("contract-major")' <<<"${PR_LABELS:-[]}" >/dev/null; then
  echo "::notice title=contract::breaking changes allowed by the contract-major label"
  exit 0
fi
if [ "$status" -eq 1 ]; then
  echo "::error title=contract::breaking change in $spec; fix it or have the owner add the contract-major label"
else
  echo "::error title=contract::oasdiff failed with status $status (not a breaking-change result)"
fi
exit "$status"
