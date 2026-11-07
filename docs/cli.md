# Command reference

Every command runs through uv from the repository root: `uv run treasury <command>`. Defaults point at the base dataset in `data/sim/base` and at the configuration in `config/`.

## Generate the data

The repository does not include the simulated dataset. Generate it once before any other command:

```bash
uv run treasury simulate --users 20000 --start 2025-11-01 --end 2026-10-31 --seed 42 --out data/sim/base
```

The run takes about 40 seconds and writes `users.parquet`, `events.parquet`, `macro.parquet`, and `params.json` to `data/sim/base/`. The same seed always produces the same 4,260,236 events.

## `treasury simulate`

Builds a synthetic population and one period of its payments.

| option | default | meaning |
|---|---|---|
| `--users` | `20000` | Number of users. |
| `--start`, `--end` | `2025-11-01`, `2026-10-31` | The simulated period. The calendar covers 2025-11-01 to 2026-12-31. |
| `--seed` | `42` | Random seed. |
| `--out` | `data/sim/base` | Output folder. |
| `--config` | `domestic` | `domestic` reads `config/`. `intl` reads `config/intl/`. |
| `--payday-hypothesis` | `late` | When salaried users get paid within the month. |
| `--sigma-m`, `--phi` | `0.15`, `0.7` | Volatility and autocorrelation of the shared macro factor. |

## `treasury backtest`

Replays weekly decision dates and reports capital held and shortfalls.

| option | default | meaning |
|---|---|---|
| `--data` | `data/sim/base` | Dataset folder. |
| `--model` | `segment_factor` | One of `seasonal_naive`, `aggregate_drivers`, `aggregate_drivers_obligations`, `segment_factor`, `segment_nofactor`. |
| `--rail` | `stablecoin` | Preferred rail. A partner that does not accept it uses its only rail. |
| `--policy` | `forecast` | `forecast` sizes deposits from the model. `fixed` keeps a fixed buffer. |
| `--alpha` | from `config/policy.yaml` | Coverage quantile. |
| `--n-paths` | `1000` | Monte Carlo paths. |
| `--n-origins` | `8` | Weekly decision dates. |
| `--central-reserve` | `0.0` | Capital kept centrally, added to the total. |

## `treasury experiments` and `treasury intl-experiments`

Run the full set of experiments and write CSV files plus a README to `reports/experiments/`. Each takes about a minute.

| option | default |
|---|---|
| `--data` | `data/sim/base` (`data/sim/intl` for `intl-experiments`) |
| `--out` | `reports/experiments` |
| `--n-paths` | `1000` |

`intl-experiments` needs the international dataset: `uv run treasury simulate --config intl --out data/sim/intl`.

## `treasury agent`

The autonomous agent and its supervised mode. [The autonomous agent](agent.md) explains both.

| command | what it does |
|---|---|
| `agent run` | Reviews every partner at `--as-of`, applies the limits and guardrails, executes into the ledger, prints a summary in Spanish, and writes the run as JSON to `--out`. |
| `agent propose` | Queues one proposal per partner the policy funds. Executes nothing. |
| `agent list` | Shows the latest state of every proposal. `--status` filters by state. |
| `agent approve <id> --approver <name>` | Approves a pending proposal. T3 needs two different approvers. |
| `agent reject <id> --approver <name> --reason <text>` | Rejects a pending proposal. |

Options of `agent run`:

| option | default | meaning |
|---|---|---|
| `--as-of` | `2026-10-26` | A day, reviewed at 09:00, or an instant (`YYYY-MM-DDTHH:MM`). |
| `--rail` | from the config set | Preferred rail: `wire`, `stablecoin`, or `swift` for the international set. |
| `--data` | `data/sim/base` | Dataset folder. |
| `--out` | `reports/demo/agent_run.json` | Where to write the run. |
| `--ledger` | `data/transfers.jsonl` | The transfer ledger. |
| `--n-paths` | `2000` | Monte Carlo paths. |
| `--segments` | `kmeans` | `kmeans` infers segments from transactions. `labels` uses the simulator's labels. |
| `--no-llm` | off | Use templated explanations even when `ANTHROPIC_API_KEY` is set. |

`agent propose` takes `--data`, `--as-of`, `--rail`, `--n-paths`, `--no-llm`, `--queue` (default `data/queue.jsonl`), and `--start-balances`. With `target`, the default, each partner starts at the policy's own target from the day before. With `fixed`, each partner starts at the fixed buffer.

## `treasury model-api`

Serves the model over HTTP for the console's live run. `--port` defaults to `8790`. [The web console](console.md#run-the-model-live-optional) documents the endpoints.

## `treasury-mcp`

Starts the MCP server over stdio. It takes no options. [MCP server](mcp.md) documents it.

## Earlier interfaces

These came before the web console. They still work and the tests cover them.

| command | port | what it shows |
|---|---|---|
| `uv run streamlit run src/treasury/dashboard/app.py` | 8501 | The analysis dashboard: model ablation, factorial, efficient frontier, stress scenarios, and the approval queue. |
| `uv run treasury monitor --seed` | 8600 | A dashboard of the agent's accounts, transfers, and alerts. It shares its files with the MCP server, so reviews executed through MCP appear on it. `--seed` first runs the reviews of `--days`. |
| `uv run treasury live` | 8700 | A replay of one weekend on a simulated clock, with the agent deciding at 09:00 each day. `--speed` sets simulated hours per 1.5 real seconds. |

## Scripts

`scripts/` holds one-off experiments and data builders. Each script's docstring says what it writes.

| script | writes |
|---|---|
| `build_console_data.py` | `web/console/data.json`, the console's data. |
| `exante_buffer_experiment.py` | `reports/experiments/exante_buffer.csv`, the policy against a buffer set ahead of time. |
| `segmentation_experiment.py` | `reports/experiments/segmentation*`, k-means segments against the simulator's labels. |
| `scaling_experiment.py` | `reports/experiments/scaling*` and `sensitivity.csv`, capital by number of users. |
| `plan_adjust_experiment.py` | `reports/experiments/plan_adjust.csv`, what pulling money back would be worth. |
| `rebalance_experiment.py` | `reports/experiments/rebalance*.csv`, sweeping surpluses between partners. |
| `build_weekend_timeline.py` | `reports/demo/weekend_timeline.json`, data for `treasury live`. |

## Tests

```bash
uv run pytest -q
```

The suite has 211 tests and runs in about a minute.
