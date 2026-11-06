"""The demo's tables: model ablation, policy x rail factorial, capital-service frontier, a dataset
designed for the bottom-up model to lose, and an evaluation under scenarios the training data lacks."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import date, timedelta
from functools import partial
from pathlib import Path

import pandas as pd
from sklearn.metrics import adjusted_rand_score

from treasury.backtest import (
    CONFIG,
    HORIZON,
    BacktestResult,
    Dataset,
    Segmenter,
    run,
    segmented_inputs,
    walk_forward,
)
from treasury.calendar import Calendar
from treasury.features import build_drivers
from treasury.harness import default_origins
from treasury.metrics import summarize
from treasury.models.aggregate_lgbm import AggregateLGBM
from treasury.models.base import Forecaster, daily_partner_table
from treasury.models.seasonal_naive import SeasonalNaive
from treasury.models.segment_lgbm import SegmentLGBM
from treasury.policy import PolicyConfig, load_policy
from treasury.routing import load_partners
from treasury.segmentation import NEW, KMeansSegmenter
from treasury.simulate import Campaign, CohortWave, SimParams, load_archetypes
from treasury.simulate.pipeline import simulate_routed

MODEL_FACTORIES: dict[str, Callable[..., Forecaster]] = {
    "seasonal_naive": lambda n_paths=1000: SeasonalNaive(),
    "aggregate_drivers": lambda n_paths=1000: AggregateLGBM(use_obligations=False),
    "aggregate_drivers_obligations": lambda n_paths=1000: AggregateLGBM(use_obligations=True),
    "segment_factor": lambda n_paths=1000: SegmentLGBM(use_factor=True, n_paths=n_paths),
    "segment_nofactor": lambda n_paths=1000: SegmentLGBM(use_factor=False, n_paths=n_paths),
}
LABELS = dict(zip(MODEL_FACTORIES, ("(a)", "(b)", "(c)", "(d)", "(d-)")))
PROPOSED = "segment_factor"
RAILS = ("wire", "stablecoin")
POLICY_COLUMNS = ["capital_total_mean", "shortfall_rate", "shortfall_amount_total", "cost_total", "n_transfers"]
DESIGNED_START = date(2026, 6, 1)  # the segment model needs 112 days of history before the first origin
# History of the unknown-scenario dataset: announced campaigns of other shapes than the test one,
# so a model can learn how ``campaign_lift`` moves outflow.
PAST_CAMPAIGNS = [
    Campaign(date(2026, 2, 9), date(2026, 2, 13), ("bill_payment",), lift=1.4),
    Campaign(date(2026, 4, 20), date(2026, 4, 22), ("card_purchase",), lift=1.3),
    Campaign(date(2026, 6, 15), date(2026, 6, 19), ("crypto_buy",), lift=1.6),
]
TEST_CAMPAIGN = Campaign(date(2026, 10, 5), date(2026, 10, 7), ("card_purchase",), lift=1.8)
TEST_WAVE = CohortWave(date(2026, 9, 15), 3000, "young_heavy")
UNKNOWN_SCENARIOS = [TEST_CAMPAIGN, TEST_WAVE]
CAMPAIGN_SCOPE = ("card_network", date(2026, 10, 5), date(2026, 10, 9))
WAVE_DAYS = 14  # cohort window scored from the wave's start
WAVE_PARTNER_SHARE = 0.05  # partners where the wave segment carries at least this share of outflow


def factory(name: str, n_paths: int = 1000) -> Callable[[], Forecaster]:
    return partial(MODEL_FACTORIES[name], n_paths=n_paths)


def _origins(dataset: Dataset, origins: Sequence[date] | None, n: int = 8) -> list[date]:
    return list(origins) if origins is not None else default_origins(dataset.end, n=n, step_days=7, horizon=HORIZON)


def _policy(cfg: PolicyConfig | None) -> PolicyConfig:
    return cfg or load_policy(CONFIG / "policy.yaml")


def ablation_table(
    dataset: Dataset, origins: Sequence[date] | None = None, models: Sequence[str] = tuple(MODEL_FACTORIES),
    n_paths: int = 1000, by: tuple[str, ...] = ("model",), segmenter: Segmenter | None = None,
) -> pd.DataFrame:
    """``summarize`` scores of each model's walk-forward forecasts (``HORIZON`` days per origin),
    pooled over partners and horizons by default; ``by=("model", "partner")`` keeps partners.
    ``segmenter`` goes to ``walk_forward`` (None: the data's own segment labels)."""
    origins = _origins(dataset, origins)
    preds = pd.concat([
        f.quantiles for m in models
        for f in walk_forward(dataset, factory(m, n_paths), origins, n_paths=n_paths, segmenter=segmenter)
    ])
    table = summarize(preds, daily_partner_table(dataset.history), by=by)
    table.insert(0, "label", table["model"].map(LABELS))
    order = table["model"].map(list(MODEL_FACTORIES).index).rename("order")
    return table.join(order).sort_values(["order", *by[1:]], ignore_index=True).drop(columns="order")


def _row(result, **keys) -> dict:
    m = result.metrics
    note = ", ".join(f"{p}={r}" for p, r in m["rail_used"].items() if r != keys.get("rail"))
    return {**keys, **{c: m[c] for c in POLICY_COLUMNS}, "realized_service": 1.0 - m["shortfall_rate"],
            "p_unresolvable_mean": m["p_unresolvable_mean"], "warmup_days": m["warmup_days"],
            "warmup_shortfall_windows": m["warmup_shortfall_windows"], "rail_note": note or "all partners on this rail"}


def matched_buffer(
    dataset: Dataset, rail: str, target_rate: float, origins: Sequence[date], cfg: PolicyConfig,
    tol: float = 0.1, max_days: float = 64.0,
) -> tuple[float, BacktestResult]:
    """Smallest fixed-buffer days (to ``tol``) whose post-warm-up ``shortfall_rate`` is at most
    ``target_rate``, by doubling then bisection (the rate falls as the buffer grows)."""
    runs: dict[float, BacktestResult] = {}

    def rate(days: float) -> float:
        runs[days] = run(dataset, None, "fixed", rail, replace(cfg, fixed_buffer_days=days), origins)
        return runs[days].metrics["shortfall_rate"]

    lo, hi = 0.0, 1.0
    while rate(hi) > target_rate:
        lo, hi = hi, 2 * hi
        if hi > max_days:
            raise ValueError(f"no buffer up to {max_days} days reaches a shortfall rate of {target_rate}")
    while hi - lo > tol:
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if rate(mid) <= target_rate else (mid, hi)
    return hi, runs[hi]


def factorial_table(
    dataset: Dataset, origins: Sequence[date] | None = None, n_paths: int = 1000, cfg: PolicyConfig | None = None,
    model: str = PROPOSED, segmenter: Segmenter | None = None,
) -> pd.DataFrame:
    """Per rail (wire, stablecoin): ``reference`` (fixed buffer of the config's ``fixed_buffer_days``
    of trailing mean drain, no model), ``proposed`` (``segment_factor`` paths + forecast policy at
    the config's ``alpha``) and ``reference_matched``, the fixed buffer with the fewest days
    (``buffer_days``) whose post-warm-up shortfall rate is at most the proposed one's.

    The config-value cells are not at the same service level; ``reference_matched`` vs
    ``proposed`` is the comparison that answers the success criterion (less capital at the same
    service level). ``rail_note`` names the partners that cannot take the rail and use their only one.
    ``model`` (default ``PROPOSED``) and ``segmenter`` choose the proposed cell's forecasts.
    """
    origins, cfg = _origins(dataset, origins), _policy(cfg)
    rows = []
    for rail in RAILS:
        ref = run(dataset, None, "fixed", rail, cfg, origins, n_paths=n_paths)
        rows.append(_row(ref, cell="reference", rail=rail, model="none", policy="fixed",
                         buffer_days=float(cfg.fixed_buffer_days)))
        prop = run(dataset, factory(model, n_paths), "forecast", rail, cfg, origins, n_paths=n_paths, segmenter=segmenter)
        rows.append(_row(prop, cell="proposed", rail=rail, model=model, policy=f"forecast_a{cfg.alpha:g}",
                         buffer_days=float("nan")))
        days, matched = matched_buffer(dataset, rail, prop.metrics["shortfall_rate"], origins, cfg)
        rows.append(_row(matched, cell="reference_matched", rail=rail, model="none", policy="fixed", buffer_days=days))
    return pd.DataFrame(rows)


def frontier(
    dataset: Dataset, alphas: Sequence[float] = (0.5, 0.7, 0.8, 0.9, 0.95, 0.99, 0.995),
    origins: Sequence[date] | None = None, n_paths: int = 1000, cfg: PolicyConfig | None = None,
    buffer_days: Sequence[float] = (2, 3, 4, 5, 6, 7, 8, 10),
) -> pd.DataFrame:
    """Capital vs shortfall per rail: the proposed model at each ``alpha``, and for comparison at
    equal service level the fixed buffer at each of ``buffer_days``."""
    origins, cfg = _origins(dataset, origins), _policy(cfg)
    rows = []
    for rail in RAILS:
        for alpha in alphas:
            res = run(dataset, factory(PROPOSED, n_paths), "forecast", rail, replace(cfg, alpha=alpha), origins, n_paths=n_paths)
            rows.append(_row(res, rail=rail, policy="forecast", model=PROPOSED, param_name="alpha", param=alpha))
        for days in buffer_days:
            res = run(dataset, None, "fixed", rail, replace(cfg, fixed_buffer_days=days), origins, n_paths=n_paths)
            rows.append(_row(res, rail=rail, policy="fixed", model="none", param_name="buffer_days", param=float(days)))
    return pd.DataFrame(rows)


def _simulate(n_users: int, archetypes: dict, start: date, end: date, seed: int, params: SimParams, scenarios=()):
    cal = Calendar.from_yaml(CONFIG / "calendar_ar.yaml")
    return simulate_routed(n_users, archetypes, cal, load_partners(CONFIG / "partners.yaml"), start, end, seed, params,
                           scenarios)


def designed_to_lose(seed: int, n_paths: int = 1000, n_users: int = 20_000) -> pd.DataFrame:
    """Pooled ablation of (c) vs (d) on a population of five identical segments (copies of
    ``salaried_formal``, shares 0.2), where splitting by segment carries no information.

    The population runs from ``DESIGNED_START`` (not three months back: the segment model needs
    112 days of history before the first of the four origins) to 2026-10-31.
    """
    archetypes = load_archetypes(CONFIG / "archetypes.yaml")
    salaried = archetypes["archetypes"]["salaried_formal"]
    archetypes = {**archetypes, "archetypes": {f"seg_{c}": {**salaried, "share": 0.2} for c in "abcde"}}
    end = date(2026, 10, 31)
    users, events, macro = _simulate(n_users, archetypes, DESIGNED_START, end, seed, SimParams())
    dataset = Dataset.from_frames(users, events, {"end": end.isoformat(), "seed": seed}, macro)
    origins = default_origins(end, n=4, step_days=7, horizon=HORIZON)
    return ablation_table(dataset, origins, models=("aggregate_drivers_obligations", PROPOSED), n_paths=n_paths)


def scenario_variants(base: Dataset, seed: int | None = None) -> dict[str, Dataset]:
    """A regeneration of ``base`` (same users, dates and simulation ``seed``, default the base's)
    with ``PAST_CAMPAIGNS`` plus ``UNKNOWN_SCENARIOS``, under two sets of drivers. Both carry the
    past campaigns, which are history. ``announced`` also carries the test campaign and every user;
    ``surprise`` neither the test campaign nor the wave's users (the wave is not a planned cohort)."""
    p = base.params
    seed = p["seed"] if seed is None else seed
    params = SimParams(sigma_m=p["sigma_m"], phi=p["phi"], payday_hypothesis=p["payday_hypothesis"],
                       inflation_monthly=p["inflation_monthly"])
    archetypes = load_archetypes(CONFIG / "archetypes.yaml")
    start, end = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
    scenarios = [*PAST_CAMPAIGNS, *UNKNOWN_SCENARIOS]
    users, events, macro = _simulate(p["n_users"], archetypes, start, end, seed, params, scenarios)
    announced = Dataset.from_frames(users, events, {**p, "n_users": len(users), "n_events": len(events)}, macro,
                                    scenarios)
    planned = users[users["user_id"] < p["n_users"]]
    dates = pd.DatetimeIndex(announced.drivers["date"])
    surprise = replace(announced, drivers=build_drivers(planned, events, dates, PAST_CAMPAIGNS), cache={})
    return {"announced": announced, "surprise": surprise}


def _scopes(dataset: Dataset) -> dict[str, Callable[[pd.DataFrame], pd.Series]]:
    """Row filters of a forecast frame: everything, the test campaign's partner-days and the wave's
    window on the partners where the wave's segment carries ``WAVE_PARTNER_SHARE`` of outflow."""
    h = dataset.history[dataset.history["date"] < pd.Timestamp(TEST_WAVE.start)]
    share = h[h["segment"] == TEST_WAVE.segment].groupby("partner")["outflow"].sum() / h.groupby("partner")["outflow"].sum()
    wave_partners = sorted(share[share >= WAVE_PARTNER_SHARE].index)
    partner, first, last = CAMPAIGN_SCOPE
    wave_end = TEST_WAVE.start + timedelta(days=WAVE_DAYS - 1)
    return {
        "pooled": lambda q: pd.Series(True, index=q.index),
        f"campaign:{partner}": lambda q: (q["partner"] == partner) & q["date"].between(str(first), str(last)),
        f"wave:{'+'.join(wave_partners)}": lambda q: q["partner"].isin(wave_partners)
        & q["date"].between(str(TEST_WAVE.start), str(wave_end)),
    }


def unknown_scenario_eval(
    base: Dataset, seed: int | None = None, n_paths: int = 1000, origins: Sequence[date] | None = None,
    cfg: PolicyConfig | None = None, rail: str = "stablecoin",
) -> pd.DataFrame:
    """(c) and (d), trained before each origin, on ``scenario_variants``: forecast scores pooled and
    restricted to the test campaign's and the wave's partner-days (``scope``, with ``n_points``),
    and on the pooled rows the forecast policy's post-warm-up backtest on ``rail``."""
    origins, cfg = _origins(base, origins), _policy(cfg)
    rows = []
    for variant, dataset in scenario_variants(base, seed).items():
        actual = daily_partner_table(dataset.history)
        for model in ("aggregate_drivers_obligations", PROPOSED):
            preds = pd.concat([f.quantiles for f in walk_forward(dataset, factory(model, n_paths), origins, n_paths=n_paths)])
            bt = run(dataset, factory(model, n_paths), "forecast", rail, cfg, origins, n_paths=n_paths).metrics
            for scope, keep in _scopes(dataset).items():
                sub = preds[keep(preds)]
                score = summarize(sub, actual, by=("model",)).iloc[0]
                pooled = scope == "pooled"
                rows.append({
                    "label": LABELS[model], "model": model, "variant": variant, "scope": scope, "n_points": len(sub),
                    **score[["pinball_q90", "cov_90", "pit_ks", "wape_q50"]].to_dict(), "rail": rail,
                    **{k: bt[k] if pooled else float("nan") for k in ("capital_total_mean", "shortfall_rate",
                                                                       "shortfall_amount_total")},
                })
    return pd.DataFrame(rows)


def run_all(data: Path, out: Path, n_paths: int = 1000) -> dict[str, float]:
    """Write every table as CSV under ``out`` with a README naming the source dataset and reading
    the service levels off the factorial and frontier; returns each table's wall time in seconds."""
    out.mkdir(parents=True, exist_ok=True)
    dataset = Dataset.load(data)
    timings: dict[str, float] = {}
    built: dict[str, pd.DataFrame] = {}
    tables: dict[str, Callable[[], pd.DataFrame]] = {
        "ablation_pooled": lambda: ablation_table(dataset, n_paths=n_paths),
        "ablation_by_partner": lambda: ablation_table(dataset, n_paths=n_paths, by=("model", "partner")),
        "factorial": lambda: factorial_table(dataset, n_paths=n_paths),
        "frontier": lambda: frontier(dataset, n_paths=n_paths),
        "designed_to_lose": lambda: designed_to_lose(seed=dataset.params["seed"], n_paths=n_paths),
        "unknown_scenario": lambda: unknown_scenario_eval(dataset, n_paths=n_paths),
    }
    for name, build in tables.items():
        began = time.perf_counter()
        built[name] = build()
        built[name].to_csv(out / f"{name}.csv", index=False)
        timings[name] = round(time.perf_counter() - began, 1)
    _write_readme(out, data, dataset, timings, n_paths, built["factorial"], built["frontier"])
    return timings


TABLE_CONTENTS = {
    "ablation_pooled": f"forecast scores of models (a)..(d-), pooled over partners and horizons 1..{HORIZON}",
    "ablation_by_partner": "the same per partner",
    "factorial": "per rail: reference (fixed buffer, config days), proposed ((d) + forecast policy, config alpha) "
    "and reference_matched (fixed buffer at the proposed policy's service level)",
    "frontier": "capital vs shortfall rate per rail: (d) at each alpha, the fixed buffer at each number of days",
    "designed_to_lose": "(c) vs (d) on five identical segments, 4 origins",
    "unknown_scenario": "(c) and (d) under an unseen card campaign and cohort wave, announced vs surprise, "
    "scored pooled and on the affected partner-days",
}


def _notes(cfg: PolicyConfig) -> list[str]:
    return [
        f"**The config-value cells of `factorial.csv` (`reference` = {cfg.fixed_buffer_days:g}-day buffer, `proposed` = "
        f"alpha {cfg.alpha:g}) are NOT at",
        "the same service level.** `reference_matched` is the fixed buffer with the fewest days whose post-warm-up",
        "shortfall rate is at most the proposed policy's; `reference_matched` vs `proposed` is the comparison that",
        "answers the success criterion (less capital at the same service level).",
        "",
        "Metrics exclude a warm-up (`warmup_days`, the same for every policy and rail): the days until the first",
        "order on the slowest rail (wire) can land, during which every balance runs on its opening alone. The",
        "warm-up's shortfalls are reported apart as `warmup_shortfall_windows`.",
        "",
        "Amounts are in the simulation's currency (ARS). Shortfall windows are partner-days: a window is short",
        "when the realized balance goes below 0 in it, and its shortfall amount is `max(0, -min balance)`;",
        "`realized_service = 1 - shortfall_rate`. `capital_total_mean` is the time-weighted mean of every",
        "partner's non-negative available balance plus the deposits in transit, plus the central reserve (0 here);",
        "`cost_total` charges it at `cost_of_capital_annual` over the evaluated days, plus rail fees and",
        "`cost_per_usd_rejected` per unit short.",
        "",
        "`p_unresolvable_mean` averages the forecast policy's `p_unresolvable` over the evaluated reviews except",
        "the structural no-ops (`backtest.structural_noop`): reviews with no deposit whose window closes before the",
        f"next day's outflow, i.e. the {min(cfg.review_hours_247):02d}:00 review of a 24/7 rail, which can never deposit "
        "anything.",
    ]


def zero_shortfall_alpha(frontier_table: pd.DataFrame) -> dict[str, float | None]:
    """Per rail the smallest alpha of the proposed policy's sweep from which every alpha has a 0 %
    post-warm-up shortfall rate; None when the sweep has no such alpha."""
    forecast = frontier_table[frontier_table["policy"] == "forecast"]
    out: dict[str, float | None] = {}
    for rail, g in forecast.groupby("rail", sort=False):
        zero = g.loc[g["shortfall_rate"] == 0, "param"]
        ok = len(zero) and (g.loc[g["param"] >= zero.min(), "shortfall_rate"] == 0).all()
        out[rail] = float(zero.min()) if ok else None
    return out


def _service_section(factorial: pd.DataFrame, frontier_table: pd.DataFrame) -> list[str]:
    """README lines read off the tables: the matched comparison and alpha's realized service."""
    header = ("| rail | proposed capital | shortfall rate | matched buffer days | matched capital | "
              "matched shortfall rate | capital saved |")
    lines = ["## Same service level", "", header, "|---|---|---|---|---|---|---|"]
    cells = factorial.set_index(["rail", "cell"])
    for rail in RAILS:
        prop, ref = cells.loc[(rail, "proposed")], cells.loc[(rail, "reference_matched")]
        saved = 1 - prop["capital_total_mean"] / ref["capital_total_mean"]
        lines.append(f"| {rail} | {prop['capital_total_mean']:.3e} | {prop['shortfall_rate']:.2%} | "
                     f"{ref['buffer_days']:.2f} | {ref['capital_total_mean']:.3e} | {ref['shortfall_rate']:.2%} | {saved:.0%} |")
    lines += ["", "## Nominal alpha vs realized service (proposed policy, post-warm-up)", "",
              "| rail | alpha | realized service | shortfall rate | capital |", "|---|---|---|---|---|"]
    forecast = frontier_table[frontier_table["policy"] == "forecast"]
    for _, r in forecast.iterrows():
        lines.append(f"| {r['rail']} | {r['param']:g} | {r['realized_service']:.2%} | {r['shortfall_rate']:.2%} | "
                     f"{r['capital_total_mean']:.3e} |")
    lines.append("")
    for rail, alpha in zero_shortfall_alpha(frontier_table).items():
        lines.append(f"- {rail}: post-warm-up shortfall rate is 0 % for alpha >= {alpha:g}." if alpha is not None
                     else f"- {rail}: no alpha in the sweep reaches a 0 % post-warm-up shortfall rate.")
    lines += [
        "",
        "Alpha is therefore not the realized service level. It is the per-decision quantile of the Monte Carlo",
        "deposit, and the policy around it is conservative: each day's forecast outflow is placed at 00:00 (a",
        "credit landing that day never covers it) and every deposit protects the window until the next review's",
        "order could land, so the realized service sits above alpha.",
        "",
    ]
    return lines


def _write_readme(
    out: Path, data: Path, dataset: Dataset, timings: dict[str, float], n_paths: int,
    factorial: pd.DataFrame, frontier_table: pd.DataFrame,
) -> None:
    lines = [
        "# Experiments",
        "",
        f"Generated by `treasury experiments --data {data} --out {out}` with `n_paths={n_paths}`, origins",
        f"`default_origins({dataset.end}, n=8, step_days=7, horizon={HORIZON})` and `config/policy.yaml`.",
        "",
        "| file | content | seconds |",
        "|---|---|---|",
        *(f"| {name}.csv | {TABLE_CONTENTS[name]} | {seconds} |" for name, seconds in timings.items()),
        "",
        *_notes(_policy(None)),
        "",
        *_service_section(factorial, frontier_table),
        *segmentation_section(out),
        f"Source dataset `{data / 'params.json'}`:",
        "",
        "```json",
        json.dumps(dataset.params, indent=2),
        "```",
        "",
    ]
    (out / "README.md").write_text("\n".join(lines))


# Inferred segments: the segment model on k-means segments vs the simulator's archetype labels.
SEGMENTATION_VARIANTS: dict[str, tuple[str, Segmenter | None]] = {
    "(d) oracle": (PROPOSED, None),
    "(d) kmeans": (PROPOSED, KMeansSegmenter()),
    "(d) kmeans k=7": (PROPOSED, KMeansSegmenter(k=7)),
    "(b) oracle": ("aggregate_drivers", None),
    "(c) oracle": ("aggregate_drivers_obligations", None),
    "(c) kmeans": ("aggregate_drivers_obligations", KMeansSegmenter()),
}
SEGMENTATION_FILES = ("segmentation_forecast", "segmentation_backtest", "segmentation_clusters", "segmentation_profiles")
SECTION_START, SECTION_END = "<!-- segmentation:start -->", "<!-- segmentation:end -->"


def _labels(segmenter: Segmenter | None) -> str:
    return "oracle" if segmenter is None else segmenter.name


def segmentation_tables(
    dataset: Dataset, origins: Sequence[date] | None = None, n_paths: int = 1000, cfg: PolicyConfig | None = None,
    variants: dict[str, tuple[str, Segmenter | None]] = SEGMENTATION_VARIANTS,
) -> dict[str, pd.DataFrame]:
    """Each variant (model, segmenter) scored like ``ablation_table`` (pooled) and backtested like
    ``factorial_table`` (``proposed`` and ``reference_matched`` per rail), plus per origin and
    segmenter the chosen ``k``, its silhouette, the adjusted Rand index of the clustered users'
    segments against the simulator's hidden archetypes (``ari_vs_archetype``, possible only on
    simulated data) and each segment's profile with its dominant archetype."""
    origins, cfg = _origins(dataset, origins), _policy(cfg)
    forecast, backtest = [], []
    for variant, (model, segmenter) in variants.items():
        score = ablation_table(dataset, origins, models=(model,), n_paths=n_paths, segmenter=segmenter)
        forecast.append(score.assign(variant=variant, labels=_labels(segmenter)))
        cells = factorial_table(dataset, origins, n_paths, cfg, model=model, segmenter=segmenter)
        backtest.append(cells[cells["cell"] != "reference"].assign(variant=variant, labels=_labels(segmenter)))
    archetype = dataset.users.set_index("user_id")["segment"]
    clusters, profiles = [], []
    segmenters = {s.name: s for _, s in variants.values() if s is not None}
    for name, segmenter in segmenters.items():
        for origin in origins:
            seg = segmented_inputs(dataset, segmenter, origin)[2]
            clustered = seg.labels[seg.labels != NEW]
            clusters.append({
                "labels": name, "origin": pd.Timestamp(origin), "k": seg.k, "silhouette": seg.silhouette,
                "silhouette_by_k": json.dumps({str(c): round(v, 4) for c, v in seg.silhouette_by_k.items()}),
                "n_clustered": len(clustered), "n_new": int((seg.labels == NEW).sum()),
                "ari_vs_archetype": adjusted_rand_score(archetype.reindex(clustered.index), clustered),
            })
            mix = pd.crosstab(seg.labels.rename("segment"), archetype.reindex(seg.labels.index).rename("archetype"),
                              normalize="index")
            profiles.append(seg.profile.assign(labels=name, origin=pd.Timestamp(origin)).merge(
                pd.DataFrame({"segment": mix.index, "top_archetype": mix.idxmax(axis=1).to_numpy(),
                              "top_archetype_share": mix.max(axis=1).to_numpy()}), on="segment"))
    first = ["variant", "labels"]
    return {
        "segmentation_forecast": pd.concat(forecast, ignore_index=True).pipe(lambda t: t[first + [c for c in t if c not in first]]),
        "segmentation_backtest": pd.concat(backtest, ignore_index=True).pipe(lambda t: t[first + [c for c in t if c not in first]]),
        "segmentation_clusters": pd.DataFrame(clusters),
        "segmentation_profiles": pd.concat(profiles, ignore_index=True).pipe(
            lambda t: t[["labels", "origin"] + [c for c in t if c not in ("labels", "origin")]]),
    }


def segmentation_section(out: Path) -> list[str]:
    """README section read off ``segmentation_*.csv`` in ``out`` (empty when they are missing),
    between ``SECTION_START`` and ``SECTION_END`` so ``run_segmentation`` can replace it."""
    paths = {name: out / f"{name}.csv" for name in SEGMENTATION_FILES[:3]}
    if not all(p.exists() for p in paths.values()):
        return []
    fc, bt, cl = (pd.read_csv(p) for p in paths.values())
    lines = [SECTION_START, "## Inferred segments (no archetype labels)", "",
             "The segment model (d) normally splits nodes by the simulator's archetype label, which a real wallet",
             "does not have. `treasury.segmentation` infers segments at each origin from the users' transactions",
             "before it (k-means, k chosen by silhouette in 2..8; users with < 30 days of tenure or < 5 events in",
             "the last 90 days, and users activated later, are `new`). In the node history every user is `new` for",
             "their first 30 days and then joins their cluster (`backtest.segmented_inputs`). Profiles and",
             "per-origin clusters: `segmentation.md`.", "",
             "| variant | wape_q50 | cov_90 | cov_99 | pit_ks |", "|---|---|---|---|---|"]
    lines += [f"| {r['variant']} | {r['wape_q50']:.3f} | {r['cov_90']:.3f} | {r['cov_99']:.3f} | {r['pit_ks']:.3f} |"
              for _, r in fc.iterrows()]
    lines += ["", "| variant | rail | capital | shortfall rate | matched buffer days | matched capital | capital saved |",
              "|---|---|---|---|---|---|---|"]
    for (variant, rail), g in bt.groupby(["variant", "rail"], sort=False):
        prop, ref = (g[g["cell"] == c].iloc[0] for c in ("proposed", "reference_matched"))
        lines.append(f"| {variant} | {rail} | {prop['capital_total_mean']:.3e} | {prop['shortfall_rate']:.2%} | "
                     f"{ref['buffer_days']:.2f} | {ref['capital_total_mean']:.3e} | "
                     f"{1 - prop['capital_total_mean'] / ref['capital_total_mean']:.0%} |")
    lines += ["", "| labels | k per origin | silhouette (mean) | ARI vs archetypes (mean) |", "|---|---|---|---|"]
    for labels, g in cl.groupby("labels", sort=False):
        lines.append(f"| {labels} | {', '.join(str(k) for k in g['k'])} | {g['silhouette'].mean():.3f} | "
                     f"{g['ari_vs_archetype'].mean():.3f} |")
    return [*lines, "", SECTION_END, ""]


def _upsert_section(readme: Path, section: list[str]) -> None:
    """Replace the segmentation section of ``readme`` (or insert it before the source dataset)."""
    text = readme.read_text() if readme.exists() else ""
    block = "\n".join(section)
    if SECTION_START in text and SECTION_END in text:
        head, rest = text.split(SECTION_START, 1)
        text = head + block.rstrip("\n") + rest.split(SECTION_END, 1)[1]
    elif "Source dataset" in text:
        head, rest = text.split("Source dataset", 1)
        text = head + block + "Source dataset" + rest
    else:
        text += "\n" + block
    readme.write_text(text)


def _markdown(table: pd.DataFrame) -> str:
    """``table`` as a markdown table, floats to 3 significant digits and timestamps as dates."""
    def cell(v) -> str:
        if isinstance(v, pd.Timestamp):
            return str(v.date())
        return f"{v:.3g}" if isinstance(v, float) else str(v)
    rows = [" | ".join(table.columns), " | ".join("---" for _ in table.columns)]
    rows += [" | ".join(cell(v) for v in r) for r in table.itertuples(index=False)]
    return "\n".join(f"| {r} |" for r in rows)


def run_segmentation(data: Path, out: Path, n_paths: int = 1000) -> dict[str, pd.DataFrame]:
    """Write ``segmentation_tables`` as ``segmentation_*.csv`` and ``segmentation.md`` under ``out``
    and refresh the segmentation section of ``out/README.md``."""
    out.mkdir(parents=True, exist_ok=True)
    dataset = Dataset.load(data)
    tables = segmentation_tables(dataset, n_paths=n_paths)
    for name, table in tables.items():
        table.to_csv(out / f"{name}.csv", index=False)
    section = segmentation_section(out)
    profiles = tables["segmentation_profiles"]
    last = profiles[profiles["origin"] == profiles["origin"].max()]
    cols = ["labels", "segment", "n_users", "outflow_monthly", "payday_share", "weekend_share", "top_archetype",
            "top_archetype_share", *[c for c in last if c.startswith("out_")]]
    md = [
        "# Inferred segments", "",
        f"Generated by `scripts/segmentation_experiment.py` on `{data}` with `n_paths={n_paths}`, origins",
        f"`default_origins({dataset.end}, n=8, step_days=7, horizon={HORIZON})` and `config/policy.yaml`.",
        "Files: " + ", ".join(f"`{n}.csv`" for n in SEGMENTATION_FILES) + ".", "",
        *[line for line in section if not line.startswith("<!--")],
        f"## Segment profiles at the last origin ({last['origin'].max().date()})", "",
        "Monthly amounts are means per user over the trailing 90 days (per 30 days); `top_archetype` is the",
        "hidden archetype most of the segment's users have, readable only because the data is simulated.", "",
        _markdown(last[cols]), "",
        "## Clusters per origin", "",
        _markdown(tables["segmentation_clusters"]), "",
    ]
    (out / "segmentation.md").write_text("\n".join(md))
    _upsert_section(out / "README.md", section)
    return tables
