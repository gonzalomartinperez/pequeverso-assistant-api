# 03 - State of the art in evaluating RAG / agentic assistants (2026)

Date: 2026-11-09. Scope: two GraphRAG assistant APIs (FastAPI + LangGraph, pgvector + Neo4j): (A) bilingual EN/ES portfolio assistant, (B) Spanish e-commerce shopping advisor that must never invent prices or claims and must abstain out of scope. Owner goal: a golden set of N questions answered 100% correctly as a release gate. LangSmith is the tracing/eval backend.

Source marks: [C] = vendor with commercial interest in the topic; [P] = primary (paper, standard, official docs); [B] = practitioner blog/secondary. Sources were read via search summaries and fetches; where I only saw a snippet it is noted in "Contested/uncertain". Numbered refs in brackets point to the Sources list.

---

## 1. Executive summary

1. A "100% golden set" is meaningful only if it is a regression suite (tasks the system already passes, graduated from a capability suite), graded mostly by deterministic checks, run with k>1 trials (pass^k), and paired with a separate harder capability suite that is allowed to fail. Anthropic states regression evals should sit near 100% and capability evals should start low "giving teams a hill to climb" [1]. Hamel Husain warns that 100% on everything means you are not challenging the system [2]. Both are right: they describe different suites.
2. Make the gate a hard-invariant gate, not a quality score. For the shopping advisor the invariants are checkable in code: every price/SKU/claim in the answer must be traceable to a tool result; out-of-scope must abstain; no cross-locale drift. These need no LLM judge.
3. Size: start at 20-50 tasks from real failures [1]; grow to roughly 100-200 for the two combined suites. Per-assistant gate set of 60-120 items is defensible. Statistics: if 60 of 60 pass, the 95% upper bound on the true failure rate is about 5% (rule of three, 3/N); to claim under 2% you need about 150 clean items. A 100% result bounds the failure rate, it does not prove perfection.
4. Retrieval and generation must be evaluated separately. Recall@k first (an LLM can ignore noise but cannot answer from missing content), then nDCG/MRR for ranking [3][4]. Use ranx with qrels for paired significance testing [5].
5. LLM judges are for the fuzzy residue only, must be validated against human labels with TPR/TNR on a held-out test split (30-50 pass + 30-50 fail examples minimum per Husain [2]), and their pass rate corrected with Rogan-Gladen style estimators with confidence intervals [6]. Binary verdicts, one criterion per judge [2][7].
6. Determinism: temperature 0 does not give determinism on hosted APIs (batch variance, kernels) [8]. Use cassette record/replay (vcrpy/pytest-recording) for the CI gate, plus a separate nightly live run with pass^k, and treat live drift as a signal, not a gate.
7. Tooling: keep LangSmith (already in use, pytest integration, dataset versions, online evaluators, prompt commits/tags) as system of record; add ranx (MIT) and a small in-repo deterministic grader library; use promptfoo (MIT core, now owned by OpenAI) or garak for red teaming in CI/nightly. Keep every dataset in the repo as JSONL so lock-in is zero.

---

## 2. Designing the golden set

### 2.1 Philosophy: three suites, not one

| Suite | Purpose | Target pass rate | Gate? |
|---|---|---|---|
| Regression ("golden") | Things that must never break | 100% (pass^k, k=3) | Yes, blocks release |
| Capability | Hill-climbing on hard/new behavior | starts 30-70% | No, trend only |
| Adversarial/safety | Prompt injection, price-bait, scope escape | 100% on the invariant subset, report rest | Invariant subset yes |

Anthropic's agent-eval guidance: capability evals with high pass rates "graduate" into regression suites run continuously; a 0% pass rate across many trials "is most often a signal of a broken task, not an incapable agent"; saturated evals track regressions but give no improvement signal; ownership "should be as routine as maintaining unit tests" [1]. Practitioner counterpoint [2]: 100% pass rate usually means the eval is too easy, a 70% pass rate may be more informative, so keep a hard suite alongside the gate.

### 2.2 Size

- Start 20-50 tasks drawn from real failures [1]. Husain: review at least 100 traces to seed, repeat in 2-4 week cycles with 100+ fresh traces, and 10-20 traces weekly in between [2].
- Code-based checks need only enough pass/fail cases to cover each condition and edge case [2]. LLM judges need 100-200 labeled examples per failure mode (30-50 pass + 30-50 fail each in dev and test splits) [2].
- Eugene Yan (secondary summary): 200+ labeled samples with 50-100 failures for evaluator alignment [7].
- Recommendation: golden regression set 80-120 items per assistant at launch (grown from 40), judge-calibration set of 100+ human-labeled outputs per judged criterion kept separate from the gate set.

### 2.3 Stratification (the actual design work)

Define dimensions first, hand-write about 20 tuples, then expand and convert tuples to natural queries in a separate prompt [2]. Synthetic data cannot tell you how common a failure is in production and is unreliable for low-resource languages and high-stakes domains [2], so seed from real traces.

Dimensions to cross (filter invalid combinations):

- Intent: factual lookup, multi-hop/relationship (graph), comparison, recommendation, how-to, chit-chat, meta (who are you), refusal-worthy.
- Locale: EN, ES, mixed/code-switched, regional Spanish variants (es-ES, es-MX, es-AR vocabulary and currency formats), typos, no-accent text. MEMERAG found "adds new information" hallucinations 7% in English vs 16% in Spanish, and XRAG shows response-language errors in cross-lingual setups [9][10], so locale must be a first-class stratum, with language-of-answer checked deterministically.
- Retrieval difficulty: single-chunk, multi-chunk, multi-hop via graph, answer absent, near-duplicate distractors.
- Answerability: answerable, partially answerable, unanswerable-in-corpus, out-of-scope, false-premise, underspecified. AbstentionBench (20 datasets) shows frontier models struggle on all abstention types except unknown answers, reasoning fine-tuning lowers abstention about 24% on average, and scale does not help [11]. So abstention needs its own stratum with at least 25% of items.
- Adversarial: direct and indirect prompt injection via retrieved content, system prompt extraction, price-bait ("it said 9.99 yesterday"), discount invention, competitor claims, medical/legal claims, jailbreak in ES, role-play.
- Conversational: single-turn, follow-up with anaphora, correction, topic switch.
- Freshness/state: price changed, product out of stock, stale doc, deleted entity.

