"""Bottom-up model (d): one Tweedie LightGBM over ``segment × product × partner`` nodes, summed
to partners by Monte Carlo with a shared daily macro factor.

``use_factor=False`` is the ablation "bottom-up without common factor": nodes are independent,
the partner sums concentrate and the quantiles come out too narrow (PIT piles up at 0 and 1).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

from treasury.calendar import Calendar
from treasury.models.aggregate_lgbm import CONFIG, FLOOR_SHARE, driver_features, trailing_level
from treasury.models.base import NODE, QCOLS, QUANTILES, enforce_quantiles
from treasury.models.seasonal_naive import seasonal_lag, seasonal_mean
from treasury.montecarlo import simulate_paths
from treasury.obligations import split_residual

LAGS = (7, 14)
HOLDOUT_DAYS = 56
MIN_TRAIN_DAYS = 56  # before the holdout
MIN_HOLDOUT_POINTS = 28
MIN_FACTOR_DAYS = 14
CV_RANGE = (0.05, 2.0)
PHI_RANGE = (0.0, 0.95)
TWEEDIE_PARAMS = {
    "objective": "tweedie", "tweedie_variance_power": 1.3, "n_estimators": 300, "learning_rate": 0.05,
    "num_leaves": 15, "min_child_samples": 50, "random_state": 0, "n_jobs": 1, "verbose": -1,
}
_OWN_DRIVERS = ("n_active_ratio_", "n_new_ratio_", "campaign_lift_")


def node_baseline(series: pd.Series, dates: pd.DatetimeIndex) -> np.ndarray:
    """``seasonal_mean`` floored at ``FLOOR_SHARE`` of the ``trailing_level`` where the seasonal
    mean is positive; where it is 0 or NaN (an intermittent node) the ``trailing_level`` itself."""
    seasonal, level = seasonal_mean(series, dates), trailing_level(series, dates)
    return np.where(seasonal > 0, np.fmax(seasonal, FLOOR_SHARE * level), level)


def node_ratio(y: np.ndarray, base: np.ndarray) -> np.ndarray:
    """``y / base``; where ``base`` is not positive, 0 when ``y == 0`` and NaN otherwise."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(base > 0, y / base, np.where(y == 0, 0.0, np.nan))


def common_factor(actual: np.ndarray, mu: np.ndarray) -> tuple[np.ndarray, float, float]:
    """``(g, sigma_f, phi_f)`` from holdout ``actual`` and ``mu`` (``[n_days, n_nodes]``).

    ``g_d = log(Σ actual_d / Σ mu_d)`` over the nodes with a finite ``mu`` that day (0 on a day
    where either total is not positive); ``sigma_f = std(g)`` over the kept days and ``phi_f`` its
    lag-1 autocorrelation over pairs of consecutive kept days, clipped to ``PHI_RANGE``. With
    fewer than ``MIN_FACTOR_DAYS`` kept days the factor cannot be told from noise, so it returns
    ``g = 0, sigma_f = 0, phi_f = 0`` and the nodes carry the whole dispersion.
    """
    known = np.isfinite(mu)
    total_actual = np.where(known, actual, 0.0).sum(axis=1)
    total_mu = np.where(known, mu, 0.0).sum(axis=1)
    keep = (total_actual > 0) & (total_mu > 0)
    g = np.zeros(len(keep))
    if keep.sum() < MIN_FACTOR_DAYS:
        return g, 0.0, 0.0
    g[keep] = np.log(total_actual[keep] / total_mu[keep])
    pairs = keep[1:] & keep[:-1]
    prev, curr = g[:-1][pairs], g[1:][pairs]
    phi = np.corrcoef(prev, curr)[0, 1] if len(prev) > 2 and prev.std() > 0 and curr.std() > 0 else 0.0
    return g, float(np.std(g[keep])), float(np.clip(phi, *PHI_RANGE))


