# treasury

Predictive-treasury demo: forecasts daily outflows per partner and sizes the
prefunded balance a fintech keeps at each one.

## Setup

```bash
uv sync
export PYTHONPATH=src   # every shell: makes `treasury` importable for the CLI, pytest and streamlit
uv run pytest -q -W error
```

Python is pinned to 3.12 (`.python-version`); `uv sync` downloads it if needed.

On macOS `uv sync` leaves the editable-install `.pth` files in `.venv/lib/python3.12/site-packages/`
with the `hidden` flag, which Python skips, so without `PYTHONPATH=src` every `uv run treasury …`,
`uv run pytest` and `uv run streamlit run …` fails with `ModuleNotFoundError: treasury`. The
alternative is to clear the flag after each `uv sync`:
`chflags nohidden .venv/lib/python3.12/site-packages/*.pth`. The commands below assume
`export PYTHONPATH=src` in the shell.

## Layout

- `config/calendar_ar.yaml`: Argentine holidays (2025-11-01 to 2026-12-31), SAC (aguinaldo) and ANSES payment windows.
- `src/treasury/calendar.py`: business-day calendar built from that YAML.
- `scripts/scaling_experiment.py`: capital immobilized by number of users, plus sensitivity to the simulator's assumptions; writes `reports/experiments/`.
- `reports/dashboard/`: source and data of the published business dashboard.

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
equal service per rail: 19 % on wire, 39 % on stablecoin, from `reports/experiments/factorial.csv`;
the dashboard reads them off the CSV):

1. **Ablación**: forecast scores of (a) seasonal naive → (d) segment × product with common factor
   and (d-) without it, pooled or per partner, and PIT histograms per model (flat = calibrated; (d-)
   is U-shaped: without the common factor its intervals are too narrow). An expander shows
   `designed_to_lose.csv`, the case built for the bottom-up model to lose (five identical segments).