Suggested mix for the gate set: 35% answerable core (both locales), 15% graph/multi-hop, 25% abstain/out-of-scope/false-premise, 15% adversarial invariants, 10% multi-turn. Balance EN/ES per assistant according to traffic, but never fewer than 30% of the minority locale.

### 2.4 Item anatomy

Each item records: id, locale, stratum tags, query (and prior turns), expected behavior class (answer/abstain/clarify/refuse), required facts (atomic claims), forbidden claims, gold evidence ids (qrels), expected tool calls (optional, outcome over path [1]), deterministic assertions, optional judge rubric id, provenance (real trace, synthetic, adversarial author), reviewer, created/last-verified dates, corpus snapshot id, status (active/quarantined/retired). See section 12 for the schema.

### 2.5 Versioning, contamination, maintenance

- Version the dataset in git (JSONL, PR-reviewed, CODEOWNERS) and mirror to LangSmith. LangSmith creates a dataset version on every example add/update/delete, supports tags on versions, a diff endpoint, evaluating at a version via `as_of`, splits, and metadata filtering [12]. Pin CI to a tagged version so scores are comparable over time; use "latest" only in capability runs.
- Pin the corpus: items reference a corpus snapshot hash (pgvector ingest manifest + Neo4j graph export hash). Otherwise a data refresh silently changes gold answers. Prices in the shop assistant should come from a fixture catalog snapshot in tests, never live.
- Contamination has two meanings. (a) Parametric leakage: questions answerable without retrieval. A May 2026 study found no-context accuracy of 31-78% on existing multi-hop RAG benchmarks and proposed entity-substituted regeneration [13]. Test: run every item with retrieval disabled; items that pass are not testing RAG (except abstain items and chit-chat). (b) Eval overfitting: a ECIR 2026 paper shows a RAG system tuned against a judge can reach near-perfect scores when evaluation elements leak [14]; a practitioner post makes the same point about held-out sets that feed prompt iteration [15]. Controls: keep a sealed holdout (about 30% of items) that prompt authors cannot view and only the CI sees; rotate in fresh production-derived items each cycle; never paste golden items into prompts as few-shots; log who looked at which failures.
- Maintenance: quarantine flaky items instead of deleting; every retirement needs a reason; review the set quarterly; reports must show per-stratum pass counts because aggregate 100% can hide a thin stratum. Husain's cadence (2-4 week error-analysis cycles) [2] is a good default.

---

## 3. Making "100% on regression" meaningful and non-flaky

### 3.1 Layered graders (deterministic first)

Anthropic: prefer deterministic graders where possible, LLM graders where necessary, humans for validation; grade outcomes not exact paths; give partial credit for multi-part tasks [1]. Applied to our assistants, in order:

1. Structural: valid JSON/response schema, language of answer equals user language (fast langid + a script check), citation ids present and exist in retrieved set.
2. Invariant checks (code): every price/currency amount in the answer exists in tool output for the same SKU (regex + normalization of es-ES "1.299,00 EUR" vs en "1,299.00"); no discount percent not in data; no SKU not in catalog; abstention phrases or abstain flag on out-of-scope items; no URLs outside allowlist; system prompt canary string absent.
3. Retrieval checks: gold evidence ids in top-k (recall@k as assertion, not only a metric).
4. Claim checks: required atomic facts matched by normalized string/entity/number match, or by an NLI/entailment step against retrieved context (ALCE-style citation recall/precision; ALCE validated at about 85% recall and 78% precision agreement with humans, with false positives on partial support [16]).
5. LLM judge only for tone, helpfulness, completeness of nuanced answers; binary rubric, validated (section 6).

### 3.2 Determinism and flakiness

- Hosted-model temperature 0 is not deterministic; Thinking Machines attributes it mainly to lack of batch invariance in inference kernels rather than only floating-point/concurrency [8] (note: I saw secondary coverage; see Contested). Do not assume repeatability.
- Cassettes: record real LLM/embedding/tool HTTP traffic once and replay in CI (vcrpy + pytest-recording; LangChain docs point to this pattern for integration tests [17]). Filter auth headers, commit cassettes, set record mode `none` in CI, re-record deliberately when prompts/models change (cassettes go stale). Streaming/chunked responses can break vcrpy; test it [18]. Cassettes make the gate deterministic but only test your code and your graders against frozen model outputs; they do not test the model. So:
- Two-lane CI: Lane 1 (every PR): replayed cassettes + deterministic graders + retrieval-only tests against a pinned test database (pgvector/Neo4j containers with fixed fixtures) = fully deterministic, must be 100%. Lane 2 (nightly and pre-release): live model, k=3 trials per item (pass^3), same graders; the release gate requires all items pass all 3 trials. Per-item flake rate is reported.
- pass^k math [1][19]: with per-trial success p, pass^k = p^k. At p=0.95, pass^3 = 0.857; at p=0.99, pass^3 = 0.970. tau-bench showed GPT-4o falling from under 50% pass^1 to under 25% pass^8 on retail tasks [19]. A 100% pass^3 gate over 100 items therefore demands per-item reliability around 99.7%, which is why it applies to the invariant subset and graduated items, not to every capability item.
- Set generation parameters explicitly (temperature 0 or low, fixed seed where the provider supports it, pinned model snapshot id), record them in trace metadata, and treat a model snapshot change as a re-baseline event.
- Flaky item policy: an item that fails 1 of 3 live trials is not noise to ignore; it is either a bad item (fix the gold/grader) or a real reliability bug (fix the system). Quarantine only with an owner and a deadline.
- Stochastic user simulators confound agent variance with simulator variance [19 caveat]; keep multi-turn items scripted (fixed user turns) in the gate.

