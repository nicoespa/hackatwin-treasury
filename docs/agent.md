# The autonomous agent

The agent turns each day's funding decision into a transfer, with no human approving it. A deterministic policy decides the amount, hard limits cap it, and an executor records it. Claude only writes the explanation. This page describes each layer, what the agent can and cannot do, and what changes when it moves real money.

## Who decides what

| step | done by | can change the amount |
|---|---|---|
| Forecast and deposit size | `treasury.policy.recommend_deposit` on the model's paths | Yes. This is the decision. |
| Limits and guardrails | `treasury.agent.guardrails.check` | Only down: it caps or holds. |
| Execution | `treasury.agent.executor` | No. It re-checks the limits and refuses a transfer that breaks them. |
| Explanation | Claude, with read-only tools | No. |
| Orders from the team | `treasury.orders`, from the chat or the MCP server | Only within the limits: pause, resume, change the risk level, set a cap. |

Claude never decides an amount or a destination. In proposal mode, `propose_transfer` refuses any amount more than one lot away from the policy's and always queues the policy's amount. Every number in Claude's explanation must appear in the tool outputs, to three significant digits. If one does not, a templated explanation replaces it, tagged `[templated: <reason>]`.

## Run it

The agent has two modes. Both need the simulated dataset (see [Command reference](cli.md#generate-the-data)).

`treasury agent run` is the autonomous mode. It reviews every partner at one instant, executes within limits, and prints a summary in Spanish:

```bash
uv run treasury agent run --as-of 2026-10-01 --rail wire
uv run treasury agent run --as-of 2026-10-01T18:00 --rail stablecoin --out reports/demo/agent_run.json
```

The summary shows, per partner, the forecast for tomorrow (q50 and q99), the available balance, money in transit, the need, the decided and executed amounts, the limit applied, the rail and arrival time, and any alerts. `--out` writes the same fields as JSON, plus seven days of forecast quantiles.

`treasury agent propose` is the supervised mode. It writes proposals to an approval queue (`data/queue.jsonl`) and executes nothing. A person approves them by tier from `config/policy.yaml`: T1 (up to 50 M ARS) is approved automatically, T2 (up to 250 M) needs one approver, T3 (up to 2,000 M) needs two different approvers, and anything larger is blocked.

```bash
uv run treasury agent propose --as-of 2026-10-26 --rail stablecoin --no-llm
uv run treasury agent list --status pending
uv run treasury agent approve <id> --approver ana
uv run treasury agent reject <id> --approver beto --reason "balance already enough"
```

In this demo the approver is a typed name, not an authenticated user, so the two-person rule for T3 is only nominal. A production version would take the approver from the logged-in identity.

Claude writes the explanations when `ANTHROPIC_API_KEY` is set and `--no-llm` is absent. The code reads the key only from the environment.

## Hard limits

The limits live in `config/policy.yaml` under `autonomy`, per currency. Daily limits add up over the calendar day of the review.

| setting | default | why |
|---|---|---|
| `enabled` | `true` | The kill switch. `false` holds every partner and executes nothing. |
| `limits.ARS.max_per_transfer` | 500 M | Most deposits in the base dataset are under 300 M. Month-start wire deposits to `card_network` reach about 850 M and get capped. |
| `limits.ARS.max_per_partner_day` | 750 M | Leaves room for the two daily reviews of a 24/7 rail. |
| `limits.ARS.max_all_partners_day` | 1,500 M | A heavy day totals about 1,100 M (2026-10-01 on wire). |
| `max_forecast_age_hours` | 24 | The agent holds when the data behind the forecast ends more than a day before the review. |
| `sanity_multiple` | 3 | The agent holds when the amount exceeds 3 times the partner's largest daily payout of the last 28 days. |
| `destinations` | one per partner and rail | The only accounts the agent can pay into. It cannot choose or change a beneficiary. |

## Guardrails

Each guardrail that fires writes an alert with a `code`, an `action`, a message, and details. The alert goes to the output and to the transfer's ledger record.

- **Hold, send nothing.** The kill switch is on, the forecast is missing or stale, the partner has no allow-listed destination on the rail, or the currency has no limits.
- **Hold, send nothing.** The amount is above the sanity bound. An amount that large more likely comes from a broken forecast than from real demand.
- **Send up to the limit and alert.** The amount is above the remaining limit. The agent sends the capped amount, rounded down to `lot_size`, and the alert asks a person for the rest. Sending nothing would leave the partner short and stop user payments.
- **Send and alert.** More than 5 % of the scenarios run short before the deposit can land (`p_unresolvable` above 0.05). No deposit can fix that, so a person should look.

## The executor

`treasury.agent.executor` writes each transfer to an append-only JSONL ledger. It never calls a network. Each record has:

- an idempotency key made of the partner and the review time, so a rerun of the same review returns the existing transfer and sends nothing new,
- the rail, the amount, the currency, and the allow-listed destination, read from the configuration and never from the caller,
- the times of `instructed`, `in_transit`, and `credited`, with the arrival from `treasury.rails.arrival_time`,
- the alerts raised when it executed.

The executor checks the kill switch, the destination, and the limits again by itself. A bug upstream cannot move more than the limits allow.

## Moving real money

Today the executor writes to a file. To move real money, the code replaces that one write with a call to the bank's or the stablecoin provider's API and passes the same idempotency key, so the provider also rejects a duplicate. The policy, the limits, the guardrails, and the ledger stay as they are.

Three more pieces would come with the connection:

1. **Reconciliation.** Compare each ledger transfer with the partner's statement and alert when a transfer does not arrive on time.
2. **Separate credentials.** The executing service holds the provider credentials in a secrets store. The model and the chat never see them.
3. **A gradual start.** First in shadow mode, where the agent decides and a person sends, to compare the two. Then automatic with low limits. Then higher limits.

The design keeps the risk small even if something fails, because three independent checks stand between a decision and the money:

- the agent's guardrails,
- the executor's own check of the limits and the destination,
- the bank's own controls: credentials that can only pay into the wallet's own accounts at its partners, with a daily cap set at the bank.

The money never leaves the wallet. Every transfer goes from the wallet's treasury to the wallet's own balance at a partner, into an account fixed in the configuration. Someone who took over the agent or wrote to it in the chat still could not send money anywhere else, or send more than the limits.
