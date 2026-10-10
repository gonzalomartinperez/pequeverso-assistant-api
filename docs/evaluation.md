# Evaluation

Four deterministic suites run in CI; a live procedure is prepared and has **not** been run. No
paid calls have been made.

| Suite | Command | What it proves | Latest result (fixture) |
|---|---|---|---|
| Retrieval | `uv run python scripts/evaluate_retrieval.py` | Lexical ranking finds the right passage (20 cases, `evals/retrieval.json`) | recall@3 = 0.95, MRR = 0.908 (miss: "correo postal" vs "producto físico") |
| Conversations: safety | `uv run python scripts/evaluate_conversations.py` | 16 scenarios through the full HTTP/SSE path. Per turn: stream grammar, catalog-valid refs, https allowlisted URLs, no price when unverified, final text passes every answer rule, no markup | 16/16 safe |
| Guards | same command (`evals/guards.json`) | 10 scripted *misbehaving* model outputs (invented product/resource/link/source, discount code, wrong price, unlisted URL, offer leak, card request, fake scarcity, unsafe follow-up, markup) are dropped or replaced server-side | 10/10 |
| Corpus | `uv run python scripts/evaluate_corpus.py` | 288 hand-written cases in 18 intent families (`evals/corpus/`), retrieval per family/split/language, and every case through the full HTTP/SSE path | Gates: 0/288 pipeline failures; reply language 285/285 as expected (`lang-016` fixed with Portuguese markers). Retrieval recall@3 = 0.70 overall (dev 0.67, holdout 0.77), 0.17 on English questions. Report: `evals/reports/corpus-fixture.json` |
| Conversations: quality | same command with `--live` | Budget recommendation, low budget honesty, resource comparison, clarification, no-match (fluent reader, app), stale price, follow-up reference, invented discount, injection, unknown shipping and license policy, refused order action, offer probe, child-data minimization, English visitor | **Not run** (needs authorization). The fixture scores 9/16 on quality checks, which says nothing about a real model |

`tests/test_evaluations.py` gates CI on retrieval ≥ 0.9 recall@3, zero safety failures, zero
guard failures, zero corpus gate failures, the exact set of known reply-language misses and
the corpus retrieval floors. `docs/verification/fixture-eval.json` holds the latest full fixture report.

## Fixture vs real model

The fixture provider receives the same `store_data` and `visitor_turn` payloads as the model. It
answers with the best lexical match, streamed as schema-valid JSON. It exercises retrieval,
streaming, validation and persistence. It does not demonstrate understanding, recommendations
or tone. The system prompt and quality checks are ready for `gpt-6-luna` but unvalidated.

## Bounded live evaluation (prepared, not executed)

Preconditions (owner):
1. Create a separate OpenAI project for Pequeverso with a hard monthly limit.
2. Put the separate project key in a private mode-600 environment file; never pass it in arguments or logs.
3. Authorize the spend explicitly.

```bash
# Explicit current owner authorization is required. Private state must be outside this repo.
uv run python scripts/run_bounded_real_eval.py --live --phase conversations \
  --key-file /private/pequeverso-eval.env.local --state-dir /private/pequeverso-eval
# Review the conversation report before proceeding; both phases reuse the same ledger.
uv run python scripts/run_bounded_real_eval.py --live --phase dev \
  --key-file /private/pequeverso-eval.env.local --state-dir /private/pequeverso-eval
uv run python scripts/run_bounded_real_eval.py --live --phase holdout \
  --key-file /private/pequeverso-eval.env.local --state-dir /private/pequeverso-eval
```

- The private file has `OPENAI_API_KEY`, `OPENAI_MODEL=gpt-6-luna` and
  `OPENAI_REASONING_EFFORT=medium`. It is read within Python, without shell evaluation or
  environment dumps. Default mode forces fixture/paid=false/key=null even when ambient
  provider variables request OpenAI, and never reads the private key file.
- The independent evaluation envelope persists across phases and database resets. It caps
  this evaluation at **USD 1.00 and 400 dispatched attempts**, sequentially, with SDK and
  adapter retries disabled. This is separate from the project's USD 10 monthly target;
  neither proves prior account spend or an administrative billing setting.
- Before each attempt, reserve USD 0.011: 24k input at the highest input rate (0.125/M), plus
  4000 output (0.50/M), multiplied by a conservative 2x Fast and 1.1x regional premium.
  The actual request uses Standard (`service_tier=default`), `store=false`, no tools and
  medium effort. UTF-8 JSON bytes (including schema, with protocol margin) and actual wire
  bytes must fit 24k; reasoning counts toward the output cap.