### 3.3 Statistical honesty

Report counts with intervals, not just "100%". For paired comparisons of two versions on retrieval, use ranx `compare` (paired t-test, significance flags) [5]. For judge-scored metrics, report corrected rates with CIs (section 6).

---

## 4. Retrieval metrics

- Build qrels: for each query the set of relevant chunk/node ids with graded relevance (0/1/2). Sources: synthetic from chunks (extract a fact, generate a question answerable only from it, filter for realism, plus adversarial variants using similar distractor chunks) [4], plus real trace annotation. Always validate synthetic queries against real ones [4].
- Metrics: Recall@k (k = the number actually passed to the generator, e.g. 5/10/20) as the primary first-stage metric; Precision@k, MRR, nDCG@k for reranker quality [4]. MRR suits single-answer lookups (shop SKU lookup), nDCG suits graded relevance (recommendations).
- ranx (MIT, Numba-fast, checked against trec_eval): `evaluate(qrels, run, ["recall@10","ndcg@10","mrr"])`, `compare()` with paired tests, fusion helpers useful for hybrid pgvector+BM25+graph runs [5]. Alternatives: ir_measures, pytrec_eval. RAGChecker adds claim-level retriever metrics (claim recall, context precision) and showed better recall can make generators more vulnerable to noise in relevant chunks [20].
- Per-stratum and per-locale breakdowns are mandatory; EN-ES cross-lingual retrieval (ES query, EN doc) should be a named stratum. XRAG and Ranaldi et al. show language mismatch degrades performance and translation strategies (CrossRAG) can help [10][21].
- Thresholds are corpus-specific; set them from your first baseline run, then gate on "no statistically significant drop" plus absolute floors for the gold-evidence-in-top-k assertion.

---

## 5. GraphRAG-specific evaluation

- Evaluate the pipeline in stages, as GraphRAG-Bench does (graph construction, knowledge retrieval, generation) [22]: (1) graph quality: entity/relation extraction precision/recall against a small hand-labeled sample, duplicate-entity rate, orphan nodes; (2) retrieval: did traversal/Cypher surface the gold nodes/paths; (3) answer.
- Text2Cypher / graph-query tools: use execution-based evaluation (run generated and gold query, compare result sets), not text similarity; ROUGE-style scores do not guarantee correct execution, and the Neo4j analysis found gold-data and metric quality problems [23]. CypherBench reports gpt-4o at about 60% execution accuracy on full-scale KGs, with a 120 s timeout rule [24]. For production assistants prefer parameterized, templated graph queries over free-form Cypher, then test each template with fixtures.
- Ablate: for every graph-dependent item record whether vector-only retrieval also passes. "When to use graphs in RAG" finds graph retrieval excels on complex multi-hop reasoning but can underperform vanilla RAG on simple fact retrieval [22b]. Keep a vector-only baseline run in CI; if graph adds nothing on a stratum, you are paying for complexity.
- Be careful with LLM-judge win-rate evaluations (comprehensiveness/diversity) used in the original Microsoft GraphRAG paper: a 2025 critique argues unrelated test questions and judge biases inflated gains, with moderate gains under a revised framework [25]. For our factual assistants, prefer claim-level correctness over win rates.
- Graph-specific invariants worth asserting: every cited entity id exists in Neo4j; path-based answers list hops that exist; graph traversal depth/latency within budget; stale node handling.

---

## 6. Faithfulness, groundedness and citation checks

- Decompose answers into atomic claims and check each against retrieved context (RAGAS faithfulness, RAGChecker claim entailment, ALCE NLI citation recall/precision) [16][20][26]. For the shop assistant, numeric and entity claims are checkable exactly in code, which is stronger than NLI.
- Separate failure modes: unfaithful to context (generation bug), faithful but wrong context (retrieval bug), correct but uncited (format bug). Husain: retrieval and generation measured separately; low context relevance points to chunking/embedding/query preprocessing fixes [4].
- NLI/LLM faithfulness checkers have known blind spots: partial support false positives [16]; GPT-3.5 caught over 95% of consistent summaries but only 30-60% of inconsistent ones [27]. Hence validate the checker with TPR/TNR on seeded-defect examples (perturb gold answers: change a price, drop a qualifier, swap a SKU).
- Citation checks to automate: cited id in retrieved set; cited span actually entails the claim; no uncited factual claim above a length threshold; for ES answers cite locale-appropriate source.
- Abstention as a groundedness case: when evidence is insufficient, the correct output is abstain/clarify. Score with confusion matrix: false-answer rate on unanswerable items (target 0 on gate), false-abstain rate on answerable items (track; a gate of 100% abstain invites an assistant that refuses everything).

---

## 7. LLM-as-a-judge validation

### 7.1 Protocol (Husain/Shankar/Yan synthesis)

1. Domain expert labels binary pass/fail with a written critique ("critique shadowing"); avoid 1-5 scales [28][2].
2. One judge per failure mode/criterion; no "god evaluator" [7].
3. Split labeled data: train 10-20% (few-shot examples), dev 40-45% (iterate prompt), test 40-45% (touch once) [2]. Large dev-test gap means overfitting [2].
4. Measure TPR (catches real failures) and TNR (does not flag good outputs) on the test split, and Cohen's kappa for chance-corrected agreement; raw agreement misleads on imbalanced classes [2][7]. Kappa is conservative (UMBRELA kappa 0.3-0.5 while rank correlations were 0.8-0.9) so set kappa targets knowing this [7].
5. Criteria drift: graders refine their own criteria as they see outputs (Shankar et al., "Who validates the validators") so re-label periodically and version rubrics [29].
6. Re-validate on any change to judge model, prompt, or domain slice (TPR/TNR hold only for that judge+prompt) [6 secondary note].

