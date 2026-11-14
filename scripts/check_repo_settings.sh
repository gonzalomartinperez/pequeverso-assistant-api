#!/usr/bin/env bash
# Read-only check of the repository security settings the ecosystem standard requires (PVA-M1.6).
# Needs `gh` authenticated as a repository admin (the Actions GITHUB_TOKEN cannot read these).
# Prints one line per setting and exits 1 when any required setting is off. Changes nothing.
set -euo pipefail

repo="${1:-gonzalomartinperez/pequeverso-assistant-api}"
fail=0

check() {
  local name=$1 actual=$2 expected=$3
  if [ "$actual" = "$expected" ]; then
    printf 'ok    %-40s %s\n' "$name" "$actual"
  else
    printf 'FAIL  %-40s %s (expected %s)\n' "$name" "$actual" "$expected"
    fail=1
  fi
}

analysis=$(gh api "repos/$repo" --jq '.security_and_analysis')
check 'secret scanning' "$(jq -r '.secret_scanning.status' <<<"$analysis")" enabled
check 'secret scanning push protection' "$(jq -r '.secret_scanning_push_protection.status' <<<"$analysis")" enabled
check 'Dependabot security updates (OD-22)' "$(jq -r '.dependabot_security_updates.status' <<<"$analysis")" disabled
if gh api "repos/$repo/vulnerability-alerts" --silent 2>/dev/null; then alerts=enabled; else alerts=disabled; fi
check 'Dependabot alerts' "$alerts" enabled
check 'private vulnerability reporting' "$(gh api "repos/$repo/private-vulnerability-reporting" --jq '.enabled')" true
check 'CodeQL default setup' "$(gh api "repos/$repo/code-scanning/default-setup" --jq '.state')" configured

exit "$fail"