- Known usage settles at conservative rates (0.275/M input, 1.10/M output), without assuming
  cache discounts. Missing usage, cancellation and failures retain the reservation. Invalid
  or duplicate usage halts; duplicates cannot reduce spend. Authentication, permissions,
  missing model, invalid schema, a gate failure or exhausted budget stops the phase. Preserve
  partial reports and missing ids; do not retry automatically or claim complete coverage.
- Older native CLI helpers now require `--budget-state /private/common.sqlite3` with `--live`.
  `--max-usd` is a shared aggregate cap (positive, at most USD 1), immutable on ledger reopen.
  They previously reset the ledger per conversation or clock offset; that did **not** enforce
  an aggregate cap. Do not run independent native ledgers for one shared authorization.
- The application reservation remains at most USD 0.005 per turn with its configured pricing;
  this evaluation's stricter independent envelope does not change application limits,
  contracts, deployment settings or storefront activation.
- Review each scenario's `quality` list and the answers by hand. Adjust `app/ai/prompt.py` (bump
  `PROMPT_VERSION`), then rerun. Commit the report with the model name and date.
- Before launch, also run 3–5 manual chats through the native storefront assistant against an isolated staging deployment.

## Evaluation corpus (`evals/corpus/`)

One file per intent family: product contents, age fit, comparison of resources, printing and
format, usage and how to start, price and currency, purchase process, delivery and access,
refunds/guarantee/withdrawal, support, multi-turn follow-ups, ambiguous questions, out of scope,
prompt injection (visitor text and quoted catalog-like text), commercial-rule probes (discounts,
urgency, testimonials, post-purchase offer, order actions, payment data, contact data, child data),
stale prices, language (Spanish variants, English, mixed, quoted English, Portuguese, French,
Italian, German) and typos/slang.

**What a case is.** `id`, `family`, `group` (paraphrases of one question), `split`, `turns`
(visitor messages; the last one is evaluated) and `expect`: `retrieval` (catalog passages, any of
which should rank in the top 3; validated against `catalog/catalog.v1.json`), `retrieval_query`
(`all` joins the turns for follow-ups), `language` (`es`, `en` or `unsupported`), `outcome`
(`answer`, `clarify`, `no_info`, `decline`, `refuse_payment_data`), `forbid` (behavior tags),
`forbid_terms`, `notices`/`user_notices` (code-enforced), plus optional `page`, `locale` and
`clock_offset_days` (stale data).

**Rules.** Cases are written by hand with real variation (register, regional Spanish, typos,
English); none is generated from a template. Paraphrases are evaluation inputs, never knowledge:
the only facts are the catalog's. The split is deterministic and keeps paraphrase groups
together, so a holdout question never has a paraphrase in dev: groups, ordered by
`sha256(family:group)`, join dev when that brings dev closer to 70 % of the family
(`assign_splits`; `tests/test_evaluations.py` re-derives it). Tune prompts and ranking on `dev`;
read `holdout` only to confirm.

**Fixture results are pipeline checks.** The fixture provider answers by lexical match. A
fixture run proves that the code path (session, streaming, validation, persistence, language
selection, notices) behaves; it says nothing about how `gpt-6-luna` answers. The production
model setting is `gpt-6-luna` with reasoning effort `medium` and `max_output_tokens` 4000
(reasoning tokens count toward that cap and are billed as output). Neither has been evaluated
with the real model.

**Four kinds of result.**

| Kind | Checks | Meaning in fixture mode |
|---|---|---|
| Gates | Stream grammar, catalog-valid references, https allowlisted URLs, answer rules, no price when stale, `payment_data_refused`, `contact_data_redacted` | Code-enforced; must pass in every mode (CI) |
| Language | `MessageOut.language` equals the expected `es`/`en`, or the `language_unsupported` notice for other languages (mixed-language and payment-refusal cases excluded: 285 checked) | Code-enforced (`app/domain/language.py` decides the reply language), so deterministic. CI asserts the exact set of known misses |
| Retrieval | Lexical rank of the evaluated turn | Decides whether ranking needs work (ADR-0002) |
| Behavior | Outcome (clarifying question, support route), grounding (expected passage referenced), forbidden behaviors by string heuristics | **None.** The fixture answers by lexical match; its 111 flags are expected. Meaningful only in a live run, then reviewed by hand. `invented_policy` has no lexical check (manual review) |

**Historical findings (fixture, catalog `ae6d237`, API develop `07405d2`; superseded language issue explicitly retained).**

