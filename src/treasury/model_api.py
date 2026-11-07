"""The model, live: an HTTP service that runs one partner's 09:00 decision from scratch and streams each step.

``GET /api/run?partner=bills_aggregator&date=2026-10-23&available=95276826&alpha=0.99`` answers a
Server-Sent Events stream. Each ``step`` event is one stage of the real pipeline on the data before
``date``: read the payments, segment the users with k-means, fit the Tweedie LightGBM per node,
simulate the Monte Carlo paths, and size the deposit with ``recommend_deposit`` for the balance the
partner holds at 09:00 (``available``, sent by the console). The last event, ``done``, carries the
decision. Nothing is cached between runs except the loaded dataset, so every click refits the model.

``GET /api/health`` reports whether the dataset is loaded. Runs are serialized (one at a time).
Run: ``treasury model-api --port 8790``; ``ALLOWED_ORIGINS`` (comma-separated) widens CORS beyond the
deployed console and localhost.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import replace
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

from treasury.backtest import Dataset, _rail_for, segmented_inputs
from treasury.experiments import PROPOSED, factory
from treasury.features import known_at
from treasury.models.base import daily_partner_table
from treasury.models.seasonal_naive import seasonal_mean
from treasury.monitor import DATA
from treasury.policy import recommend_deposit
from treasury.segmentation import KMeansSegmenter

REVIEW_HOUR = 9
HORIZON = 3  # today, tomorrow and the day after: enough for the window to the next 09:30 load
N_PATHS = 1000
PARTNERS = ("bills_aggregator", "crypto_exchange")
ORIGINS = ["https://prefoundly.vercel.app"] + [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]


class Engine:
    def __init__(self, data=DATA) -> None:
        self.dataset = Dataset.load(data)
        self.lock = threading.Lock()
        configs = self.dataset.configs
        self.cfg = replace(configs.policy(), review_hours_247=(REVIEW_HOUR,))
        self.partners, self.rails = configs.partners(), configs.rails()
        ev = self.dataset.events
        self.events = ev[ev["direction"] == 1]
        self.last_day = pd.Timestamp(self.dataset.drivers["date"].max()).normalize()

    def run(self, partner: str, day: pd.Timestamp, available: float, alpha: float):
        """Yield ``(kind, payload)``: one ``step`` per stage of the pipeline, then ``done``."""
        ds, t0 = self.dataset, time.perf_counter()
        ds.cache.clear()  # every run segments and fits from scratch
        at = day + pd.Timedelta(hours=REVIEW_HOUR)
        ev = self.events[self.events["partner"] == partner]
        before = ev[pd.to_datetime(ev["at"]) < day]
        yield "step", {"key": "read", "title": "Leyó los pagos hasta ayer",
                       "detail": f"{len(before):,} pagos de {before['user_id'].nunique():,} usuarios".replace(",", ".")}

        history, drivers, seg = segmented_inputs(ds, KMeansSegmenter(), day.date())
        yield "step", {"key": "segment", "title": "Agrupó a los usuarios según su comportamiento",
                       "detail": f"{seg.k} grupos con k-means, más los usuarios nuevos"}

        model = factory(PROPOSED, N_PATHS)()
        model.fit(history[history["date"] < day], drivers[drivers["date"] < day])
        yield "step", {"key": "fit", "title": "Entrenó el pronóstico",
                       "detail": f"LightGBM por grupo, producto y partner ({len(model._nodes)} combinaciones)"}

        dates = pd.date_range(day, periods=HORIZON, freq="D")
        model.predict(dates, known_at(drivers[drivers["date"] <= dates[-1]], day))
        paths, partners = model.last_paths, list(model.partner_index)
        j = partners.index(partner)
        yield "step", {"key": "simulate", "title": f"Simuló {N_PATHS:,} escenarios".replace(",", "."),
                       "detail": "Monte Carlo con un factor común entre grupos"}

        inflow = daily_partner_table(history[history["date"] < day]).pivot(index="date", columns="partner", values="inflow")
        inflow = np.nan_to_num(seasonal_mean(inflow[partner], dates)) if partner in inflow else np.zeros(len(dates))
        p, rail = self.partners[partner], _rail_for(self.partners[partner], self.rails, "stablecoin")
        today = ev[(pd.to_datetime(ev["at"]) >= day) & (pd.to_datetime(ev["at"]) < at)]["amount"].sum()
        cal = ds.configs.rail_calendar(p)
        decide = lambda a: recommend_deposit(paths[:, :, j], dates, p, rail, available, [], at, cal,  # noqa: E731
                                             replace(self.cfg, alpha=a), realized_today=float(today), inflow_forecast=inflow)
        d, expected = decide(alpha), decide(0.5)
        yield "step", {"key": "decide", "title": "Calculó cuánto mandar",
                       "detail": f"necesita {_m(d.target)} con margen; hay {_m(available)}"}
        yield "done", {"partner": partner, "date": day.strftime("%Y-%m-%d"), "alpha": alpha, "deposit": d.amount,
                       "target": d.target, "expected": expected.target, "available": available,
                       "arrival": pd.Timestamp(d.arrival_at).isoformat() if d.arrival_at is not None else None,
                       "window_end": pd.Timestamp(d.window_end).isoformat() if d.window_end is not None else None,
                       "groups": seg.k, "seconds": round(time.perf_counter() - t0, 1)}


def _m(x: float) -> str:
    return "$ " + f"{x / 1e6:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".") + " M"


def serve(port: int = 8790, data=DATA) -> ThreadingHTTPServer:
    engine = Engine(data)

    class Handler(BaseHTTPRequestHandler):
        def _cors(self) -> None:
            origin = self.headers.get("Origin") or ""
            local = origin.startswith(("http://localhost", "http://127.0.0.1"))
            if origin in ORIGINS or local:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _json(self, status: int, body: dict) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            url = urlparse(self.path)
            if url.path == "/api/health":
                return self._json(200, {"ok": True, "last_day": engine.last_day.strftime("%Y-%m-%d")})
            if url.path != "/api/run":
                return self._json(404, {"error": "not found"})
            q = parse_qs(url.query)
            try:
                partner = q.get("partner", ["bills_aggregator"])[0]
                day = pd.Timestamp(date.fromisoformat(q.get("date", [""])[0]))
                available = float(q.get("available", ["0"])[0])
                alpha = float(q.get("alpha", ["0.99"])[0])
            except ValueError:
                return self._json(400, {"error": "partner, date (YYYY-MM-DD), available and alpha"})
            if partner not in PARTNERS or not 0.5 <= alpha < 1 or not 0 <= available < 1e13:
                return self._json(400, {"error": "unknown partner or value out of range"})
            if day + pd.Timedelta(days=HORIZON - 1) > engine.last_day:
                return self._json(400, {"error": f"the data covers up to {engine.last_day.date()}"})
            if not engine.lock.acquire(blocking=False):
                return self._json(429, {"error": "a run is in progress"})
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self._cors()
                self.end_headers()
                for kind, payload in engine.run(partner, day, available, alpha):
                    self.wfile.write(f"event: {kind}\ndata: {json.dumps(payload, default=str)}\n\n".encode())
                    self.wfile.flush()
            except BrokenPipeError:
                pass
            finally:
                engine.lock.release()

        def log_message(self, *args) -> None:
            pass

    return ThreadingHTTPServer(("0.0.0.0", port), Handler)
