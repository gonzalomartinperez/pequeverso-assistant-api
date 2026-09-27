"""Eligibility policy for unattended Dependabot merges (stdlib only; runs from the base branch).

The decision uses authenticated GitHub API metadata and a semantic comparison of the manifests
at the base and head revisions. It never uses PR titles, labels or branch names as authority,
and never executes code from the pull request.

    GITHUB_TOKEN=... python3 scripts/dependabot_policy.py --repo owner/name --pr 12 --head-sha <sha>

Outputs a JSON decision on stdout and `eligible=<true|false>` / `automerge=<true|false>` to
$GITHUB_OUTPUT when set. See docs/dependency-updates.md.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEPENDABOT_LOGIN = 'dependabot[bot]'
DEPENDABOT_ID = 49699333
POLICY_FILE = Path(__file__).resolve().parents[1] / '.github' / 'dependabot-policy.json'
_PRERELEASE = re.compile(r'^\d+(?:\.\d+)*(?:(?:a|b|rc)\d+|\.dev\d+)')
_VERSION = re.compile(r'^(\d+)\.(\d+)(?:\.(\d+))?(?:\.post\d+)?$')


@dataclass(frozen=True)
class Policy:
    base_branch: str
    allowed_files: frozenset[str]
    patch: frozenset[str]
    minor: frozenset[str]
    required_checks: frozenset[str]

    @classmethod
    def load(cls, path: Path = POLICY_FILE) -> Policy:
        data = json.loads(path.read_text())
        return cls(
            base_branch=data['base_branch'],
            allowed_files=frozenset(data['allowed_files']),
            patch=frozenset(_normalize(n) for n in data['patch']),
            minor=frozenset(_normalize(n) for n in data['minor']),
            required_checks=frozenset(data['required_checks']),
        )


@dataclass(frozen=True)
class Commit:
    author_login: str | None
    committer_login: str | None
    verified: bool


@dataclass(frozen=True)
class CheckRun:
    name: str
    status: str
    conclusion: str | None


@dataclass(frozen=True)
class PullFacts:
    author_login: str
    author_type: str
    author_id: int
    head_repo: str | None
    base_repo: str
    base_ref: str
    state: str
    draft: bool
    head_sha: str
    expected_head_sha: str
    mergeable_state: str
    commits: tuple[Commit, ...]
    files: tuple[tuple[str, str], ...]
    base_manifests: dict[str, str]
    head_manifests: dict[str, str]
    check_runs: tuple[CheckRun, ...]
    protection_available: bool


@dataclass
class Decision:
    eligible: bool = True
    automerge: bool = False
    reasons: list[str] = field(default_factory=list)
    updates: list[dict[str, str]] = field(default_factory=list)
    ci: str = 'missing'

    def reject(self, reason: str) -> None:
        self.eligible = False
        self.reasons.append(reason)


def _normalize(name: str) -> str:
    return re.sub(r'[-_.]+', '-', name).lower()


def classify(old: str | None, new: str | None) -> str:
    """Semantic change of one package: patch, minor, major, prerelease, added, removed or unknown."""
    if old is None:
        return 'added'
    if new is None:
        return 'removed'
    a, b = _VERSION.match(old), _VERSION.match(new)
    if b is None:
        return 'prerelease' if _PRERELEASE.match(new) else 'unknown'
    if a is None:
        return 'unknown'
    old_parts = [int(x or 0) for x in a.groups()]
    new_parts = [int(x or 0) for x in b.groups()]
    if new_parts <= old_parts:
        return 'unknown'  # downgrade or no change
    if new_parts[0] != old_parts[0]:
        return 'major'
    if new_parts[1] != old_parts[1]:
        # In 0.x, a minor bump may break the API (semver item 4): treat it like a major.
        return 'major' if new_parts[0] == 0 else 'minor'
    return 'patch'


def lock_versions(text: str) -> dict[str, str]:
    data = tomllib.loads(text)
    return {_normalize(p['name']): str(p.get('version', '')) for p in data.get('package', [])}


def _requirement_name(spec: str) -> str:
    match = re.match(r'\s*([A-Za-z0-9][A-Za-z0-9._-]*)', spec)
    return _normalize(match.group(1)) if match else spec


def _pyproject_skeleton(text: str) -> tuple[Any, dict[str, list[str]]]:
    """Everything except dependency specifiers, plus the dependency names per list."""
    data = tomllib.loads(text)
    lists: dict[str, list[str]] = {}
    project = data.get('project', {})
    if 'dependencies' in project:
        lists['project'] = sorted(_requirement_name(s) for s in project['dependencies'])
        project['dependencies'] = None
    for group, specs in data.get('dependency-groups', {}).items():
        lists[f'group:{group}'] = sorted(_requirement_name(s) for s in specs)
        data['dependency-groups'][group] = None
    return data, lists


def evaluate(facts: PullFacts, policy: Policy) -> Decision:
    decision = Decision()

    # Identity and target: only Dependabot's own same-repository PR against the integration branch.
    if (facts.author_login, facts.author_type, facts.author_id) != (DEPENDABOT_LOGIN, 'Bot', DEPENDABOT_ID):
        decision.reject('author is not the Dependabot app')
    if facts.head_repo != facts.base_repo:
        decision.reject('head comes from another repository')
    if facts.base_ref != policy.base_branch:
        decision.reject(f'base branch is {facts.base_ref!r}, not {policy.base_branch!r}')
    if facts.state != 'open' or facts.draft:
        decision.reject('pull request is not open and ready')
    if facts.head_sha != facts.expected_head_sha:
        decision.reject('head moved since this evaluation started')

    # Provenance of every commit: authored and committed by Dependabot, GitHub-verified.
    if not facts.commits:
        decision.reject('no commits')
    for commit in facts.commits:
        if commit.author_login != DEPENDABOT_LOGIN or not commit.verified:
            decision.reject('a commit is not a verified Dependabot commit (human or foreign change)')
            break

    # File scope.
    names = {name for name, _ in facts.files}
    if unexpected := sorted(names - policy.allowed_files):
        shown = ', '.join(unexpected[:10]) + (
            f' (+{len(unexpected) - 10} more)' if len(unexpected) > 10 else ''
        )
        decision.reject(f'unexpected files changed: {shown}')
    if any(status != 'modified' for _, status in facts.files):
        decision.reject('files were added, removed or renamed')

    # pyproject.toml may only change dependency specifiers of the same packages.
    if 'pyproject.toml' in names:
        try:
            base_skeleton, base_lists = _pyproject_skeleton(facts.base_manifests['pyproject.toml'])
            head_skeleton, head_lists = _pyproject_skeleton(facts.head_manifests['pyproject.toml'])
        except (KeyError, tomllib.TOMLDecodeError):
            decision.reject('pyproject.toml could not be compared')
        else:
            if base_skeleton != head_skeleton:
                decision.reject(
                    'pyproject.toml changes more than dependency versions (scripts, tools or settings)'
                )
            if base_lists != head_lists:
                decision.reject('dependencies were added, removed or moved between groups')

    # Every changed locked package must qualify under the allowlist.
    try:
        old = lock_versions(facts.base_manifests['uv.lock'])
        new = lock_versions(facts.head_manifests['uv.lock'])
    except (KeyError, tomllib.TOMLDecodeError):
        decision.reject('uv.lock could not be compared')
        old, new = {}, {}
    changed = sorted(
        n for n in old.keys() | new.keys() if old.get(n) != new.get(n) and n != 'pequeverso-assistant-api'
    )
    if 'uv.lock' in names and not changed:
        decision.reject('lockfile changed without a version change (impact unknown)')
    for name in changed:
        kind = classify(old.get(name), new.get(name))
        decision.updates.append(
            {'package': name, 'from': old.get(name, ''), 'to': new.get(name, ''), 'type': kind}
        )
        if kind == 'patch' and (name in policy.patch or name in policy.minor):
            continue
        if kind == 'minor' and name in policy.minor:
            continue
        decision.reject(f'{name} {old.get(name)} -> {new.get(name)} ({kind}) is not allowlisted')

    # Merge state and checks (native auto-merge still enforces required checks itself).
    if facts.mergeable_state in ('dirty', 'unknown'):
        decision.reject(f'mergeable state is {facts.mergeable_state!r} (conflict or not computed)')
    decision.ci = ci_state(facts.check_runs, policy.required_checks)
    if decision.ci in ('failure', 'cancelled'):
        decision.reject(f'required checks {decision.ci}')

    decision.automerge = decision.eligible and facts.protection_available
    if decision.eligible and not facts.protection_available:
        decision.reasons.append(
            'eligible, but auto-merge stays off: the base branch has no enforceable protection '
            '(required checks) on this plan'
        )
    return decision


def protection_from_rules(rules: list[dict[str, Any]], required: frozenset[str]) -> bool:
    """True when the active branch rules require a PR and every required check, up to date (strict)."""
    has_pull_request = any(rule.get('type') == 'pull_request' for rule in rules)
    enforced: set[str] = set()
    for rule in rules:
        if rule.get('type') != 'required_status_checks':
            continue
        parameters = rule.get('parameters') or {}
        if parameters.get('strict_required_status_checks_policy'):
            enforced |= {check.get('context', '') for check in parameters.get('required_status_checks', [])}
    return has_pull_request and required <= enforced


def ci_state(runs: tuple[CheckRun, ...], required: frozenset[str]) -> str:
    """success | pending | failure | cancelled | missing, over the required check names."""
    states = []
    for name in required:
        matching = [r for r in runs if r.name == name]
        if not matching:
            states.append('missing')
            continue
        run = matching[-1]
        if run.status != 'completed':
            states.append('pending')
        elif run.conclusion == 'success':
            states.append('success')
        elif run.conclusion == 'cancelled':
            states.append('cancelled')
        else:
            states.append('failure')
    for state in ('failure', 'cancelled', 'pending', 'missing'):
        if state in states:
            return state
    return 'success'


# --- GitHub API collection (read-only) -------------------------------------------------------


class Api:
    def __init__(self, token: str, base: str = 'https://api.github.com') -> None:
        self._token = token
        self._base = base

    def get(self, path: str) -> Any:
        request = urllib.request.Request(  # noqa: S310 - fixed https API base, relative paths only
            f'{self._base}{path}',
            headers={
                'Authorization': f'Bearer {self._token}',
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - fixed https base
            return json.load(response)


def collect(api: Api, repo: str, number: int, expected_head: str) -> PullFacts:
    pr = api.get(f'/repos/{repo}/pulls/{number}')
    head_sha, base_sha = pr['head']['sha'], pr['base']['sha']
    commits = api.get(f'/repos/{repo}/pulls/{number}/commits?per_page=100')
    files = api.get(f'/repos/{repo}/pulls/{number}/files?per_page=100')

    def manifest(sha: str, path: str) -> str | None:
        try:
            data = api.get(f'/repos/{repo}/contents/{path}?ref={sha}')
        except urllib.error.HTTPError:
            return None
        return base64.b64decode(data['content']).decode()

    base_manifests = {p: t for p in ('pyproject.toml', 'uv.lock') if (t := manifest(base_sha, p)) is not None}
    head_manifests = {p: t for p in ('pyproject.toml', 'uv.lock') if (t := manifest(head_sha, p)) is not None}
    runs = api.get(f'/repos/{repo}/commits/{head_sha}/check-runs?per_page=100')['check_runs']
    rules = api.get(f'/repos/{repo}/rules/branches/{pr["base"]["ref"]}')
    protection = protection_from_rules(rules, Policy.load().required_checks)
    return PullFacts(
        author_login=pr['user']['login'],
        author_type=pr['user']['type'],
        author_id=pr['user']['id'],
        head_repo=(pr['head'].get('repo') or {}).get('full_name'),
        base_repo=pr['base']['repo']['full_name'],
        base_ref=pr['base']['ref'],
        state=pr['state'],
        draft=bool(pr.get('draft')),
        head_sha=head_sha,
        expected_head_sha=expected_head,
        mergeable_state=pr.get('mergeable_state') or 'unknown',
        commits=tuple(
            Commit(
                author_login=(c.get('author') or {}).get('login'),
                committer_login=(c.get('committer') or {}).get('login'),
                verified=bool(c['commit'].get('verification', {}).get('verified')),
            )
            for c in commits
        ),
        files=tuple((f['filename'], f['status']) for f in files),
        base_manifests=base_manifests,
        head_manifests=head_manifests,
        check_runs=tuple(CheckRun(r['name'], r['status'], r['conclusion']) for r in runs),
        protection_available=protection,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--repo', required=True)
    parser.add_argument('--pr', type=int, required=True)
    parser.add_argument('--head-sha', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', args.repo) or not re.fullmatch(r'[0-9a-f]{40}', args.head_sha):
        print('invalid arguments', file=sys.stderr)
        return 2
    facts = collect(Api(os.environ['GITHUB_TOKEN']), args.repo, args.pr, args.head_sha)
    decision = evaluate(facts, Policy.load())
    print(json.dumps(asdict(decision), indent=2))
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a') as handle:
            handle.write(
                f'eligible={str(decision.eligible).lower()}\nautomerge={str(decision.automerge).lower()}\n'
            )
    if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(summary, 'a') as handle:
            verdict = 'eligible' if decision.eligible else 'manual review'
            handle.write(
                f'### Dependabot policy: {verdict} (auto-merge {"on" if decision.automerge else "off"})\n\n'
            )
            handle.writelines(f'- {reason}\n' for reason in decision.reasons)
            handle.writelines(
                f'- `{u["package"]}` {u["from"]} → {u["to"]} ({u["type"]})\n' for u in decision.updates
            )
    return 0


if __name__ == '__main__':
    sys.exit(main())