- Reply language: 284 of 285 checked cases as expected (272 Spanish, 8 English, 5 unsupported).
  The miss is `lang-016`, "Quanto custa o kit e como faço para comprar?": the detector returns
  `unknown` (the message shares "kit", "como", "para" with Spanish), so the visitor gets a Spanish
  answer instead of the unsupported-language note. This was corrected before the
  2026-10-10 baseline (`b27d35c`); the current corpus gate expects zero known misses.
  Keep this initial observation as history, not as an outstanding defect.

- The model always receives the whole catalog: its evidence payload is about 10.8K characters,
  under `MAX_EVIDENCE_CHARS` (40K). Ranking therefore affects only fixture answers and future
  truncation, not what a live model can see. This supports keeping lexical ranking without
  embeddings (ADR-0002) until the catalog outgrows the evidence limit.
- Lexical recall@3 by family: age fit 0.93, follow-ups 0.89, product contents 0.85, price 0.83,
  comparison 0.81, delivery 0.80, refunds 0.80, printing 0.77, usage 0.67, typos 0.56,
  purchase 0.43, support 0.36, language family 0.33 (English questions alone: 0.17, because the
  catalog text is Spanish). Misses concentrate on paraphrases without shared
  words ("hablar con una persona" vs "Contacto"), misspellings ("reenbolso", "yego") and English.
  CI floors (0.75) cover only the families that already meet them; the others are reported.
- If the catalog grows past the evidence limit, re-run this corpus first: English and support
  questions are where lexical truncation would drop the right document.

**Live run (not executed; needs authorization).** Same gate as the conversations suite:

Use the bounded runner's `--phase dev`, then `--phase holdout`, with the same private state
path shown above. The native helpers are for separately authorized evaluations only and must
share one `--budget-state`; never create a fresh cap per phase.

Run `dev` first, adjust the prompt, then `holdout` once. Review every behavior flag by hand; a
heuristic flag is a prompt to read the answer, not a verdict.

## Socket matrix frozen on 2026-10-10

`evals/end_to_end.json` freezes 224 queries in 208 cases: 200 independent questions in
20 intent families, plus eight three-turn conversations. Spanish and English questions are
varied by intent, not counted as direct translation pairs. The manifest is development
evidence, not a reserved independent holdout. No questions or expected answers enter the
public catalog or runtime indexes.

```sh
uv sync --frozen
uv run python scripts/evaluate_end_to_end.py \
  --source-revision <exact-application-commit> \
  --output-dir /absolute/private/path/new-initial-run
```

The runner is fixture-only and has no live-mode option. It forces no provider key, disables
paid AI and avoids `.env.local`. It starts Uvicorn on loopback and uses real HTTP/SSE, session
cookies, Origin and CSRF. Each turn records HTTP/terminal outcome, first-content and total
latency, public evidence hash/ids actually sent, lexical ranking separately, final citations,
observed-language heuristics and exact restored-history comparison. Completed-request replay
checks that no new provider call occurs. Invalid Origin/CSRF and fresh-visitor isolation are
checked explicitly. Fixture token/ledger numbers are synthetic estimates, never an invoice.

Full synthetic answers and database state are private local artifacts (files0600, output
directory0700), outside Git. Existing output directories cannot be overwritten. Keep the
initial manifest, catalog and answer hashes before fixes; use a separate post-fix directory
and a separate variants manifest (`evals/end_to_end_postfix.json`: original224 plus12 new
queries, passed with `--manifest`). Inspect evidence and response relevance beyond exit status.

Initial application `b27d35c`, manifest SHA256
`9bcffa12162143c5dcc2a9e163ddf5a64ba9752e8a954b4580d257fecdf74758`:
224 queries, 223 fixture calls, one local abstention, zero structural flags, zero history
mismatches (final-message membership/equality check) and 35 heuristic language flags.
The post-fix runner additionally requires final-message position, unique ids, complete
user/assistant ordering and unchanged history after replay. Invalid Origin/CSRF returned403. Actual provider
cost was$0. Agent inspection of all224 synthetic final answers additionally found irrelevant
answers, incomplete comparisons, failed follow-up resolution and unrelated citations; those
are not captured by the structural score. No human review or live-model quality is claimed.

Known manifest annotation issue: `languages-10` asks in English to receive Spanish, but the
original expected metadata was annotated `en` from the UI locale. Preserve the frozen
manifest; report that error and use an explicit-`es` post-fix variant. Do not retrospectively
change the baseline or present improved flags as independent quality validation.

The whole current catalog (one product, nine resources, 23 documents) fits the evidence
bound and is sent in full. Both resources in comparisons were therefore available even
when the fixture mentioned only one. Low English lexical scores do not establish omitted
model evidence. Vector and graph search are absent by design. Real-model commercial
accuracy, source entailment, tone and English fluency remain activation blockers.
