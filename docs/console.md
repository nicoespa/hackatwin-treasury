# The web console

The console at [prefoundly.vercel.app](https://prefoundly.vercel.app) is the screen a treasury team watches. It shows the agent's 09:00 decision for two partners, the day's payments against the forecast, the last 14 days of transfers, and a chat with the agent. Nobody approves anything on it. The interface is in Spanish.

The console is a static site in `web/console/` plus one serverless function. It does not run the model. It reads the model's decisions from `web/console/data.json`, which `scripts/build_console_data.py` writes ahead of time.

## What each view shows

- **Monitoreo.** The day's deposit and its arrival, the available balance at the partner, the payments so far, the deviation from the forecast, and tomorrow's estimated deposit. A chart shows the payments of each completed hour against the expected curve. The agent's feed on the right logs each step of the day.
- **Historial.** The last 14 days: deposit, payments, closing balance, forecast, and error per day.
- **Conectar agente.** The commands that connect the [MCP server](mcp.md) to Claude Code or Claude Desktop, and its tools.

A first visit opens a splash screen and an eight-step tour (`web/console/assets/tour.js`). The **Ver recorrido** button opens the tour again. On a phone the console switches to a tab layout.

The data is the simulated dataset seen on Friday 2026-10-23. Partner A is `bills_aggregator` (bills and mobile top-ups) and Partner B is `crypto_exchange`. The console replays the day on a clock that starts at 15:30.

## Regenerate the data

`scripts/build_console_data.py` runs the walk-forward forecast (k-means segments, Tweedie LightGBM, Monte Carlo) and the backtest with one daily review at 09:00, then writes `web/console/data.json`. It needs the simulated dataset (see [Command reference](cli.md#generate-the-data)).

```bash
PYTHONPATH=src uv run python scripts/build_console_data.py
```

To change the day or the partners, edit `TODAY` and `PARTNERS` at the top of the script.

## Run it locally

Serve the folder with any static server:

```bash
python3 -m http.server 8710 -d web/console
```

Open `http://localhost:8710`. Without the serverless function, the chat answers from the same numbers with built-in templates.

## The chat: `POST /api/ask`

`web/console/api/ask.js` answers the team's questions with Claude (`claude-haiku-5-5` by default, `ANTHROPIC_MODEL` to change it). The page sends the question and the numbers on screen. The system prompt tells Claude to use only those numbers and to answer in two or three sentences in Argentine Spanish.

The function spends the project's API key, so it accepts a request only when:

- the request comes from the deployed console or from `localhost` (origin allow-list, extendable with `ALLOWED_ORIGINS`),
- the question is at most 500 characters and the context at most 8,000,
- the same IP has sent at most 12 questions in the last minute.

| status | meaning |
|---|---|
| 200 | `{ "text": "..." }` with the answer. |
| 400 | The question is missing or too long. |
| 403 | The origin is not allowed. |
| 413 | The context is too large. |
| 429 | The IP or the API rate limit was reached. |
| 502 | Claude refused, returned no text, or could not be reached. |
| 503 | `ANTHROPIC_API_KEY` is not set. The page falls back to its templates. |

Orders typed in the chat ("frená los envíos", "no mandes más de 100 M") constrain the agent on screen. They never set an amount.

## Run the model live (optional)

The console can also run the model from scratch instead of reading the precomputed decision. `treasury model-api` serves the model over HTTP:

```bash
uv run treasury model-api --port 8790
```

`GET /api/run?partner=bills_aggregator&date=2026-10-23&available=95276826&alpha=0.99` returns a Server-Sent Events stream. Each `step` event is one stage of the pipeline: read the payments, segment the users, fit the model, simulate 1,000 paths, and size the deposit. The last event, `done`, carries the decision. A run takes about 2 seconds on a laptop. The service runs one decision at a time and answers `429` while one is in progress. `GET /api/health` reports the last day of the dataset.

To show the **Correr el modelo en vivo** button, open the console with the service address:

```
https://prefoundly.vercel.app/?model=http://localhost:8790
```

The browser remembers the address. `?model=` with no value turns the button off. The console accepts only the addresses listed in `MODEL_ORIGINS` in `web/console/index.html`, so a link cannot point it at someone else's server.

## Deploy

The Vercel project is `prefoundly`, linked from `web/console/.vercel`. Set `ANTHROPIC_API_KEY` in the project's environment variables, then deploy from the console folder:

```bash
cd web/console
vercel deploy --prod
```
