"""Data for the web console (web/console): the model's daily 09:00 decisions for two partners, the
last 14 days and one replayable day minute by minute.

Runs the walk-forward forecast (k-means segments, Tweedie LightGBM, Monte Carlo) and the backtest with
one 24/7 review a day at 09:00 on the stablecoin rail, then writes per partner:

- ``today``: the 09:00 decision on TODAY (deposit, target, balance before and after, arrival), the
  deposit the same review would have made at other coverage levels, users' payments per minute
  (amount and count, by product) and the expected curve, and tomorrow's forecast plus how much it
  moves with today's deviation (the slope of tomorrow on today across the Monte Carlo paths).
- ``history``: the 14 days before and including TODAY: deposit, settled outflow, balance at the close,
  the forecast's median and a short reason.

Run: PYTHONPATH=src uv run python scripts/build_console_data.py
Writes web/console/data.json.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from treasury.backtest import Dataset, _rail_for, run, walk_forward
from treasury.experiments import PROPOSED, factory
from treasury.ledger import Credit
from treasury.policy import recommend_deposit
from treasury.segmentation import KMeansSegmenter

TODAY = pd.Timestamp("2026-10-23")  # a Friday whose forecast windows the data covers (it ends on 31 Oct)
ORIGINS = [date(2026, 10, 3), date(2026, 10, 10), date(2026, 10, 17)]  # weekly refits, 14-day horizon
HORIZON = 14
REVIEW_HOUR = 9
PARTNERS = {  # partner id -> (name on screen, what its users do, product labels)
    "bills_aggregator": ("Partner A", "Pagos de servicios y recargas", {"bill_payment": "servicios", "mobile_topup": "recargas"}),
    "crypto_exchange": ("Partner B", "Compra y venta de cripto", {"crypto_buy": "compras", "crypto_sell": "ventas"}),
}
ALPHAS = (0.95, 0.99, 0.995)
HISTORY_DAYS = 14
OUT = Path("web/console/data.json")
DAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def minute_series(ev: pd.DataFrame, day: pd.Timestamp) -> np.ndarray:
    d = ev[(ev["at"] >= day) & (ev["at"] < day + pd.Timedelta(days=1))]
    idx = ((d["at"] - day) / pd.Timedelta(minutes=1)).astype(int).to_numpy()
    return np.bincount(idx, weights=d["amount"].to_numpy(), minlength=1440)[:1440]


def note_for(day: pd.Timestamp, cal, error: float | None) -> str:
    d = day.date()
    parts = []
    if d in cal.holidays:
        parts.append("Feriado")
    elif day.dayofweek >= 5:
        parts.append("Fin de semana")
    prev = (day - pd.Timedelta(days=1)).date()
    if cal.is_business_day(d) and prev in cal.holidays:
        parts.append("Después de feriado")
    bd = cal.nth_business_day_of_month(d) if cal.is_business_day(d) else 0
    if 1 <= bd <= 4:
        parts.append("Cobro de sueldos")
    if error is not None and abs(error) >= 0.12:
        parts.append("Más pagos de lo esperado" if error > 0 else "Menos pagos de lo esperado")
    return ", ".join(parts) if parts else "Día típico"


def main() -> None:
    dataset = Dataset.load("data/sim/base")
    configs = dataset.configs
    cfg = replace(configs.policy(), review_hours_247=(REVIEW_HOUR,))
    cal, partners, rails = configs.calendar(), configs.partners(), configs.rails()
    forecasts = walk_forward(dataset, factory(PROPOSED, 1000), ORIGINS, horizon=HORIZON, n_paths=1000, segmenter=KMeansSegmenter())
    res = run(dataset, factory(PROPOSED, 1000), "forecast", "stablecoin", cfg, ORIGINS, n_paths=1000, horizon=HORIZON, segmenter=KMeansSegmenter())
    events = dataset.events if hasattr(dataset, "events") else pd.read_parquet("data/sim/base/events.parquet")
    out = {"today": TODAY.strftime("%Y-%m-%d"), "weekday": DAYS_ES[TODAY.dayofweek], "review_hour": REVIEW_HOUR,
           "alpha": cfg.alpha, "partners": []}

    for pid, (name, label, products) in PARTNERS.items():
        partner, rail = partners[pid], _rail_for(partners[pid], rails, "stablecoin")
        dec = res.decisions[res.decisions["partner"] == pid].copy()
        dec["day"] = pd.to_datetime(dec["at"]).dt.normalize()
        log = res.ledger_log[res.ledger_log["partner"] == pid]
        ev = events[(events["partner"] == pid) & (events["direction"] == 1)].copy()
        ev["at"] = pd.to_datetime(ev["at"])
        settled = ev.assign(day=pd.to_datetime(ev["settle_at"]).dt.normalize()).groupby("day")["amount"].sum()
        by_event_day = ev.assign(day=ev["at"].dt.normalize()).groupby("day")["amount"].sum()
        # payments known ahead (scheduled bills) are added to the model's forecast, which covers the rest
        confirmed = ev[ev["confirmed"]].assign(day=pd.to_datetime(ev["settle_at"]).dt.normalize()).groupby("day")["amount"].sum()

        def fc_for(t: pd.Timestamp):
            return next(f for f in reversed(forecasts) if f.origin <= t)

        def median_for(day: pd.Timestamp) -> float | None:
            fc = fc_for(day)
            if day not in fc.dates:
                return None
            return float(np.median(fc.paths[:, fc.dates.get_loc(day), fc.partners.index(pid)])) + float(confirmed.get(day, 0.0))

        # last 14 days
        history = []
        for day in pd.date_range(TODAY - pd.Timedelta(days=HISTORY_DAYS - 1), TODAY, freq="D"):
            row = dec[dec["day"] == day]
            deposit = float(row["amount"].iloc[0]) if len(row) else 0.0
            close = log[log["at"] < (day + pd.Timedelta(days=1)).to_datetime64()]["balance"]
            during = log[(log["at"] >= day.to_datetime64()) & (log["at"] < (day + pd.Timedelta(days=1)).to_datetime64())]["balance"]
            actual = float(settled.get(day, 0.0))
            med = median_for(day)
            err = (actual / med - 1) if med and med > 0 and day < TODAY else None
            history.append({"date": day.strftime("%Y-%m-%d"), "deposit": deposit, "outflow": actual,
                            "close": float(close.iloc[-1]) if len(close) else None, "forecast": med,
                            "error": err, "note": note_for(day, cal, err), "short": bool(len(during) and during.min() < 0)})

        # today at 09:00
        t = TODAY + pd.Timedelta(hours=REVIEW_HOUR)
        r = dec[dec["at"] == t].iloc[0]
        fc = fc_for(t)
        j = fc.partners.index(pid)
        today_before = float(ev[(ev["at"] >= TODAY) & (ev["at"] < t)]["amount"].sum())
        alt = {}
        for a in ALPHAS:
            d = recommend_deposit(fc.paths[:, :, j], fc.dates, partner, rail, float(r["available"]),
                                  [Credit(pd.Timestamp(r["arrival_at"]), float(r["pending"]))] if r["pending"] > 0 else [],
                                  t, configs.rail_calendar(partner), replace(cfg, alpha=a), realized_today=today_before,
                                  inflow_forecast=fc.inflow[:, j])
            alt[str(a)] = {"deposit": d.amount, "target": d.target}

        # payments per minute, and the expected curve: the model's median for today in event time,
        # spread with the intraday profile of the 8 previous same weekdays
        same = [TODAY - pd.Timedelta(days=7 * k) for k in range(1, 9)]
        profile = np.zeros(96)
        for d in same:
            m = minute_series(ev, d).reshape(96, 15).sum(axis=1)
            profile += m / max(m.sum(), 1.0)
        profile /= profile.sum()
        ratio = np.mean([by_event_day.get(d, 0.0) / max(settled.get(d, 0.0), 1.0) for d in same[:4]])
        med_today = median_for(TODAY) or 0.0
        expected_day = med_today * ratio
        expected = np.repeat(profile * expected_day / 15.0, 15)
        actual_min = minute_series(ev, TODAY)
        counts = np.bincount(((ev[(ev["at"] >= TODAY) & (ev["at"] < TODAY + pd.Timedelta(days=1))]["at"] - TODAY)
                              / pd.Timedelta(minutes=1)).astype(int).to_numpy(), minlength=1440)[:1440]
        by_product = {lab: minute_series(ev[ev["product"] == p], TODAY).round(0).tolist() for p, lab in products.items()}
        prod_share = {}
        for p, lab in products.items():
            tot = sum(minute_series(ev[ev["product"] == p], d).sum() for d in same)
            prod_share[lab] = float(tot)
        s = sum(prod_share.values()) or 1.0
        prod_share = {k: v / s for k, v in prod_share.items()}
        # active users per hour today vs the same weekdays
        def users_by_hour(d: pd.Timestamp) -> np.ndarray:
            x = ev[(ev["at"] >= d) & (ev["at"] < d + pd.Timedelta(days=1))]
            return x.groupby(x["at"].dt.hour)["user_id"].nunique().reindex(range(24), fill_value=0).to_numpy()
        users_today = users_by_hour(TODAY)
        users_typical = np.mean([users_by_hour(d) for d in same[:4]], axis=0)

        # tomorrow: median, a bad day, and how it moves with today's deviation (slope across paths)
        tomorrow = TODAY + pd.Timedelta(days=1)
        k0, k1 = fc.dates.get_loc(TODAY), fc.dates.get_loc(tomorrow)
        x0, x1 = np.log(np.maximum(fc.paths[:, k0, j], 1.0)), np.log(np.maximum(fc.paths[:, k1, j], 1.0))
        slope = float(np.cov(x0, x1)[0, 1] / np.var(x0)) if np.var(x0) > 0 else 0.0

        out["partners"].append({
            "id": pid, "name": name, "label": label, "rail": r["rail_used"],
            "today": {
                "deposit": float(r["amount"]), "target": float(r["target"]), "available": float(r["available"]),
                "pending": float(r["pending"]), "arrival": pd.Timestamp(r["arrival_at"]).isoformat() if r["amount"] > 0 else None,
                "window_end": pd.Timestamp(r["window_end"]).isoformat() if pd.notna(r["window_end"]) else None,
                "alt": alt, "median_today": med_today, "expected_day": expected_day,
                "minutes": {"amount": actual_min.round(0).tolist(), "count": counts.tolist(), "expected": expected.round(1).tolist()},
                "products": by_product, "product_share": prod_share,
                "users": {"today": users_today.tolist(), "typical": users_typical.round(1).tolist()},
                "tomorrow": {"median": median_for(tomorrow), "bad": float(np.quantile(fc.paths[:, k1, j], cfg.alpha)) + float(confirmed.get(tomorrow, 0.0)),
                             "slope": slope},
            },
            "history": history,
            "kpis": {
                "deposits": float(sum(h["deposit"] for h in history)),
                "short_days": int(sum(h["short"] for h in history)),
                "avg_close": float(np.mean([h["close"] for h in history if h["close"] is not None])),
                "mape": float(np.mean([abs(h["error"]) for h in history if h["error"] is not None])),
            },
        })
        print(name, pid, "deposit", round(r["amount"] / 1e6, 1), "M; mape", round(out["partners"][-1]["kpis"]["mape"] * 100, 1), "%")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print("wrote", OUT, OUT.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
