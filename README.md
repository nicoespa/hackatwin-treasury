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

- `config/calendar_ar_2026.yaml`: Argentine 2026 holidays, SAC (aguinaldo) and ANSES payment windows.
- `src/treasury/calendar.py`: business-day calendar built from that YAML.
