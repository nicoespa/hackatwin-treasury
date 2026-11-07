"""Live demo: plan once, then watch it hold and top up if it falls short.

Two kinds of decisions, on a running simulated clock:

- **Plan** (business days at ``PLAN_HOUR``): how much to send to each account so it covers, on a bad
  day (the policy's ``alpha``), everything until the next plan lands. On Friday that is the whole
  weekend. This is the one deposit decision.
- **Check** (once a day at the same hour on non-business days; ``review_every`` adds intraday checks for the
  measuring experiment): re-forecast with what already settled and
  compare. An account holding less than its need gets the gap from the pool, and from a liquidity line
  when the pool runs short. Money already sent stays where it is: an intermediary does not hand a
  prefunded balance back on demand, so by default nothing is pulled out (``give_back=False``). With
  ``give_back=True`` (only for the measuring experiment) an account holding more than its new need times
  ``1 + HEADROOM`` gives the excess back, first to short accounts, the rest to the pool. Moves below
  ``MIN_MOVE_SHARE`` of the need are skipped: not worth their fee.

Only accounts that accept a 24/7 rail (stablecoin) take part: a bank-only account cannot be corrected
at night or on a weekend. Users' payments are the dataset's settled events. Nothing leaves the process.

``LiveSim.evaluate`` runs the same logic without the clock over several weeks to measure it;
``serve`` runs it live behind a small HTTP server (page at ``/``, state at ``/api/live``, controls
``/api/play``, ``/api/pause``, ``/api/reset``, ``/api/speed?x=``). The MCP pause switch
(``TREASURY_STATE``) is read at every decision, so pausing the agent from an MCP client shows live.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

from treasury.agent.guardrails import load_autonomy
from treasury.backtest import Dataset, _rail_for, _realized, walk_forward
from treasury.experiments import PROPOSED, factory
from treasury.ledger import Credit, min_deposit_paths
from treasury.monitor import DATA, STATE
from treasury.orders import parse as parse_order
from treasury.policy import ceil_to_lot, window_flows
from treasury.rails import arrival_time
from treasury.segmentation import KMeansSegmenter

START, STOP = pd.Timestamp("2026-10-16 09:00"), pd.Timestamp("2026-10-19 12:00")
PLAN_HOUR = 9
HEADROOM, MIN_MOVE_SHARE = 0.10, 0.10
POOL, CREDIT_LINE = 1200e6, 500e6  # ARS: the wallet's pool on Friday and a liquidity line, demo assumptions
PHASE_SECONDS = 0.6
PAGE, LOGO = Path(__file__).with_name("live.html"), Path(__file__).with_name("monitor_logo.png")
NAMES = {"bills_aggregator": "Partner de pagos", "card_network": "Procesador de tarjetas", "crypto_exchange": "Exchange cripto",
         "remittance": "Remesadora"}  # the intermediary partners holding the wallet's prefunded balances
DEMO_PARTNERS = ("bills_aggregator",)  # a wallet usually prefunds a single partner
ROLES = {"bills_aggregator": "paga servicios", "card_network": "procesa tarjetas", "crypto_exchange": "exchange cripto",
         "remittance": "envía remesas"}  # each account is the wallet's prefunded balance at another company


def _day(t: pd.Timestamp) -> str:
    days = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    return f"{days[t.dayofweek]} {t.hour}:{t.minute:02d}"


def _set_paused(paused: bool) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"paused": paused}))


def _paused() -> bool:
    try:
        return bool(json.loads(STATE.read_text()).get("paused", False))
    except (FileNotFoundError, json.JSONDecodeError):
        return False


@dataclass
class Account:
    pid: str
    balance: float
    pending: list[tuple[pd.Timestamp, float]] = field(default_factory=list)
    need_now: float = 0.0
    plan_need: float = 0.0
    plan_sent: float = 0.0
    plan_at: pd.Timestamp | None = None

    @property
    def incoming(self) -> float:
        return sum(x for _, x in self.pending)


class LiveSim:
    def __init__(self, data: Path = DATA, origins: list[date] | None = None, seconds_per_hour: float = 1.5,
                 only: tuple[str, ...] = DEMO_PARTNERS) -> None:
        self.dataset = Dataset.load(data)
        configs = self.dataset.configs
        self.cfg = configs.policy()
        self.default_alpha = self.cfg.alpha
        partners, rails = configs.partners(), configs.rails()
        self.partners = {pid: p for pid, p in partners.items() if "stablecoin" in p.accepts_rails and pid in only}
        self.rail = {pid: _rail_for(p, rails, "stablecoin") for pid, p in self.partners.items()}
        self.cal = {pid: configs.rail_calendar(p) for pid, p in self.partners.items()}
        self.home = configs.calendar()
        self.limits = load_autonomy(configs.dir / "policy.yaml").limits["ARS"]
        self.forecasts = walk_forward(self.dataset, factory(PROPOSED, 1000), origins or [date(2026, 10, 11)], horizon=14,
                                      n_paths=1000, segmenter=KMeansSegmenter())
        self.seconds_per_hour = seconds_per_hour
        self.adjust = True  # False: plan only, the measuring baseline
        self.review_every: int | None = None  # None: one decision a day; 3: also a check every 3 hours
        self.give_back = False  # True: pull excess back out of accounts (assumes the intermediary allows it)
        self.unlimited = False  # True: no pool, line or transfer limits (how the other experiments measure)
        self.lock = threading.Lock()
        self.reset()

    # -- forecasts and needs -------------------------------------------------------------------
    def _fc(self, t: pd.Timestamp):
        return next(f for f in reversed(self.forecasts) if f.origin <= t)

    def plan_end(self, t: pd.Timestamp) -> pd.Timestamp:
        """When the next plan's transfer lands: the next business day's plan hour after ``t``, plus the lead."""
        day = t.normalize()
        while True:
            candidate = day + pd.Timedelta(hours=PLAN_HOUR)
            if candidate > t and self.home.is_business_day(day.date()):
                return candidate + pd.Timedelta(minutes=30)
            day += pd.Timedelta(days=1)

    def _cover(self, a: Account, t: pd.Timestamp) -> tuple[float, float]:
        """``(need, gap)`` at ``t``: the bad-day need until the next plan lands, and the smallest
        transfer landing now + lead that keeps the balance non-negative on a bad day."""
        fc, pid = self._fc(t), a.pid
        j = fc.partners.index(pid)
        times, signed = self.flows[pid]
        mask = (times >= t.normalize().to_datetime64()) & (times < t.to_datetime64())
        today = float(np.maximum(signed[mask], 0.0).sum())
        partner = self.partners[pid]
        at, amounts = window_flows(fc.paths[:, :, j], fc.dates, partner, t, self.plan_end(t), today, fc.inflow[:, j],
                                   lagged_at_cutoff=self.cfg.place_lagged_at_cutoff and not partner.is_realtime)
        res = min_deposit_paths(a.balance, at, amounts, [Credit(x, y) for x, y in a.pending],
                                arrival_time(self.rail[pid], t, self.cal[pid]))
        self.detail[pid] = {"today": today, "expected": float(np.median(res.need)), "until": self.plan_end(t)}
        return float(np.quantile(res.need, self.cfg.alpha)), ceil_to_lot(float(np.quantile(res.amount, self.cfg.alpha)), self.cfg.lot_size)

    # -- state ---------------------------------------------------------------------------------
    def reset(self, start: pd.Timestamp = START, stop: pd.Timestamp = STOP) -> None:
        with self.lock:
            self.start, self.stop, self.now = start, stop, start
            self.playing, self.phase = False, None
            self.pool, self.credit_used = POOL, 0.0
            self.moves: list[dict] = []
            self.agent_log: list[dict] = []
            self.user_cap: float | None = None
            self.cfg = replace(self.cfg, alpha=self.default_alpha)
            self.detail: dict[str, dict] = {}
            self.sent_today: dict[tuple[str, pd.Timestamp], float] = {}
            self.flows = {pid: _realized(self.dataset, p, start - pd.Timedelta(days=1), stop + pd.Timedelta(days=2))
                          for pid, p in self.partners.items()}
            self.flow_i = {pid: int(np.searchsorted(self.flows[pid][0], start.to_datetime64(), "right")) for pid in self.partners}
            self.accounts = {}
            for pid in self.partners:  # opens with what yesterday's plan left: the bad-day need until the plan hour
                a = Account(pid, 0.0)
                need, _ = self._cover(a, start - pd.Timedelta(hours=1))
                a.balance = 0.5 * need
                a.need_now = self._cover(a, start)[0]
                self.accounts[pid] = a
            self.events = self._schedule(start, stop)
            self.event_i = 0
            self.history: list[dict] = []
            self.next_sample = start
            self.preview = self._preview(start)
            self._sample(start)
            self.capital_area, self.short_minutes, self.last_t = 0.0, 0.0, start

    def _preview(self, t: pd.Timestamp) -> list[dict]:
        """What the plan at ``t`` would send, per account, with the day-by-day forecast it rests on:
        the expected outflow (median of the paths) and a bad day (the policy's ``alpha`` quantile)."""
        out = []
        end = self.plan_end(t)
        fc = self._fc(t)
        days = [d for d in fc.dates if t.normalize() <= d <= end.normalize()]
        for pid, a in self.accounts.items():
            need, gap = self._cover(a, t)
            j = fc.partners.index(pid)
            daily = [{"date": d.strftime("%Y-%m-%d"), "expected": float(np.median(fc.paths[:, k, j])),
                      "bad": float(np.quantile(fc.paths[:, k, j], self.cfg.alpha))}
                     for k, d in enumerate(fc.dates) if d in days]
            out.append({"account": NAMES[pid], "role": ROLES[pid], "have": a.balance, "need": need, "send": gap,
                        "days": daily})
        return out

    def _sample(self, t: pd.Timestamp) -> None:
        self.history.append({"t": t.isoformat(), "pool": self.pool,
                             "a": {NAMES[pid]: [round(a.balance), round(a.need_now)] for pid, a in self.accounts.items()}})

    def run_plan_now(self) -> None:
        """Execute the opening plan right away (the first event), without the step-by-step display."""
        with self.lock:
            if self.event_i == 0 and self.events and self.events[0][1] == "plan":
                t = self.events[0][0]
                self._advance_to(t)
                self._decide(t, "plan")
                self.event_i = 1
                self._sample(t)

    def _schedule(self, start: pd.Timestamp, stop: pd.Timestamp) -> list[tuple[pd.Timestamp, str]]:
        """One decision a day at ``PLAN_HOUR`` (a plan on business days, a check otherwise); with
        ``review_every`` set, a check every that many hours as well (the measuring experiment)."""
        if self.review_every is None:
            times = [d + pd.Timedelta(hours=PLAN_HOUR) for d in pd.date_range(start.normalize(), stop.normalize(), freq="D")]
        else:
            times = list(pd.date_range(start.normalize(), stop, freq=f"{self.review_every}h"))
        out = [(t, "plan" if t.hour == PLAN_HOUR and self.home.is_business_day(t.date()) else "adjust")
               for t in times if start <= t <= stop]
        if not any(t == start for t, _ in out):
            out.insert(0, (start, "plan" if self.home.is_business_day(start.date()) else "adjust"))
        return out

    def _log(self, at, kind, amount, src=None, dst=None, **extra) -> None:
        self.moves.append({"at": at.isoformat(), "kind": kind, "amount": float(amount),
                           "from": NAMES.get(src, src) if src else "Tu billetera", "to": NAMES.get(dst, dst) if dst else "Tu billetera", **extra})

    def _advance_to(self, t: pd.Timestamp) -> None:
        """Settle payments and land transfers up to ``t``; accrue capital and shortfall time."""
        span = (t - self.last_t) / pd.Timedelta(minutes=1)
        if span > 0:
            self.capital_area += span * sum(max(a.balance, 0.0) + a.incoming for a in self.accounts.values())
            self.short_minutes += span * sum(a.balance < 0 for a in self.accounts.values())
        self.last_t = t
        for pid, a in self.accounts.items():
            times, signed = self.flows[pid]
            i = self.flow_i[pid]
            while i < len(times) and times[i] <= t.to_datetime64():
                a.balance -= signed[i]
                i += 1
            self.flow_i[pid] = i
            for x in [p for p in a.pending if p[0] <= t]:
                a.balance += x[1]
            a.pending = [p for p in a.pending if p[0] > t]

    def _cap(self, pid: str, t: pd.Timestamp, amount: float) -> float:
        if self.unlimited:
            return float(amount)
        room = min(self.limits.max_per_transfer, self.limits.max_per_partner_day - self.sent_today.get((pid, t.normalize()), 0.0))
        if self.user_cap is not None:
            room = min(room, self.user_cap)
        return float(max(0.0, min(amount, room)))

    def _send(self, t: pd.Timestamp, dst: str, amount: float, kind: str, src: str | None = None) -> float:
        """Move ``amount`` into ``dst`` from account ``src`` or, when None, from the pool (drawing the
        liquidity line if the pool is short). Returns what was sent after limits."""
        send = self._cap(dst, t, amount)
        if send < amount:
            self._log(t, "capped", amount - send, src, dst)
        if send <= 0:
            return 0.0
        if src is None and self.pool < send and not self.unlimited:
            draw = min(send - self.pool, CREDIT_LINE - self.credit_used)
            if draw > 0:
                self.credit_used += draw
                self.pool += draw
                self._log(t, "credit", draw, "Línea de liquidez", None)
            send = min(send, self.pool)
        if src is None:
            self.pool -= send
        else:
            self.accounts[src].balance -= send
        self.sent_today[(dst, t.normalize())] = self.sent_today.get((dst, t.normalize()), 0.0) + send
        lands = arrival_time(self.rail[dst], t, self.cal[dst])
        self.accounts[dst].pending.append((lands, send))
        self._log(t, kind, send, src, dst, arrives=lands.isoformat())
        return send

    def _decide(self, t: pd.Timestamp, kind: str) -> None:
        """Run one decision and record it, step by step, in ``agent_log``."""
        before = {pid: (a.balance, a.incoming) for pid, a in self.accounts.items()}
        first = len(self.moves)
        self._decide_moves(t, kind)
        made = self.moves[first:]
        for pid, a in self.accounts.items():
            name, d = NAMES[pid], self.detail.get(pid, {})
            have = before[pid][0] + before[pid][1]
            mine = [m for m in made if m["to"] == name]
            sent = sum(m["amount"] for m in mine if m["kind"] in ("plan", "adjust_in"))
            capped = sum(m["amount"] for m in mine if m["kind"] == "capped")
            held = sum(m["amount"] for m in mine if m["kind"] == "held")
            arrives = next((m.get("arrives") for m in mine if m["kind"] in ("plan", "adjust_in")), None)
            until = d.get("until")
            self.agent_log.append({"at": t.isoformat(), "kind": kind, "account": name, "sent": sent, "today": d.get("today", 0.0),
                                   "expected": d.get("expected", 0.0), "need": a.need_now, "have": have, "capped": capped,
                                   "held": held, "arrives": arrives, "until": until.isoformat() if until is not None else None,
                                   "alpha": self.cfg.alpha})

    def _decide_moves(self, t: pd.Timestamp, kind: str) -> None:
        paused = _paused()
        needs = {pid: self._cover(a, t) for pid, a in self.accounts.items()}
        for pid, (need, _) in needs.items():
            self.accounts[pid].need_now = need
        if kind == "plan":
            for pid, (need, gap) in needs.items():
                a = self.accounts[pid]
                a.plan_need, a.plan_at = need, t
                if gap <= 0:
                    a.plan_sent = 0.0
                    continue
                if paused:
                    self._log(t, "held", gap, None, pid)
                    continue
                a.plan_sent = self._send(t, pid, gap, "plan")
            return
        if not self.adjust:
            return
        excess, short = {}, {}
        for pid, (need, gap) in needs.items():
            a = self.accounts[pid]
            free = a.balance - need * (1 + HEADROOM)
            if gap > 0 and gap >= MIN_MOVE_SHARE * max(need, 1.0):
                short[pid] = gap
            elif self.give_back and free > 0 and free >= MIN_MOVE_SHARE * max(need, 1.0):
                excess[pid] = float(self.cfg.lot_size * np.floor(free / self.cfg.lot_size))
        if paused:
            for pid, gap in short.items():
                self._log(t, "held", gap, None, pid)
            return
        for dst, gap in sorted(short.items(), key=lambda kv: -kv[1]):
            for src in sorted(excess, key=lambda k: -excess[k]):
                if gap <= 0 or excess[src] <= 0:
                    continue
                moved = self._send(t, dst, min(gap, excess[src]), "p2p", src)
                excess[src] -= moved
                gap -= moved
            if gap > 0:
                self._send(t, dst, gap, "adjust_in")
        for src, free in excess.items():
            if free > 0:
                self.accounts[src].balance -= free
                self.pool += free
                self._log(t, "adjust_out", free, src, None)

    # -- running -------------------------------------------------------------------------------
    def _run_event(self, t: pd.Timestamp, kind: str, show: bool) -> None:
        names = list(NAMES[p] for p in self.accounts)
        if show:
            for step in ("forecast", "decide", "move"):
                with self.lock:
                    self.phase = {"at": t.isoformat(), "kind": kind, "step": step, "accounts": names}
                time.sleep(PHASE_SECONDS)
        with self.lock:
            self._decide(t, kind)
            self.phase = None
            self._sample(t)

    def evaluate(self, start: pd.Timestamp, stop: pd.Timestamp) -> dict:
        """Run plan and adjustments from ``start`` to ``stop`` with no clock and no pool, line or limits
        (``unlimited``), like the other experiments: mean capital in the accounts (balance plus transfers
        on their way), account-hours with a negative balance, and the moves by kind."""
        self.unlimited = True
        self.reset(start, stop)
        for t, kind in self.events:
            self._advance_to(t)
            self._decide(t, kind)
        self._advance_to(stop)
        minutes = (stop - start) / pd.Timedelta(minutes=1)
        kinds = pd.Series([m["kind"] for m in self.moves]).value_counts().to_dict()
        self.unlimited = False
        return {"capital": self.capital_area / minutes, "short_account_hours": self.short_minutes / 60,
                "moves": kinds, "credit_used": self.credit_used}

    def run_forever(self) -> None:
        last = time.monotonic()
        while True:
            time.sleep(0.05)
            now = time.monotonic()
            dt, last = now - last, now
            if not self.playing or self.now >= self.stop:
                continue
            target = min(self.stop, self.now + pd.Timedelta(hours=dt / self.seconds_per_hour))
            if self.event_i < len(self.events) and self.events[self.event_i][0] <= target:
                t, kind = self.events[self.event_i]
                self.event_i += 1
                with self.lock:
                    self._advance_to(t)
                    self.now = t
                self._run_event(t, kind, show=True)
                last = time.monotonic()
                continue
            with self.lock:
                self._advance_to(target)
                self.now = target
                while self.next_sample <= target:
                    self._sample(self.next_sample)
                    self.next_sample += pd.Timedelta(hours=1)

    def command(self, text: str) -> dict:
        """Apply an optional order from the treasury team and log it as an agent entry."""
        order = parse_order(text, self.cfg.alpha)
        risk_name = {0.99: "bajo", 0.95: "medio", 0.9: "alto"}
        with self.lock:
            t, pid = self.now, next(iter(self.accounts))
            a = self.accounts[pid]
            steps = []
            if order.action == "pause":
                _set_paused(True)
                steps = [{"text": "Entendió: frenar los envíos"}, {"text": "Sigue pronosticando, pero no manda plata"}]
            elif order.action == "resume":
                _set_paused(False)
                steps = [{"text": "Entendió: volver a enviar"}, {"text": "Desde la próxima decisión manda lo que haga falta"}]
            elif order.action == "set_risk" and order.risk is not None:
                self.cfg = replace(self.cfg, alpha=order.risk)
                for acc in self.accounts.values():
                    acc.need_now = self._cover(acc, t)[0]
                if self.event_i == 0:
                    self.preview = self._preview(t)
                steps = [{"text": f"Entendió: riesgo {risk_name.get(round(order.risk, 2), order.risk)}"},
                         {"text": "Recalculó lo que necesita, con margen", "value": a.need_now},
                         {"text": "Lo ya enviado queda en el partner"}]
            elif order.action == "set_cap" and order.amount:
                self.user_cap = float(order.amount)
                steps = [{"text": "Entendió: tope por envío", "value": self.user_cap},
                         {"text": "Si hace falta más, lo completa en las próximas revisiones"}]
            elif order.action == "clear_cap":
                self.user_cap = None
                steps = [{"text": "Entendió: sin tope propio"}, {"text": "Quedan los límites de autonomía de siempre"}]
            elif order.action == "send_now" and order.amount:
                sent = self._send(t, pid, float(order.amount), "manual")
                steps = [{"text": "Entendió: enviar ahora", "value": float(order.amount)},
                         {"text": "Revisó los límites de autonomía"},
                         {"text": "Envió por stablecoin" if sent else "No envió: lo frenó un límite", "value": sent or None,
                          "warn": not sent}]
            elif order.action == "status":
                steps = [{"text": "Saldo en el partner", "value": a.balance + a.incoming},
                         {"text": "Necesita, con margen", "value": a.need_now},
                         {"text": "Alcanza" if a.balance + a.incoming >= a.need_now else "Falta: completa en la próxima revisión"}]
            else:
                steps = [{"text": "No entendió la orden", "warn": True},
                         {"text": "Probá: frená los envíos, riesgo medio, no mandes más de 100 M, reanudá"}]
            sent_now = sum(m["amount"] for m in self.moves if m["kind"] == "manual" and m["at"] == t.isoformat()) if order.action == "send_now" else 0.0
            self.agent_log.append({"at": t.isoformat(), "kind": "order", "account": NAMES[pid], "text": text, "sent": sent_now,
                                   "action": order.action, "source": order.source, "steps": steps})
            self._sample(t)
        return {"action": order.action, "source": order.source}

    def _actual_days(self) -> dict[str, dict[str, float]]:
        """Net outflow per day that already settled, per account (what the forecast is checked against)."""
        out = {}
        for pid in self.accounts:
            times, signed = self.flows[pid]
            seen = pd.Series(signed[: self.flow_i[pid]], index=pd.DatetimeIndex(times[: self.flow_i[pid]]))
            seen = seen[seen.index >= self.start.normalize()]
            out[NAMES[pid]] = {d.strftime("%Y-%m-%d"): float(v) for d, v in seen.groupby(seen.index.normalize()).sum().items()}
        return out

    def set_alpha(self, alpha: float) -> None:
        """Change how bad a day the agent covers. Applies from the next decision; money already sent stays."""
        with self.lock:
            self.cfg = replace(self.cfg, alpha=float(min(0.999, max(0.5, alpha))))
            for a in self.accounts.values():
                a.need_now = self._cover(a, self.now)[0]
            if self.event_i == 0:
                self.preview = self._preview(self.now)

    def state(self) -> dict:
        with self.lock:
            accounts = [{"account": NAMES[pid], "role": ROLES[pid], "balance": a.balance, "need": a.need_now, "incoming": a.incoming,
                         "plan_need": a.plan_need, "plan_sent": a.plan_sent,
                         "plan_at": a.plan_at.isoformat() if a.plan_at is not None else None} for pid, a in self.accounts.items()]
            nxt = self.events[self.event_i] if self.event_i < len(self.events) else None
            return {"now": self.now.isoformat(), "start": self.start.isoformat(), "stop": self.stop.isoformat(),
                    "playing": self.playing, "done": self.now >= self.stop, "paused_agent": _paused(),
                    "pool": self.pool, "credit_used": self.credit_used, "credit_line": CREDIT_LINE,
                    "accounts": accounts, "phase": self.phase, "moves": self.moves, "history": self.history,
                    "preview": self.preview, "planned": self.event_i > 0, "alpha": self.cfg.alpha,
                    "agent_log": self.agent_log, "actual": self._actual_days(), "user_cap": self.user_cap,
                    "next": {"at": nxt[0].isoformat(), "kind": nxt[1]} if nxt else None}


def serve(port: int = 8700, seconds_per_hour: float = 1.5) -> ThreadingHTTPServer:
    _set_paused(False)
    sim = LiveSim(seconds_per_hour=seconds_per_hour)
    threading.Thread(target=sim.run_forever, daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: bytes, kind: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            url = urlparse(self.path)
            if url.path == "/api/live":
                return self._send(json.dumps(sim.state(), default=str).encode(), "application/json")
            if url.path in ("/", "/index.html"):
                return self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
            if url.path == "/logo.png":
                return self._send(LOGO.read_bytes(), "image/png")
            if url.path == "/api/plan":
                sim.run_plan_now()
            elif url.path == "/api/play":
                sim.playing = True
            elif url.path == "/api/pause":
                sim.playing = False
            elif url.path == "/api/reset":
                _set_paused(False)
                sim.reset()
            elif url.path == "/api/risk":
                sim.set_alpha(float(parse_qs(url.query).get("alpha", ["0.99"])[0]))
            elif url.path == "/api/speed":
                x = float(parse_qs(url.query).get("x", ["1"])[0])
                sim.seconds_per_hour = 1.5 / max(0.25, min(8.0, x))
            else:
                return self.send_error(404)
            self._send(b'{"ok": true}', "application/json")

        def do_POST(self) -> None:  # noqa: N802 (http.server API)
            if urlparse(self.path).path != "/api/command":
                return self.send_error(404)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            text = str(body.get("text", "")).strip()[:300]
            if not text:
                return self.send_error(400)
            self._send(json.dumps(sim.command(text)).encode(), "application/json")

        def log_message(self, *args) -> None:
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