### 7.2 Known biases (Yan survey) [7]

Position bias (about 50% GPT-3.5, 70% Claude-v1 in cited studies), verbosity bias (over 90% preference for padded answers in one study), self-enhancement (about 10 to 25 points). Mitigation: swap order, use a different model family for the judge than the generator, binary rubric with reference answer, CoT, ensembles of smaller judges (PoLL beat GPT-4 at about one seventh cost) [7].

### 7.3 Bias correction and confidence intervals

The Rogan-Gladen correction estimates true prevalence as (observed pass rate + TNR - 1) / (TPR + TNR - 1). The 2025 paper "How to Correctly Report LLM-as-a-Judge Evaluations" builds intervals that account for both test-set and calibration-set uncertainty, with small-sample adjustments and adaptive calibration allocation [6]. A 2026 paper argues Rogan-Gladen has finite-sample bias and prediction-powered inference gives tighter intervals [30]. Practical rules: when TPR+TNR is near 1 the correction explodes, so judges that close to chance are unusable; stratify labeling because TNR uncertainty dominates when most items pass; bootstrap.

### 7.4 Thresholds I recommend

Judge acceptance: TPR >= 0.90 and TNR >= 0.85 on a test split with at least 40 pass and 40 fail, lower CI bound of kappa >= 0.6. For safety-critical judges (abstention, invented-claim) use deterministic code first, and run the judge only as an additional net with TPR >= 0.95.

---

## 8. Error analysis workflow

Husain/Shankar loop [2][31]: sample at least 30 traces yourself, open coding (free-text notes on first upstream failure), axial coding into a taxonomy with counts, continue to theoretical saturation, then convert each frequent category into either a deterministic check, a judge, or a fix. Re-run after significant changes, 100+ fresh traces per cycle [2]. Build a custom annotation UI (a small FastAPI/HTML page over LangSmith runs or an annotation queue) because generic UIs slow review; LangSmith annotation queues work for this. Every production incident becomes a golden item within 48 hours (with the redacted trace) and the fix PR must reference it. Track a failure taxonomy per assistant: retrieval miss, wrong-language answer, hallucinated price, over-abstention, tool-arg error, graph traversal miss, injection compliance.

---

## 9. Synthetic data generation

- Tuple-then-query method (dimensions, 20 hand-written tuples, LLM expands tuples, second prompt writes natural queries) [2].
- Chunk-grounded QA for retrieval qrels, with realism filter (keep 4-5 of 5 on few-shot LLM rating) and adversarial distractor variants [4].
- RAGAS TestsetGenerator builds a knowledge graph of documents and uses personas and single/multi-hop synthesizers [32]; user reports describe over-simple output and noisy extraction, and API differences across versions [32 secondary]. Treat output as a draft for human review, never as the gate set unreviewed.
- Spanish: generate natively in each variant, do not machine-translate English items (translation artifacts make questions unnatural and hide locale bugs). Have a native speaker review at least the gate set.
- Always tag provenance; cap synthetic share of the gate set at about 50% until real traces accumulate; check each synthetic item is not answerable without retrieval [13].

---

## 10. Online evals and production monitoring

- LangSmith automation rules: item type + filter + sampling rate + action; actions include online LLM-judge/code evaluator, add to dataset, add to annotation queue, webhook [33]. Rules poll independently so ordering across rules is not guaranteed [33]. Sampling-rate scale (0-1 vs percent) is inconsistently documented, verify in UI.
- Recommended online evaluators (cheap deterministic first): language-match, price-grounding check (every number in answer appears in tool outputs), abstention-rate, citation-present, latency/cost, empty-retrieval rate, thumbs-down. LLM-judge faithfulness on 5-10% sampled traces.
- Feedback loop: auto-add flagged traces (low faithfulness, user thumbs-down, guardrail trigger) to an annotation queue, label weekly, promote to dataset.
- Alert on rates with minimum counts (e.g. invented-price events: any occurrence pages someone; abstain-rate shift of more than 5 points over 7 days opens a ticket).
- Drift watchers: embedding model/provider changes, corpus freshness, model snapshot changes, judge drift (re-run calibration set monthly).
- Privacy: redact PII before traces leave the service; check retention.

---

## 11. Guardrails, red teaming, security

### 11.1 Guardrails (runtime)

Categories differ: NeMo Guardrails (dialogue/flow control runtime), Guardrails AI (structured-output validators), Llama Guard 4 (safety classifier model) [34]. Reported latencies vary widely (tens of ms for small classifiers like Prompt Guard to about 460 ms p95 for Llama Guard class models); vendor/blog numbers disagree so benchmark on your traffic [34]. Clean vs adversarial performance gaps are large (one source: F1 0.96 clean vs 0.80 adversarial) [34]. For our assistants, the highest-value guardrails are not generic safety classifiers but domain output rails written as code: price/SKU/claim grounding validator (blocks response and falls back to "I do not have that information" if any number is ungrounded), language-match, scope classifier on input (cheap, embedding or small model), PII/secret scrubbing, URL allowlist. Guardrails must themselves be in the golden set (guardrail-trigger cases).

### 11.2 Standards

