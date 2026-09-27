# Evaluation

Three deterministic suites run in CI; a fourth is a prepared live procedure that has **not**
been run. No paid calls have been made.

| Suite | Command | What it proves | Latest result (fixture) |
|---|---|---|---|
| Retrieval | `uv run python scripts/evaluate_retrieval.py` | Lexical ranking finds the right passage (20 cases, `evals/retrieval.json`) | recall@3 = 0.95, MRR = 0.908 (miss: "correo postal" vs "producto físico") |
| Conversations: safety | `uv run python scripts/evaluate_conversations.py` | 16 scenarios through the full HTTP/SSE path. Per turn: stream grammar, catalog-valid refs, https allowlisted URLs, no price when unverified, final text passes every answer rule, no markup | 16/16 safe |
| Guards | same command (`evals/guards.json`) | 10 scripted *misbehaving* model outputs (invented product/resource/link/source, discount code, wrong price, unlisted URL, offer leak, card request, fake scarcity, unsafe follow-up, markup) are dropped or replaced server-side | 10/10 |
| Conversations: quality | same command with `--live` | Budget recommendation, low budget honesty, resource comparison, clarification, no-match (fluent reader, app), stale price, follow-up reference, invented discount, injection, unknown shipping and license policy, refused order action, offer probe, child-data minimization, English visitor | **Not run** (needs authorization). The fixture scores 9/16 on quality checks, which says nothing about a real model |

`tests/test_evaluations.py` gates CI on retrieval ≥ 0.9 recall@3, zero safety failures and
zero guard failures. `docs/verification/fixture-eval.json` holds the latest full fixture report.

## Fixture vs real model

The fixture provider receives the same `store_data` and `visitor_turn` payloads as the model. It
answers with the best lexical match, streamed as schema-valid JSON. It exercises retrieval,
streaming, validation and persistence. It does not demonstrate understanding, recommendations
or tone. The system prompt and quality checks are ready for `gpt-6-luna` but unvalidated.

## Bounded live evaluation (prepared, not executed)

Preconditions (owner):
1. Create a separate OpenAI project for Pequeverso with a hard monthly limit.
2. Export a project key into the shell only.
3. Authorize the spend explicitly.

```
ALLOW_PAID_AI=true OPENAI_API_KEY=<pequeverso project key> \
  uv run python scripts/evaluate_conversations.py --live --max-usd 0.25 \
  --output docs/verification/live-eval-<date>.json
```

- The service's own ledger caps the run at `--max-usd` (monthly = daily = cap, no margin).
  Expected cost: 17 turns × ~6k input tokens (largely cached) + ≤1.2k output ≈ under USD 0.02.
- Review each scenario's `quality` list and the answers by hand. Adjust `app/ai/prompt.py` (bump
  `PROMPT_VERSION`), then rerun. Commit the report with the model name and date.
- Before launch, also run 3–5 manual chats through the web app against a staging deployment.
