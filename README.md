# Prefoundly

Prefoundly forecasts how much a digital wallet must prefund at each payment partner, and sends it every morning on its own, within hard limits.

A wallet pays its users' bills, top-ups, and crypto purchases through partners that pay out of a balance the wallet funds in advance. Today a treasury team sets that balance by hand, with a buffer of several days of payments. When the buffer is short, the partner charges a penalty and payments stop. When it is long, money sits idle all year. Prefoundly sizes it from how the users actually behave.

**Live console:** [prefoundly.vercel.app](https://prefoundly.vercel.app) (Spanish interface, simulated data)

Built in 12 hours at HackaTwin, 7 November 2026.

## How it works

Every day at 09:00, for each partner:

1. Group the users by behavior with k-means on their transactions.
2. Forecast each group's payments per product and partner with a Tweedie LightGBM model.
3. Simulate 1,000 scenarios with a macro factor shared by all groups, so that a bad day hits every group at once.
4. Take the need that covers 99 of every 100 scenarios until the next transfer lands, and subtract what the partner already holds.
5. Send the difference, cut to hard limits, into a fixed account. Claude explains each decision and never changes the amount.

[How Prefoundly decides how much to send](docs/architecture.md) explains each step.

## Results

On one simulated year (20,000 users, 4.26 million payments) and against a fixed buffer chosen ahead of time, the policy holds less capital with no day short:

| rail | capital held, Prefoundly | capital held, fixed buffer | saved | days short |
|---|---|---|---|---|
| wire, business days | 3.62e9 ARS | 4.71e9 ARS | 23 % | 0 % for both |
| stablecoin, any day | 1.97e9 ARS | 3.35e9 ARS | 41 % | 0 % for both |

The data is synthetic, so these numbers show the mechanism, not the savings at a real wallet. Method and full tables: [`reports/experiments/`](reports/experiments/README.md).

## Quick start

You need [uv](https://docs.astral.sh/uv/) and Git. uv installs Python 3.12 if it is missing.

```bash
git clone https://github.com/nicoespa/hackatwin-treasury
cd hackatwin-treasury
uv sync
uv run treasury simulate --users 20000 --start 2025-11-01 --end 2026-10-31 --seed 42 --out data/sim/base
```

The last command generates the simulated dataset in about 40 seconds. Then run the agent's review for one day:

```bash
uv run treasury agent run --as-of 2026-10-23 --rail wire --no-llm
```

It prints, per partner, the forecast, the balance, the need, and the transfer it recorded in `data/transfers.jsonl`. It also writes the run to `reports/demo/agent_run.json`.

To control the agent from Claude, connect the MCP server:

```bash
claude mcp add prefoundly -- uv run --directory "$PWD" treasury-mcp
```

On macOS, if a command fails with `ModuleNotFoundError: No module named 'treasury'`, run `chflags nohidden .venv/lib/python3.12/site-packages/*.pth` once, or prefix commands with `PYTHONPATH=src`.

## Documentation

| page | read it to |
|---|---|
| [How Prefoundly decides how much to send](docs/architecture.md) | Understand the data, the model, the scenarios, and the deposit rule. |
| [The autonomous agent](docs/agent.md) | See the limits, the guardrails, the executor, and what changes with real money. |
| [MCP server](docs/mcp.md) | Connect Claude or another agent and use its six tools. |
| [The web console](docs/console.md) | Run, rebuild, or deploy the console, its chat, and the live model. |
| [Command reference](docs/cli.md) | Look up every command, option, and script. |
| [Experiment results](reports/experiments/README.md) | Read the backtests behind the numbers above. |

## Repository layout

```
config/             Partners, rails, policy and autonomy limits, calendar, user archetypes
  intl/             The same for the international variant
src/treasury/
  simulate/         Synthetic users and their payments
  models/           Forecasters: seasonal naive, aggregate LightGBM, segment LightGBM
  agent/            Autonomous agent: guardrails, executor, approval queue, Claude tools
  dashboard/        Streamlit analysis dashboard
  segmentation.py   k-means segments inferred from transactions
  montecarlo.py     Scenario paths with the shared macro factor
  policy.py         Deposit sizing
  mcp_server.py     MCP server
  model_api.py      HTTP service for the live model
  cli.py            The treasury command
web/console/        The web console (static site and the /api/ask function)
scripts/            Experiments and data builders
reports/            Experiment results and demo data
tests/              Test suite (uv run pytest -q)
docs/               Guides, plus research/ (the original research) and development/ (build logs)
data/               Generated datasets, not committed
```

## Status and limits

- Every transfer is simulated. The executor writes to a local ledger and calls no bank. [Moving real money](docs/agent.md#moving-real-money) describes what the connection would add.
- The users and payments are simulated. The Argentine holidays, aguinaldo, and ANSES windows are real.
- Claude's explanations of the agent's decisions have been tested only against a scripted client. The console chat runs against the real API.
