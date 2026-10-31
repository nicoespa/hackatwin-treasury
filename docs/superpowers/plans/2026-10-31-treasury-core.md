# Predictive Treasury (prefunding engine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the demo for HackaTwin (2026-11-07): a system that, from a simulated population of wallet users, forecasts the daily outflow of each external partner, sizes the prefunded balance per partner as the α-quantile of the maximum cumulative deficit over the protection window, recommends deposits per rail (wire vs stablecoin), backtests four forecasting models × two rails against a written success criterion, and lets an LLM agent propose transfers that a human approves.

**Architecture:** A Python package `treasury` with small single-purpose modules, built in the order the reviews fixed: balance/settlement engine first (with verifiable shortfall tests), then the population simulator (synthetic history, drivers, stress), then a seasonal baseline and shared metrics, then an aggregate model with drivers, then the obligations layer and the segment × product model with a shared macro factor and Monte Carlo aggregation, then the policy and the walk-forward backtest, then the agent and the dashboard. Every model exposes the same quantile interface at partner × day level so the comparison table is one function.

**Tech Stack:** Python 3.12 (uv), numpy, pandas, pyarrow, scipy, lightgbm, pyyaml, pytest, typer (CLI), anthropic (agent, Task 9), streamlit (dashboard, Task 10).

**Spec:** `reports/Prefondeo desde comportamiento de usuarios.md` (copied into this repo when the session moved) and its predecessor `reports/Tesorería predictiva para prefondeo.md`. Research notes under `research_notes/`.

## Global Constraints

- Python pinned `>=3.12,<3.13` (`.python-version` = `3.12`); dependencies managed with `uv`; run everything as `uv run …`.
- All amounts are floats in one unit (USD-equivalent); timestamps are tz-naive `pandas.Timestamp` in Argentina local time.
- Quantile grid everywhere: `QUANTILES = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)`; quantile columns are named `q05, q10, q25, q50, q75, q90, q95, q99`.
- Single balance convention: `available = book - blocked`. The ledger only ever receives `available`. Nothing subtracts "blocked" a second time.
- In-transit money is counted once in total capital (at the origin until it credits, at the destination afterwards).
- Randomness only through `numpy.random.default_rng(seed)`; every artifact records its seed.
- Confirmed obligations (amount and settlement date known ahead) are excluded from the residual any model forecasts (anti double counting).
- Success criterion of the demo, written here before building: **less total capital immobilized, at the same service level, in scenarios the model does not know in advance.**
- Code identifiers, commits and file names in English. Commit after every task with a conventional message.

## Review Focus

1. A replenishment credited at 18:00 must not cover an outflow at 10:00 of the same day, even inside the protection window (test in Task 2).
2. A Monday for a partner whose rail does not credit on weekends must accumulate Friday + Saturday + Sunday outflows against Friday's balance (test in Task 3 and Task 8).
3. A partner that both receives and pays (FCI custodian) needs the gross intraday peak, not the daily net, when the inflow arrives after the outflow (test in Task 2).
4. A bottom-up model must be allowed to lose: five near-identical segments with 3 months of history must not show the segment model beating the aggregate-with-drivers model (test in Task 8).
5. Payday mass between business days 1–4 is a simulator hypothesis; switching the hypothesis (`late`, `uniform`, `bimodal`) must change the simulated series and be reported as a parameter (test in Task 4).

---

