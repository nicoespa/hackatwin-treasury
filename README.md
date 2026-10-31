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

## Agent: policy decides, LLM explains, human approves

`treasury agent` turns a day's funding decisions into proposals in an append-only approval queue
(`data/queue.jsonl`). Nothing executes a payment.

1. The deterministic policy (`policy.recommend_deposit` on `SegmentLGBM` paths) computes each
   partner's deposit first. The LLM never changes the amount: `propose_transfer` refuses an
   amount more than one lot away from the policy's and always queues the policy amount.
2. The LLM (optional) calls read-only tools (forecast, balance, decision, components) and writes
   a rationale plus an optional `exception` (e.g. `p_unresolvable > 0.05`). Every number in the
   rationale must appear in the tool outputs (3 significant digits); otherwise a templated
   rationale replaces it, tagged `[templated]`.
3. A human approves by tier (`config/policy.yaml` → `tiers`): T1 is queued `auto_approved`, T2
   needs one approver, T3 two distinct approvers, and anything above `T3_dual_max` is blocked.

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
day queues nothing new: one proposal per partner and forecast run. Note that the simulated amounts
are ARS, so with the tiers as configured (50k / 250k / 1M) every deposit of the base data is
blocked and logged rather than queued.

## Troubleshooting

- `ModuleNotFoundError: treasury` after `uv sync`/`uv add` on macOS: the editable-install `.pth` got the hidden flag, which Python skips; run `chflags nohidden .venv/lib/python3.12/site-packages/*.pth`.
