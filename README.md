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

## Troubleshooting

- `ModuleNotFoundError: treasury` after `uv sync`/`uv add` on macOS: the editable-install `.pth` got the hidden flag, which Python skips; run `chflags nohidden .venv/lib/python3.12/site-packages/*.pth`.
