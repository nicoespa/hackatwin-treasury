# treasury

Predictive-treasury demo: forecasts daily outflows per partner and sizes the
prefunded balance a fintech keeps at each one.

## Setup

```bash
uv sync
uv run pytest
```

Python is pinned to 3.12 (`.python-version`); `uv sync` downloads it if needed.

## Layout

- `config/calendar_ar.yaml`: Argentine holidays (2025-11-01 to 2026-12-31), SAC (aguinaldo) and ANSES payment windows.
- `src/treasury/calendar.py`: business-day calendar built from that YAML.

## Demo

**Success criterion:** less total capital immobilized, at the same service level, in scenarios the
model does not know in advance.

```bash
# 1. data: 20 000 users, one year, seed 42
uv run treasury simulate --users 20000 --start 2025-11-01 --end 2026-10-31 --seed 42 --out data/sim/base
# 2. experiments (≈ 1 min): ablation, factorial, frontier, designed-to-lose, unknown-scenario CSVs + README
uv run treasury experiments --data data/sim/base --out reports/experiments
# 3. dashboard (Spanish UI), http://localhost:8501, bound to 127.0.0.1 by .streamlit/config.toml
uv run streamlit run src/treasury/dashboard/app.py
# 4. agent from the command line (the dashboard's Aprobaciones tab does the same)
uv run treasury agent propose --as-of 2026-10-26 --no-llm   # templated rationales
ANTHROPIC_API_KEY=... uv run treasury agent propose --as-of 2026-10-26   # LLM writes the rationale
```

The five things the jury must see, one tab each after the **Resumen** headline (capital saved at
equal service per rail: 19 % on wire, 39 % on stablecoin, from `reports/experiments/factorial.csv`):

1. **Ablación**: forecast scores of (a) seasonal naive → (d) segment × product with common factor
   and (d-) without it, pooled or per partner, and PIT histograms per model (flat = calibrated; (d-)
   is U-shaped: without the common factor its intervals are too narrow).
2. **Factorial**: fixed buffer vs proposed policy × wire vs stablecoin, plus the `reference_matched`
   row (the fixed buffer with the fewest days at the proposed policy's service level). The
   config-value cells (3-day buffer, α = 0.99) are not at the same service level; proposed vs
   matched is the comparison that answers the criterion.
3. **Frontera**: capital vs realized shortfall rate per rail, the proposed policy's α sweep against
   the fixed buffer's days sweep; the α slider picks the row compared in the table.
4. **Estrés**: sliders for a campaign, a cohort wave, an FX jump, a partner outage and the payday
   hypothesis. "Recalcular" re-simulates the last 60 days with the saved seed (< 1 s), re-forecasts
   the last week with (d) and shows per partner the target balance and deposit against the run
   without scenarios, plus the forecast's decomposition (confirmed autodebits, residual by segment,
   predicted recurring payments, common-factor share). Campaign lift 1.5 on `bill_payment` raises
   `bills_aggregator`'s deposit; the other partners do not move.
5. **Aprobaciones**: the approval queue (`data/queue.jsonl`) with approve / reject, and "Proponer
   hoy" with or without the LLM (the LLM button is enabled only when `ANTHROPIC_API_KEY` is set).

How the stress tab works, and what it cannot show:

- The model it uses is fitted on the base population re-simulated with three past campaigns
  (`experiments.PAST_CAMPAIGNS`): on the base data every campaign lift is 1, so a model fitted
  there would ignore the campaign and FX sliders.
- It decides at the 18:00 review of the week's first day. On a 24/7 rail that review funds the
  next day; at 09:00 the day's whole forecast outflow is placed before any deposit can land, so the
  deposit would always be 0. Each partner starts at the baseline run's target, so the deposit is
  what the scenario adds.
- The model sees only drivers: campaigns and the FX jump (`campaign_lift`) and cohort waves
  (`n_active`). It does not see partner outages or the payday hypothesis, which move only the
  simulated outflow (shown next to the forecast), and it barely extrapolates a cohort wave larger
  than any in its history. The forecast week (2026-10-25 to 31) has no business days 1–4, so the
  payday hypothesis changes almost nothing there.

Known limitations:

- **Synthetic data.** The demo shows the mechanism and its sensitivity under stated assumptions,
  not real savings.
- **`phi_f ≈ 0`.** The common factor's estimated day-to-day autocorrelation is about zero, so the
  model treats macro shocks as not persisting across days.
- **Realized vs nominal service.** α is a per-decision quantile, not the service level; the policy
  is conservative and its realized service sits above α (see Frontera and
  `reports/experiments/README.md`).
- **Approvals are not authenticated.** The approver is a typed name, so two-person control on T3
  is only nominal in the demo. `.streamlit/config.toml` binds the dashboard to `127.0.0.1`; do not
  expose it beyond localhost as it is (in production the approver comes from the authenticated
  identity).
- **LLM run owed.** The agent's LLM path is tested only with a scripted fake client; a run against
  the real API is still owed.

## Agent: policy decides, LLM explains, human approves

`treasury agent` turns a day's funding decisions into proposals in an append-only approval queue
(`data/queue.jsonl`). Nothing executes a payment.

1. The deterministic policy (`policy.recommend_deposit` on `SegmentLGBM` paths) computes each
   partner's deposit first. The LLM never changes the amount: `propose_transfer` refuses an
   amount more than one lot away from the policy's and always queues the policy amount.
2. The LLM (optional) calls read-only tools (forecast, balance, decision, components) and writes
   a rationale plus an optional `exception` (e.g. `p_unresolvable > 0.05`). The rationale must
   cite the policy amount or target, and every number in it (and in the exception) must appear
   in the tool outputs (3 significant digits). Otherwise a templated rationale replaces it,
   tagged `[templated: <reason>]` (the exception is dropped), and every fallback is logged with
   the partner and the reason: offline, LLM call failed, refusal, max_tokens, round cap,
   unparseable final JSON, rationale rejected by the validator.
3. A human approves by tier (`config/policy.yaml` → `tiers`, in ARS): T1 (≤ 50M) is queued
   `auto_approved`, T2 (≤ 250M) needs one approver, T3 (≤ 2B) two distinct approvers (ids
   compared case-insensitively, each approval stamped with `at`), and anything above is blocked
   and logged, not queued.

```bash
# offline: templated rationales, no API call
uv run treasury agent propose --data data/sim/base --as-of 2026-10-26 --rail stablecoin --no-llm
# with the LLM (claude-opus-5-5); the key is read only from the environment
export ANTHROPIC_API_KEY=...
uv run treasury agent propose --data data/sim/base --as-of 2026-10-26 --rail stablecoin
uv run treasury agent list --status pending
uv run treasury agent approve <id> --approver ana
uv run treasury agent reject <id> --approver beto --reason "balance already enough"
```

The demo fits the model on the data before `--as-of` and starts every partner at its
fixed-buffer target (3 days of trailing mean drain) with nothing in transit. Re-running the same
day queues nothing new: one proposal per partner and forecast run. On the base data at
2026-10-26 with `--rail stablecoin`, the policy funds fci_custodian (≈ 320M, T3) and
cash_network (≈ 180M, T2), both on wire, their only rail; every other partner needs nothing.

The LLM path is covered by offline tests with a scripted fake client only. A run against the
real API is still owed: it needs `ANTHROPIC_API_KEY`, which was not available when this was built.

## Troubleshooting

- `ModuleNotFoundError: treasury` after `uv sync`/`uv add` on macOS: the editable-install `.pth` got the hidden flag, which Python skips; run `chflags nohidden .venv/lib/python3.12/site-packages/*.pth`.
