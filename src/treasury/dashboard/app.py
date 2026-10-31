"""The demo's single screen. Run: ``uv run streamlit run src/treasury/dashboard/app.py``.

Only renders: the tables come from ``treasury.dashboard.data``, the decisions from the existing
policy, model and approval queue. Nothing here executes a payment.
"""

from __future__ import annotations

import os
import time
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from treasury.agent.queue import ApprovalQueue
from treasury.agent.run import build_context, propose_for_day
from treasury.backtest import CONFIG, Dataset
from treasury.dashboard import data
from treasury.experiments import zero_shortfall_alpha
from treasury.policy import PolicyConfig, load_policy
from treasury.simulate import PAYDAY_HYPOTHESES

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "data" / "sim" / "base"
REPORTS = ROOT / "reports" / "experiments"
QUEUE = ROOT / "data" / "queue.jsonl"
SUCCESS = ("**Criterio de éxito:** menos capital total inmovilizado, al mismo nivel de servicio, "
           "en escenarios que el modelo no conoce de antemano.")
MODEL_NAMES = {
    "(a)": "naive estacional", "(b)": "LightGBM agregado + drivers", "(c)": "(b) + obligaciones conocidas",
    "(d)": "segmento × producto + factor común", "(d-)": "(d) sin factor común",
}
RAIL_NAMES = {"wire": "Transferencia (wire)", "stablecoin": "Stablecoin"}
POLICY = load_policy(CONFIG / "policy.yaml")


def ars(x: float) -> str:
    """Millions of ARS with Argentine separators: ``$ 1.680,5 M``."""
    if pd.isna(x):
        return "—"
    return "$ " + f"{x / 1e6:,.1f} M".replace(",", "_").replace(".", ",").replace("_", ".")


def pct(x: float, digits: int = 1) -> str:
    return "—" if pd.isna(x) else f"{x:.{digits}%}".replace(".", ",")


def md(text: str) -> None:
    """``st.markdown`` with ``$`` escaped, so amounts are not read as LaTeX."""
    st.markdown(text.replace("$", "\\$"))


