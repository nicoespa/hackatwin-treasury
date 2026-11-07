# Prefondeo óptimo por partner: del pronóstico probabilístico de salidas a la política de saldo y reposición

Notación común a todo el documento (un partner, un activo USD):
- `X_t` salida diaria pagada desde el saldo en el partner; `μ = E[X_t]`, `σ = sd(X_t)`.
- `L` lead time de reposición (desde que tesorería ordena hasta que el partner acredita); `R` período de revisión (cada cuánto se decide); `T = L + R` ventana de protección.
- `B_t` saldo en el partner; `IP_t = B_t + en tránsito` posición de inventario; `S` nivel objetivo (order-up-to); `s` punto de reorden; `SS` safety stock.
- `k` costo anual de capital; `i = k/365` diario; `F` costo fijo por transferencia; `C_u` costo de faltante por USD no pagado; `C_o` costo de sobrante por USD-día.
- `z_α = Φ⁻¹(α)`; `Q_α(·)` cuantil α.

---

## 1. Modelos clásicos de cash management (Baumol, Miller–Orr, Stone, Eppen–Fama) y qué cambia cuando el lead time pasa de 2–3 días a casi instantáneo

### Takeaway
Los modelos clásicos fijan el saldo objetivo y las bandas de control como función del costo fijo de transferencia `F`, la varianza diaria `σ²` y la tasa de oportunidad `i`; el costo de transferencia entra como raíz cúbica (Miller–Orr) o raíz cuadrada (Baumol), así que abaratar la transferencia es una palanca débil. Ninguno modela el lead time explícitamente (asumen transferencia instantánea), por lo que el efecto del lead time hay que traerlo de la teoría de inventarios (sección 2); además, los supuestos de random walk sin drift y normalidad fallan en datos reales, y un ajuste directo a datos (programación estocástica) bate al Miller–Orr de libro de texto en ~12 % de costo fuera de muestra.