def node_cv(r: np.ndarray, r_hat: np.ndarray, g: np.ndarray, products: list[str]) -> np.ndarray:
    """Per node ``std(r - r_hat·exp(g)) / mean(r_hat)`` over the holdout days with a finite ``r``
    (``[n_days, n_nodes]``; ``g`` is ``[n_days]``, zeros for the raw error), clipped to
    ``CV_RANGE``. A node with under ``MIN_HOLDOUT_POINTS`` finite days takes the median cv of the
    other nodes of its product (else of all nodes, else the upper clip)."""
    finite = np.isfinite(r)
    ok = finite.sum(axis=0) >= MIN_HOLDOUT_POINTS
    err = np.where(finite, r - r_hat * np.exp(g)[:, None], np.nan)[:, ok]
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = np.nanstd(err, axis=0) / np.nanmean(np.where(finite, r_hat, np.nan)[:, ok], axis=0)
    cv = pd.Series(np.nan, index=range(r.shape[1]))
    cv[ok] = np.clip(np.nan_to_num(raw, nan=CV_RANGE[1]), *CV_RANGE)
    by_product = cv.groupby(pd.Series(products, index=cv.index)).transform("median")
    return cv.fillna(by_product).fillna(cv.median()).fillna(CV_RANGE[1]).to_numpy()