- OWASP Top 10 for LLM Applications 2025: LLM01 Prompt Injection, LLM02 Sensitive Information Disclosure, LLM03 Supply Chain, LLM04 Data and Model Poisoning, LLM05 Improper Output Handling, LLM06 Excessive Agency, LLM07 System Prompt Leakage, LLM08 Vector and Embedding Weaknesses, LLM09 Misinformation, LLM10 Unbounded Consumption [35].
- OWASP Top 10 for Agentic Applications 2026 (published December 2025): ASI01 Agent Goal Hijack, ASI02 Tool Misuse and Exploitation, ASI03 Identity and Privilege Abuse, ASI04 Agentic Supply Chain, ASI05 Unexpected Code Execution, ASI06 Memory and Context Poisoning, ASI07 Insecure Inter-Agent Communication, ASI08 Cascading Failures, ASI09 Human-Agent Trust Exploitation, ASI10 Rogue Agents [36] (list as reported by Giskard [C], a red-teaming vendor; official OWASP page not opened).
- Most relevant to us: LLM01 (indirect injection through retrieved docs/product descriptions/reviews), LLM07, LLM08 (vector store poisoning, cross-tenant leakage), LLM09 (misinformation = invented price/claims), LLM10 (cost abuse), ASI01/ASI06 (goal hijack, memory poisoning if conversation memory is persisted).

### 11.3 Tools

| Tool | License / owner | Strength | Notes |
|---|---|---|---|
| promptfoo | MIT core; acquired by OpenAI (announced 2026-03-09), OpenAI says OSS continues [37][C] | CI-first, YAML configs, RAG/agent red team plugins, eval + red team in one | Vendor-neutrality risk post-acquisition; pin version; reported 50+ vuln types (secondary) |
| garak (NVIDIA) | Apache-2.0 (not verified in this research) | Broad fixed probe scanner | Thin on agent/tool context [38] |
| PyRIT (Microsoft) | MIT (not verified) | Multi-turn scripted attacks, multimodal | Requires code [38] |
| Inspect (UK AISI) | MIT (reported) [39] | Eval framework with sandboxes, 200+ evals | Heavier; more suited to agent capability research than RAG CI |

Pattern: run a curated promptfoo (or in-repo pytest) attack pack on every PR touching prompts/tools (about 30-60 deterministic-graded attacks including injection payloads placed inside retrieved documents), full garak/PyRIT sweep weekly or pre-release, and promote every successful attack into the adversarial golden subset.

---

## 12. Prompt versioning, cost and latency budgets

- Prompts: LangSmith commits are immutable; movable commit tags and reserved staging/production environment tags support promotion and rollback [40]. Alternatively keep prompts in git and push by SHA; either way the trace must record prompt commit id, model snapshot id, retriever config hash, corpus snapshot id, graph schema version. A golden-set run is only comparable when all five are recorded. Pin production to a commit (or git SHA) in the app, and change by PR, so prompt changes pass the same gate as code.
- Budgets as eval dimensions (assert in the same harness): p50/p95 end-to-end latency, time-to-first-token, tokens in/out per answer, number of retrieval/graph calls, LLM calls per turn, cost per answer, recursion/step cap (e.g., 10 steps) [23 secondary]. Fail the gate if p95 or mean cost per golden item regresses more than 20% vs baseline unless approved.
- Example starting budgets (tune after baseline): portfolio assistant p95 under 6 s, under 2 cents per answer; shop advisor p95 under 8 s, under 4 cents per answer; max 6 LLM+tool steps.

---

## 13. Eval tooling comparison

| Tool | License | Hosting / lock-in | Fit for us |
|---|---|---|---|
| LangSmith [C: LangChain] | SDK MIT; platform closed; self-host only on higher/enterprise tier (per comparison sites) | Datasets/experiments in vendor store; export via SDK; native with LangGraph | System of record; keep datasets mirrored as JSONL in repo; pytest plugin, `as_of` versions, splits, online rules, prompt commits [12][33][40][41] |
| Braintrust [C] | Closed; self-host enterprise | Vendor | Good CI Action with PR comments [42]; unnecessary second platform |
| Langfuse [C] | MIT core; acquired by ClickHouse Jan 2026, says no licence change [43] | Self-hostable, OTel-friendly | Best OSS fallback if leaving LangSmith |
| Arize Phoenix [C] | Elastic License 2.0 (source-available, not OSI) [44] | Free self-host, hosted-service restriction | OTel-native, evals; license caveat |
| DeepEval [C: Confident AI] | Apache-2.0 [45] | Local lib; paid hosted layer | pytest-style metrics (G-Eval, faithfulness); good for unit-style RAG tests |
| RAGAS [C-light: Exploding Gradients] | Apache-2.0 [26] | Library | Metrics and synthetic generation; metric implementations are LLM-judged, validate before trusting |
| promptfoo [C: OpenAI-owned] | MIT core [37] | Local CLI, YAML | CI red teaming and prompt matrices |
| Inspect | MIT (reported) [39] | Library | Agent evals with sandboxes; optional |
| ranx | MIT [5] | Library | Retrieval metrics, significance tests; adopt |

Caveat: most comparison pages (Arize, FutureAGI, Braintrust, PostHog, Langwatch) are vendor-authored; I used them only for licensing/hosting facts and cross-checked those where possible.

Lock-in policy: gold data and graders live in the repo; LangSmith is a runner/viewer. Avoid LangSmith-only evaluator definitions for gate checks (UI-defined LLM judges are fine for online monitoring).

---

## 14. CI integration patterns

```
PR (always, under 5 min, no network):
  ruff/pyright -> unit tests -> retrieval tests vs ephemeral pgvector+Neo4j fixtures
  -> golden-regression via cassettes + deterministic graders (must be 100%)
  -> ranx recall@k/nDCG vs committed baseline (fail on significant drop or floor breach)
  -> guardrail/invariant attack pack (cassettes)
Nightly / pre-release (live, budget-capped):
  golden-regression x3 trials (pass^3 = 100% on gate subset)
  capability suite (trend only), judge-scored items with corrected rates + CI
  promptfoo/garak sweep; cost and latency budget asserts
  upload results to LangSmith experiment (LANGSMITH_TEST_SUITE, experiment name = git sha)
Post-deploy:
  online evaluators on sampled traces; incident -> dataset item within 48 h
```

