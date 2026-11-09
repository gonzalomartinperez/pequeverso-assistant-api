# Sources — pequeverso-assistant-api master plan

Every external source behind a decision. All were read or verified by the research pass of 2026-11-09 and are carried in `research/` (copies of the cited notes); where a note saw only a search snippet, the note says so. Flag: **C** = commercial interest in the topic or tool (vendor, consultancy, affiliate-style site), **P** = primary (standard, paper, official docs), **B** = practitioner blog. Repo-internal evidence is listed last; the audit numbers come from `audit/` files and the repository at develop `6912579`.

## AI quality (research note `research/03-rag-evals.md`)

| Source | URL | Flag | Used for |
|---|---|---|---|
| Anthropic, "Demystifying evals for AI agents" | https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents | P, C (model vendor) | regression versus capability suites, pass^k, graders |
| Hamel Husain, Evals FAQ | https://hamel.dev/blog/posts/evals-faq/ | B, C (training) | judge validation, label counts, 100% caveat |
| ranx (Bassani) | https://pypi.org/project/ranx/ | P (MIT) | recall, nDCG, MRR, paired tests |
| "How to Correctly Report LLM-as-a-Judge Evaluations" | https://arxiv.org/html/2511.21140v3 | P | corrected pass rates, intervals |
| MEMERAG; XRAG cross-lingual RAG | https://aclanthology.org/2025.findings-emnlp.849 ; https://arxiv.org/abs/2505.10089 | P | locale as a first-class stratum; Spanish faithfulness weaker |
| AbstentionBench | https://arxiv.org/abs/2506.09038 | P | abstention stratum at least 25% |
| ALCE; RAGChecker | https://arxiv.org/pdf/2305.14627 ; https://arxiv.org/pdf/2408.08067 | P | citation and claim checks |
| tau-bench (pass^k) | https://arxiv.org/pdf/2406.12045 | P | k = 3 live trials |
| LangSmith pytest integration and prompt management | https://docs.langchain.com/langsmith/pytest ; https://docs.langchain.com/langsmith/manage-prompts | P, C (LangChain) | considered; not used at runtime, repo is the registry |
| OWASP Top 10 for LLM Applications 2025 | https://genai.owasp.org/llm-top-10/ | P | red-team classes |
| OpenAI to acquire Promptfoo; red-team tool comparisons | https://openai.com/index/openai-to-acquire-promptfoo/ ; https://appsecsanta.com/garak-vs-promptfoo | C (fetch blocked, via summaries) | promptfoo not adopted |
| Thinking Machines, nondeterminism (secondary coverage) | https://simonwillison.net/2025/Sep/11/defeating-nondeterminism | B | cassette lane rationale |

## Testing (`research/04-testing.md`)

| Source | URL | Flag | Used for |
|---|---|---|---|
| mutmut | https://github.com/boxed/mutmut | P | scoped mutation |
| Python mutation comparisons | https://arxiv.org/html/2601.19088v1 | P | tool choice, equivalent mutants |
| Practical Mutation Testing at Scale (Google) | https://arxiv.org/pdf/2102.11378v1 | P | gate with headroom, review aid |
| Hypothesis docs and settings | https://hypothesis.readthedocs.io/en/latest/tutorial/settings.html | P | profiles `ci` and `nightly` |
| Schemathesis stateful testing | https://schemathesis.readthedocs.io/en/latest/guides/stateful-testing/ | P | OpenAPI links, 50/500 examples |
| oasdiff | https://github.com/oasdiff/oasdiff | P, C (hosted tier) | breaking-change gate |
| diff-cover | https://pypi.python.org/pypi/diff_cover/0.9.1 | P | diff coverage 90% |
| xk6-sse; SSE load guides | https://github.com/phymbert/xk6-sse ; https://loadforge.com/guides/api-protocols/load-testing-server-sent-events-sse | P ; C | load tool choice (Locust picked) |
| Testcontainers for Python | https://testcontainers-python.readthedocs.io/en/latest/ | P | considered; repo keeps its own service jobs |

## Python architecture and standards (`research/02-python-architecture.md`, `research/10-standards-dependencies.md`)

| Source | URL | Flag | Used for |
|---|---|---|---|
| import-linter docs | https://import-linter.readthedocs.io/en/stable/ | P | layer contracts |
| uv Docker guide | https://docs.astral.sh/uv/guides/integration/docker/ | P | Dockerfile |
| uv resolution and cooldowns | https://docs.astral.sh/uv/concepts/resolution/ | P | `exclude-newer` |
| FastAPI SSE tutorial | https://fastapi.tiangolo.com/tutorial/server-sent-events/ | P | native SSE |
| Google Python Style Guide | https://google.github.io/styleguide/pyguide.html | P | style and docstrings |
| Ruff rules and formatter | https://docs.astral.sh/ruff/rules/ | P | rule families, format migration |
| Python 3.14 What's New; Python devguide versions | https://docs.python.org/3/whatsnew/3.14.html ; https://devguide.python.org/versions/ | P | 3.14.x policy |
| Pyrefly 1.0; ty releases | https://github.com/facebook/pyrefly/releases/tag/1.0.0 ; https://github.com/astral-sh/ty/releases | P | second checker non-blocking |
| MADR | https://adr.github.io/madr/ | P | ADR template, dependency ADR |
| "We should all be using dependency cooldowns" | https://blog.yossarian.net/2025/11/21/We-should-all-be-using-dependency-cooldowns | B | cooldown values |

