# Agent skills

`AGENTS.md` is the repository operating contract and `CLAUDE.md` imports it. Ordinary
orientation starts with the README; load the skill matching the requested task rather than
loading all six. Default automatic discovery remains enabled.

Each skill is a real directory under `.agents/skills/` (canonical; Codex reads this root), with
its only maintained procedure in `SKILL.md`. `.claude/skills/` is a real directory containing one
relative directory symlink per skill: `../../.agents/skills/<name>` (Claude Code reads this root).
Both clients therefore read the same physical file; there are no copied adapters or parallel
procedure versions.

Each `SKILL.md` frontmatter carries a `metadata` block with `owner`, `last-reviewed` (ISO date)
and `version` (semver). Each skill also has an `evals/triggers.json` activation-eval stub.

| Skill | Use it for | Previous name |
| --- | --- | --- |
| `api-change-use-case` | Prompts, answer rules, evidence and evaluations | `change-assistant-behavior` |
| `api-maintain-knowledge` | Catalog export from committed storefront main | `update-catalog` |
| `api-verify-release` | Candidate verification without paid calls or deployment | `verify-release` |
| `api-change-contract` | Compatible public HTTP/SSE or private operations contract changes | `change-api-contract` |
| `api-review-weekly-dependencies` | Review of the single weekly Dependabot PR; the owner merges | `review-dependency-update` |
| `api-release-and-hotfix` | Owner-authorized release or specific hotfix procedure | `release-and-hotfix` |

The rename preserves each existing procedure and its limits. It creates no new storage,
streaming or deployment capability. Skills never authorize paid calls, budget increases,
protected-branch mutations, cross-repository edits or deployment. A relevant skill remains
discoverable even when its mutation step needs explicit current owner authorization.

## Validation

Run from the repository root:

```sh
python -m scripts.validate_skills
uv run pytest -q tests/test_skills.py tests/test_ci_profile.py tests/test_dependabot_config.py
```

The stdlib-only validator checks the exact paired inventory, real canonical directories,
relative directory links, in-checkout targets and existing local references. Canonical resource
files and directories must also be real; use Markdown references rather than resource symlinks. It checks name
and description frontmatter, unique descriptions/procedures, limits/exclusions, unfinished
scaffolds, machine-specific paths and secret-like material. Frontmatter supports plain,
quoted and indented block descriptions; the `metadata` block (`owner`, `last-reviewed`,
`version`) and `evals/triggers.json` are required; other optional metadata is not executed. It follows no
URLs, executes no skill commands and reads no environment configuration.

These structural checks do not establish that a skill makes correct decisions. Review routing,
procedure changes and authorization boundaries separately. Negative fixtures exercise broken,
escaping, copied and mismatched discovery plus malformed metadata and local references.
Static CI invokes the validator in addition to existing full quality checks.

The physical layout was compared read-only with Portfolio API commit
`33c544dead74e0d30283516b6653b0e0aea84bca`; Pequeverso's six business-specific procedures
and approval boundaries remain its own.

## Activation evals

Each canonical skill ships `evals/triggers.json`, currently a stub:

```json
{"skill": "<name>", "status": "stub", "protocol": "docs/agent-skills.md#activation-evals",
 "queries": [{"query": "<text>", "should_trigger": true, "split": "train"}]}
```

`queries` holds synthetic English queries: positives that should activate the skill and near-miss
negatives that should not, divided into `train` and `validation` splits. The validator checks the
shape, that `skill` matches the directory and that both a positive and a negative exist. The full
protocol from `docs/master-plan/skills.md` section 3 arrives later.