LangSmith's pytest plugin (langsmith>=0.3.4, `langsmith[pytest]`) maps each test file to a dataset and each run to an experiment, tracks assertions in LangSmith while still failing locally in CI, and `LANGSMITH_TEST_TRACKING=false` runs offline [41]. Fork PRs lack secrets: run cassette lane only. Store a baseline JSON of per-item results in the repo; the gate fails on any item regression, not on an average.

---

## 15. Example golden-set schema (JSONL, one item per line)

```json
{
  "id": "shop-es-0042",
  "schema_version": 3,
  "assistant": "shop_advisor",
  "locale": "es-AR",
  "strata": ["answerable", "price_lookup", "single_hop", "es"],
  "provenance": {"source": "prod_trace", "trace_id": "redacted-hash", "author": "gm", "reviewed_by": "gm", "created": "2026-11-09", "last_verified": "2026-11-09"},
  "corpus_snapshot": "catalog-2026-11-08@sha256:...",
  "graph_snapshot": "neo4j-export-2026-11-08@sha256:...",
  "turns": [{"role": "user", "content": "Cuanto sale la cafetera Oster de 12 tazas?"}],
  "expected_behavior": "answer",           // answer | abstain | clarify | refuse
  "required_facts": [
    {"id": "f1", "type": "price", "sku": "OST-12C", "value": "49990", "currency": "ARS", "match": "numeric_normalized"}
  ],
  "forbidden": [
    {"type": "any_price_not_in_tool_output"},
    {"type": "discount_claim"},
    {"type": "regex", "pattern": "(?i)siempre el mas barato"}
  ],
  "gold_evidence": [{"id": "sku:OST-12C", "grade": 2}],
  "expected_tools": [{"name": "get_product", "args_subset": {"sku": "OST-12C"}, "required": false}],
  "deterministic_checks": ["lang_matches_user", "citations_in_retrieved", "price_grounded", "no_url_off_allowlist"],
  "judge": {"rubric_id": "helpfulness_v2", "required": false, "judge_version": "j-2026-11-01"},
  "budget": {"max_steps": 6, "max_cost_usd": 0.04, "p95_latency_ms": 8000},
  "trials": 3,
  "tier": "regression",                    // regression | capability | adversarial
  "status": "active",                      // active | quarantined | retired
  "retired_reason": null,
  "notes": ""
}
```

For abstain items: `expected_behavior: "abstain"`, `forbidden` includes `any_factual_claim_beyond_scope`, and `required_facts` is empty. For graph items add `gold_paths: [["entity:A","REL","entity:B"]]`. For injection items add `attack: {"vector": "retrieved_doc", "payload_id": "inj-017", "canary": "ZX9-CANARY"}` and the check `canary_absent`.

---

## 16. Recommendations for our 2 assistants

Shared:

1. Three tiers (regression, capability, adversarial) as above; the owner's "N questions at 100%" is the regression tier only. Launch N = 40 per assistant (about 80 including adversarial invariants) within week 1, grow to 100 per assistant within 8 weeks, 150 for a tight bound.
2. Gate definition: all regression items pass all 3 live trials AND cassette lane passes AND deterministic invariants have zero violations AND retrieval floors met AND no p95 latency/cost regression over 20%. Report counts per stratum; no aggregate-only reporting. A 100/100 result is reported as "failure rate under about 3% (95% upper bound)".
3. Retrieval floors (set from baseline, starting guesses): gold-evidence recall@10 >= 0.95 on answerable strata, >= 0.90 on multi-hop; MRR >= 0.80 on SKU/entity lookup; no significant drop (paired t-test p<0.05 in ranx) vs previous release.
4. Judge acceptance: TPR >= 0.90, TNR >= 0.85, kappa lower CI bound >= 0.6 on a 40+40 test split; re-validate on judge/prompt/model change; report corrected pass rates with CI. Judges never decide the gate on safety invariants.
5. Contamination controls: sealed 30% holdout; no-retrieval ablation on every item; rotate 10-20% fresh items each 4 weeks; version dataset with LangSmith tags (`gate-vN`) and repo tags.
6. Error analysis cadence: 100 traces every 2-4 weeks; every incident to a dataset item in 48 h.
7. Prompt/model/corpus/retriever versions recorded in every trace; pin model snapshot; model change = rebaseline and full gate.
8. Security: PR-time injection pack of 30-60 attacks (including payloads inside retrieved docs); weekly garak/promptfoo sweep; map findings to OWASP LLM01/07/08/09/10 and ASI01/06.

Assistant A (portfolio, EN/ES):

- Strata emphasis: bilingual parity (each EN item has an ES twin written natively, expected facts identical), answer-language match 100%, citation to portfolio source, "about the owner" claims limited to corpus (no invented employers, dates, credentials), refusal of out-of-scope (legal/medical/personal data, unrelated chat), prompt-leak and role-play jailbreaks in ES.
- Gate: 100% on language match, no-invention, abstention; recall@10 >= 0.95; EN vs ES pass-rate difference reported, investigate if over 5 points (MEMERAG suggests Spanish faithfulness is weaker [9]).

Assistant B (shop advisor, ES):