## CI, supply chain, containers (`research/05-cicd-supply-chain.md`, `research/11-containers-dynamic-ci.md`)

| Source | URL | Flag | Used for |
|---|---|---|---|
| GitHub Dependabot options reference | https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference | P | multi-ecosystem groups, cooldown |
| GitHub, "Tame Dependabot" | https://github.blog/security/application-security/tame-dependabot-group-your-updates-slow-the-cadence-keep-security-fast/ | P, C (GitHub) | grouping |
| Dependabot wildcard groups and cooldown trap (single source) | https://dev.classmethod.jp/en/articles/dependabot-wildcard-group-cooldown-trap/ | B | unverified point (4) |
| zizmor docs | https://docs.zizmor.sh/release-notes/ | P | workflow audit |
| GitHub artifact attestations | https://docs.github.com/en/actions/concepts/security/artifact-attestations | P | provenance, verify |
| Immutable releases GA | https://github.blog/changelog/2025-10-28-immutable-releases-are-now-generally-available/ | P | release rule |
| SLSA v1.2 announcement | https://slsa.dev/blog/2025/11/announce-slsa-v1.2 | P | claim limits |
| OpenSSF Scorecard | https://securityscorecards.dev | P | weekly score |
| Trivy supply chain compromise (Aqua; Snyk) | https://www.aquasec.com/blog/trivy-supply-chain-attack-what-you-need-to-know/ ; https://snyk.io/articles/trivy-github-actions-supply-chain-compromise/ | C (vendors) | Grype default, Trivy binary pinned |
| tj-actions compromise | https://thehackernews.com/2025/03/github-action-compromise-puts-cicd.html | B | SHA pinning rationale |
| release-please action | https://github.com/googleapis/release-please-action | P | release automation |
| StepSecurity harden-runner | https://docs.stepsecurity.io/harden-runner | C | egress control on publish job |
| Node, Debian, PostgreSQL, Neo4j lifecycle data | https://endoflife.date ; https://raw.githubusercontent.com/nodejs/Release/main/schedule.json | P | LTS matrix |
| Docker SLSA provenance and GHA attestations | https://docs.docker.com/build/ci/github-actions/attestations/ | P | image attest |
| hadolint, dockle, container-structure-test | https://github.com/hadolint/hadolint ; https://github.com/goodwithtech/dockle ; https://github.com/GoogleContainerTools/container-structure-test | P | image gates |
| Grype | https://github.com/anchore/grype | P, C (Anchore) | image scan |
| Docker Hardened Images | https://docs.docker.com/dhi/ | C | pilot only, not adopted here |

## Documentation and harness (`research/08-docs-readme-skills.md`)

| Source | URL | Flag | Used for |
|---|---|---|---|
| Agent Skills specification and evaluation | https://agentskills.io/specification ; https://agentskills.io/skill-creation/evaluating-skills | P | skill layout and activation evals |
| Anthropic, skill authoring best practices | https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices | P, C | skill size and description rules |
| AGENTS.md; evaluating AGENTS.md | https://www.agents.md ; https://arxiv.org/abs/2602.11988 | P | agent docs scope |
| Diátaxis; Keep a Changelog; Conventional Commits | https://diataxis.fr ; https://keepachangelog.com/en/1.1.0/ ; https://www.conventionalcommits.org/en/v1.0.0/ | P | docs system |
| lychee; markdownlint-cli2 | https://github.com/lycheeverse/lychee ; https://github.com/DavidAnson/markdownlint-cli2 | P | docs CI |
| VPS and SLOs (backup, alerting on SLOs) | https://sre.google/workbook/alerting-on-slos/ | P, C (Google) | SLO design for MV (`research/09-vps-ops.md`) |

## Repository evidence (not external)

| Evidence | Path or commit | Used for |
|---|---|---|
| Audit measurements | planner `audit/pequeverso-assistant-api/` (pytest, coverage, mypy, ruff, Trivy, corpus, retrieval) and the copies under `audit/` here | all baseline numbers |
| Real-model evaluation records | `docs/verification/real-model-2026-10-12.md`, `real-evaluation-2026-10-18.md`, `real-evaluation-2026-10-19.md` at develop `6912579` | acceptance baseline, cost per generation |
| ADR-0002, ADR-0003, ADR-0006, ADR-0008, ADR-0009 | `docs/decisions/` | architecture and language constraints |
| `AGENTS.md`, `docs/security.md`, `docs/evaluation.md`, `docs/ci.md`, `docs/dependency-updates.md` | develop `6912579` | rules and drift findings |
| Owner requirements and decisions | `owner-decisions.md`, `shared/ecosystem.md` section 2 (copied here as `ecosystem.md`) | binding constraints |
| Retrieval recall@k, ruff families | `audit/recall-at-k.txt`, `audit/ruff-ecosystem-families.txt` (measured by the planner on a `git archive` of develop `6912579`) | weak-family analysis, migration size |

Unverified in this plan and marked where used: GHSA-6q48-6c7w-9gw2 text (only its ID, severity and fixed version were read from the scan); mutmut and ranx on CPython 3.14; Dependabot multi-ecosystem group behaviour (ecosystem 5.4); Dependabot resolution of ARG-substituted `FROM`; release-please on `develop` (E5); package licences (to be checked by the licence job).
