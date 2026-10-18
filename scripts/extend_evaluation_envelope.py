"""Explicit offline fixed audit transitions of one existing private evaluation ledger.

No provider/key handling. Provenance hashes record operator evidence; they do not grant permission.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.real_eval_budget import (
    extend_evaluation_envelope,
    extend_evaluation_followup,
    inspect_extension_candidate,
    inspect_followup_candidate,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'action', choices=('inspect', 'extend-1100-6-usd', 'inspect-followup', 'extend-1600-6-usd')
    )
    parser.add_argument('--budget-state', type=Path, required=True)
    parser.add_argument('--expected-snapshot', type=Path)
    parser.add_argument('--previous-audit-sha256')
    parser.add_argument('--authorization-ref')
    parser.add_argument('--authorization-sha256')
    parser.add_argument('--source-revision')
    parser.add_argument('--manifest-sha256')
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == 'inspect':
        print(json.dumps(inspect_extension_candidate(args.budget_state), sort_keys=True))
        return
    if args.action in ('inspect-followup', 'extend-1600-6-usd') and args.previous_audit_sha256 is None:
        parser.error('followup requires the exact previous audit SHA256')
    if args.action == 'inspect-followup':
        print(
            json.dumps(
                inspect_followup_candidate(
                    args.budget_state, previous_audit_sha256=args.previous_audit_sha256
                ),
                sort_keys=True,
            )
        )
        return
    if args.action == 'extend-1100-6-usd' and args.previous_audit_sha256 is not None:
        parser.error('previous audit applies only to the fixed followup')
    if any(
        value is None
        for value in (
            args.expected_snapshot,
            args.authorization_ref,
            args.authorization_sha256,
            args.source_revision,
            args.manifest_sha256,
        )
    ):
        parser.error('extension requires the exact snapshot and all owner/source/manifest provenance')
    migrate = extend_evaluation_followup if args.action == 'extend-1600-6-usd' else extend_evaluation_envelope
    previous = (
        {'previous_audit_sha256': args.previous_audit_sha256} if args.action == 'extend-1600-6-usd' else {}
    )
    digest = migrate(
        args.budget_state,
        expected_snapshot=json.loads(args.expected_snapshot.read_text()),
        authorization_ref=args.authorization_ref,
        authorization_sha256=args.authorization_sha256,
        source_revision=args.source_revision,
        manifest_sha256=args.manifest_sha256,
        **previous,
    )
    print(
        json.dumps(
            {'audit_sha256': digest, 'new_max_attempts': 1600 if previous else 1100, 'new_cap_micro': 6000000}
        )
    )


if __name__ == '__main__':
    main()