- Zero tolerance invariants (code-checked, 0 violations in gate and production alerts): no price/currency amount, stock, discount, shipping time, warranty or compatibility claim that is not in the current tool output for that SKU; no SKU outside catalog; no medical/safety/performance superlatives unless in data; abstain/clarify when price tool errors or returns empty.
- Strata: price/stock lookup, comparison, recommendation under constraints (budget in local currency formats), false-premise price claims ("last week it cost X"), competitor price requests, out-of-scope (non-shop, advice needing professionals), regional Spanish variants and currency formats, injection through product descriptions/reviews, stale-catalog.
- Online: price-grounding evaluator at 100% sampling (deterministic and cheap); any violation pages the owner and auto-opens a dataset item.
- Gate: 100% pass^3 on invariants; false-answer rate on unanswerable = 0 of at least 25 items; false-abstain rate on answerable <= 5% (tracked, not gating at 0); graph-vs-vector ablation reported.

Tooling decisions: keep LangSmith + pytest plugin as runner/viewer; add ranx, vcrpy/pytest-recording, in-repo grader library, promptfoo for attack packs (pin version; watch OpenAI-ownership implications). Do not add Braintrust/Langfuse/Phoenix unless leaving LangSmith; Langfuse (MIT) is the exit option. RAGAS/DeepEval metrics optional for diagnostics, not gating.

---

## 17. Contested / uncertain

