#!/usr/bin/env bash
# Contract gate: fail when a public or internal OpenAPI spec breaks the base revision, unless the
# pull request carries the label `contract-major`. Usage: contract_breaking.sh <base-ref> [oasdiff]
# Env: PR_LABELS (JSON array of label names, may be empty). Labels are data, never interpolated.
set -euo pipefail

base_ref="${1:?base git ref}"
oasdiff="${2:-oasdiff}"
base_spec="$(mktemp)"
trap 'rm -f "$base_spec"' EXIT

if ! git cat-file -e "$base_ref^{commit}" 2>/dev/null; then
  echo "::error title=contract::base ref '$base_ref' is not a commit; cannot compare OpenAPI specs"
  exit 2
fi
breaking=0
for spec in contracts/openapi.json contracts/openapi.internal.json; do
  # ls-tree prints nothing for a missing path. A repository error fails the assignment.
  base_path="$(git ls-tree --name-only "$base_ref" -- "$spec")"
  if [ -z "$base_path" ]; then
    echo "::notice title=contract::no $spec at the base revision; nothing to compare"
    continue
  fi
  git show "$base_ref:$spec" >"$base_spec"

  status=0
  "$oasdiff" breaking --fail-on ERR "$base_spec" "$spec" || status=$?
  if [ "$status" -eq 0 ]; then
    continue
  fi
  # Only exit 1 means "breaking changes found" (--fail-on ERR).
  if [ "$status" -ne 1 ]; then
    echo "::error title=contract::oasdiff failed with status $status (not a breaking-change result)"
    exit "$status"
  fi
  if jq -e 'index("contract-major")' <<<"${PR_LABELS:-[]}" >/dev/null; then
    echo "::notice title=contract::breaking changes allowed by the contract-major label"
  else
    echo "::error title=contract::breaking change in $spec; fix it or have the owner add the contract-major label"
    breaking=1
  fi
done
exit "$breaking"