class SegmentLGBM:
    """One global ``LGBMRegressor(**TWEEDIE_PARAMS)`` on the ratio ``r = residual / baseline`` of
    every node with a positive ``outflow_residual`` (``split_residual``), ``baseline`` per
    ``node_baseline``. Features: calendar, the node's own segment ``n_active_ratio`` and
    ``n_new_ratio``, its product's ``campaign_lift``, ``segment`` and ``product`` as categoricals,
    and lags 7/14 of ``r``. Point per node: ``mu = r_hat × baseline``.

    Noise, estimated in ``fit`` on an internal holdout (the last ``HOLDOUT_DAYS`` of history):
    the model is first fit on the days before it and predicts the holdout days (features lag
    the target by ≥ 7 days, as in ``predict``). Per node ``cv = std(error) / mean(r_hat)``
    clipped to ``CV_RANGE`` (``node_cv``); a node with under ``MIN_HOLDOUT_POINTS`` finite
    holdout ratios takes its product's median cv. On the holdout daily totals over all nodes ``g_d = log(Σ actual_d /
    Σ mu_d)``; ``sigma_f = std(g_d)`` and ``phi_f`` = lag-1 autocorrelation of ``g_d`` clipped to
    ``PHI_RANGE`` (``common_factor``). The node error then has the common shock removed,
    ``r - r_hat · exp(g_d)``, so it is not counted twice (once in ``cv``, once in ``f``).
    ``use_factor=False`` sets ``sigma_f = 0`` and keeps the raw ``r - r_hat``, so the nodes carry
    the full dispersion. The model is then refit on all history.

    ``predict`` simulates ``n_paths`` node paths (``montecarlo.simulate_paths``), sums them to
    partners, adds each partner's ``confirmed_<partner>`` from the drivers once per path (the
    target excludes it), stores ``last_paths`` ``[n_paths, n_dates, n_partners]``,
    ``partner_index`` (partner of each path column) and ``last_dates``, and returns the paths'
    quantiles at ``QUANTILES``.
    """

    def __init__(
        self, name: str | None = None, n_paths: int = 2000, use_factor: bool = True, seed: int = 0,
        payday_hypothesis: str = "late",
    ) -> None:
        self.name = name or ("segment_factor" if use_factor else "segment_nofactor")
        self.n_paths = n_paths
        self.use_factor = use_factor
        self.seed = seed
        self.payday_hypothesis = payday_hypothesis
        self._cal = Calendar.from_yaml(CONFIG / "calendar_ar.yaml")
        self._model: LGBMRegressor | None = None
        self.sigma_f = 0.0
        self.phi_f = 0.0
        self.last_paths: np.ndarray | None = None
        self.last_dates: pd.DatetimeIndex | None = None
        self.partner_index: list[str] = []

    def _design(self, dates: pd.DatetimeIndex, drivers: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
        """Node-major long design matrix for ``dates`` and the baseline ``[n_dates, n_nodes]``."""
        shared = driver_features(dates, drivers, self._cal, self.payday_hypothesis)
        calendar = shared[[c for c in shared if not c.startswith(_OWN_DRIVERS)]]
        frames, bases = [], []
        for j, (segment, product, _) in enumerate(self._nodes):
            X = calendar.assign(
                n_active_ratio=shared[f"n_active_ratio_{segment}"],
                n_new_ratio=shared[f"n_new_ratio_{segment}"],
                campaign_lift=shared[f"campaign_lift_{product}"],
                segment=pd.Categorical([segment] * len(dates), categories=self._segments),
                product=pd.Categorical([product] * len(dates), categories=self._products),
                **{f"lag_{k}": seasonal_lag(self._ratio[j], dates, k) for k in LAGS},
            )
            frames.append(X)
            bases.append(node_baseline(self._target[j], dates))
        return pd.concat(frames, ignore_index=True), np.column_stack(bases)

    def _fit_rows(self, X: pd.DataFrame, y: np.ndarray, rows: np.ndarray) -> LGBMRegressor:
        lags = X[[f"lag_{k}" for k in LAGS]].to_numpy()
        rows = rows & np.isfinite(y) & np.isfinite(lags).all(axis=1)
        return LGBMRegressor(**TWEEDIE_PARAMS).fit(X[rows], y[rows])

    def _estimate_noise(self, X: pd.DataFrame, y: np.ndarray, base: np.ndarray, hold: np.ndarray) -> None:
        """Set ``_cv``, ``sigma_f`` and ``phi_f`` from a fit on the days before the ``hold`` mask."""
        n_dates, n_nodes = base.shape
        r_hat = self._fit_rows(X, y, ~np.tile(hold, n_nodes)).predict(X).reshape(n_nodes, n_dates).T
        r = y.reshape(n_nodes, n_dates).T
        r_hat, r, base = r_hat[hold], r[hold], base[hold]
        g, sigma_f, self.phi_f = common_factor(self._target.to_numpy()[hold], r_hat * base)
        self.sigma_f = sigma_f if self.use_factor else 0.0
        products = [product for _, product, _ in self._nodes]
        self._cv = node_cv(r, r_hat, g if self.use_factor else np.zeros_like(g), products)

    def fit(self, history: pd.DataFrame, drivers: pd.DataFrame | None) -> None:
        if drivers is None:
            raise ValueError(f"{self.name} needs drivers")
        hist = split_residual(history)
        wide = hist.groupby(["date", *NODE])["outflow_residual"].sum().unstack(NODE)
        days = pd.date_range(wide.index.min(), wide.index.max(), freq="D", name="date")
        if len(days) < HOLDOUT_DAYS + MIN_TRAIN_DAYS:
            raise ValueError(f"need at least {HOLDOUT_DAYS + MIN_TRAIN_DAYS} days of history, got {len(days)}")
        wide = wide.reindex(days).fillna(0.0)
        self.partner_index = sorted(hist["partner"].unique())
        active = wide.loc[:, wide.sum() > 0]
        self._nodes = list(active.columns)
        self._segments = sorted({s for s, _, _ in self._nodes})
        self._products = sorted({p for _, p, _ in self._nodes})
        self._node_partner = np.array([self.partner_index.index(p) for _, _, p in self._nodes])
        self._target = pd.DataFrame(active.to_numpy(), index=days)
        self._ratio = pd.DataFrame(
            {j: node_ratio(self._target[j].to_numpy(), node_baseline(self._target[j], days)) for j in self._target},
            index=days,
        )
        X, base = self._design(days, drivers)
        y = self._ratio.to_numpy().T.reshape(-1)
        self._estimate_noise(X, y, base, np.asarray(days > days[-1] - pd.Timedelta(days=HOLDOUT_DAYS)))
        self._model = self._fit_rows(X, y, np.ones(len(y), dtype=bool))

    def predict(self, dates: pd.DatetimeIndex, drivers: pd.DataFrame | None) -> pd.DataFrame:
        if self._model is None:
            raise RuntimeError("fit before predict")
        if drivers is None:
            raise ValueError(f"{self.name} needs drivers")
        dates = pd.DatetimeIndex(dates)
        X, base = self._design(dates, drivers)
        r_hat = self._model.predict(X).reshape(len(self._nodes), len(dates)).T
        mu = np.nan_to_num(r_hat * base)
        paths = simulate_paths(
            mu, self._cv, self._node_partner, len(self.partner_index), self.sigma_f, self.phi_f, self.n_paths,
            self.seed,
        )
        confirmed = drivers.set_index("date").reindex(dates)
        paths += confirmed[[f"confirmed_{p}" for p in self.partner_index]].to_numpy()[None]
        self.last_paths, self.last_dates = paths, dates
        q = np.quantile(paths, list(QUANTILES), axis=0)  # [n_q, n_dates, n_partners]
        frame = pd.DataFrame(
            {"date": np.repeat(dates, len(self.partner_index)), "partner": np.tile(self.partner_index, len(dates))}
        )
        frame[list(QCOLS)] = q.reshape(len(QUANTILES), -1).T
        return enforce_quantiles(frame)[["date", "partner", *QCOLS]]
