#!/usr/bin/env bash
# Redacted secret scan of the full git history with gitleaks (image pinned by digest, v8.30.1).
# Findings print rule, file, line and commit; secret values are always redacted. Fails closed:
# an error, a finding, or a scan that saw no commits (e.g. a shallow or broken checkout) all fail.
#   .github/scripts/secret-scan.sh [repo-dir]
set -uo pipefail

REPO="$(cd "${1:-.}" && pwd)"
IMAGE="ghcr.io/gitleaks/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f"

if [[ "$(git -C "$REPO" rev-parse --is-shallow-repository)" == true ]]; then
  echo "::error::secret scan needs the full history (checkout with fetch-depth: 0)"
  exit 1
fi

output="$(docker run --rm -v "$REPO:/repo:ro" "$IMAGE" git /repo \
  --config /repo/.github/gitleaks.toml --redact=100 --no-banner --no-color --verbose 2>&1)"
status=$?
printf '%s\n' "$output"

if [[ $status -ne 0 ]]; then
  echo "::error::gitleaks reported findings or failed (exit $status)"
  exit 1
fi
if ! grep -Eq '\b[1-9][0-9]* commits scanned' <<<"$output"; then
  echo "::error::gitleaks scanned no commits; refusing to report a clean result"
  exit 1
fi
