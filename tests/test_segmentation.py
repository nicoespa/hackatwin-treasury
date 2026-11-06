from datetime import date

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import adjusted_rand_score

from treasury.backtest import forecast_key, segmented_inputs, walk_forward
from treasury.harness import default_origins
from treasury.models.segment_lgbm import SegmentLGBM
from treasury.segmentation import (
    NEW,
    KMeansSegmenter,
    kmeans_segments,
    segment_users,
    user_features,
)

AS_OF = pd.Timestamp("2026-09-06")


@pytest.fixture(scope="module")
def sample(sim) -> tuple[pd.DataFrame, pd.DataFrame]:
    """2000 users of the base data and their events from 120 days before ``AS_OF`` to 30 after."""
    users, events = sim
    users = users[users["user_id"] < 2000].reset_index(drop=True)
    keep = events["user_id"].lt(2000) & events["at"].between(AS_OF - pd.Timedelta(days=120), AS_OF + pd.Timedelta(days=30))
    return users, events[keep].reset_index(drop=True)


def test_features_ignore_events_at_or_after_as_of(sample):
    users, events = sample
    base = user_features(users, events, AS_OF)
    late = events["at"] >= AS_OF
    changed = events.assign(amount=np.where(late, events["amount"] * 50, events["amount"]),
                            product=np.where(late, "card_purchase", events["product"]))
    pd.testing.assert_frame_equal(user_features(users, changed, AS_OF), base)
    pd.testing.assert_frame_equal(user_features(users, events[~late], AS_OF), base)


def test_features_never_read_segment_labels(sample):
    users, events = sample
    base = user_features(users, events, AS_OF)
    shuffled = users.assign(segment="x"), events.assign(segment="y")
    pd.testing.assert_frame_equal(user_features(*shuffled, AS_OF), base)


def test_new_and_future_users_get_new(sample):
    users, events = sample
    users = users.copy()
    users.loc[0, "activation_date"] = AS_OF + pd.Timedelta(days=10)  # activates after as_of
    users.loc[1, "activation_date"] = AS_OF - pd.Timedelta(days=5)  # 5 days of tenure
    seg = segment_users(users, events, AS_OF, k=3)
    assert seg.labels.loc[users.loc[0, "user_id"]] == NEW and seg.labels.loc[users.loc[1, "user_id"]] == NEW
    features = user_features(users, events, AS_OF)
    expected_new = (features["tenure_days"] < 30) | (features["n_events"] < 5)
    assert ((seg.labels == NEW) == expected_new).all()
    assert set(seg.labels) == {NEW, "k0", "k1", "k2"}
    assert seg.profile["n_users"].sum() == len(users)


def test_segmentation_is_deterministic_with_a_seed(sample):
    users, events = sample
    a, b = segment_users(users, events, AS_OF, seed=3), segment_users(users, events, AS_OF, seed=3)
    pd.testing.assert_series_equal(a.labels, b.labels)
    assert a.k == b.k and a.silhouette == b.silhouette and 2 <= a.k <= 8


def test_kmeans_recovers_separated_groups():
    rng = np.random.default_rng(0)
    centers = np.array([[0.0, 0.0, 0.0], [8.0, 0.0, 2.0], [0.0, 8.0, -2.0], [8.0, 8.0, 5.0]])
    truth = np.repeat(np.arange(4), 150)
    points = centers[truth] + rng.normal(scale=0.5, size=(len(truth), 3))
    features = pd.DataFrame(points, columns=["a", "b", "c"]).assign(outflow_monthly=truth * 100.0 + 1)
    labels, info = kmeans_segments(features, seed=0)
    assert info["k"] == 4 and info["silhouette"] > 0.5
    assert adjusted_rand_score(truth, labels) == 1.0
    assert (labels.to_numpy() == np.array([f"k{t}" for t in truth])).all()  # named by mean outflow_monthly


@pytest.mark.slow
def test_walk_forward_with_segmenter(dataset):
    origins = default_origins(date(2026, 10, 31), n=2, step_days=7, horizon=14)
    segmenter = KMeansSegmenter(k=4)
    factory = lambda: SegmentLGBM(n_paths=100)
    kmeans = walk_forward(dataset, factory, origins, n_paths=100, segmenter=segmenter)
    oracle = walk_forward(dataset, factory, origins, n_paths=100)
    assert forecast_key(factory, origins, 14, 100, 0, segmenter) != forecast_key(factory, origins, 14, 100, 0)
    assert forecast_key(factory, origins, 14, 100, 0, segmenter) in dataset.cache
    assert forecast_key(factory, origins, 14, 100, 0) in dataset.cache
    for fk, fo in zip(kmeans, oracle):
        assert fk.paths.shape == fo.paths.shape and fk.partners == fo.partners
        assert np.isfinite(fk.paths).all() and not np.array_equal(fk.paths, fo.paths)
    history, drivers, seg = segmented_inputs(dataset, segmenter, origins[-1])
    assert set(history["segment"]) <= {NEW, "k0", "k1", "k2", "k3"} and history["date"].max() < pd.Timestamp(origins[-1])
    assert {"n_active_k0", "n_active_new"} <= set(drivers) and len(drivers) == len(dataset.drivers)
    new_outflow = history[history["segment"] == NEW].groupby("date")["outflow"].sum()
    assert (new_outflow[new_outflow.index < pd.Timestamp("2026-06-01")] > 0).mean() > 0.9  # every cohort's first month
    # relabeling moves flows between nodes, never changes partner totals
    oracle_totals = dataset.history[dataset.history["date"] < pd.Timestamp(origins[-1])].groupby("partner")["outflow"].sum()
    pd.testing.assert_series_equal(history.groupby("partner")["outflow"].sum(), oracle_totals)
    # every user is counted once: the cohort drivers sum to the oracle's at every date
    active = lambda d: d[[c for c in d if c.startswith("n_active_")]].sum(axis=1).to_numpy()
    assert (active(drivers) == active(dataset.drivers)).all()