2. **Factorial**: fixed buffer vs proposed policy × wire vs stablecoin, plus the `reference_matched`
   row (the fixed buffer with the fewest days at the proposed policy's service level). The
   config-value cells (`fixed_buffer_days` = 5, α = 0.99, from `config/policy.yaml`) are not at the
   same service level (the 5-day buffer is short on 28 % of wire and 10 % of stablecoin partner-days);
   proposed vs matched is the comparison that answers the criterion.
3. **Frontera**: capital vs realized shortfall rate per rail, the proposed policy's α sweep against
   the fixed buffer's days sweep; the α slider picks the row compared in the table.
4. **Estrés**: sliders for a campaign, a cohort wave, an FX jump, a partner outage and the payday
   hypothesis. "Recalcular" simulates a new week with the same population and seed (60 days ending
   2026-10-31, < 1 s; the simulator draws them from another stretch of its random stream, so they
   are not the base history's last days), forecasts its last week with (d) and shows per partner
   the target balance and deposit against the run without scenarios, plus the forecast's
   decomposition (confirmed autodebits, residual by segment, predicted recurring payments detected in
   the training history, common-factor share). Campaign lift 1.5 on `bill_payment` raises
   `bills_aggregator`'s deposit; the other partners do not move.
5. **Aprobaciones**: the approval queue (`data/queue.jsonl`) with approve / reject, and "Proponer
   hoy" with or without the LLM (the LLM button is enabled only when `ANTHROPIC_API_KEY` is set).
   Partners start at the policy's own target of the day before (see the agent section).

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

## Agent: policy decides, LLM explains, human approves (or the agent executes within limits)

`treasury agent` has two modes. `propose` turns a day's funding decisions into proposals in an
append-only approval queue (`data/queue.jsonl`) and executes nothing. `run` is the autonomous mode:
no human in the loop, the agent executes the deposit itself (simulated, no network call) within hard
limits (see "Autonomous mode" below).

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

The demo fits the model on the data before `--as-of`, with nothing in transit. By default
(`--start-balances target`) every partner starts at the policy's own target at the last review of
the day before (18:00 on a 24/7 rail, 09:00 on wire), as a treasury already running the policy would;
`--start-balances fixed` starts at the fixed-buffer target (`fixed_buffer_days` of trailing mean
drain), which on wire leaves many paths short before the deposit lands. Each proposal records the
forecast's `seed` and `n_paths`. Re-running the same day queues nothing new: one proposal per partner
and forecast run. On the base data at 2026-10-26 (2000 paths) every partner's `p_unresolvable` is at
most 0.015; with `--rail stablecoin` the policy funds fci_custodian (≈ 86M, T2) and cash_network
(≈ 51M, T2), both on wire, their only rail; with `--rail wire` it also funds card_network (≈ 319M,
T3) and bills_aggregator (≈ 32M, T1).

### Autonomous mode (`treasury agent run`)

```bash
uv run treasury agent run --as-of 2026-10-01 --rail wire          # review at 09:00 (review_hour)
uv run treasury agent run --as-of 2026-10-01T18:00 --rail stablecoin --data data/sim/base \
    --out reports/demo/agent_run.json                             # review at that instant
```

Per partner it forecasts (same fit and opening balances as `propose`), lets the policy decide, applies
the guardrails, executes into the simulated ledger `data/transfers.jsonl` (`--ledger`), prints a
Spanish summary (forecast for tomorrow q50/q99, available balance, in transit, need, decided and
executed amounts, limit applied, rail and ETA, alerts) and writes the same fields plus the next 7 days
of forecast quantiles and the rationale to `--out` for the demo page. The LLM writes the rationale only
when `ANTHROPIC_API_KEY` is set (and not `--no-llm`); it never changes an amount.

Limits, in `config/policy.yaml` → `autonomy` (per currency, the partner's `currency` in
`partners.yaml`, ARS when absent; summed over the calendar day of the review):

| Setting | Default | Why |
|---|---|---|
| `enabled` | `true` | Kill switch: `false` holds every partner and executes nothing. |
| `limits.ARS.max_per_transfer` | 500M | Most policy deposits on `data/sim/base` are under 300M; month-start wire deposits to card_network reach ~850M and get capped. |
| `limits.ARS.max_per_partner_day` | 750M | Room for the two daily reviews of a 24/7 rail. |
| `limits.ARS.max_all_partners_day` | 1.5B | A heavy day's total is ~1.1B (2026-10-01 on wire). |
| `max_forecast_age_hours` | 24 | Hold when the data behind the forecast ends more than a day before the review. |
| `sanity_multiple` | 3 | Hold when the amount exceeds 3 × the partner's trailing 28-day max daily drain. |
| `destinations` | one per partner and rail | The only accounts the agent can pay into; it cannot choose or change the beneficiary. |

Guardrails, each with an explicit alert record (`code`, `action`, message, details) in the output and
in the ledger record of the transfer:

- kill switch on, forecast missing (it does not cover the decision window) or stale, no allow-listed
  destination on the rail, no limits for the currency: **hold**.
- amount above the sanity bound: **hold** (more likely a broken forecast than real demand).
- `p_unresolvable` above 0.05: **execute** and alert.
- amount above the remaining limit: **execute up to the limit** (rounded down to `lot_size`) and alert
  with the remainder. Sending nothing would leave the partner short and reject user payments; the
  capped amount covers what the limits allow and the alert asks a human for the rest.

The executor (`agent/executor.py`) records each transfer with an idempotency key (partner + review
time: rerunning the same review sends nothing new and reports `already_executed`), rail, amount,
currency, allow-listed destination and the times of `instructed → in_transit → credited` (`arrival_at`
from `rails.arrival_time`); `ledger_status(path, at)` gives each transfer's status at any time. It
re-checks the kill switch, the destination and the limits itself and refuses a transfer that breaks
them. Transfers still in transit at a review are the partner's pending credits for that review. The
approval queue and the dashboard's Aprobaciones tab are unchanged; the autonomous run does not use them.

The LLM path is covered by offline tests with a scripted fake client only. A run against the
real API is still owed: it needs `ANTHROPIC_API_KEY`, which was not available when this was built.

## International variant

The same pipeline for partners abroad: `pix_br` (BRL, Pix payments by Argentine users in Brazil) and
`usd_acquirer` (USD, international cards, remittances, freelance income), funded by `swift` (2
business days open in both countries) or `stablecoin`. Configs live in `config/intl/` (archetypes,
partners with `country` and `currency`, rails, policy, Brazilian and US bank calendars, `market.yaml`
with FX and tourism); the dataset's `params.json` records `"config": "intl"`, so `backtest` and the
experiments load them. The domestic config and its results are unchanged.

```bash
uv run treasury simulate --config intl --users 20000 --start 2025-11-01 --end 2026-10-31 --seed 42 --out data/sim/intl
uv run treasury intl-experiments --data data/sim/intl --out reports/experiments
```

Setup, assumptions and results (capital in USD): `reports/experiments/intl_README.md`.

## Checklist pre-demo

1. `export PYTHONPATH=src` in the shell that runs the demo (or `chflags nohidden
   .venv/lib/python3.12/site-packages/*.pth` after the last `uv sync`).
2. If `data/sim/base/` or `reports/experiments/*.csv` are missing or `config/policy.yaml` changed,
   regenerate (steps 1 and 2 of the Demo) and run `uv run streamlit cache clear`: the PIT histograms
   are cached on disk and would show the old data.
3. Run the agent once against the real API (`ANTHROPIC_API_KEY=... uv run treasury agent propose
   --as-of 2026-10-26`) and read the rationales; that run is still owed.
4. Start the dashboard and click through the six tabs (Resumen, Ablación with its expander,
   Factorial, Frontera, Estrés with one "Recalcular", Aprobaciones with one "Proponer hoy").

## Troubleshooting

- `ModuleNotFoundError: treasury` after `uv sync`/`uv add` on macOS: the editable-install `.pth` got the hidden flag, which Python skips; `export PYTHONPATH=src`, or run `chflags nohidden .venv/lib/python3.12/site-packages/*.pth`.