- 100% target vs "too easy": Anthropic says regression suites near 100% [1]; Husain says 100% suggests a weak eval and suggests aiming nearer 70% for informative evals [2]. Reconciled here by splitting suites, but this is my synthesis, not either author's claim.
- Determinism cause: the Thinking Machines batch-invariance claim and the cost of fixing it (reported 34-60% throughput loss) were seen only via secondary coverage [8]; whether hosted APIs expose deterministic modes varies by provider.
- Judge correction method: Rogan-Gladen [6] vs prediction-powered inference [30]; small-N behavior is debated; my thresholds (TPR 0.90, TNR 0.85, kappa 0.6) are engineering judgment, not from a standard. Husain gives no universal threshold [2].
- Sample sizes: Husain/Yan numbers (100 traces, 30-50 per class, 200+ labeled) come partly from secondary summaries [7]; Husain's FAQ page was truncated before its RAG/CI sections in my fetch.
- GraphRAG value: results conflict (Microsoft's win rates vs critique showing moderate gains [25]; graphs help multi-hop but hurt simple fact lookups [22b]); two different papers are both named GraphRAG-Bench [22][22b], and a summary was inconsistent on dataset size.
- Licenses: garak and PyRIT licenses not verified in this run; Inspect reported MIT by PyPI/CASRAI-class sources but one page said Apache-2.0; Phoenix ELv2 confirmed by multiple sources but its JS evals package may differ; promptfoo post-acquisition license commitments are from the company announcement summary (OpenAI page returned 403 to my fetch).
- Guardrail benchmarks: all latency/F1 numbers are from blog comparisons, several vendor-authored; an October 2026 claim that LLM Guard was archived and Guardrails AI acquired is unverified.
- LangSmith docs inconsistencies: online-evaluator sampling rate documented as both 0-1 and 0-100; prompt tag semantics differ between official docs and a third-party guide; GitHub Actions integration status for the pytest plugin unconfirmed [41].
- OWASP agentic list wording came via Giskard and other secondary summaries; verify against the official OWASP GenAI Security Project document.
- Spanish-specific retrieval benchmarks (MIRACL etc.) were not found in this pass; cross-lingual evidence is from XRAG/MEMERAG/Ranaldi only.
- Several claims (Eugene Yan numbers, Hamel Honeycomb 90% agreement) are secondary; check originals before citing externally.

---

## Sources

[1] Anthropic, "Demystifying evals for AI agents" - https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents [P, vendor blog; Anthropic has commercial interest as model vendor]
[2] Hamel Husain, Evals FAQ - https://hamel.dev/blog/posts/evals-faq/ [B; author sells evals training/consulting, C]
[3] Hamel Husain/Shreya Shankar, "Evals for AI Engineers" ch. 7 (RAG) - https://www.oreilly.com/library/view/evals-for-ai/9798341660717/ch07.html [B, book, C]
[4] hamelsmu/evals-skills evaluate-rag skill (mirror) - https://skills.sh/hamelsmu/evals-skills/evaluate-rag [B; mirrors differ]
[5] ranx (Bassani) PyPI/README - https://pypi.org/project/ranx/ [P, MIT]
[6] "How to Correctly Report LLM-as-a-Judge Evaluations" - https://arxiv.org/html/2511.21140v3 [P]
[7] Eugene Yan, "Evaluating the Effectiveness of LLM-Evaluators" - https://eugeneyan.com/writing/llm-evaluators/ ; "Product Evals in Three Simple Steps" - https://eugeneyan.com/writing/product-evals/ [B]
[8] Thinking Machines, "Defeating Nondeterminism in LLM Inference" (secondary coverage) - https://simonwillison.net/2025/Sep/11/defeating-nondeterminism [B; original post not fetched; Thinking Machines is a model/tooling vendor, C]
[9] MEMERAG multilingual RAG meta-evaluation (via XRAG/search summary) - see https://aclanthology.org/2025.findings-emnlp.849 [P, summary only]
[10] XRAG: Cross-lingual RAG - https://arxiv.org/abs/2505.10089 [P]
[11] AbstentionBench - https://arxiv.org/abs/2506.09038 [P]
[12] LangSmith, Manage datasets / version datasets - https://docs.langchain.com/langsmith/manage-datasets ; https://docs.smith.langchain.com/evaluation/how_to_guides/dataset_version [P, C]
[13] "Generating Leakage-Free Benchmarks for Robust RAG Evaluation" - https://arxiv.org/html/2605.08838 [P]
[14] "Insider Knowledge: How Much Can RAG Systems Gain from Evaluation Secrets" (ECIR 2026) - https://arxiv.org/abs/2601.13227 [P]
[15] "A Held-Out Set Stops Being Held Out..." - https://tianpan.co/blog/2026-05-17-test-set-leaks-into-fine-tuning [B]
[16] ALCE, "Enabling LLMs to Generate Text with Citations" - https://arxiv.org/pdf/2305.14627 [P]
[17] LangChain docs, integration testing - https://docs.langchain.com/oss/langchain/test/integration-testing [P, C]
[18] VCR-style record/replay for LLM tests (various) - https://dev.to/mukundakatta/vcr-style-recordreplay-for-llm-tests-make-your-agent-tests-deterministic-and-free-3o6d ; https://tianpan.co/blog/2026-04-10-integration-testing-ai-agents-ci [B]
[19] tau-bench (pass^k) - https://arxiv.org/pdf/2406.12045 ; Sierra blog https://sierra.ai/blog/benchmarking-ai-agents [P; Sierra C]
[20] RAGChecker - https://arxiv.org/pdf/2408.08067 [P]
[21] Ranaldi et al., multilingual RAG / CrossRAG - https://arxiv.org/abs/2504.03616 [P]
[22] GraphRAG-Bench (domain reasoning) - https://arxiv.org/abs/2506.02404 [P]
[22b] "When to use Graphs in RAG" (GraphRAG-Bench #2) - https://arxiv.org/abs/2506.05690 [P]
[23] Neo4j Text2Cypher analyses - https://neo4j.com/blog/developer/text2cypher-model-struggles-dataset-improvements/ ; "Evaluating graph retrieval in MCP agentic systems" https://towardsdatascience.com/evaluating-graph-retrieval-in-mcp-agentic-systems/ [B; Neo4j C]
[24] CypherBench - https://arxiv.org/pdf/2412.18702 [P]
[25] RAG vs GraphRAG systematic evaluation - https://arxiv.org/pdf/2502.11371 ; Microsoft GraphRAG - https://arxiv.org/pdf/2404.16130 ; BenchmarkQED https://www.microsoft.com/en-us/research/?p=1140429 [P; Microsoft C]
[26] RAGAS repo/docs - https://docs.ragas.io/en/stable/ [P; Apache-2.0 per secondary sources]
[27] (within [7]) Yan survey figures on factual-consistency recall
[28] Hamel Husain, "Creating a LLM-as-a-Judge That Drives Business Results" - https://hamel.dev/blog/posts/llm-judge/ [B, C]
[29] Shankar et al., "Who Validates the Validators?" - https://arxiv.org/abs/2404.12272 [P]
[30] LLM-judge measurement-error paper (Rogan-Gladen vs PPI) - https://www.arxiv.org/pdf/2601.05420 [P]
[31] Shankar/Husain error-analysis material (evals-skills error-analysis) - https://hamel.dev/blog/posts/evals-faq/ [B]
[32] RAGAS synthetic testset docs - https://docs.ragas.io/en/stable/howtos/applications/singlehop_testset_gen/ ; issue https://github.com/explodinggradients/ragas/issues/2233 [P/B]
[33] LangSmith online evaluations and automation rules - https://docs.langchain.com/langsmith/online-evaluations-llm-as-judge ; https://docs.langchain.com/langsmith/rules [P, C]
[34] Guardrail comparisons - https://blog.premai.io/production-llm-guardrails-nemo-guardrails-ai-llama-guard-compared ; https://www.morphllm.com/llm-guardrails [B, vendor-authored, C]
[35] OWASP Top 10 for LLM Applications 2025 - https://genai.owasp.org/llm-top-10/ [P]
[36] OWASP Top 10 for Agentic Applications 2026 (via Giskard) - https://www.giskard.ai/knowledge/owasp-top-10-for-agentic-application-2026 ; Cycode https://cycode.com/blog/owasp-top-10-agentic-applications/ [B, both C]
[37] OpenAI to acquire Promptfoo - https://openai.com/index/openai-to-acquire-promptfoo/ (fetch blocked; facts via search summary and SecurityWeek/Builtin coverage) [C]
[38] Red teaming tool comparisons - https://appsecsanta.com/garak-vs-promptfoo ; https://qawerk.com/blog/llm-red-teaming-tools/ ; https://www.braintrust.dev/articles/best-llm-red-teaming-tools-2026 [B, several C]
[39] Inspect AI (UK AISI) - https://pypi.org/project/inspect-ai/ ; https://casrai.org/guides/inspect-ai-evaluation-framework-uk-aisi [P/B]
[40] LangSmith prompt management - https://docs.langchain.com/langsmith/manage-prompts ; https://changelog.langchain.com/announcements/prompt-tags-in-langsmith-for-version-control [P, C]
[41] LangSmith pytest integration - https://docs.langchain.com/langsmith/pytest ; https://blog.langchain.com/pytest-and-vitest-for-langsmith-evals [P, C]
[42] Braintrust, run evals in CI - https://www.braintrust.dev/docs/evaluate/run-in-ci [P, C]
[43] ClickHouse acquires Langfuse - https://clickhouse.com/blog/clickhouse-acquires-langfuse-open-source-llm-observability [P, C]
[44] Arize Phoenix license - https://arize.com/docs/phoenix/self-hosting/license ; Arize comparison https://arize.com/llm-evaluation-platforms-top-frameworks [C]
[45] DeepEval - https://github.com/confident-ai/deepeval [P, C]
[46] Eval tooling comparisons - https://dev.to/gabrielanhaia/picking-llm-eval-tooling-in-2026-4-questions-before-you-commit-4c5l ; https://posthog.com/compare/best-braintrust-alternatives ; https://futureagi.com/blog/best-llm-evaluation-tools-2026/ [B, C]
[47] LangChain, "How to calibrate LLM-as-judge with human corrections" - https://www.langchain.com/resources/llm-as-a-judge [C]
