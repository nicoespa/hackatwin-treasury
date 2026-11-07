# MCP server

`treasury-mcp` exposes the autonomous agent over the Model Context Protocol, so Claude or any other MCP client can read its state, run a review, and pause or resume it. The server runs on your machine over stdio and works on the simulated dataset. Executions write only to a local ledger file. No money moves.

## Connect it to your agent

You need [uv](https://docs.astral.sh/uv/) and Git. uv installs Python 3.12 if it is missing.

1. Clone the repository and install the dependencies:

	```bash
	git clone https://github.com/nicoespa/hackatwin-treasury
	cd hackatwin-treasury
	uv sync
	```

2. Generate the simulated dataset. The repository does not include it. This step takes about 40 seconds and writes `data/sim/base/`:

	```bash
	uv run treasury simulate --users 20000 --start 2025-11-01 --end 2026-10-31 --seed 42 --out data/sim/base
	```

	The command prints `4,260,236 events for 20,000 users` when it finishes.

3. Register the server in your client.

	For Claude Code, run this from the repository root:

	```bash
	claude mcp add prefoundly -- uv run --directory "$PWD" treasury-mcp
	```

	For Claude Desktop, add this entry to `claude_desktop_config.json` and replace the path with the absolute path of your clone:

	```json
	{
		"mcpServers": {
			"prefoundly": {
				"command": "uv",
				"args": ["run", "--directory", "/absolute/path/to/hackatwin-treasury", "treasury-mcp"]
			}
		}
	}
	```

4. Restart the client and ask it something, for example "¿Cuánto mandaría hoy el agente a cada partner?". The client calls `run_review` and answers from the result.

## Tools

Dates are `YYYY-MM-DD` inside the simulated year (2025-11-01 to 2026-10-31). Amounts are in each partner's currency (ARS for the base dataset). `rail` is `wire` or `stablecoin`.

| tool | parameters | returns | writes |
|---|---|---|---|
| `get_status` | `at` (optional, `YYYY-MM-DD[THH:MM]`) | Whether the agent is executing or paused, its limits per currency, and every ledger transfer with its status at `at`. | Nothing. |
| `get_limits` | none | Hard limits per currency, the allow-listed destination per partner and rail, `max_forecast_age_hours`, and `sanity_multiple`. | Nothing. |
| `forecast` | `partner`, `as_of`, `rail` (default `wire`) | The next 7 days of outflow quantiles (q05, q50, q95, q99) for the partner, its available balance, money in transit, need, and the policy amount. | Nothing. |
| `run_review` | `as_of`, `rail` (default `wire`), `execute` (default `false`) | The 09:00 review of `as_of` for every partner: status, available balance, need, policy amount, executed amount, limit applied, ETA, alerts, and a summary in Spanish. | With `execute=true`, one simulated transfer per funded partner in the ledger and one entry in the runs log. |
| `list_transfers` | `at` (optional) | Ledger transfers with their status (`instructed`, `in_transit`, `credited`) at `at`. | Nothing. |
| `set_autonomy` | `enabled` | The new pause state. A paused agent still reviews and reports, but sends nothing. | The state file. |

When `at` is omitted, `get_status` and `list_transfers` use 23:00 of the dataset's last day.

## What the server cannot do

- Change an amount. `run_review` sends what the policy decides, cut to the limits.
- Change a limit or a destination account. Those live in `config/policy.yaml` and the server only reads them.
- Send twice. Each transfer carries an idempotency key made of the partner and the review time, so running the same review again with `execute=true` reports `already_executed` and records nothing new.
- Override a pause from the configuration. `set_autonomy(enabled=true)` resumes only if `autonomy.enabled` is also `true` in `config/policy.yaml`.

[The autonomous agent](agent.md) describes the limits and guardrails in full.

## Files and environment variables

The server shares its files with the monitoring dashboard (`treasury monitor`), so a review executed through MCP shows up there. Each path has a default and an environment variable that overrides it.

| variable | default | content |
|---|---|---|
| `TREASURY_DATA` | `data/sim/base` | The simulated dataset. |
| `TREASURY_LEDGER` | `data/transfers_mcp.jsonl` | The append-only transfer ledger. |
| `TREASURY_RUNS` | `data/agent_runs.jsonl` | One record per executed review. |
| `TREASURY_STATE` | `data/agent_state.json` | The pause switch. |

To start over, delete the ledger, runs, and state files.

## Troubleshooting

- **The client says the server failed to start.** Run `uv run treasury-mcp` from the repository root. If it exits with `FileNotFoundError` on `data/sim/base`, run step 2 of the setup.
- **`ModuleNotFoundError: No module named 'treasury'`.** On macOS, `uv sync` can leave the editable-install `.pth` file hidden, and Python skips hidden `.pth` files. Run `chflags nohidden .venv/lib/python3.12/site-packages/*.pth`, or set `PYTHONPATH=src`.
- **A review takes about 20 seconds.** The server fits the forecast for every partner on each call. That is the expected time on a laptop.