def num(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def signed_ars(x: float) -> str:
    return ars(0.0) if abs(x) < 5e4 else ("+" if x > 0 else "−") + ars(abs(x))


def cell_names(cfg: PolicyConfig) -> dict[str, str]:
    return {"reference": f"buffer fijo (config: {num(cfg.fixed_buffer_days)} días)",
            "proposed": f"propuesto (d), α = {num(cfg.alpha)}", "reference_matched": "buffer fijo al mismo servicio"}


@st.cache_data
def experiments() -> dict[str, pd.DataFrame]:
    return data.load_experiments(REPORTS)


@st.cache_resource
def base_dataset() -> Dataset:
    return Dataset.load(BASE)


@st.cache_data(persist="disk", show_spinner="Calculando PIT de los cinco modelos (4 orígenes)…")
def pit_table() -> pd.DataFrame:
    return data.pit_values(base_dataset(), n_origins=4)


@st.cache_resource(show_spinner="Simulando la historia con campañas pasadas y ajustando el modelo (d)…")
def stress_base() -> data.StressBase:
    return data.build_stress_base(base_dataset(), n_paths=1000)


@st.cache_resource(show_spinner="Corrida base del estrés…")
def baseline_run() -> data.StressRun:
    return data.stress_run(stress_base(), data.StressSpec())


def summary_tab(tables: dict[str, pd.DataFrame]) -> None:
    st.markdown(SUCCESS)
    head = data.headline(tables["factorial"])
    cols = st.columns(len(head))
    for col, row in zip(cols, head.itertuples()):
        col.metric(f"{RAIL_NAMES[row.rail]}: capital ahorrado al mismo servicio", pct(row.capital_saved, 0), border=True)
        with col:
            md(f"Propuesto **{ars(row.proposed_capital)}** (faltantes {pct(row.proposed_shortfall_rate, 2)}) vs "
               f"buffer fijo de **{num(row.matched_buffer_days)} días** **{ars(row.matched_capital)}** (faltantes "
               f"{pct(row.matched_shortfall_rate, 2)}).")
    st.caption("Backtest walk-forward sobre datos sintéticos: muestra mecanismo y sensibilidad bajo supuestos, no ahorro "
               "real.")
    st.subheader("Cuando el escenario no estaba anunciado")
    sur = data.surprise_summary(tables["unknown_scenario"])
    sur = sur.assign(modelo=sur["label"] + " " + sur["label"].map(MODEL_NAMES),
                     escenario=sur["variant"].map({"announced": "anunciado", "surprise": "sorpresa"}))
    st.dataframe(pd.DataFrame({
        "modelo": sur["modelo"], "escenario": sur["escenario"], "capital medio": sur["capital_total_mean"].map(ars),
        "tasa de faltantes": sur["shortfall_rate"].map(lambda x: pct(x, 2)), "cobertura 90 %": sur["cov_90"].map(pct),
    }), hide_index=True)
    st.caption(f"{data.unknown_scenarios_text()} que no están en la historia. 'Sorpresa' = los drivers no los traen. "
               "Riel stablecoin, política de pronóstico.")
    st.subheader("Cómo leer esto")
    st.markdown(
        "Cada partner (red de tarjetas, agregador de facturas, exchange…) necesita saldo prefondeado para pagar lo que "
        "los usuarios gastan. Un **buffer fijo** guarda N días de salida promedio; la **política propuesta** guarda el "
        "cuantil α de la necesidad simulada por el modelo (d) hasta que pueda llegar el próximo depósito. Para comparar "
        "en serio, buscamos el buffer fijo con **menos días que logra la misma tasa de faltantes** que la propuesta "
        "(fila *al mismo servicio*): la diferencia de capital entre esos dos es el ahorro. Todo en backtest "
        "walk-forward (el modelo se reentrena en cada origen y no ve el futuro), excluyendo los días de arranque."
    )
    with st.expander("Límites conocidos"):
        st.markdown(
            "- **Datos sintéticos.** La demo muestra el mecanismo y su sensibilidad bajo supuestos, no ahorros reales.\n"
            "- **phi_f ≈ 0.** La autocorrelación del factor común estimada en el holdout es casi nula: los shocks "
            "macro no persisten entre días en el modelo.\n"
            "- **Servicio realizado vs nominal.** α es el cuantil por decisión, no el servicio: la política es "
            "conservadora y el servicio realizado queda por encima de α (ver Frontera).\n"
            "- **Agente con LLM.** El camino con LLM solo está probado con un cliente falso; falta una corrida "
            "contra la API real."
        )


def ablation_tab(tables: dict[str, pd.DataFrame]) -> None:
    st.markdown("Scores de pronóstico walk-forward, horizontes 1–14, 8 orígenes semanales. Menor es mejor salvo "
                "`cov_90` (ideal 0,90). `pit_ks` mide cuán lejos está el PIT de la uniforme (0 = calibrado).")
    per_partner = st.toggle("Ver por partner")
    if per_partner:
        table = tables["ablation_by_partner"]
        partner = st.selectbox("Partner", sorted(table["partner"].unique()))
        table = table[table["partner"] == partner]
    else:
        table = tables["ablation_pooled"]
    view = table[data.ABLATION_COLUMNS].assign(descripcion=table["label"].map(MODEL_NAMES))
    st.dataframe(view[["label", "descripcion", *data.ABLATION_COLUMNS[2:]]].style.format(
        {"wape_q50": "{:.3f}", "pinball_q90": lambda x: ars(x), "cov_90": "{:.3f}", "pit_ks": "{:.3f}"}),
        hide_index=True)
    st.subheader("Histogramas PIT")
    st.caption("PIT de cada punto pronosticado (4 orígenes, 14 días, 6 partners). Plano = bien calibrado; en U = "
               "intervalos demasiado angostos (ver (d-)); joroba al centro = demasiado anchos.")
    pits = pit_table()
    pits = pits.assign(modelo=pits["label"] + " " + pits["label"].map(MODEL_NAMES))
    fig = px.histogram(pits, x="pit", facet_col="modelo", nbins=10, histnorm="probability density",
                       range_x=[0, 1], facet_col_spacing=0.03)
    fig.add_hline(y=1.0, line_dash="dot", line_color="gray")
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    fig.update_layout(height=320, margin={"t": 40, "b": 10}, yaxis_title="densidad", bargap=0.05)
    fig.update_yaxes(rangemode="tozero")
    st.plotly_chart(fig)
    with st.expander("Caso diseñado para que el bottom-up pierda"):
        lose = tables["designed_to_lose"]
        md(f"Cinco segmentos idénticos (copias de `salaried_formal`), 4 orígenes: partir por segmento no aporta "
           f"información. **{data.designed_to_lose_sentence(lose)}.**")
        st.dataframe(lose.assign(descripcion=lose["label"].map(MODEL_NAMES))[
            ["label", "descripcion", "wape_q50", "pinball_q90", "crps", "cov_90", "pit_ks"]].style.format(
            {"wape_q50": "{:.3f}", "pinball_q90": lambda x: ars(x), "crps": lambda x: ars(x), "cov_90": "{:.3f}",
             "pit_ks": "{:.3f}"}), hide_index=True)


def factorial_tab(tables: dict[str, pd.DataFrame]) -> None:
    view = data.factorial_view(tables["factorial"])
    days, alpha = num(POLICY.fixed_buffer_days), num(POLICY.alpha)
    rates = "; ".join(
        f"{rail}: {pct(g.loc[g['cell'] == 'reference', 'shortfall_rate'].iloc[0], 1)} el buffer, "
        f"{pct(g.loc[g['cell'] == 'proposed', 'shortfall_rate'].iloc[0], 1)} el propuesto"
        for rail, g in view.groupby("rail", sort=False))
    st.warning(f"Las celdas con los valores de config (**buffer fijo de {days} días** y **propuesto con α = {alpha}**) "
               f"**no están al mismo nivel de servicio** (tasa de faltantes {rates}). La comparación que responde al "
               "criterio de éxito es *propuesto* vs *buffer fijo al mismo servicio*.")
    for rail, g in view.groupby("rail", sort=False):
        st.subheader(RAIL_NAMES[rail])
        st.dataframe(pd.DataFrame({
            "celda": g["cell"].map(cell_names(POLICY)),
            "días de buffer": g["buffer_days"].map(lambda x: "—" if pd.isna(x) else num(x)),
            "capital medio inmovilizado": g["capital_total_mean"].map(ars),
            "tasa de faltantes": g["shortfall_rate"].map(lambda x: pct(x, 2)),
            "costo total": g["cost_total"].map(ars), "transferencias": g["n_transfers"],
            "mismo servicio que el propuesto": g["equal_service"].map({True: "sí", False: "no"}),
        }), hide_index=True)
        st.caption(f"Partners fuera de este riel (usan su único riel): {g['rail_note'].iloc[0]}.")
    st.caption("Costo total = costo de capital (12 % anual) + comisiones de riel + 5 % de cada peso no cubierto.")


def frontier_tab(tables: dict[str, pd.DataFrame]) -> None:
    fr = tables["frontier"]
    fr = fr.assign(
        serie=fr["policy"].map({"forecast": "propuesto (d), barrido de α", "fixed": "buffer fijo, barrido de días"}),
        etiqueta=[f"α={num(p)}" if pol == "forecast" else f"{num(p)} d" for pol, p in zip(fr["policy"], fr["param"])],
        riel=fr["rail"].map(RAIL_NAMES), capital_m=fr["capital_total_mean"] / 1e6,
        faltantes=fr["shortfall_rate"] * 100,
    )
    fig = px.line(fr, x="faltantes", y="capital_m", color="serie", facet_col="riel", markers=True, text="etiqueta",
                  color_discrete_sequence=["#d1495b", "#8d99ae"], labels={"faltantes": "tasa de faltantes realizada (%)", "capital_m": "capital medio (M ARS)"})
    fig.update_traces(textposition="top right", textfont_size=10)
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    fig.update_layout(height=460, legend={"title_text": "", "orientation": "h", "y": -0.2}, margin={"t": 40})
    st.plotly_chart(fig)
    zero = zero_shortfall_alpha(fr)
    reached = " y ".join(f"α ≥ {num(a)} en {rail}" for rail, a in zero.items() if a is not None)
    missing = ", ".join(rail for rail, a in zero.items() if a is None)
    st.caption("Abajo a la izquierda es mejor: menos capital y menos faltantes. α no es el servicio realizado"
               + (f": con {reached} la tasa de faltantes post-arranque ya es 0 %" if reached else "")
               + (f"; en {missing} ningún α del barrido llega a 0 %" if missing else "") + ".")
    alphas = sorted(fr.loc[fr["policy"] == "forecast", "param"].unique())
    alpha = st.select_slider("α", options=alphas, value=POLICY.alpha if POLICY.alpha in alphas else alphas[-1],
                             format_func=num)
    at = data.frontier_at_alpha(tables["frontier"], alpha, tables["factorial"])
    st.dataframe(pd.DataFrame({
        "riel": at["rail"].map(RAIL_NAMES), "capital propuesto": at["proposed_capital"].map(ars),
        "faltantes propuesto": at["proposed_shortfall_rate"].map(lambda x: pct(x, 2)),
        "buffer fijo más barato igual de seguro": at["fixed_days"].map(lambda x: "ninguno" if pd.isna(x) else f"{num(x)} días"),
        "capital buffer": at["fixed_capital"].map(ars),
        "faltantes buffer": at["fixed_shortfall_rate"].map(lambda x: pct(x, 2)),
        "capital ahorrado": at["capital_saved"].map(lambda x: pct(x, 0)),
    }), hide_index=True)
    if (at["source"] == "factorial").all():
        st.caption(f"En α = {num(alpha)} (el de la config) el buffer es el del Factorial, buscado fino por bisección: "
                   "el mismo ahorro que el Resumen.")
    else:
        st.caption("En este α el buffer sale del barrido grueso de la frontera (2–10 días), no de la bisección del "
                   "Factorial: el ahorro es aproximado.")


def _stress_form(sb: data.StressBase) -> data.StressSpec | None:
    products = sorted(c.removeprefix("campaign_lift_") for c in sb.train.drivers if c.startswith("campaign_lift_"))
    segments = sorted(sb.archetypes["archetypes"])
    partners = list(sb.partners)
    days = [d.date() for d in sb.dates]
    saved = sb.params.payday_hypothesis
    with st.form("stress"):
        c1, c2, c3 = st.columns(3)
        with c1:
            lift = st.slider("Campaña: multiplicador", 1.0, 2.0, 1.0, 0.1)
            product = st.selectbox("Producto en campaña", products, index=products.index("bill_payment"))
            payday = st.radio("Hipótesis de día de cobro", list(PAYDAY_HYPOTHESES), index=list(PAYDAY_HYPOTHESES).index(saved),
                              horizontal=True)
        with c2:
            cohort = st.slider("Ola de usuarios nuevos", 0, 10_000, 0, 500)
            segment = st.selectbox("Segmento de la ola", segments, index=segments.index("young_heavy"))
            fx = st.slider("Salto cambiario: multiplicador de crypto_buy", 1.0, 4.0, 1.0, 0.5)
            fx_day = st.select_slider("Día del salto", options=list(range(len(days))), format_func=lambda i: str(days[i]))
        with c3:
            outage = st.checkbox("Caída de un partner toda la semana")
            down = st.selectbox("Partner caído", partners, index=partners.index("bills_aggregator"))
            reroute = st.selectbox("Se reenruta a", partners, index=partners.index("remittance"))
        if not st.form_submit_button("Recalcular", type="primary"):
            return None
    if outage and reroute == down:
        st.error("El partner caído no puede reenrutarse a sí mismo.")
        return None
    return data.StressSpec(campaign_lift=lift, campaign_product=product, cohort_size=cohort, cohort_segment=segment,
                           fx_lift=fx, fx_day=fx_day, outage=outage, outage_partner=down, reroute_to=reroute,
                           payday_hypothesis=None if payday == saved else payday)


def stress_tab() -> None:
    sb, base = stress_base(), baseline_run()
    st.markdown(
        f"Simula **una semana nueva con la misma población y semilla** que la base ({data.STRESS_DAYS} días que "
        f"terminan el **{sb.dates[-1].date()}**, con los escenarios elegidos sobre la semana **{sb.dates[0].date()} – "
        f"{sb.dates[-1].date()}**): el simulador consume otro tramo de su generador aleatorio, así que no repite los "
        "últimos días de la historia base. El modelo (d), ajustado con la historia anterior, pronostica esa semana y "
        f"la política decide en la revisión de las "
        f"**{data.review_at(sb.as_of):%H:%M} del {sb.as_of.date()}**, sobre stablecoin (o el único riel del partner). "
        "Cada partner parte con el objetivo de la corrida base: el depósito es lo que el escenario agrega. "
        "Este modelo se ajusta sobre la población base re-simulada con tres campañas pasadas (feb, abr, jun), porque "
        "los datos base no tienen campañas y sin ellas no podría aprender su efecto; **no es el modelo de las otras "
        "pestañas**."
    )
    spec = _stress_form(sb)
    if spec is not None:
        began = time.perf_counter()
        st.session_state["stress_result"] = (spec, data.stress_run(sb, spec, balances=base.balances))
        st.session_state["stress_seconds"] = time.perf_counter() - began
    spec, run = st.session_state.get("stress_result", (data.StressSpec(), base))
    if "stress_seconds" in st.session_state:
        st.caption(f"Recalculado en {st.session_state['stress_seconds']:.1f} s.")
    scenarios = spec.scenarios(sb.dates[0].date(), sb.dates[-1].date())
    st.markdown("**Escenarios activos:** " + (", ".join(type(s).__name__ for s in scenarios) or "ninguno")
                + ("" if spec.payday_hypothesis is None else f", cobro {spec.payday_hypothesis}"))
    diff = data.compare(base.table, run.table)
    st.dataframe(pd.DataFrame({
        "partner": diff["partner"], "riel": diff["rail_used"],
        "objetivo base": base.table["target"].map(ars), "objetivo escenario": diff["target"].map(ars),
        "Δ objetivo": diff["delta_target"].map(signed_ars), "depósito": diff["amount"].map(ars),
        "Δ depósito": diff["delta_amount"].map(signed_ars),
        "Δ pronóstico semana": diff["delta_forecast_week"].map(signed_ars),
        "Δ salida simulada semana": diff["delta_realized_week"].map(signed_ars),
        "p_unresolvable": diff["p_unresolvable"].map(pct),
    }), hide_index=True)
    st.info(
        "El modelo solo ve lo que viene en los drivers: campañas y salto cambiario (vía `campaign_lift`, aprendido de "
        "campañas pasadas en la historia) y olas de usuarios (vía `n_active`). **No ve caídas de partner ni la "
        "hipótesis de cobro**: esas solo mueven la salida simulada. Esta semana no tiene días hábiles 1–4, así que la "
        "hipótesis de cobro casi no cambia nada. El objetivo cubre hasta que pueda llegar el próximo depósito, así que "
        "un shock en días posteriores mueve el pronóstico de la semana pero no el depósito de hoy."
    )
    partner = st.selectbox("Descomposición del pronóstico para", list(sb.partners))
    comp = data.components(run, partner)
    segs = [c for c in comp.columns if c.startswith("segment:")]
    fig = go.Figure([go.Bar(name="confirmado (débitos automáticos)", x=comp["date"], y=comp["confirmed"] / 1e6)]
                    + [go.Bar(name=s.removeprefix("segment:"), x=comp["date"], y=comp[s] / 1e6) for s in segs]
                    + [go.Scatter(name="recurrente predicho, detectado en la historia (parte del residuo)",
                                  x=comp["date"],
                                  y=comp["predicted_recurring"] / 1e6, mode="markers", marker_symbol="diamond",
                                  marker_size=10)])
    fig.update_layout(barmode="stack", height=380, yaxis_title="media pronosticada (M ARS)", margin={"t": 20})
    st.plotly_chart(fig)
    st.dataframe(pd.DataFrame({
        "fecha": comp["date"], "confirmado": comp["confirmed"].map(ars),
        "recurrente predicho (detectado en la historia)": comp["predicted_recurring"].map(ars),
        "residuo": comp["residual_total"].map(ars),
        "participación del factor común": comp["factor_share"].map(pct),
    }), hide_index=True)


def _llm_client():
    import anthropic

    return anthropic.Anthropic()


def approvals_tab() -> None:
    queue = ApprovalQueue(QUEUE)
    st.caption(f"Cola `{QUEUE.relative_to(ROOT)}`. La política decide el monto, el LLM solo lo explica y una persona "
               "aprueba por tramo (T1 automático, T2 una firma, T3 dos firmas distintas). Nada ejecuta un pago.")
    st.caption(f"Saldo inicial de cada partner: el objetivo que la propia política fijó en la última revisión del día "
               f"anterior ({max(POLICY.review_hours_247):02d}:00 en stablecoin, {POLICY.review_hour:02d}:00 en wire), "
               "con el mismo modelo y nada en tránsito.")
    c1, c2, c3, c4 = st.columns([2, 2, 2, 2], vertical_alignment="bottom")
    as_of = c1.date_input("Fecha de la revisión", date(2026, 10, 26))
    rail = c2.selectbox("Riel preferido", ["stablecoin", "wire"])
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    offline = c3.button("Proponer hoy (sin LLM)")
    online = c4.button("Proponer hoy (con LLM)", disabled=not has_key,
                       help=None if has_key else "Definí ANTHROPIC_API_KEY en el entorno para habilitarlo.")
    if offline or online:
        try:
            with st.spinner("Ajustando el modelo y proponiendo…"):
                ctx = build_context(base_dataset(), pd.Timestamp(as_of), queue, rail=rail, start_balances="target")
                made = propose_for_day(ctx, client=_llm_client() if online else None, rail=rail)
            st.success(f"{len(made)} propuestas para {ctx.forecast_run_id} (las ya existentes no se duplican).")
        except Exception as e:  # noqa: BLE001 - a demo button: any failure (data, API, network) is shown, not raised
            st.error(f"No se pudo proponer para {as_of}: {type(e).__name__}: {e}")
    status = st.segmented_control("Estado", ["todas", "pending", "approved", "rejected", "auto_approved"],
                                  default="todas")
    proposals = queue.list(None if status in (None, "todas") else status)
    frame = data.queue_frame(proposals)
    if frame.empty:
        st.info("No hay propuestas con ese estado.")
        return
    st.dataframe(pd.DataFrame({
        "creada": frame["created_at"].str[:19], "partner": frame["partner"], "riel": frame["rail"],
        "monto": frame["amount"].map(ars), "tramo": frame["tier"], "estado": frame["status"],
        "firmas": frame["approvals"], "firmantes": frame["approvers"], "rechazo": frame["rejection"],
        "corrida": frame["forecast_run_id"], "id": frame["id"].str[:8],
    }), hide_index=True)
    for p in sorted((p for p in proposals if p.status == "pending"), key=lambda p: p.created_at, reverse=True):
        with st.expander(f"{p.partner} · {ars(p.amount)} · {p.tier} · {p.forecast_run_id} · {p.id[:8]}"):
            st.caption("Salida del modelo (no verificada)")
            st.text(p.rationale)
            if p.exception:
                st.caption("Excepción marcada por el LLM, salida del modelo (no verificada)")
                st.text(p.exception)
            who = st.text_input("Nombre de quien firma (demo: en producción viene de la identidad autenticada)",
                                key=f"who-{p.id}")
            reason = st.text_input("Motivo (para rechazar)", key=f"why-{p.id}")
            a, r = st.columns(2)
            try:
                if a.button("Aprobar", key=f"ok-{p.id}", type="primary"):
                    queue.approve(p.id, who)
                    st.rerun()
                if r.button("Rechazar", key=f"no-{p.id}"):
                    if not reason.strip():
                        raise ValueError("el rechazo necesita un motivo")
                    queue.reject(p.id, who, reason)
                    st.rerun()
            except ValueError as e:
                st.error(str(e))


def main() -> None:
    st.set_page_config(page_title="Tesorería predictiva", layout="wide")
    st.title("Tesorería predictiva")
    st.caption("Cuánto saldo prefondeado tener en cada partner: pronóstico probabilístico + política + aprobación humana.")
    missing = [f"data/sim/base/{f}" for f in ("users.parquet", "events.parquet", "macro.parquet", "params.json")
               if not (BASE / f).exists()]
    missing += [f"reports/experiments/{t}.csv" for t in data.EXPERIMENT_TABLES if not (REPORTS / f"{t}.csv").exists()]
    if missing:
        st.error(f"Faltan datos: {', '.join(missing)}. Corré `PYTHONPATH=src uv run treasury simulate --users 20000 "
                 "--start 2025-11-01 --end 2026-10-31 --seed 42 --out data/sim/base` y después `PYTHONPATH=src uv run "
                 "treasury experiments --data data/sim/base --out reports/experiments`.")
        st.stop()
    tables = experiments()
    names = ["Resumen", "Ablación", "Factorial", "Frontera", "Estrés", "Aprobaciones"]
    tabs = st.tabs(names, key="tab", on_change="rerun")
    renders = [lambda: summary_tab(tables), lambda: ablation_tab(tables), lambda: factorial_tab(tables),
               lambda: frontier_tab(tables), stress_tab, approvals_tab]
    for tab, render in zip(tabs, renders):
        if tab.open:
            with tab:
                render()


main()
