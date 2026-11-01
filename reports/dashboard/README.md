# Business dashboard

Source of the published dashboard "Prefondeo: cuánta plata queda inmovilizada": assumptions, results
and capital immobilized by number of users. All amounts are Argentine pesos from simulated data.

- `index.html`: the page. It runs on the Claude Artifact Dashboard runtime (`dash.*`), so it does not
  render when opened directly in a browser. The Streamlit app in `src/treasury/dashboard/` runs locally.
- `datasets/`: the JSON files the page reads.
- `build_static.py`: writes the assumptions table and the simulated user vs public data comparison.
  Needs `data/sim/base/` (see the Demo section of the root README).
- `build_data.py`: writes every other dataset from `reports/experiments/*.csv`.

Regenerate:

```bash
PYTHONPATH=src uv run python scripts/scaling_experiment.py
uv run python reports/dashboard/build_static.py reports/dashboard/datasets
uv run python reports/dashboard/build_data.py reports/dashboard/datasets
```