### Task 1: Project scaffold and Argentine business calendar

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.gitignore`, `README.md`
- Create: `config/calendar_ar_2026.yaml`
- Create: `src/treasury/__init__.py`, `src/treasury/calendar.py`
- Test: `tests/test_calendar.py`

**Interfaces:**
- Produces: `class Calendar` with `Calendar.from_yaml(path) -> Calendar`; `is_business_day(d: date) -> bool`; `add_business_days(d: date, n: int) -> date` (n may be 0 or negative); `nth_business_day_of_month(d: date) -> int` (1-based, 0 if not a business day); `business_days_to_month_end(d: date) -> int`; `is_sac_window(d: date) -> bool`; `anses_window(d: date) -> bool`; `holidays: frozenset[date]`.
- YAML schema: `holidays: [YYYY-MM-DD, …]` (Ley 27.399 fixed + movable + Res. 164/2025 puentes 2026-03-23, 2026-07-10, 2026-12-07), `sac_windows: [{start, end}]` with 2026-06-24..2026-07-06 and 2026-12-12..2026-12-24, `anses_windows: [{start, end}]` one per month, business days 9..25 as default hypothesis.

- [ ] **Step 1: Scaffold** — `pyproject.toml` with `[project] name="treasury"`, `requires-python=">=3.12,<3.13"`, deps `numpy pandas pyarrow scipy lightgbm pyyaml typer`, dev deps `pytest pytest-cov`; `[project.scripts] treasury = "treasury.cli:app"`; `[tool.pytest.ini_options] testpaths=["tests"]`; src layout (`[tool.hatch.build.targets.wheel] packages = ["src/treasury"]`). Run `uv sync` and `uv run python -c "import lightgbm"`; expected: no error.
- [ ] **Step 2: Write failing tests** in `tests/test_calendar.py`:
  - `test_holiday_is_not_business_day`: 2026-05-25 → False; 2026-05-26 → True.
  - `test_add_business_days_skips_weekend_and_holiday`: `add_business_days(date(2026,5,22), 1) == date(2026,5,26)` (Fri → Tue, Monday 25 holiday).
  - `test_nth_business_day`: 2026-11-04 → 3 (Nov 2 is a Monday; 2026-11-02 is not a holiday); a Saturday → 0.
  - `test_sac_window`: 2026-06-30 → True; 2026-07-15 → False.
- [ ] **Step 3: Run** `uv run pytest tests/test_calendar.py -v`; expected: FAIL (module not found).
- [ ] **Step 4: Implement** `Calendar` in `src/treasury/calendar.py` reading the YAML; business day = Mon–Fri and not in `holidays`.
- [ ] **Step 5: Run** tests; expected PASS.
- [ ] **Step 6: Commit** `chore: scaffold project and Argentine business calendar`.

---

### Task 2: Balance engine (ledger) and rails

**Files:**
- Create: `src/treasury/ledger.py`, `src/treasury/rails.py`
- Create: `config/rails.yaml`
- Test: `tests/test_ledger.py`, `tests/test_rails.py`

**Interfaces:**
- Consumes: `Calendar` (Task 1).
- Produces in `ledger.py`:
  - `@dataclass(frozen=True) Flow(at: Timestamp, amount: float)` — positive = outflow from the partner balance, negative = inflow credited to it.
  - `@dataclass(frozen=True) Credit(at: Timestamp, amount: float)` — a replenishment that becomes available at `at`.
  - `balance_path(opening_available: float, flows: Sequence[Flow], credits: Sequence[Credit]) -> pd.DataFrame` with columns `at, delta, balance`, sorted by `at`; at equal timestamps credits apply before flows.
  - `max_need(path: pd.DataFrame, opening_available: float) -> float` = `max(0, opening_available - path.balance.min())` (largest cumulative net debit against the opening balance).
  - `first_shortfall(path) -> Timestamp | None` (first `at` with `balance < 0`).
  - `min_deposit(opening_available, flows, credits, arrival_at: Timestamp) -> DepositResult(amount: float, unresolvable: bool, first_shortfall: Timestamp | None)`: the minimum `x ≥ 0` such that adding `Credit(arrival_at, x)` leaves `balance ≥ 0` at every `at ≥ arrival_at`; `unresolvable=True` if a shortfall exists at some `at < arrival_at` (that shortfall is reported, and `amount` still covers everything after arrival).
- Produces in `rails.py`: `@dataclass(frozen=True) Rail(name: str, lead_time_hours: float, business_days_only: bool, instruct_cutoff_hour: int | None, credit_hour: int | None, fixed_fee: float, bps: float)`; `load_rails(path) -> dict[str, Rail]`; `arrival_time(rail: Rail, instruct_at: Timestamp, cal: Calendar) -> Timestamp`. For `business_days_only`: if `instruct_at` is not on a business day or is after `instruct_cutoff_hour`, start counting from the next business day; arrival = `add_business_days(start, ceil(lead_time_hours/24))` at `credit_hour`. For 24/7 rails: `instruct_at + lead_time_hours`.
- `config/rails.yaml`: `wire: {lead_time_hours: 48, business_days_only: true, instruct_cutoff_hour: 15, credit_hour: 10, fixed_fee: 30, bps: 0}`; `stablecoin: {lead_time_hours: 0.5, business_days_only: false, instruct_cutoff_hour: null, credit_hour: null, fixed_fee: 2, bps: 10}`.

- [ ] **Step 1: Write failing tests** `tests/test_ledger.py`:
  - `test_credit_at_18_does_not_cover_outflow_at_10`: opening 0, flow +100 at 10:00, credit 100 at 18:00 → `first_shortfall == 10:00`, `max_need == 100`, and `min_deposit(..., arrival_at=18:00).unresolvable is True`.
  - `test_credit_before_outflow_covers_it`: same but credit at 09:00 → no shortfall, `min_deposit(...).amount == 0`.
  - `test_intraday_net_zero_needs_gross`: opening 0, +100 at 10:00, −100 at 18:00 → `max_need == 100`.
  - `test_inflow_before_outflow_nets`: −100 at 09:00, +100 at 10:00 → `max_need == 0`.
  - `test_min_deposit_covers_post_arrival_shortfall`: opening 50, flows +30 (10:00), +100 (12:00), arrival 11:00 → `amount == 80`, `unresolvable False`.
  - `test_min_deposit_reports_pre_arrival_shortfall`: opening 0, +30 at 10:00, +100 at 12:00, arrival 11:00 → `amount == 100`, `unresolvable True`, `first_shortfall == 10:00`.
  - `tests/test_rails.py`: `test_wire_friday_after_cutoff_arrives_wednesday` (instruct Fri 2026-11-06 16:00 → Wed 2026-11-11 10:00; 2026-11-09 is a business day — if your calendar says otherwise, fix the expected date and state why in the test); `test_stablecoin_sunday_arrives_in_30_min`.
- [ ] **Step 2: Run** tests; expected FAIL.
- [ ] **Step 3: Implement** `ledger.py` and `rails.py` as specified. `min_deposit`: compute the path without the new credit; `amount = max(0, -min(balance at at ≥ arrival_at))` where the running balance before arrival is not altered; set `unresolvable` from the pre-arrival segment.
- [ ] **Step 4: Run** tests; expected PASS.
- [ ] **Step 5: Commit** `feat: balance engine with intraday need, min deposit and rail arrival times`.

---

### Task 3: Partners and routing of events to settlement time

**Files:**
- Create: `config/partners.yaml`, `src/treasury/routing.py`
- Test: `tests/test_routing.py`

**Interfaces:**
- Consumes: `Calendar`.
- Produces: `@dataclass(frozen=True) Partner(id: str, products: tuple[str, ...], settle_lag_business_days: int, settle_cutoff_hour: int, same_day_before_cutoff: bool, nets_inflows: bool, accepts_rails: tuple[str, ...])`; `load_partners(path) -> dict[str, Partner]`; `partner_for_product(product: str, partners) -> Partner`; `settle_at(event_at: Timestamp, partner: Partner, cal: Calendar) -> Timestamp`: real-time partners (`settle_lag_business_days == 0 and same_day_before_cutoff`) return `event_at` itself; lagged partners return `add_business_days(day0, lag)` at `settle_cutoff_hour`, where `day0` is the event date if it is a business day and the event is before the cutoff, else the next business day. `route_events(events: pd.DataFrame, partners, cal) -> pd.DataFrame` adds columns `partner`, `settle_at`, `direction` (+1 outflow, −1 inflow).
- `config/partners.yaml` (six partners, these values):
  - `bills_aggregator`: products `[bill_payment, mobile_topup]`, lag 0, cutoff 15, same_day true, nets false, rails `[wire, stablecoin]`
  - `card_network`: `[card_purchase, card_refund]`, lag 1, cutoff 17, same_day false, nets true (refunds), rails `[wire, stablecoin]`
  - `fci_custodian`: `[fci_subscription, fci_redemption]`, lag 0, cutoff 17, same_day true, nets true, rails `[wire]`
  - `crypto_exchange`: `[crypto_buy, crypto_sell]`, lag 0, cutoff 23, same_day true, nets true, rails `[stablecoin]`
  - `cash_network`: `[cash_out, cash_in]`, lag 1, cutoff 18, same_day false, nets true, rails `[wire]`
  - `remittance`: `[remittance_out]`, lag 0, cutoff 14, same_day true, nets false, rails `[wire, stablecoin]`
  - Inflow products: `card_refund, fci_redemption, crypto_sell, cash_in` (direction −1).

- [ ] **Step 1: Write failing tests**: `test_weekend_card_purchase_settles_tuesday` (Sat 2026-11-07 purchase → Tue 2026-11-10 17:00: day0 = Mon 9, +1 bd); `test_bill_payment_settles_realtime`; `test_route_marks_inflow_direction` (`fci_redemption` → −1).
- [ ] **Step 2: Run**; FAIL. **Step 3: Implement.** **Step 4: Run**; PASS.
- [ ] **Step 5: Commit** `feat: partner config and event routing to settlement time`.

---

### Task 4: Population simulator, scenarios and validation

**Files:**
- Create: `config/archetypes.yaml`, `src/treasury/simulate/__init__.py`, `src/treasury/simulate/population.py`, `src/treasury/simulate/events.py`, `src/treasury/simulate/scenarios.py`, `src/treasury/simulate/validate.py`, `src/treasury/cli.py`
- Test: `tests/test_simulate.py`

**Interfaces:**
- Consumes: `Calendar`, `route_events`.
- Produces:
  - `generate_users(n: int, archetypes: dict, start: date, end: date, seed: int) -> pd.DataFrame` with columns `user_id, segment, activation_date, payday_bd (int 1..4 or NaN), anses_day (int or NaN), n_bills (int), has_autodebit (bool)`. Activation dates spread so that ~60 % of users exist at `start` and the rest arrive as monthly cohorts.
  - `@dataclass SimParams(sigma_m: float = 0.15, phi: float = 0.7, payday_hypothesis: Literal["late","uniform","bimodal"] = "late", inflation_monthly: float = 0.02)`.
  - `simulate_events(users, archetypes, cal, start, end, params: SimParams, scenarios: list[Scenario], seed) -> tuple[pd.DataFrame, pd.DataFrame]` returning `(events, macro)`; `events` columns `at, user_id, segment, product, amount, confirmed (bool)`; `macro` columns `date, m_t` (the shared lognormal AR(1) factor: `log m_t = phi*log m_{t-1} + eps, eps ~ N(0, sigma_m*sqrt(1-phi^2))`). Daily intensity per user×product = `base_rate × dow_mult × dom_mult × payday_mult(user, date, hypothesis) × scenario_mult × m_t`; counts Poisson; amounts lognormal with `inflation_monthly` drift; timestamp hour drawn from a per-product hour profile. Recurring bills: each user has `n_bills` with a fixed due day 1..10 and a counterparty id; `confirmed=True` only for users with `has_autodebit` (amount and date known ahead), others pay the bill on a day in `[due-2, due+3]` with probability 0.9 (`confirmed=False`).
  - Payday hypotheses as the mass over business days 1–4: `late = (0.10, 0.20, 0.30, 0.40)`, `uniform = (0.25,)*4`, `bimodal = (0.45, 0.05, 0.05, 0.45)`; each user draws `payday_bd` from it; the `payday_mult` for salaried users is 3.0 on their payday and 1.8 the day after for `bill_payment` and `fci_subscription`.
  - `Scenario` protocol: `multiplier(date, segment, product) -> float` and `extra_users(date) -> int`; implementations in `scenarios.py`: `Campaign(start, end, products, lift)`, `CohortWave(start, n_users, segment)`, `FxJump(date, days, crypto_lift=3.0)`, `PartnerOutage(partner, start, end, reroute_to)` (reroute implemented in routing step by remapping the product→partner for the window), `PaydayShift(delta_bd)`.
  - `validate(events_routed: pd.DataFrame, cal) -> dict[str, float | bool]` with keys `dispersion_index` (var/mean of daily counts; expect > 1.5), `acf7_gt_acf3` (bool), `salaried_argmax_in_bd1_5` (bool), `p99_over_median` (float).
  - CLI: `treasury simulate --users 20000 --start 2025-11-01 --end 2026-10-31 --seed 42 --out data/sim/base` writing `users.parquet`, `events.parquet` (routed), `macro.parquet`, `params.json`.
- `config/archetypes.yaml` (seven archetypes, `share` sums to 1): `salaried_formal 0.35`, `informal 0.20`, `anses_beneficiary 0.12`, `young_heavy 0.13`, `investor 0.08`, `crypto_active 0.07`, `merchant 0.05`; each with `products: {product: {adoption, base_rate_per_day, amount_median, amount_sigma}}` and `hour_profile` per product. Pin at least: `salaried_formal.bill_payment.base_rate_per_day = 0.08`, `investor.fci_subscription.base_rate_per_day = 0.15`, `crypto_active.crypto_buy.base_rate_per_day = 0.12`; other values are the implementer's choice but must produce a daily total CV between 10 % and 25 % at 20 000 users with `sigma_m = 0.15`.

- [ ] **Step 1: Write failing tests**: `test_users_shares_and_payday_hypothesis` (segment shares within ±2 pp; `payday_hypothesis="late"` gives mean `payday_bd` > 2.8, `"uniform"` ≈ 2.5 ± 0.1); `test_macro_factor_autocorrelation` (lag-1 autocorrelation of `log m_t` between 0.5 and 0.85 over 365 days); `test_events_have_confirmed_only_for_autodebit`; `test_campaign_raises_volume` (a `Campaign` with lift 1.5 on `bill_payment` over 7 days raises that product's volume in the window by at least 30 % vs the same seed without it); `test_validate_flags` on a 20 000-user, 6-month run: `dispersion_index > 1.5`, `salaried_argmax_in_bd1_5 True`.
- [ ] **Step 2: Run**; FAIL. **Step 3: Implement** vectorized per day with numpy over user arrays (no Python loop over users). **Step 4: Run**; PASS (the 6-month test may take ≤ 60 s; mark `@pytest.mark.slow` if slower).
- [ ] **Step 5: Run the CLI** for the 12-month base dataset and commit the `params.json` (not the parquet; add `data/` to `.gitignore`).
- [ ] **Step 6: Commit** `feat: population simulator with shared macro factor, scenarios and validation`.

---

### Task 5: Metrics, seasonal baseline and the forecast harness

**Files:**
- Create: `src/treasury/metrics.py`, `src/treasury/models/__init__.py`, `src/treasury/models/base.py`, `src/treasury/models/seasonal_naive.py`, `src/treasury/harness.py`
- Test: `tests/test_metrics.py`, `tests/test_seasonal_naive.py`, `tests/test_harness.py`

**Interfaces:**
- Produces in `base.py`: `QUANTILES`, `QCOLS`, `class Forecaster(Protocol)` with `name: str`; `fit(history: pd.DataFrame, drivers: pd.DataFrame) -> None`; `predict(dates: pd.DatetimeIndex, drivers: pd.DataFrame) -> pd.DataFrame` returning rows `date, partner, q05..q99` (non-crossing enforced by sorting across quantile columns). `history` is the daily partner table `date, partner, outflow, inflow, net` built by `daily_partner_table(events_routed) -> pd.DataFrame` (also in `base.py`; aggregates by `settle_at.date`).
- `seasonal_naive.py`: `SeasonalNaive(season=7, window_weeks=8)` — point = mean of the same weekday over the last 8 weeks; quantiles = point + empirical quantiles of the last 8 weeks' same-weekday residuals.
- `metrics.py`: `pinball(y, q, tau)`, `coverage(y, lo, hi)`, `pit(y, quantile_df) -> np.ndarray` (PIT via linear interpolation on the quantile grid), `crps_from_quantiles(y, quantile_df)`, `wape(y, yhat)`, and `summarize(preds: pd.DataFrame, actual: pd.DataFrame) -> pd.DataFrame` keyed by `model, partner, horizon` with `wape_q50, pinball_q90, pinball_q99, cov_90, cov_99, crps, pit_ks` (KS distance of PIT from uniform).
- `harness.py`: `rolling_origin(history, drivers, model_factory, origins: list[date], horizon=7) -> pd.DataFrame` producing `origin, date, horizon, partner, q05..q99, actual`; refits at every origin; `default_origins(end: date, n=8, step_days=7)`.

- [ ] **Step 1: Tests**: `test_pit_uniform_for_calibrated_gaussian` (synthetic y ~ N(0,1), quantiles from the true distribution → KS < 0.05 at n = 2000); `test_pinball_known_value`; `test_seasonal_naive_weekday_pattern` (a series with exact weekday levels → q50 equals the level, coverage 100 % for zero noise); `test_rolling_origin_shapes` (8 origins × 7 horizons × 6 partners rows, no `actual` NaN).
- [ ] **Step 2–4:** FAIL → implement → PASS. **Step 5: Commit** `feat: metrics, seasonal naive baseline and rolling-origin harness`.

---

### Task 6: Drivers, obligations layer and aggregate models (b) and (c)

**Files:**
- Create: `src/treasury/features.py`, `src/treasury/obligations.py`, `src/treasury/models/aggregate_lgbm.py`
- Test: `tests/test_features.py`, `tests/test_obligations.py`, `tests/test_aggregate_lgbm.py`

**Interfaces:**
- `features.py`: `calendar_features(dates, cal) -> pd.DataFrame` (`dow, dom, bd_index, bd_to_month_end, is_business_day, is_holiday, is_sac_window, is_anses_window, payday_mass` where `payday_mass` is the hypothesis vector evaluated at `bd_index`, 0 outside 1–4); `drivers_as_of(users, events_routed, as_of: date, dates) -> pd.DataFrame` keyed by `date, segment` with `n_active` (users activated ≤ as_of with ≥ 1 event in the 30 days before `as_of`, carried forward, plus cohorts whose `activation_date` is known ≤ as_of because cohorts are planned), `n_new_30d`; `campaign_flags(scenarios, dates) -> pd.DataFrame` (`date, product, lift`). Leakage rule: no column may use events after `as_of`; test enforces it.
- `obligations.py`: `confirmed_obligations(events_routed, as_of, horizon_dates) -> pd.DataFrame` (`date, partner, amount` from events with `confirmed=True` and `settle_at` in the horizon — these are known at `as_of` by construction); `detect_recurring(events_routed, as_of, min_occurrences=3, tolerance_days=3) -> pd.DataFrame` (`user_id, counterparty, partner, period_days, next_date, p_occur, amount_median`); `split_residual(history, confirmed) -> pd.DataFrame` (history with `outflow_residual = outflow − confirmed_amount`, never negative).
- `aggregate_lgbm.py`: `AggregateLGBM(name="aggregate_drivers", use_obligations: bool = False, quantiles=QUANTILES, params=dict(n_estimators=400, learning_rate=0.05, num_leaves=15, min_child_samples=20))` — one `LGBMRegressor(objective="quantile", alpha=τ)` per partner per τ, features = calendar features + segment drivers pivoted wide (`n_active_<segment>`) + campaign lift for the partner's products + lags 7/14/28 of the target (target = `outflow` when `use_obligations=False`, else `outflow_residual`, with confirmed amounts added back in `predict`). Model (b) is `use_obligations=False`; model (c) is `use_obligations=True`.

- [ ] **Step 1: Tests**: `test_drivers_no_leakage` (drivers for dates after `as_of` do not change when events after `as_of` are altered); `test_calendar_features_payday_mass`; `test_confirmed_obligations_only_confirmed_rows`; `test_detect_recurring_monthly_bill` (a synthetic user paying 100 on the 10th for 5 months → `period_days ≈ 30`, `next_date` the 10th of the next month, `p_occur ≥ 0.8`); `test_split_residual_non_negative`; `test_aggregate_lgbm_beats_naive_on_sim` (on the 12-month base dataset, 8 origins: mean `pinball_q90` of (b) < that of SeasonalNaive on at least 4 of 6 partners); `test_model_c_adds_confirmed_back` (sum of q50 of (c) ≥ confirmed amount for each date).
- [ ] **Step 2–4:** FAIL → implement → PASS. **Step 5: Commit** `feat: drivers, obligations layer and aggregate LightGBM models with drivers`.

---

### Task 7: Segment × product model (d) with shared factor and Monte Carlo

**Files:**
- Create: `src/treasury/models/segment_lgbm.py`, `src/treasury/montecarlo.py`
- Test: `tests/test_segment_lgbm.py`, `tests/test_montecarlo.py`

**Interfaces:**
- `segment_lgbm.py`: `SegmentLGBM(name="segment_factor", n_paths=2000, use_factor=True)`: fits one global `LGBMRegressor(objective="tweedie", tweedie_variance_power=1.3)` on the residual at `date × segment × product` with features = calendar + `n_active` of the segment + campaign lift + `segment` and `product` as categoricals + lags 7/14; estimates `sigma_f` and `phi_f` from the backtest residuals of the fitted model aggregated by day (log of ratio actual/predicted total, AR(1) fit) when `use_factor=True`, else `sigma_f = 0`; `predict` calls `montecarlo.simulate_paths` and returns partner-level quantiles from the paths, plus stores `self.last_paths` (array `[n_paths, n_dates, n_partners]`) for the policy.
- `montecarlo.py`: `simulate_paths(mu: np.ndarray [n_dates, n_nodes], dispersion: np.ndarray [n_nodes], node_partner: np.ndarray [n_nodes], sigma_f: float, phi_f: float, n_paths: int, seed: int) -> np.ndarray [n_paths, n_dates, n_partners]`: draw `log f_d` AR(1) across dates, node draws from Tweedie-like Gamma with mean `mu * f_d` and the node's dispersion, sum nodes to partners; `need_from_paths(paths, window: int, direction_sign: np.ndarray | None) -> np.ndarray [n_paths, n_partners]` = max cumulative sum over the first `window` days; `cumulative_quantiles(paths, taus) -> pd.DataFrame`.
- `use_factor=False` is the ablation "bottom-up sin factor común".

- [ ] **Step 1: Tests**: `test_paths_shape_and_mean` (mean of paths ≈ `mu` summed per partner within 3 %); `test_factor_increases_aggregate_variance` (same `mu`, `sigma_f=0.15` gives aggregate CV > 3× the `sigma_f=0` CV at 200 nodes); `test_need_ge_terminal_sum` (`need_from_paths ≥` sum over the window on every path); `test_segment_model_pit_flat_with_factor` (on the base dataset, `pit_ks` of `SegmentLGBM(use_factor=True)` < `pit_ks` of `use_factor=False`).
- [ ] **Step 2–4:** FAIL → implement → PASS. **Step 5: Commit** `feat: segment x product Tweedie model with shared factor and Monte Carlo aggregation`.

---

### Task 8: Policy, backtest, factorial and ablation tables

**Files:**
- Create: `config/policy.yaml`, `src/treasury/policy.py`, `src/treasury/backtest.py`, `src/treasury/experiments.py`
- Modify: `src/treasury/cli.py` (add `backtest` and `experiments` commands)
- Test: `tests/test_policy.py`, `tests/test_backtest.py`, `tests/test_experiments.py`

**Interfaces:**
- `config/policy.yaml`: `alpha: 0.99`, `cost_of_capital_annual: 0.12`, `cost_per_usd_rejected: 0.05`, `lot_size: 1000`, `review_hour: 9`, `fixed_buffer_days: 3`.
- `policy.py`: `target_balance(need_samples: np.ndarray, alpha) -> float`; `recommend_deposit(paths_partner: np.ndarray [n_paths, n_dates], opening_available: float, pending_credits: list[Credit], arrival_at: Timestamp, alpha, review_at: Timestamp) -> Decision(amount, p_unresolvable, target, expected_shortfall_if_none)`: builds, for each path, the daily `Flow`s (a path's day-d outflow placed at the partner's `settle_cutoff_hour` of day d — conservative: a credit on day d counts only if `arrival_at ≤` that hour), runs `ledger.min_deposit`, takes the α-quantile of `amount` across paths, and `p_unresolvable` = share of paths with `unresolvable=True`; amount rounded up to `lot_size`. `fixed_buffer_decision(trailing_daily_mean, days, opening_available) -> Decision` as the reference policy.
- `backtest.py`: `run(events_routed, users, cal, partners, rails, model_factory, policy_cfg, rail_name: str, policy: Literal["fixed","forecast"], origins, horizon=7, central_reserve: float) -> BacktestResult` with `ledger_log` (`at, partner, balance, in_transit`), `decisions`, and `metrics`: `capital_total_mean` (partner available + in-transit counted once + central reserve), `shortfall_windows` (count and rate), `shortfall_amount_total`, `shortfall_duration_hours_mean`, `n_transfers`, `fees`, `cost_total = k·capital + fees + cost_per_usd_rejected·shortfall_amount`. Review once per day at `review_hour` (twice for 24/7 rails: 9 and 18). Realized flows come from the simulated events; forecasts from the model refit at each origin and reused within the week.
- `experiments.py`: `ablation_table(dataset, origins) -> pd.DataFrame` rows = models `(a) seasonal_naive, (b) aggregate_drivers, (c) aggregate_drivers+obligations, (d) segment_factor, (d-) segment_nofactor`, columns = `summarize` metrics averaged over partners and horizons; `factorial_table(dataset) -> pd.DataFrame` 2×2 (`reference` = SeasonalNaive+fixed buffer vs `proposed` = (d) + forecast policy) × (`wire`, `stablecoin`) with `capital_total_mean, shortfall_rate, cost_total`; `frontier(dataset, alphas=(0.9,0.95,0.99,0.995)) -> pd.DataFrame` of capital vs shortfall rate per rail; `designed_to_lose(seed) -> pd.DataFrame`: a dataset with five archetypes copied from `salaried_formal` (identical parameters) and 3 months of history, returns the ablation table for it; `unknown_scenario_eval(dataset_without_scenario, dataset_with_scenario)` trains on the first and evaluates on the second (a `Campaign` with a different shape than the training campaigns and a `CohortWave`).
- CLI: `treasury backtest --data data/sim/base --model segment_factor --rail stablecoin --policy forecast`; `treasury experiments --data data/sim/base --out reports/experiments/` writing the four CSVs.

- [ ] **Step 1: Tests**: `test_target_balance_is_quantile`; `test_recommend_deposit_flags_unresolvable_when_shortfall_before_arrival`; `test_monday_accumulates_weekend_for_wire` (a partner draining 100/day 7/7, wire rail, opening Friday equal to exactly 3 days → no shortfall; opening 2.5 days → shortfall Sunday; opening on Friday for a stablecoin rail with twice-daily review needs < 1.5 days); `test_capital_counts_in_transit_once` (total capital unchanged at the instant a credit lands); `test_factorial_table_has_four_cells`; `test_designed_to_lose_segment_does_not_win` (on the designed dataset, `pinball_q90` of (d) ≥ 0.97 × that of (c), i.e. not a clear win; if (d) wins clearly the test fails and the comparison must be inspected); `test_unknown_scenario_eval_runs`.
- [ ] **Step 2–4:** FAIL → implement → PASS. **Step 5: Run** `treasury experiments` on the base dataset, commit the CSVs under `reports/experiments/` with the `params.json` of the dataset they came from.
- [ ] **Step 6: Commit** `feat: funding policy, walk-forward backtest, factorial and ablation experiments`.

---

### Task 9: Agent that proposes transfers with human approval

**Files:**
- Create: `src/treasury/agent/__init__.py`, `src/treasury/agent/tools.py`, `src/treasury/agent/run.py`, `src/treasury/agent/queue.py`
- Modify: `pyproject.toml` (add `anthropic`), `src/treasury/cli.py` (add `agent propose` and `agent approve`)
- Test: `tests/test_agent_queue.py`, `tests/test_agent_tools.py`

**Interfaces:**
- Before writing any Anthropic SDK code, the implementer loads the `claude-api` skill and uses the model id it gives for the most capable current model; the API key comes from `ANTHROPIC_API_KEY` in the environment, never from a file in the repo.
- `queue.py`: `ApprovalQueue(path: Path)` backed by a JSONL file; `propose(Proposal(id, created_at, partner, rail, amount, tier, rationale, forecast_run_id)) -> Proposal`; `approve(id, approver)`, `reject(id, approver, reason)`; `list(status=None)`. Tiers from `config/policy.yaml` → `tiers: {T1_auto_max: 50000, T2_single_max: 250000, T3_dual_max: 1000000}`; above T3 → `T4_blocked`.
- `tools.py`: pure functions the agent may call, each returning JSON-serialisable dicts: `get_forecast(partner, run_id)`, `get_policy_decision(partner, rail)` (from `policy.recommend_deposit`), `get_balance(partner)`, `propose_transfer(partner, rail, amount, rationale)` (writes to the queue; the only side effect; never executes), `explain_components(partner, date)` (confirmed / predicted-recurring / residual / factor shares from the model's last run).
- `run.py`: `propose_for_day(as_of: Timestamp, partners, …) -> list[Proposal]`: for each partner, the deterministic policy computes the decision first; the LLM receives decision + forecast + components via tool calling and must return a rationale that cites the numbers; a validation step checks every number in the rationale appears in the tool outputs (reject the rationale otherwise and fall back to a templated one). The LLM cannot change `amount`; it can only flag `exception: str | None`.

- [ ] **Step 1: Tests**: `test_queue_roundtrip_and_tiers` (50 001 → T2, 1 000 001 → T4 blocked and `propose` raises); `test_propose_transfer_tool_only_enqueues` (no ledger change); `test_rationale_numbers_validated` (a rationale with a number not in tool outputs is rejected; uses a fake LLM client).
- [ ] **Step 2–4:** FAIL → implement → PASS (LLM calls mocked in tests; one manual run against the real API documented in README).
- [ ] **Step 5: Commit** `feat: agent proposes transfers through an approval queue; policy decides, LLM explains`.

---

### Task 10: Streamlit dashboard for the demo

**Files:**
- Create: `src/treasury/dashboard/app.py`
- Modify: `pyproject.toml` (add `streamlit`, `plotly`), `README.md` (how to run the demo end-to-end)

**Interfaces:**
- Consumes: CSVs from `experiments.py`, parquet from the simulator, `ApprovalQueue`, `simulate_events` with scenarios.
- Tabs: **Ablation** (table a–d and PIT histograms per model), **Factorial** (2×2 capital vs shortfall, cost), **Frontier** (capital vs shortfall rate per rail, α slider), **Stress** (sliders for campaign lift, cohort size, FX jump, partner outage → reruns simulator on the last 60 days with the saved seed, re-forecasts with (d) and shows new target balance and deposit per partner with the confirmed / predicted / residual / factor decomposition), **Approvals** (queue with approve/reject buttons writing to the JSONL).
- Run: `uv run streamlit run src/treasury/dashboard/app.py`.

- [ ] **Step 1:** Build the app reading the Task 8 outputs; the stress tab must finish a rerun in < 10 s for 20 000 users × 60 days.
- [ ] **Step 2:** Manual check in the browser: every tab renders with the base dataset; stress rerun changes the deposit of `bills_aggregator` when the campaign lift is set to 1.5 on `bill_payment`.
- [ ] **Step 3:** Update `README.md` with the five things the jury must see (ablation table, factorial, frontier, live stress, approval) and the success criterion sentence.
- [ ] **Step 4: Commit** `feat: Streamlit demo dashboard`.
