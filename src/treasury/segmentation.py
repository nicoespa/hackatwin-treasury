"""Behavioral segments inferred from transactions, for a wallet that has no archetype labels.

``segment_users`` builds per-user features from the events before an origin (``user_features``),
marks users with too little history as ``NEW``, and clusters the rest with k-means
(``kmeans_segments``). ``KMeansSegmenter`` wraps it as the segmenter ``backtest.walk_forward``
calls at each origin. Nothing here reads ``users["segment"]`` or ``events["segment"]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from treasury.calendar import Calendar

CONFIG = Path(__file__).resolve().parents[2] / "config"
NEW = "new"
WINDOW_DAYS = 90
MIN_TENURE_DAYS = 30
MIN_EVENTS = 5
PAYDAY_BUSINESS_DAYS = 4  # business days 1..4 of the month, as in ``features.calendar_features``
K_RANGE = range(2, 9)
SILHOUETTE_SAMPLE = 4000
MONTH_DAYS = 30
# Columns of ``user_features`` that describe a user but are not clustered on: tenure and volume
# would split users by signup cohort, and ``out_*`` repeats ``rate_*`` × ``amt_*`` for profiles.
NOT_CLUSTERED = ("tenure_days", "n_events")
PROFILE_PREFIX = "out_"
LOG_COLUMNS = ("rate_", "outflow_monthly")


def user_features(
    users: pd.DataFrame, events: pd.DataFrame, as_of, window_days: int = WINDOW_DAYS, cal: Calendar | None = None,
) -> pd.DataFrame:
    """One row per user of ``users`` (index ``user_id``), from the events with
    ``as_of - window_days <= at < as_of`` only, so nothing at or after ``as_of`` enters.

    Rates are per 30 days of the user's observed window, ``min(window_days, tenure_days)``
    (at least 1 day); ``tenure_days`` counts from ``activation_date`` to ``as_of`` and is <= 0 for
    users activated at or after it. Columns:

    - ``rate_<product>``: events of the product per 30 days, every product in the window.
    - ``amt_<product>``: ``log1p`` of the mean amount of the user's outflows of the product (0 if none).
    - ``out_<product>``: outflow amount of the product per 30 days (for profiles, not clustered).
    - ``outflow_monthly``: total outflow amount per 30 days.
    - ``payday_share``: share of outflow amount on business days 1..``PAYDAY_BUSINESS_DAYS``.
    - ``weekend_share``: share of events on Saturday or Sunday.
    - ``active_day_share``: days with an event over the observed days.
    - ``inflow_share``: inflow amount over inflow plus outflow amount.
    - ``tenure_days``, ``n_events`` (events in the window).

    Shares are 0 for a user without the events they divide by.
    """
    as_of = pd.Timestamp(as_of)
    cal = cal or Calendar.from_yaml(CONFIG / "calendar_ar.yaml")
    at = events["at"]
    rows = ((at >= as_of - pd.Timedelta(days=window_days)) & (at < as_of)).to_numpy()
    ev = pd.DataFrame({
        "user_id": events["user_id"].to_numpy()[rows],
        "product": events["product"].to_numpy()[rows],
        "day": at.to_numpy()[rows].astype("datetime64[D]"),
        "amount": events["amount"].to_numpy(float)[rows],
        "out": events["direction"].to_numpy()[rows] == 1,
    })
    ids = pd.Index(users["user_id"], name="user_id")
    tenure = (as_of - users["activation_date"].dt.normalize()).dt.days.to_numpy()
    observed = pd.Series(np.clip(np.minimum(tenure, window_days), 1, None), index=ids).astype(float)

    days = pd.DatetimeIndex(np.unique(ev["day"]))
    bd = pd.Series([cal.nth_business_day_of_month(d.date()) for d in days], index=days)
    ev["payday"] = ev["day"].map(bd).between(1, PAYDAY_BUSINESS_DAYS).to_numpy()
    ev["weekend"] = pd.DatetimeIndex(ev["day"]).day_of_week.to_numpy() >= 5
    ev["outflow"] = np.where(ev["out"], ev["amount"], 0.0)
    ev["inflow"] = np.where(ev["out"], 0.0, ev["amount"])
    by_user = ev.groupby("user_id")

    def per_user(values: pd.Series) -> pd.Series:
        return values.reindex(ids, fill_value=0).astype(float)

    def share(num: pd.Series, den: pd.Series) -> pd.Series:
        return (num / den).where(den > 0, 0.0)

    per_month = MONTH_DAYS / observed
    counts = ev.groupby(["user_id", "product"]).size().unstack(fill_value=0).reindex(ids, fill_value=0)
    outs = ev[ev["out"]].groupby(["user_id", "product"])["amount"].agg(["sum", "mean"])
    out_sum = outs["sum"].unstack(fill_value=0.0).reindex(ids, fill_value=0.0)
    out_mean = outs["mean"].unstack(fill_value=0.0).reindex(ids, fill_value=0.0)
    outflow, inflow = per_user(by_user["outflow"].sum()), per_user(by_user["inflow"].sum())
    n_events = per_user(by_user.size())
    payday_amount = per_user(ev[ev["payday"]].groupby("user_id")["outflow"].sum())
    return pd.concat(
        [
            counts.mul(per_month, axis=0).add_prefix("rate_"),
            np.log1p(out_mean).add_prefix("amt_"),
            out_sum.mul(per_month, axis=0).add_prefix(PROFILE_PREFIX),
            pd.DataFrame({
                "outflow_monthly": outflow * per_month,
                "payday_share": share(payday_amount, outflow),
                "weekend_share": share(per_user(by_user["weekend"].sum()), n_events),
                "active_day_share": (per_user(by_user["day"].nunique()) / observed).clip(upper=1.0),
                "inflow_share": share(inflow, inflow + outflow),
                "tenure_days": pd.Series(tenure, index=ids),
                "n_events": n_events,
            }),
        ],
        axis=1,
    ).sort_index(axis=1)


def design_matrix(features: pd.DataFrame) -> np.ndarray:
    """Standardized clustering inputs: every column except ``NOT_CLUSTERED`` and ``out_*``, with
    ``log1p`` on the heavy-tailed ``rate_*`` and ``outflow_monthly``."""
    cols = [c for c in features if c not in NOT_CLUSTERED and not c.startswith(PROFILE_PREFIX)]
    X = features[cols].astype(float)
    logged = [c for c in cols if c.startswith(LOG_COLUMNS)]
    X[logged] = np.log1p(X[logged].clip(lower=0.0))
    return StandardScaler().fit_transform(X.to_numpy())


def kmeans_segments(
    features: pd.DataFrame, k: int | None = None, seed: int = 0, k_range: range = K_RANGE,
    sample: int = SILHOUETTE_SAMPLE,
) -> tuple[pd.Series, dict]:
    """K-means on ``design_matrix(features)``: labels ``"k0".."k{k-1}"`` (index of ``features``)
    ordered by the cluster's mean ``outflow_monthly`` (else its first column's mean), lowest first,
    so the same clusters get the same names whatever k-means' internal order.

    With ``k=None`` every k of ``k_range`` (capped below the number of rows) is fitted and the one
    with the highest silhouette, on a ``sample`` of rows drawn with ``seed``, is kept. Returns the
    labels and ``{"k", "silhouette", "silhouette_by_k"}``.
    """
    X = design_matrix(features)
    candidates = [k] if k is not None else [c for c in k_range if c < len(X)]
    n_sample = min(sample, len(X))
    fits, scores = {}, {}
    for c in candidates:
        fits[c] = KMeans(n_clusters=c, n_init=4, random_state=seed).fit(X)
        scores[c] = float(silhouette_score(X, fits[c].labels_, sample_size=n_sample, random_state=seed))
    best = max(scores, key=scores.get)
    raw = fits[best].labels_
    order_by = features["outflow_monthly"] if "outflow_monthly" in features else features.iloc[:, 0]
    means = pd.Series(order_by.to_numpy(float)).groupby(raw).mean()
    rank = {cluster: i for i, cluster in enumerate(means.sort_values(kind="stable").index)}
    labels = pd.Series([f"k{rank[c]}" for c in raw], index=features.index, name="segment")
    return labels, {"k": best, "silhouette": scores[best], "silhouette_by_k": scores}


def segment_profile(features: pd.DataFrame, segments: pd.Series) -> pd.DataFrame:
    """Per segment: ``n_users``, mean ``outflow_monthly``, mean ``out_<product>``, and mean
    ``payday_share``, ``weekend_share``, ``active_day_share`` and ``inflow_share``."""
    cols = ["outflow_monthly", *[c for c in features if c.startswith(PROFILE_PREFIX)],
            "payday_share", "weekend_share", "active_day_share", "inflow_share"]
    grouped = features[cols].groupby(segments.reindex(features.index).rename("segment"))
    return grouped.mean().assign(n_users=grouped.size()).reset_index()[["segment", "n_users", *cols]]


@dataclass(frozen=True)
class Segmentation:
    """Segments of every user at ``as_of``: ``labels`` (user_id → segment), the ``profile`` table,
    the chosen ``k`` and its ``silhouette`` (``silhouette_by_k`` for every k tried)."""

    as_of: pd.Timestamp
    labels: pd.Series
    profile: pd.DataFrame
    k: int
    silhouette: float
    silhouette_by_k: dict[int, float]


def segment_users(
    users: pd.DataFrame, events: pd.DataFrame, as_of, k: int | None = None, seed: int = 0,
    window_days: int = WINDOW_DAYS, min_tenure_days: int = MIN_TENURE_DAYS, min_events: int = MIN_EVENTS,
    cal: Calendar | None = None,
) -> Segmentation:
    """``NEW`` for users with ``tenure_days < min_tenure_days`` (activated at or after ``as_of``
    included) or under ``min_events`` events in the window; the rest by ``kmeans_segments``."""
    features = user_features(users, events, as_of, window_days, cal)
    new = (features["tenure_days"] < min_tenure_days) | (features["n_events"] < min_events)
    clustered, info = kmeans_segments(features[~new], k, seed)
    labels = pd.Series(NEW, index=features.index, name="segment", dtype=object)
    labels[clustered.index] = clustered
    return Segmentation(pd.Timestamp(as_of), labels, segment_profile(features, labels), info["k"],
                        info["silhouette"], info["silhouette_by_k"])


@dataclass(frozen=True)
class KMeansSegmenter:
    """Callable ``(users, events, as_of) -> Segmentation`` with fixed settings; ``k=None`` picks k by
    silhouette at every call. ``name`` identifies the settings in caches."""

    k: int | None = None
    seed: int = 0
    window_days: int = WINDOW_DAYS
    min_tenure_days: int = MIN_TENURE_DAYS
    min_events: int = MIN_EVENTS

    @property
    def name(self) -> str:
        k = "auto" if self.k is None else self.k
        return (f"kmeans(k={k},seed={self.seed},window={self.window_days},"
                f"min_tenure={self.min_tenure_days},min_events={self.min_events})")

    def __call__(self, users: pd.DataFrame, events: pd.DataFrame, as_of) -> Segmentation:
        return segment_users(users, events, as_of, self.k, self.seed, self.window_days, self.min_tenure_days,
                             self.min_events)