### Cited Findings
- Miller–Orr: spread `H − L = 3 · (3·F·σ²/(4·i))^(1/3)`; punto de retorno `Z = L + spread/3`; límite superior `H = L + spread`; requiere varianza de flujos **diarios** y tasa **diaria**; el retorno no es el punto medio de la banda. Ejemplo ACCA: `L = 8.000`, `F = 50`, `σ² = 4.000.000`, `i = 0,00025` ⇒ spread ≈ 25.303, `Z ≈ 16.434` — [OpenTuition ACCA FM ch.6](https://opentuition.com/acca/fm/practice/guided/ch6-cash-management-models-baumol-miller-orr/); [Eduyush ACCA FM working capital](https://eduyush.com/blogs/acca/acca-fm-working-capital); [acowtancy Miller-Orr notes](https://acowtancy.com/textbook/acca-fm/c2f-managing-cash/miller-orr-model/notes)
- Forma equivalente en la literatura de OR: `Z = L + (3·γ₀·σ²/(4·v))^(1/3)` y `H = 3·Z − 2·L`, con `γ₀` costo fijo de transferencia y `v` costo de tenencia por unidad monetaria y día; política: si `b_{t−1}+f_t > H` o `< L`, transferir `Z − b_{t−1} − f_t`, si no, nada. El modelo asume que los flujos siguen un random walk estacionario con desvío `σ` y minimiza `γ₀·E[n]/τ + v·E[b]` (número esperado de transferencias × costo fijo + saldo promedio × costo de tenencia). "The greater the transfer cost (γ₀), the higher the target cash balance (Z), and the greater the holding cost (v), the lower the target cash balance (Z)." — [Salas-Molina 2019, *Computers & Operations Research* 106:298-306 (preprint RiuNet)](https://riunet.upv.es/bitstream/10251/201125/11/Salas-Molina%20-%20Fitting%20random%20cash%20management%20models%20to%20data.pdf)
- Miller y Orr fijaron `L = 0`; la recomendación de Ross et al. es fijar `L > 0` como colchón precautorio, cuya elección "depende de la aversión al riesgo del cash manager" — [Salas-Molina 2019](https://riunet.upv.es/bitstream/10251/201125/11/Salas-Molina%20-%20Fitting%20random%20cash%20management%20models%20to%20data.pdf)
- Estructura de costos general usada en la literatura reciente de cash management: transferencia con parte fija (`γ₀⁺`, `γ₀⁻`) y variable (`γ₁⁺`, `γ₁⁻`) en cada sentido, costo de tenencia `v` por USD si el saldo de cierre es positivo, penalidad `u` por USD si es negativo. Estructura de ejemplo del caso real: `γ₀⁺ = γ₀⁻ = 20 €`, `γ₁⁺ = γ₁⁻ = 0,01 %`, `v = 0,02 %/día`, `u = ∞` — [Salas-Molina 2019](https://riunet.upv.es/bitstream/10251/201125/11/Salas-Molina%20-%20Fitting%20random%20cash%20management%20models%20to%20data.pdf)
- "The bound-based control approach is based on the strong assumption of a particular probability distribution for cash flows, which is usually assumed to be a normal, independent and stationary cash flow as in Miller and Orr (1966)". Al relajar ese supuesto y ajustar los tres límites `(L, Z, H)` directamente a datos diarios reales de una empresa vía programación estocástica/MILP, el modelo ajustado obtuvo `G(f_test) = C(f_test)/C₀(f_test) = 0,88` frente al Miller–Orr calculado con las ecuaciones de libro, es decir ~12 % menos costo total fuera de muestra; el resultado fue estable al duplicar costos fijos o de tenencia — [Salas-Molina 2019](https://riunet.upv.es/bitstream/10251/201125/11/Salas-Molina%20-%20Fitting%20random%20cash%20management%20models%20to%20data.pdf)
- Stone (1972): modificación de Miller–Orr para cuando se puede pronosticar los flujos a pocos días; usa dos juegos de límites (externos e internos); cruzar un límite externo no dispara una corrección automática, sino que se verifica con el pronóstico si el saldo seguirá fuera de banda. Eppen–Fama (1969) y Stone (1972) proponen más límites que los tres de Miller–Orr — [Michalski, arXiv 1301.3824](https://arxiv.org/pdf/1301.3824); [Salas-Molina 2019](https://riunet.upv.es/bitstream/10251/201125/11/Salas-Molina%20-%20Fitting%20random%20cash%20management%20models%20to%20data.pdf)
- Modelos de ATM (análogo de un partner con drift de salida puro): Simutis et al. (2007) combinan red neuronal de demanda + optimizador de carga y reportan 15–20 % menos costo de mantenimiento en simulación — [Simutis et al., Information Technology and Control (vía xreiss)](https://xreiss.efri.uniri.hr/article.php?id=41470)

### Inferences
- **Baumol** (no encontrado como texto citable en esta ronda, pero es el modelo EOQ aplicado a caja): `C* = sqrt(2·F·D/i)`, con `D` salida total del período y `i` tasa del período; saldo promedio `C*/2`; número de transferencias `D/C*`. Para `D = 200.000·365 = 73 M USD/año`, `F = 30 USD`, `k = 12 %`: `C* ≈ 191.000 USD` ⇒ ~1 transferencia por día. Es el límite determinístico del problema: sólo sirve para el *cycle stock*, no dice nada del colchón de seguridad.
- **Lectura de Miller–Orr para prefondeo.** Con `F = 30` (wire), `σ = 60.000` ⇒ `σ² = 3,6·10⁹`, `i = 0,12/365 = 3,29·10⁻⁴`: `(3·F·σ²/(4·i))^(1/3) ≈ 62.700`, spread ≈ 188.000, `Z = L + 62.700`, `H = L + 188.000`. Si la transferencia on-chain cuesta `F = 2`, el spread baja sólo por el factor `(2/30)^(1/3) = 0,41` ⇒ ≈ 76.000. El costo de transferencia es palanca débil (raíz cúbica); lo que domina el capital inmovilizado es `L` (colchón precautorio), que Miller–Orr deja exógeno.
- **Dónde falla Miller–Orr para un partner de pagos:** (a) asume random walk simétrico sin drift; un saldo de prefondeo tiene drift negativo `−μ` (sólo salidas) y entradas discretas (reposiciones), así que se parece a un inventario con demanda, no a una caja corporativa con cobros y pagos; (b) asume transferencia instantánea — el saldo cruza `L` y "vuelve" a `Z` el mismo día. Con `L_lead = 2–3 días` el modelo subestima el faltante porque durante el lead time el saldo sigue drenando `μ·L_lead ± σ·√L_lead`. La corrección correcta es la de Stone (usar el pronóstico de los próximos días antes de decidir) o, mejor, pasar al marco de inventario de la sección 2 donde `L_lead` es variable explícita.
- **Qué cambia con liquidación 24/7 casi instantánea:** `L_lead → ~0` hace que Miller–Orr vuelva a ser aplicable tal cual (el supuesto de transferencia instantánea se cumple), y permite bajar `L` (colchón precautorio) a lo necesario para cubrir el intervalo entre revisiones. Además, el período de revisión deja de estar atado a cut-offs bancarios (una decisión por día hábil) y puede ser intradiario y en fines de semana; eso reduce `T = L + R` por ambas vías.
- Dado el resultado de Salas-Molina, la recomendación profesional es no usar las fórmulas cerradas como política final, sino como *benchmark* y punto de partida; la política definitiva se ajusta a los datos del partner por simulación/optimización (sección 7).

### Gaps
- No se obtuvo el texto primario de Baumol (1952), Miller–Orr (1966), Eppen–Fama (1969) ni Stone (1972); las fórmulas de Stone/Eppen–Fama no aparecen en ninguna fuente accesible esta ronda (sólo descripciones cualitativas). Para citas formales: Stone, B.K. (1972) *Financial Management* 1(1):72–84; Eppen & Fama (1969) "Cash balance and simple dynamic portfolio problems with proportional costs", *International Economic Review*.
- Las páginas de ACCA consultadas vía fetch no devolvieron el cuerpo (acowtancy) — las fórmulas de Miller–Orr se tomaron de los snippets de búsqueda de OpenTuition/Eduyush y se confirmaron con la forma `Z = L + (3γ₀σ²/4v)^(1/3)`, `H = 3Z − 2L` del paper de Salas-Molina.

---

## 2. Análogos de teoría de inventarios: newsvendor, safety stock `z·σ·√T`, políticas (s,S)/(R,S)/base-stock, lead time estocástico, lost sales vs backorder, y mapeo a prefondeo

### Takeaway
El prefondeo es un problema de inventario de revisión periódica con demanda estocástica (salidas de usuarios), lead time (lag de liquidación), ventas perdidas (pagos rechazados) y costo de capital como costo de tenencia; la política natural es order-up-to `S = μ·T + z·σ_T`, con `σ_T = sqrt(T·σ² + μ²·σ_L²)` cuando el lead time también varía, y el `z` sale del fractil crítico del newsvendor `C_u/(C_u + C_o)`, no de una convención.

### Cited Findings
- Safety stock con lead time constante y demanda variable: `SS = z · σ_d · √L` (`σ_d` desvío por período, `L` en los mismos períodos). Con demanda y lead time variables: `σ_DLT = sqrt(L̄·σ_D² + D̄²·σ_L²)`, `SS = z·σ_DLT`, `z = Φ⁻¹(nivel de servicio de ciclo)`; punto de reorden `ROP = D̄·L̄ + SS`. Ejemplo: `D̄ = 200/sem`, `σ_D = 60`, `L = 2 sem`, `z = 1,65` ⇒ `σ_DLT ≈ 84,9`, `SS ≈ 140` — [Cleverence, safety stock formula](https://www.cleverence.com/articles/for-business/saftey-stock-formula-4382/); [Method.me safety stock guide](https://www.method.me/blog/safety-stock-calculator-guide/); [MetricGate safety stock calculator](https://metricgate.com/docs/safety-stock-calculator/)
- Varias fuentes de divulgación confunden `σ_d` por período con `σ` de la demanda durante el lead time; la forma `√L` requiere `σ_d` por período — [Cleverence](https://www.cleverence.com/articles/for-business/how-to-calculate-safety-stock-formula-5831/)
- Newsvendor: cantidad óptima `q* = F⁻¹((p − c)/p)` con `F⁻¹` inversa generalizada de la CDF de la demanda; `(p − c)/p` es el fractil crítico. Costo de faltante (underage) `(D − q)(p − c)` = ingreso perdido por falta de inventario; costo de sobrante `(q − D)·c`. Con costo de tenencia `h` y costo variable `c_v`: `K(q) = c_f + c_v(q − x) + p·E[max(D − q,0)] + h·E[max(q − D,0)]`, óptimo `q* = F⁻¹((p − c_v)/(p + h))`. Ejemplo normal: `μ = 50`, `σ = 20`, fractil 0,285 ⇒ `q* = μ + σ·Φ⁻¹(0,285) = 38,7`. "Each unit of demand above q is lost in potential sales" (lost sales) — [Wikipedia, Newsvendor model](https://en.wikipedia.org/wiki/Newsvendor_model)
- En cash management la formulación general equivalente penaliza con `u` por USD de saldo negativo y `v` por USD positivo al cierre de cada día (sección 1) — [Salas-Molina 2019](https://riunet.upv.es/bitstream/10251/201125/11/Salas-Molina%20-%20Fitting%20random%20cash%20management%20models%20to%20data.pdf)

### Inferences
- **Mapeo de términos** (prefondeo ↔ inventario):

| Inventario | Prefondeo en partner |
|---|---|
| Demanda por período `D_t` | Salidas diarias pagadas por el partner `X_t` (payouts, compras, retiros) |
| Inventario on-hand | Saldo acreditado en el partner `B_t` |
| Pedido / orden de reposición | Transferencia tesorería → partner (wire, SWIFT, stablecoin) |
| Lead time `L` | Lag de liquidación: cut-off bancario + T+1/T+2 + compliance holds del partner; incluye fines de semana si el rail no opera |
| Período de revisión `R` | Frecuencia de decisión de tesorería (1/día hábil típico; intradiario si el rail es 24/7) |
| En tránsito (pipeline) | Fondos enviados aún no acreditados |
| Posición de inventario `IP` | Saldo + en tránsito = capital de trabajo (NOF) atribuible al partner |
| Stockout | Pago rechazado por saldo insuficiente ("insufficient prefunded balance") |
| Lost sales | Usuario cuyo pago fue rechazado y no reintenta (o reintenta por otro proveedor) |
| Backorder | Pago encolado y reintentado automáticamente al acreditarse la reposición (sólo si el producto lo permite y el usuario tolera el retraso) |
| Costo de tenencia `h` | `k/365` + spread de riesgo de contraparte del partner + costo de exposición FX si el saldo está en moneda distinta a la de financiamiento |
| Costo de faltante `C_u` | Margen perdido + churn + penalidades SLA + daño reputacional por USD rechazado |
| Costo fijo de pedido `F` | Fee de wire / SWIFT / gas + on/off-ramp fijo + costo operativo humano por transferencia |

- **Política (R,S) para prefondeo** (revisión cada `R` días, order-up-to `S`): `S = μ·(L + R) + z·σ·√(L + R)` bajo salidas i.i.d. aproximadamente normales; se ordena `S − IP_t` en cada revisión. **Política (s,S) de revisión continua** (monitoreo en tiempo real del saldo): `s = μ·L + z·σ·√L` como disparador, `S = s + Q` con `Q` del tamaño económico (Baumol/EOQ). **Base-stock** es (s,S) con `S − s` = una unidad, apropiada cuando `F ≈ 0` (rails baratos): se repone cada período lo que salió.
- **Con lead time estocástico** (bancos con holds variables, compliance del partner): `σ_T = sqrt(T̄·σ² + μ²·σ_L²)`. Con `μ = 200.000`, `σ_L = 0,5 día`: el término `μ²σ_L² = 10¹⁰` supera `T̄σ² = 4·3,6·10⁹ = 1,44·10¹⁰` en orden de magnitud similar ⇒ la variabilidad del lag puede pesar tanto como la de la demanda. Un rail con liquidación determinística (finality on-chain en minutos, `σ_L ≈ 0`) elimina ese término completo, no sólo lo acorta.
- **Lost sales vs backorder:** el pago rechazado por saldo insuficiente es predominantemente *lost sales* (el usuario ve "rechazado", no "pendiente"). En modelos lost-sales el nivel óptimo es mayor que en backorder para el mismo `C_u`, porque la demanda no servida no se recupera; si el producto puede encolar y reintentar en minutos (rail instantáneo), parte del faltante se convierte en backorder con costo mucho menor — otra forma en que el lead time corto baja el costo de faltante además del colchón.
- **Nivel de servicio de ciclo vs fill rate.** `α = P(sin faltante en la ventana T)` es lo que fija `z`. El *fill rate* (fracción de USD pagados) es la métrica que ve negocio: para demanda normal, faltante esperado por ciclo `= σ_T · G(z)` con `G(z) = φ(z) − z·(1 − Φ(z))` (función de pérdida normal estándar), y `β = 1 − σ_T·G(z)/(μ·R)`. Para `μR = 200.000`, `σ_T = 120.000`, `z = 2,326`: `G(2,326) ≈ 0,0032` ⇒ faltante esperado ≈ 384 USD/ciclo ⇒ `β ≈ 99,8 %` con `α = 99 %`. Reportar ambos.

### Gaps
- No se accedió a Silver–Pyke–Thomas ni Zipkin para citar directamente las fórmulas (s,S), (R,S), la función de pérdida `G(z)` y lost-sales vs backorder; están en los Inferences como teoría estándar. Referencias para la versión final: Silver, Pyke & Thomas, *Inventory and Production Management in Supply Chains* (4ª ed., caps. 6–7); Zipkin, *Foundations of Inventory Management* (cap. 6–7).

---

## 3. Cómo fijar el nivel de servicio / probabilidad objetivo de faltante: costo del pago rechazado vs costo de tenencia

### Takeaway
El nivel de servicio no debe fijarse por convención (99 %) sino derivarse del fractil crítico `α* = C_u/(C_u + C_o·T)`; como el costo de tenencia por USD-día es minúsculo (`k/365 ≈ 3·10⁻⁴` a `k = 12 %`) frente a casi cualquier estimación del costo por USD rechazado (margen + churn), el óptimo cae en 97–99,5 % y es muy sensible a `C_u`, que hay que estimar con datos propios; las cifras públicas sobre costo de fallos de pago son de encuestas de proveedores y sirven sólo como orden de magnitud.

### Cited Findings
- Costo global de pagos fallidos 2020: USD 118,5 mil millones en fees, mano de obra y negocio perdido (Accuity/LexisNexis, encuesta ~240 respondentes); 60 % de los encuestados dijo que los pagos fallidos les costaron clientes; dos tercios de los fallos por error humano/datos inexactos. Desgloses regionales inconsistentes entre fuentes (Américas USD 33,7 bn; APAC USD 43,7 bn ó 47,3 bn; EMEA USD 41,1 bn) — [LexisNexis Risk Solutions press release 2021](https://risk.lexisnexis.com/about-us/press-room/press-release/20210714-true-cost-of-failed-payments); [PaymentsNEXT](https://paymentsnext.com/?p=14243); [Payments Dive](https://paymentsdive.com/news/failed-payments-cost-over-33-billion-for-north-american-banks-report/603560)
- Estudio 2026 "True Impact of Failed Payments": tres cuartos de las instituciones financieras pierden hasta USD 5 M/año de ingresos de clientes por pagos fallidos — [LexisNexis Risk Solutions 2026](https://risk.lexisnexis.com/about-us/press-room/press-release/20261007-tifp-study)
- False declines (rechazos de pagos legítimos, proxy del rechazo por saldo insuficiente): 40 % de los compradores nuevos rechazados no vuelve a intentar comprar en ese comercio (Forter, vía PaymentsNEXT); 41 % de los consumidores nunca vuelve tras un false decline (ClearSale, vendor) — [PaymentsNEXT](https://paymentsnext.com/?p=12925); [ClearSale](https://www.clear.sale/blog/everything-you-need-to-know-about-false-declines.md)
- Magnitud en EE. UU.: USD 157 bn de ventas e-commerce en riesgo por false declines en 2023, USD 81 bn permanentemente perdidos — [PYMNTS 2025](https://pymnts.com/checkout-conversion/2025/47-percent-of-retailers-say-false-declines-impact-consumer-satisfaction); Checkout.com/Oxford Economics: USD 20,3 bn (2019, 4 países) y USD 50,7 bn más recientemente — [PaymentsNEXT](https://paymentsnext.com/false-declines-cost-merchants-20-3-billion/); [CrowdFund Insider](https://www.crowdfundinsider.com/2023/09/212859-checkout-com-research-reveals-us-firms-lag-behind-in-payment-performance/). Las estimaciones difieren en órdenes de magnitud según metodología y patrocinador.
- Suscripciones: 40 % de los negocios vio aumentar el churn involuntario (por fallos de pago) en el último año; 79 % no tenía estrategia para reducirlo — [PYMNTS](https://www.pymnts.com/?p=3350752)
- Costo de tenencia en el lado del partner: el pre-funding genera "trapped balances in nostro/vostro accounts" y expone a "settlement and credit risks" (riesgo de contraparte) — [Oliver Wyman & J.P. Morgan 2021 (PDF)](https://www.oliverwyman.com/content/dam/oliver-wyman/v2/publications/2021/nov/unlocking-120-billion-value-in-cross-border-payments.pdf)

### Inferences
- **Fórmula de decisión.** Para una ventana de protección de `T` días: `C_o = (k + s_cp + s_fx)·T/365` por USD de sobrante, con `s_cp` prima por riesgo de contraparte (p. ej. spread CDS/implícito del partner o haircut interno) y `s_fx` costo de cobertura/exposición FX si aplica; `C_u` por USD rechazado `= m + c_churn + c_sla`, con `m` margen bruto sobre el pago, `c_churn = P(churn | rechazo) · LTV_restante / ticket_promedio`, `c_sla` penalidad contractual prorrateada. Entonces `α* = C_u/(C_u + C_o)` y `z* = Φ⁻¹(α*)`.
- **Sensibilidad numérica** (`k = 12 %`, `T = 1`, `C_o = 3,3·10⁻⁴`): `C_u = 0,002` (sólo margen de 20 bps) ⇒ `α* = 85,9 %`, `z = 1,08`; `C_u = 0,01` ⇒ `α* = 96,8 %`, `z = 1,85`; `C_u = 0,05` (margen + churn) ⇒ `α* = 99,35 %`, `z = 2,48`; `C_u = 0,20` ⇒ `α* = 99,84 %`, `z = 2,94`. Con `T = 4` los `C_o` se cuadruplican y los `α*` bajan ~1 punto. Conclusión: un negocio de margen fino que ignore el churn infra-asegura; uno que lo cuente bien aterriza en 99–99,5 % de probabilidad de no-faltante por ciclo.
- **Churn como componente dominante.** Con 40 % de no-reintento tras un rechazo (dato de false declines de e-commerce; es proxy, no medida de wallets LATAM), si el LTV restante de un usuario es 20× su ticket promedio, `c_churn ≈ 0,4 · 20 = 8` USD por USD de ticket… lo cual es un orden de magnitud que vuelve `α*` > 99,9 %. En la práctica hay que acotar: no todo USD rechazado es un usuario perdido (un rechazo afecta a un pago, no a la fracción proporcional de USD), así que `C_u` debe calcularse por *transacción* rechazada y convertirse a USD con el ticket medio. Esto es lo que hay que medir con datos propios: tasa de reintento y retención 30/90 días post-rechazo vs grupo de control.
- El costo de tenencia debe incluir el riesgo de dejar dinero en el partner (quiebra, congelamiento, controles de capital en LATAM): un `s_cp` de 2–5 % anual sobre saldos no asegurados es razonable como haircut interno; con stablecoins el riesgo de contraparte se mueve al emisor/custodio y al smart contract, no desaparece.

### Gaps
- No se encontró ningún valor publicado del costo de un pago rechazado *por insuficiencia de prefondeo* en wallets/fintechs; todas las cifras disponibles son de fallos de pago en general (datos incorrectos, cuentas erróneas) o false declines de tarjetas. La estimación de `C_u` debe hacerse con datos internos.
- No se encontraron valores públicos de penalidades SLA entre fintechs y partners de payout por rechazos atribuibles a saldo insuficiente.
- No se verificaron los PDFs completos de LexisNexis/Accuity; los desgloses regionales son contradictorios entre fuentes secundarias.

---

## 4. Uso directo de pronósticos por cuantiles: saldo = cuantil `q` de la salida acumulada sobre `L + R`; agregación correcta de cuantiles diarios

### Takeaway
El nivel objetivo es `S = Q_α(Σ_{t=1}^{T} X_t)`, el cuantil de la **suma** sobre la ventana de protección, y el cuantil de una suma no es la suma de los cuantiles (eso es la cota comonotónica, que sobreestima en factor hasta `√T` bajo independencia); la forma correcta es generar trayectorias conjuntas (muestreo del modelo, copula o block bootstrap de residuos), sumar dentro de cada trayectoria y tomar el cuantil empírico de las sumas.

### Cited Findings
- Para totales sobre una ventana hay tres rutas: sumar medias derivadas de cuantiles por paso, muestrear de las marginales y sumar, o sumar cada trayectoria simulada; "the sum of quantiles is not the quantile of the sum"; la ruta por trayectorias es la que preserva la dependencia temporal (cada camino da un total; la CDF empírica se construye de esos totales) — [Foundation Model Forecasts: Form and Function, arXiv 2510.19345](https://arxiv.org/pdf/2510.19345)
- "Aggregation induces dependence and nonlinear transformations, so combining pointwise intervals is invalid"; el método propuesto simula caminos con block bootstrap sobre secuencias de residuos y toma cuantiles empíricos de las trayectorias agregadas (predicción conforme para totales acumulados) — [Simulation-Augmented Multi-Step Split Conformal Prediction for Aggregated Forecasts, arXiv 2606.16356](https://arxiv.org/abs/2606.16356)
- En pronóstico multi-paso recursivo, los lags futuros son desconocidos y deben generarse dentro de cada trayectoria Monte Carlo — [Bayesian Quantile Deep Echo State Networks, arXiv 2609.17579](https://arxiv.org/pdf/2609.17579)
- Comparación empírica: agregar sumando cuantil a cuantil vs método coherente; el método coherente reduce la pinball loss 0,15 %–0,78 % y da una CDF "more rational" (contexto energía, HEFTCom2024) — [arXiv 2505.10367](https://arxiv.org/pdf/2505.10367)
- Vincentization = combinar linealmente funciones cuantil (para *ensamblar* modelos, no para agregar en el tiempo) — [Aggregating distribution forecasts from deep ensembles, arXiv 2204.02291](https://arxiv.org/html/2204.02291v2)

### Inferences
- **Cota y error de sumar cuantiles.** Bajo independencia y normalidad, `Q_α(ΣX_t) = μT + z_α·σ·√T`, mientras que `ΣQ_α(X_t) = μT + z_α·σ·T`; la segunda sobreestima el colchón en factor `√T` (para `T = 4`: el doble; para `T = 6`: 2,45×). Sumar cuantiles es la cota superior comonotónica (dependencia perfecta), válida sólo si las salidas de días consecutivos son perfectamente correlacionadas.
- **Autocorrelación.** Con salidas AR(1) de coeficiente `ρ`: `Var(Σ_{t=1}^{T} X_t) = σ²·[T + 2·Σ_{k=1}^{T−1} (T − k)·ρ^k]`. Para `ρ = 0,3`, `T = 4`: `Var = 6,21·σ²` ⇒ `σ_T = 2,49·σ` vs `2σ` i.i.d. (+25 % de colchón) y vs `4σ` sumando cuantiles (+100 %). Los payouts tienen autocorrelación positiva real (campañas, ciclos de pago, FX), así que ni i.i.d. ni comonotónico son correctos: hay que estimarla.
- **Procedimiento recomendado (implementable):**
  1. Modelo probabilístico diario (cuantiles por horizonte `h = 1..H`, o distribución paramétrica) con regresores de calendario (día de semana, feriados LATAM y EE. UU., quincena/fin de mes, campañas).
  2. Generar `N` trayectorias (p. ej. 10.000): si el modelo emite cuantiles marginales, usar copula gaussiana con matriz de correlación estimada de los residuos históricos de 1 paso (o block bootstrap de residuos estandarizados, bloques de 5–7 días) para muestrear uniformes dependientes `u_1..u_T` y mapear por la inversa de cada cuantil marginal `X_h = Q_{u_h}^{(h)}`.
  3. `Y^{(n)} = Σ_{h=1}^{T} X_h^{(n)}`; `S = cuantil empírico α de {Y^{(n)}}`.
  4. Ventana `T` por evento de decisión: contar días **calendario** en que el partner paga pero la reposición no puede acreditarse (viernes con wire T+2 ⇒ `T = 5–6`; stablecoin 24/7 ⇒ `T = L + R` constante).
  5. Backtest: cobertura empírica de `S` (fracción de ventanas sin faltante) debe ≈ `α`; pinball/CRPS del modelo sobre la **suma**, no sólo por día.
- Si el equipo arranca sin modelo cuantil, el fallback paramétrico `S = μ̂_T + z·σ̂_T` con `σ̂_T` estimado **directamente** de sumas móviles históricas de `T` días (no de `σ·√T`) ya captura la autocorrelación de forma no paramétrica.

### Gaps
- No se encontró una referencia canónica única sobre agregación temporal de cuantiles para inventario/cash (los papers encontrados son de energía y de foundation models); los Inferences derivan el procedimiento de la teoría general.
- Falta literatura específica sobre newsvendor con pronósticos de cuantiles (p. ej. "quantile regression newsvendor", Ban & Rudin 2019 "The big data newsvendor") — no se alcanzó a buscar en esta ronda; sería la cita académica directa para "poner el saldo en el cuantil del modelo".

---

## 5. Efectos de portafolio multi-partner: pooling, netting, valor de reducir el lead time y de cubrir fines de semana (argumento cuantitativo pro stablecoin)

### Takeaway
Con una tesorería central que puede mover fondos dentro de la ventana de protección, el colchón total cae de `Σ z·σ_i·√T` a `z·√T·sqrt(Σσ_i² + 2Σρ_ij σ_i σ_j)` (ley de la raíz cuadrada de Eppen 1979: `1/√n` para `n` partners i.i.d.), pero ese beneficio **sólo existe si el rail es más rápido que la ventana**; acortar `T` reduce el colchón en `√T`, el pipeline linealmente en `L` y, si cubre fines de semana, elimina el dimensionamiento al peor caso (`T = 5–6` días de viernes a miércoles), con la salvedad de que colas pesadas reducen el beneficio de pooling muy por debajo de `√n`.

### Cited Findings
- Eppen (1979, *Management Science*): agrupar `n` flujos de demanda i.i.d. cuesta `√n` veces menos que servirlos por separado — [Bimpikis & Markakis, Stanford GSB working paper](https://web.stanford.edu/~kostasb/papers/inventory_pooling.pdf)
- Ese resultado "depends critically on the 'light-tailed' nature of the demand uncertainty"; con demanda de cola pesada (estable de índice `α ∈ (1,2)`) el beneficio de pooling es `n^{(α−1)/α}`, "significantly lower than the square-root benefit predicted for normal demand"; simulaciones con power-law y log-normal lo confirman — [Bimpikis & Markakis 2016, *Management Science* 62(6):1800–1813](https://econpapers.repec.org/RePEc:inm:ormnsc:v:62:y:2016:i:6:p:1800-1813)
- Liquidity-saving mechanisms (netting) reducen la liquidez necesaria en plataformas de settlement mayorista — [GFTN, Agorá roundtable](https://gftn.co/insights/architecting-the-future-of-cross-border-payments-an-agora-roundtable)
- "Atomic settlement… will be critical to address the pain points around trapped liquidity, settlement risk, transaction turnaround time"; el uso de CBDC para settlement lleva a "a reduction in transaction fees and liquidity requirements"; la provisión de liquidez debe estar "always present on the network for round-the-clock" operación — [Oliver Wyman & J.P. Morgan 2021 (PDF)](https://www.oliverwyman.com/content/dam/oliver-wyman/v2/publications/2021/nov/unlocking-120-billion-value-in-cross-border-payments.pdf)
- Circle a emisores/adquirentes: "Send near-instant payments, including on weekends, to minimize prefunding needs" y "Reduce capital requirements and program costs by settling in USDC" — [Circle issuer program](https://www.circle.com/issuer-program)
- Visa: prefondeo en stablecoin tratado "as immediately available funds, reducing the need to lock up capital in multi-currency accounts" (piloto USDC/EURC en Visa Direct anunciado en Sibos 2025) — [Glenbrook](https://glenbrook.com/payments_news/visa-direct-taps-stablecoins-to-unlock-faster-funding-for-businesses/); [Cryptometer](https://www.cryptometer.io/news/visa-pilots-stablecoin-pre-funding-with-usdc-and-eurc-for-faster-global-payments/)
- Testimonio de un operador (MANSA): "you overextend yourself because you tie up all your capital in all these different places around the world"; un fundador fintech "had to turn down a hundred million dollars worth of deals" por capital atrapado en prefondeo — [Glenbrook Payments on Fire ep. 278, nov 2025](https://glenbrook.com/?p=55450)

### Inferences
- **Pooling con tesorería central.** Si cada partner `i` tiene colchón `SS_i = z·σ_i·√T_i` y la tesorería mantiene un pool central que puede llegar a cualquier partner en `L_c` días, el sistema equivale a un inventario multi-escalón: colchón local sólo para `T_i' = L_c + R` y colchón central `z·√T_c·sqrt(Σσ_i² + 2Σ_{i<j}ρ_ij σ_i σ_j)`. Con `n = 5` partners de igual `σ`, `ρ = 0`: colchón total `1/√5 = 0,45` del descentralizado. Con `ρ = 0,5` entre todos: `sqrt(n + n(n−1)ρ)/n = sqrt(5 + 10)/5 = 0,77`. La correlación entre partners (misma base de usuarios, mismos feriados, mismo FX) erosiona el pooling; hay que estimarla.
- **Precondición:** el pooling sólo es realizable si `L_c < T_i`; con wires T+2 y revisión diaria el pool central no llega a tiempo y cada partner debe autoasegurarse; con rails 24/7 de minutos el pool central cubre todo. Esto es el argumento estructural a favor de stablecoins más allá del colchón individual: habilitan la centralización.
- **Valor de reducir lead time (fórmula):** `ΔNOF ≈ μ·(L₁ − L₂) + μ·(R₁ − R₂)/2 + z·σ·(√T₁ − √T₂)` (pipeline + cycle stock + safety stock); `ahorro anual = k·ΔNOF`. Ver sección 8 para números.
- **Fin de semana / feriados.** Un buffer estático se dimensiona al peor `T` del calendario (viernes → acreditación miércoles = 6 días calendario de salidas si el partner paga 7/7); un rail 24/7 mantiene `T` constante. El ahorro por cobertura de fin de semana es `μ·(T_worst − T_avg) + z·σ·(√T_worst − √T_avg)` si el buffer es estático, o, si es dinámico por día de la semana, el ahorro aparece sólo en los ciclos de viernes/pre-feriado pero con un partner que paga sábado y domingo esos ciclos son los de mayor riesgo de rechazo.
- **Colas pesadas.** Salidas de wallets tienen picos (campañas, pánico FX, fraude) ⇒ el beneficio de pooling y el `z·σ` normal subestiman el riesgo de cola; usar cuantiles empíricos/simulación (sección 4) y un stress overlay tipo LCR (sección 6) en lugar de `z` normal para el extremo.

### Gaps
- No se encontró un cálculo publicado de "lead-time reduction value" específico para prefondeo de payouts; el cálculo está derivado en Inferences/sección 8.
- Las afirmaciones de ahorro de capital de Visa/Circle son de vendors y prensa, sin cifras auditadas de reducción de prefondeo.

---

## 6. Análogos de liquidez bancaria: LCR/NSFR, BCBS 248 intradía, nostro, "trapped liquidity" cuantificado, y trabajos BIS (Agorá, Nexus, mBridge)

### Takeaway
El prefondeo en un partner es exactamente un nostro: el LCR aporta la plantilla "activos líquidos ≥ salidas netas estresadas sobre una ventana" y BCBS 248 la métrica operativa "mayor posición neta acumulada negativa del día" que es lo que el modelo debe pronosticar; la industria cuantifica el problema en USD 23,5 bn de flujo corporativo transfronterizo anual con USD 120 bn de costos de transacción y liquidaciones de 2–3 días (Oliver Wyman/JPM), mientras que las cifras de "liquidez atrapada" (USD 4 bn, USD 27 bn) circulan sin fuente primaria verificable; Agorá demostró liquidación en ~80 segundos 24/7 pero no publicó ahorros de capital.

### Cited Findings
- LCR: el banco debe mantener "an adequate stock of unencumbered high-quality liquid assets (HQLA)" para cubrir "a 30 calendar day liquidity stress scenario"; mínimo 100 % desde 1-ene-2019 — [BCBS 238, BIS](https://www.bis.org/publ/bcbs238.htm)
- BCBS 248 (abril 2013): siete herramientas cuantitativas de monitoreo intradía, "for monitoring purposes only", obligatorias para bancos internacionalmente activos; reporte mensual desde 1-ene-2015; incluye "detailed design of the monitoring tools", "stress scenarios", "the reporting regime"; desarrollado con el CPSS; integrado al Basel Framework consolidado — [BCBS 248, BIS](https://www.bis.org/publ/bcbs248.htm)
- Medida central de BCBS 248: la mayor posición neta acumulada negativa del día determina el uso máximo de liquidez intradía; se mide desde una posición inicial de cero; se reportan las tres mayores posiciones netas positivas y negativas; requiere seguir la posición por cuenta en tiempo real — [Bank of England intraday liquidity reporting guidance](https://edu.bankofengland.co.uk/-/media/boe/files/prudential-regulation/crd-iv/intraday-liquidity-monitoring-reporting.pdf); [Global Treasurer](https://www.theglobaltreasurer.com/2016/03/30/intraday-monitoring-tools-bcbs-248-and-satisfying-the-regulator/); [slides BCBS 248](https://www.slideshare.net/slideshow/bcbs-248-intraday-liquidity-management/28684712)
- Oliver Wyman & J.P. Morgan (nov 2021): "Global corporates move nearly $23.5 trillion across borders annually… correspondent banking networks that cost approximately $120 billion in transaction charges annually"; "$27 average cross border fee per transaction, excluding FX"; "not uncommon for payments to take 2-3 days to reach end beneficiary"; "these processes also result in additional costs from FX conversion, trapped liquidity and delayed settlements" (excluidos del $120 bn); pre-funding genera "trapped balances in nostro/vostro accounts"; una red mCBDC "could save global corporates nearly $100 billion annually" — [Oliver Wyman & J.P. Morgan, Unlocking $120 Billion Value in Cross-Border Payments (PDF)](https://www.oliverwyman.com/content/dam/oliver-wyman/v2/publications/2021/nov/unlocking-120-billion-value-in-cross-border-payments.pdf); [Finextra](https://finextra.com/newsarticle/39148/jpmorgan-estimates-cbdcs-could-save-corporates-100-billion-in-transaction-costs)
- "$4 trillion that's locked in all these prefunded accounts" — afirmación del CEO de MANSA en podcast, sin fuente — [Glenbrook Payments on Fire ep. 278](https://glenbrook.com/?p=55450); "more than $27 trillion sits idle in nostro and vostro accounts" atribuido por Circle al BIS, no verificado contra el BIS — [Circle blog](https://www.circle.com/es/blog/why-liquidity-fragmentation-holds-back-global-payments); "several trillion dollars" en cuentas prefondeadas sin fuente precisa — [Netcoins](https://netcoins.com/blog/pre-funding-problem-cross-border-payments)
- Project Agorá (BIS, 8 bancos centrales, >40 instituciones vía IIF): apunta a "structural inefficiencies that make them slow, costly and opaque" y a "silo liquidity"; en pruebas con valor real "the average time from payment initiation to settlement was approximately 80 seconds"; operación "around-the-clock… if implemented"; informe 27-may-2026; pruebas con valor real julio 2026; **no publica cifras de ahorro**; no estaba integrado a RTGS ni core banking — [BIS Innovation Hub, Project Agorá](https://www.bis.org/about/bisih/topics/fmis/agora.htm)
- Project Nexus: conecta sistemas de pago instantáneo domésticos con una sola conexión; prototipo conectó TIPS, RPP Malasia y FAST Singapur; blueprint fase 3 completado jul-2024 con India, Malasia, Filipinas, Singapur, Tailandia; objetivo de pagos en 60 segundos; se creará la Nexus Scheme Organisation — [BIS press release 1-jul-2024](https://www.bis.org/press/p240701.htm); [BIS othp62](https://bis.org/publ/othp62.htm); [Central Banking](https://www.centralbanking.com/central-banks/financial-stability/fmi/7862261/bis-project-nexus-targets-60-second-cross-border-payments)
- mBridge: el BIS se retiró en 2024 tras alcanzar MVP; descrito como ahorro por eliminar cuentas nostro (fuente secundaria) — [Kitco](https://www.kitco.com/news/article/2024-11-04/bis-withdraws-project-mbridge-after-brics-lauded-its-potential-aid-de); [Fintechnews.sg](https://fintechnews.sg/102951/innovation/bis-exits-project-mbridge/)
- Visa: >USD 3,5 bn de volumen anualizado de settlement en stablecoins; emisores/adquirentes de EE. UU. pueden liquidar obligaciones VisaNet en USDC (dic-2025) — [BusinessWire](https://www.businesswire.com/news/home/20251216483172/en); Circle: "Settle with Visa in real time, 7 days a week" — [Circle](https://www.circle.com/issuer-program)
- McKinsey/Artemis: ~USD 390 bn de pagos reales en stablecoin (≈0,02 % del volumen global de pagos; ~1 % del volumen on-chain total de USD 35 bn), <1 % del volumen transfronterizo — [The Paypers](https://thepaypers.com/payments/expert-views/the-real-economics-of-stablecoin-payments-and-where-the-math-actually-works); [KuCoin news](https://www.kucoin.com/news/flash/mckinsey-and-artemis-report-only-1-of-stablecoin-35t-volume-is-real-payments) (secundarias; cifras discrepan entre USD 27 bn y 35 bn)

### Inferences
- **Plantilla LCR para prefondeo:** `Saldo_partner + reposiciones_acreditables_en_T ≥ Q_α(salidas netas acumuladas en T)`, con `T` = horizonte en que no puede llegar nueva liquidez (análogo a los 30 días de estrés). El "ratio de cobertura de prefondeo" `PCR = IP_t / Q_α(Σ_{h≤T} X_h)` ≥ 1 es un KPI directamente reportable; `PCR` por partner y agregado reemplaza a "días de cobertura" como métrica.
- **Plantilla BCBS 248:** la "mayor posición neta acumulada negativa" dentro de la ventana es exactamente el máximo del drenaje acumulado `max_{τ≤T} Σ_{h≤τ}(X_h − entradas_h)`; con sólo salidas es monótono y coincide con la suma al final de `T`, pero si el partner también acredita entradas (cobros, devoluciones) hay que pronosticar el *máximo* de la trayectoria, no el total — por simulación de caminos (sección 4) tomando `max` en vez de `sum`.
- Las cifras de "trapped liquidity" en billones son de calidad baja (podcast, blog de emisor); la única fuente consultora primaria (OW/JPM) **excluye** explícitamente la liquidez atrapada de su USD 120 bn y no la cuantifica. Para un documento interno conviene citar OW/JPM (volumen, costo, 2–3 días) y presentar el capital atrapado como cálculo propio (sección 8), no como cifra de industria.
- Lo relevante de Agorá/Nexus para el argumento no es un ahorro publicado sino la evidencia de que 24/7 + settlement en segundos es técnicamente alcanzable con bancos centrales; el ahorro hay que derivarlo con la fórmula de reducción de lead time.

### Gaps
- No se obtuvo el PDF completo de BCBS 248 (el fetch devolvió sólo la página índice); las definiciones exactas de las 7 herramientas y los 4 escenarios de estrés provienen de fuentes secundarias (BoE, consultoras).
- La fórmula exacta del LCR (`HQLA / salidas netas 30d`, inflows capados al 75 % de outflows) no apareció en la página consultada; está en el texto de BCBS 238 §69 y en el Basel Framework LCR30/LCR40.
- No se encontró el informe de Agorá ni el de Nexus fase 3 con detalle de mecánica de prefondeo/liquidez; tampoco una cifra BIS/CPMI de capital prefondeado global.
- No se encontró el McKinsey Global Payments Report 2025 primario; sólo cobertura secundaria.

---

## 7. Reinforcement learning y programación estocástica para reposición de efectivo (ATM / cash logistics): métodos y ahorros reportados vs reglas

### Takeaway
La literatura de ATM es el análogo más cercano (saldo que sólo drena, reposición con costo fijo y lead time, stockout con costo de servicio): combinaciones pronóstico + optimizador reportan 15–20 % de ahorro vs práctica común, la optimización robusta y la programación estocástica con límites ajustados a datos ~12 % vs fórmulas cerradas, y los enfoques DQN existen pero sin ahorros verificables en las fuentes accesibles; para un equipo chico la ruta profesional es pronóstico probabilístico + política (R,S)/base-stock optimizada por simulación, con RL como experimento posterior.

### Cited Findings
- Simutis et al. (2007): red neuronal para demanda diaria + optimizador de cargas; "maintenance costs fall by about 15–20 % under certain cost conditions" (simulación) — [xreiss / Information Technology and Control](https://xreiss.efri.uniri.hr/article.php?id=41470)
- Ekinci, Serban & Duman (2021, *Operational Research*), "Optimal ATM replenishment policies under demand uncertainty": optimización robusta de montos de reposición con datos de 98 ATMs en Estambul; reportan reducciones de costo "significativas" vs práctica común (cifra no accesible) — [Bilgi University repository](https://acikerisim.bilgi.edu.tr/items/d8bcc63b-e5b4-4b35-9fa9-1bb8389404ef); [Özyeğin repository](https://eresearch.ozyegin.edu.tr/handle/10679/7042?show=full)
- Kiyaei & Kiaee (2021): Double Deep Q-Network para decidir diariamente si reponer cada ATM, con fees de la empresa de seguridad más altos en fin de semana/feriado; reportan menores costos operativos que métodos de predicción de demanda (magnitud no accesible) — DOI 10.1109/CSICC52343.2021.9420561, vía [sotaverified](https://sotaverified.org/papers/research-of-an-optimization-model-for)
- Reposición de ATM con costos submodulares (política de reposición conjunta) — [Bohrium, ATM replenishment with submodular costs](https://www.bohrium.com/paper-details/automated-teller-machine-replenishment-policies-with-submodular-costs/813042604382879745-98001); optimización logística multiobjetivo para reposición automatizada — [arXiv 2304.13671](https://arxiv.deeppaper.ai/papers/2304.13671v5)
- Cash management corporativo: ajuste de límites `(L, Z, H)` a datos por programación estocástica/MILP con ensambles de muestras aleatorias ("random cash management models"): `G(f_test) = 0,88` vs Miller–Orr de libro; "a small random sample of data is enough to fit sufficiently good bound-based models" — [Salas-Molina 2019](https://riunet.upv.es/bitstream/10251/201125/11/Salas-Molina%20-%20Fitting%20random%20cash%20management%20models%20to%20data.pdf). Trabajos previos: Gormley & Meade (2007) límites con pronósticos + algoritmos genéticos; Salas-Molina et al. (2016) Miller–Orr + simulación multiobjetivo costo/riesgo — citados en el mismo paper.

### Inferences
- **Jerarquía de métodos por costo/beneficio para un prototipo:**
  1. *Regla paramétrica* `S = μ̂_T + z·σ̂_T` con `σ̂_T` empírico de sumas móviles: 1 día de trabajo, captura 80 % del valor.
  2. *Cuantil por simulación de trayectorias* (sección 4) + política (R,S): captura autocorrelación, calendario y colas; backtest de cobertura.
  3. *Optimización de la política por simulación* (grid/Bayesian search sobre `(s, S)` o `(L, Z, H)` minimizando `k·NOF + C_u·faltante + F·n_transfers` sobre trayectorias históricas y simuladas): es lo que hace Salas-Molina con MILP; reproducible con un simulador de 200 líneas.
  4. *Programación estocástica multi-etapa / RL*: justificado sólo si hay restricciones acopladas (límite de pool central, varios rails con costos distintos, cut-offs) que rompan la separabilidad por partner; los papers de ATM no demuestran ventaja robusta de RL sobre 2–3 con datos accesibles.
- El ahorro realista de pasar de "regla de pulgar" (p. ej. 7 días de cobertura) a 2–3 es del orden 10–20 % del NOF (consistente con 12–20 % de ATM/cash), **además** del ahorro estructural por reducir `T` (sección 8), que suele ser mayor.

### Gaps
- No se accedió al texto completo de Ekinci et al. (2021) ni de Kiyaei & Kiaee (2021); los porcentajes de ahorro de RL y optimización robusta no se pudieron verificar.
- No se encontró literatura de stochastic programming/RL aplicada específicamente a prefondeo de payouts en fintech (sólo ATM y cash corporativo).

---

## 8. Ejemplo trabajado: colchón y capital liberado al pasar de `L = 3` días a `~0,5` días; conversión a ahorro anual; plantilla implementable

### Takeaway
Para un partner con `μ = 200.000 USD/día`, `σ = 60.000`, `α = 99 %`, pasar de wire T+3 con revisión diaria (`T = 4`, o `T = 6` en el peor caso de fin de semana) a stablecoin con `L = 0,5` y revisión cada medio día (`T = 1`) reduce la posición de inventario promedio de ≈ 979 k (≈ 1,44 M dimensionado al peor caso) a ≈ 290 k USD, liberando ≈ 690 k–1,15 M USD, que a `k = 12 %` son ≈ 83 k–138 k USD/año por partner, antes de netear fees proporcionales de on/off-ramp.

### Cited Findings
- Fórmulas base usadas: `SS = z·σ·√T`, `σ_DLT = sqrt(L̄σ_D² + D̄²σ_L²)`, `ROP = D̄L̄ + SS` — [Cleverence](https://www.cleverence.com/articles/for-business/saftey-stock-formula-4382/); fractil crítico `q* = F⁻¹(C_u/(C_u + C_o))` — [Wikipedia, Newsvendor model](https://en.wikipedia.org/wiki/Newsvendor_model); cuantil de la suma por trayectorias, no suma de cuantiles — [arXiv 2510.19345](https://arxiv.org/pdf/2510.19345)
- Liquidación tradicional 2–3 días (OW/JPM) vs ~80 s (Agorá) y "7 days a week" (Circle/Visa) — [Oliver Wyman & J.P. Morgan 2021](https://www.oliverwyman.com/content/dam/oliver-wyman/v2/publications/2021/nov/unlocking-120-billion-value-in-cross-border-payments.pdf); [BIS Agorá](https://www.bis.org/about/bisih/topics/fmis/agora.htm); [Circle](https://www.circle.com/issuer-program)

### Inferences
**Supuestos:** salidas diarias ≈ normales i.i.d. (para el ejemplo; en producción usar simulación de trayectorias), `μ = 200.000`, `σ = 60.000` (CV 0,3), `α = 99 %` ⇒ `z = 2,326`, `k = 12 %`. Posición de inventario promedio `≈ S − μ·R/2` (el pipeline cuenta como capital de trabajo).

| Escenario | `L` | `R` | `T` | `μT` | `SS = zσ√T` | `S` | `IP promedio ≈ S − μR/2` |
|---|---|---|---|---|---|---|---|
| A. Wire T+3, revisión diaria, días hábiles | 3 | 1 | 4 | 800.000 | 279.120 | 1.079.120 | 979.120 |
| A'. Igual, peor caso viernes (partner paga 7/7) | 5 | 1 | 6 | 1.200.000 | 341.780 | 1.541.780 | 1.441.780 |
| B. Stablecoin, `L = 0,5`, revisión diaria | 0,5 | 1 | 1,5 | 300.000 | 170.920 | 470.920 | 370.920 |
| C. Stablecoin, `L = 0,5`, revisión 2×/día, 7/7 | 0,5 | 0,5 | 1 | 200.000 | 139.560 | 339.560 | 289.560 |

- Capital liberado A→C: `979.120 − 289.560 ≈ 689.560 USD` (−70 %); A'→C: `≈ 1.152.000 USD` (−80 %). Descomposición A→C: pipeline+cycle `μ(T_A − T_C) − μ(R_A − R_C)/2 = 600.000 − 50.000 = 550.000`; safety stock `zσ(√4 − √1) = 139.560`.
- Ahorro anual `= k·ΔNOF`: a 12 % ⇒ 82.700 (A→C) / 138.300 (A'→C) USD/año; a 20 % (costo de capital típico de fintech LATAM apalancada) ⇒ 137.900 / 230.400.
- **Costo del lado stablecoin a netear:** `n_transfers·F_onchain + bps_onramp·volumen_anual`. Con `F = 2 USD` y 730 transferencias/año ⇒ 1.460 USD (despreciable). El término proporcional domina: a 10 bps sobre 73 M USD/año = 73.000 USD/año — comparable al ahorro de capital a `k = 12 %`. La decisión depende de `bps_onramp` vs (fee de wire + spread FX bancario que ya se paga) y del `C_u` evitado; no se puede concluir sin los bps reales del proveedor.
- **Efecto sobre rechazos:** con `T` más corto la misma `α` requiere menos colchón; alternativamente, con el mismo colchón se puede subir `α`. En C, mantener `IP ≈ 979 k` (el de A) daría `z = (979.120 + 50.000 − 200.000)/60.000 = 13,8` ⇒ probabilidad de faltante ≈ 0 — i.e., el rail rápido permite elegir entre liberar capital o eliminar rechazos.

**Plantilla implementable (por partner `i`, por evento de decisión):**

```
inputs:
  paths[n, h]      # N trayectorias de salidas diarias h = 1..H del modelo probabilístico
                   # (muestreo con dependencia temporal: copula gaussiana o block bootstrap)
  L, R             # lead time y período de revisión, en días calendario, para ESTE evento
                   # (contar fines de semana/feriados en que el partner paga y el rail no acredita)
  k, s_cp, s_fx    # costo de capital anual, prima contraparte, costo FX (anuales)
  C_u              # costo por USD rechazado (margen + churn + SLA), medido internamente
  F                # costo fijo por transferencia
  IP_t             # saldo actual + en tránsito

T      = L + R
C_o    = (k + s_cp + s_fx) * T / 365
alpha  = C_u / (C_u + C_o)                     # fractil crítico (newsvendor)
Y      = sum(paths[:, 1:T], axis=1)            # salida acumulada por trayectoria
S      = quantile(Y, alpha)                    # nivel objetivo = cuantil de la SUMA
order  = max(0, S - IP_t)
if F > 0: order = 0 if order < Q_min           # Q_min por EOQ/Baumol: sqrt(2*F*mu*R/(k/365)) o umbral s
KPIs:
  PCR          = IP_t / S                      # ratio de cobertura de prefondeo (análogo LCR)
  E_short      = mean(max(Y - IP_t, 0))        # faltante esperado en la ventana
  fill_rate    = 1 - E_short / mean(Y)
  NOF_i        = mean(IP) over time;  ahorro_anual = k * (NOF_baseline - NOF_i)
backtest: cobertura empírica de S ≈ alpha; pinball loss sobre Y (no sobre X_h); recalibrar C_u con churn observado.
```

- Variante paramétrica de arranque: `S = μ̂_T + z_α·σ̂_T`, con `μ̂_T, σ̂_T` estimados de sumas móviles históricas de `T` días (no `σ·√T`), y `σ̂_T² += μ̂²·σ̂_L²` si el lag es variable.
- Agregado multi-partner: `NOF_total = Σ_i NOF_i` descentralizado vs `NOF_pool = Σ_i μ_i T_i' + z·sqrt(Σ_i σ_i² T_i + 2Σ_{i<j} ρ_ij σ_i σ_j sqrt(T_i T_j))` cuando el pool central alcanza cada partner en `L_c`; reportar ambos y la diferencia como "valor de la centralización", condicional al rail.

### Gaps
- Los bps de on/off-ramp USD↔stablecoin↔moneda local en LATAM y los fees/spreads bancarios equivalentes no se investigaron en esta ronda; son el término que decide el break-even y deben venir de cotizaciones de proveedores.
- El ejemplo asume normalidad e independencia para ser cerrado; la versión de producción debe usar los cuantiles simulados de la sección 4 y validar cobertura en backtest.
- No hay fuente pública para `k` de una fintech LATAM; 12–20 % es rango de juicio, debe reemplazarse por el WACC/costo marginal de deuda real.
