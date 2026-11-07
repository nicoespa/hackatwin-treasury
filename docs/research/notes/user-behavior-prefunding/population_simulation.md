# Simulador de población de usuarios de una billetera (ABM / microsimulación) para generar egresos transaccionales y estresar una política de prefondeo

Notas de investigación (31-10-2026). Alcance: generadores sintéticos de transacciones existentes, ABMs de sistemas de pago/liquidez en bancos centrales, estructura generativa para una población de billetera LATAM (Argentina), ruteo acción→producto→partner→fecha de liquidación, diseño de escenarios de estrés, calibración/validación y un plan de implementación de 2–3 h. **La sección "Diseño propuesto" es síntesis propia**, no está en ninguna fuente; todo lo demás lleva cita.

Convención: "fuente secundaria" = nota de prensa o resumen de terceros, no el documento primario. Donde no encontré dato primario lo digo en Gaps.

---

## KQ1. Generadores sintéticos de transacciones existentes: ¿qué estructura generativa usan y cómo validan realismo?

### Takeaway
Todos los generadores "clásicos" (PaySim, Sparkov, AMLworld, TabFormer-data) son **simuladores basados en reglas/agentes con perfiles de cliente + muestreo estocástico por paso de tiempo**, calibrados contra agregados reales (volumen por tipo, transacciones por cuenta, distribución de montos) y validados con tests de bondad de ajuste de marginales (KS, SSE) o con utilidad downstream (fraude/AML). Ninguno de los que encontré valida la **estructura temporal agregada** (autocorrelación diaria, correlación entre segmentos), que es justamente lo que importa para tesorería. La ola 2023–2026 (GAN/difusión/LLM) mejora marginales y privacidad pero reproduce peor grafos, colas y dependencia temporal.

### Cited Findings

**PaySim (mobile money, 2016)**
- PaySim se desarrolló en dos fases: (1) un simulador multiagente (MABS) que sigue el esquema de un servicio real de mobile money y genera datos sintéticos a partir de escenarios; (2) una versión revisada que usa **logs transaccionales agregados del servicio real** para producir datos más realistas. Código Java, licencia GPL-3.0; paper original Lopez-Rojas, Elmir y Axelsson, "PaySim: A financial mobile money simulator for fraud detection", EMSS 2016. Extensión de lavado de dinero en 2019 (Barneaud/Flaminem) — [GitHub EdgarLopezPhD/PaySim](https://github.com/EdgarLopezPhD/PaySim)
- La tesis doctoral asociada afirma que PaySim usa datos agregados anonimizados de un dataset financiero real para producir datos sintéticos que "se parecen a la dinámica transaccional y propiedades estadísticas del original", y que los datos simulados son "tan prudentes como el dataset original para fijar controles óptimos de fraude" — es una validación de **utilidad**, no estadística detallada — [Dissertations.se, Lopez-Rojas](https://www.dissertations.se/dissertation/0e1ec26eec/)
- El repo tiene carpeta `paramFiles` y `PaySim.properties` (parámetros agregados por tipo de transacción y paso), pero el README no documenta su contenido — [GitHub EdgarLopezPhD/PaySim](https://github.com/EdgarLopezPhD/PaySim)

**MoMTSim (mobile money, 2024) — el sucesor con calibración explícita**
- Azamuke, Katarahweire y Bainomugisha, "MoMTSim: A Multi-Agent-Based Simulation Platform Calibrated for Mobile Money Transactions", IEEE Access vol. 12, pp. 120226–120238 (2024), DOI 10.1109/ACCESS.2024.3439012. Aporta un **algoritmo de calibración iterativa** para simulaciones multiagente (identifica y corrige inexactitudes, introduce parámetros nuevos y descarta erróneos) — [DOAJ](https://doaj.org/article/86e345aafb184c23872fb4de1f71f742)
- Validación: comparan datos reales vs sintéticos con **test de Kolmogorov-Smirnov, suma de errores cuadrados (SSE) y gráficos de Bland-Altman**; con SSE los datos sintéticos "se parecen" a los reales. Motivación declarada: la "calibración no iterativa" limita la explicabilidad de estos modelos — [DOAJ](https://doaj.org/article/86e345aafb184c23872fb4de1f71f742)

**Sparkov (tarjetas de crédito)**
- Generador de transacciones de tarjeta para investigación de fraude; código basado en el original de Josh Plotkin, muy modificado. Cada cliente se asigna a un **perfil** según edad, género y población de la ciudad (`find_profile(age, gender, city_pop, profiles)`), y el perfil gobierna su comportamiento — [DeepWiki Sparkov](https://deepwiki.com/namebrandon/Sparkov_Data_Generation)
- Del changelog del repo: los perfiles definen **ventanas de gasto con pesos AM/PM**, **categorías de gasto** con merchants específicos por categoría, **probabilidad de viaje y distancia máxima** (la ubicación del merchant se aleatoriza alrededor del domicilio), y desde v0.3 los **montos se muestrean de una distribución Gamma**; v0.3 también introdujo perfiles y transacciones fraudulentas. CLI: `python datagen.py -n <N_CUSTOMERS> -o <OUT> <START_DATE> <END_DATE>` con `-seed <INT>` (semilla de Faker) y `-config` (default `./profiles/main_config.json`); la generación se paraleliza por chunks de clientes — [GitHub namebrandon/Sparkov_Data_Generation](https://github.com/namebrandon/Sparkov_Data_Generation)
- El dataset Kaggle derivado cubre 1000 clientes y 800 merchants — [Kaggle kartik2112 (vía Baselight)](https://baselight.app/u/kaggle/dataset/kartik2112_fraud_detection)

**AMLworld / IBM (NeurIPS 2023 Datasets & Benchmarks)**
- Altman, Blanuša, von Niederhäusern, Egressy, Anghel, Atasu (IBM Research + ETH), "Realistic Synthetic Financial Transactions for Anti-Money Laundering Models". Generador **agent-based** calibrado "lo más cerca posible" a transacciones reales; datasets públicos — [arXiv 2306.16424](https://arxiv.org/abs/2306.16424); [NeurIPS 2023](https://proceedings.neurips.cc/paper_files/paper/2023/hash/5f38404edff6f3f642d6fa5892479c42-Abstract.html)
- Estructura: mundo virtual multibanco con **bancos, individuos y empresas**; en cada paso discreto individuos y empresas eligen entre actividad legítima (salarios, compras) y criminal; los criminales ejecutan patrones (fan-out, stack, scatter-gather; ciclo placement–layering–integration) a través de múltiples cuentas y bancos — [alphaXiv overview](https://alphaxiv.org/overview/2306.16424v3)
- Calibración declarada: **transacciones por cuenta alineadas a datos de la Fed** sobre transacciones anualizadas por cuenta; **distribuciones de salario y pensión según IRS**; **mix de medios de pago (cheque, ACH, wire, tarjeta) según estadísticas bancarias reales**; tasa de lavado contrastada con un estudio de datos bancarios reales. Sin métricas numéricas de ajuste publicadas en el resumen — [alphaXiv overview](https://alphaxiv.org/overview/2306.16424v3)
- Seis datasets en Kaggle (HI/LI × Small/Medium/Large), el mayor hasta ~180 M de transacciones; ratio ilícito LI ≈ 1 en 1.750. El argumento de realismo es por **matching de estadísticas agregadas**, no hay sección de limitaciones; el F1 de PNA cae de 59,71 % (HI-Medium) a 27,73 % (LI-Medium) — [alphaXiv overview](https://alphaxiv.org/overview/2306.16424v3)

**IBM TabFormer (2020)**
- "Tabular Transformers for Modeling Multivariate Time Series" (arXiv 2011.01843): dos arquitecturas (BERT-like para representaciones, GPT-like para generar secuencias tabulares). El dataset de tarjeta que liberan fue creado con un **generador basado en reglas con muestreo estocástico**; código y datos en github.com/IBM/TabFormer; dependencias viejas (Python 3.7, PyTorch 1.6, Transformers 3.2) — [arXiv 2011.01843](https://arxiv.org/abs/2011.01843)
- Tamaño reportado: ~24 M de registros, 12 campos — [SourcePulse TabFormer](https://www.sourcepulse.org/projects/1592834)

**J.P. Morgan AI Research**
- Proceso publicado para datos sintéticos: (1) computar métricas sobre datos reales, (2) construir un generador ("métodos estadísticos o simulación basada en agentes"), (3) comparar métricas reales vs sintéticas y refinar. Un dataset suyo de actividad de clientes bancarios (apertura de cuenta, pagos, retiros, compras) fue generado con un **simulador AI planning-execution** — [J.P. Morgan Synthetic Data](https://www.jpmorgan.com/technology/artificial-intelligence/initiatives/synthetic-data)
- Review 2024 co-escrito por JPM AI Research: "Synthetic Data Applications in Finance" — [arXiv 2401.00081](https://arxiv.org/abs/2401.00081)
- ABIDES (Byrd, Hybinette, Balch; arXiv 1904.12066, abril 2019; SIGSIM-PADS 2020): simulador de **eventos discretos** de mercado para decenas de miles de agentes, latencias configurables por par, mensajes según ITCH/OUCH de NASDAQ; su núcleo es un DES de propósito general; código en github.com/abides-sim/abides — [arXiv 1904.12066](https://arxiv.org/abs/1904.12066)
- Calibración de simuladores multiagente (JPM AI Research): calibración por **optimización bayesiana a partir de series de salida** — [arXiv 2112.03874](https://arxiv.org/abs/2112.03874); y **calibración adversarial** ("Learning who is in the market from time series") — [arXiv 2108.00664](https://arxiv.org/abs/2108.00664)

**Generadores neuronales 2023–2026**
- FinDiff: modelos de difusión para datos tabulares financieros (sept. 2023) — [arXiv 2309.01472](https://arxiv.org/abs/2309.01472)
- Karst et al., "Generative AI for Banks: Benchmarks and Algorithms for Synthetic Financial Transaction Data" (dic. 2024, WITS Bangkok): compara CTGAN, DoppelGANger, WGAN, FinDiff y TVAE en fidelidad, calidad de síntesis, eficiencia, privacidad y **estructura de grafo**; **ningún modelo reproduce la estructura de grafo real**; FinDiff y TVAE mejores en replicación/aumentación, DGAN en privacidad, CTGAN balance; en la literatura previa las GAN eran 70 % de los enfoques, con declive reciente — [arXiv 2412.14730](https://arxiv.org/abs/2412.14730)
- PersonaLedger (ene. 2026): **LLM condicionado por personas + motor de reglas** experto-configurable que actualiza el estado del usuario tras cada evento y hace cumplir reglas financieras, en lazo cerrado con un "nextprompt" de factibilidad; dataset público de **30 M de transacciones de 23.000 usuarios**; tareas benchmark de iliquidez y robo de identidad; no reporta métricas de realismo en el abstract — [arXiv 2601.03149](https://arxiv.org/abs/2601.03149)
- Truman (AAMAS 2025, extended abstract): generador multiagente que usa LLMs para construir perfiles de clientes y transacciones, con inyección de patrones de lavado — [AAMAS 2025 p2594](https://aamas.csc.liv.ac.uk/Proceedings/aamas2025/pdfs/p2594.pdf)

### Inferences
- El patrón común es **perfil/arquetipo → proceso de actividad por paso → categoría → monto de una familia paramétrica (Gamma en Sparkov; "muestreo estocástico" en TabFormer/PaySim)**. Es exactamente la columna vertebral que necesita un simulador de billetera; lo que ninguno hace es (a) un factor común diario que correlacione usuarios y (b) la capa de liquidación por partner.
- La validación estándar de la literatura (KS/SSE sobre marginales, utilidad downstream) **no** garantiza que la serie agregada diaria tenga la varianza y autocorrelación correctas; para tesorería hay que agregar esos chequeos (ver KQ6).
- Los generadores neuronales (GAN/difusión/LLM) son peores candidatos para un prototipo de horas: necesitan datos reales para entrenar, reproducen mal grafo/colas, y pierden la interpretabilidad de parámetros que el tesorero va a querer mover ("¿qué pasa si la campaña dura 10 días?").

### Gaps
- No pude leer el PDF del paper PaySim 2016 ni `PaySim.properties`: la estructura exacta de pasos (744 pasos horarios = 31 días) y los parámetros por tipo de transacción no quedaron confirmados por fuente primaria en esta sesión (el fetch de la página de Kaggle devolvió solo el título).
- El PDF de AMLworld no se pudo parsear; las distribuciones exactas de montos/tiempos y los tamaños por dataset provienen de un resumen de terceros (alphaXiv).
- No encontré una encuesta 2024–2026 que compare generadores **por fidelidad de la serie temporal agregada** (CV diario, ACF); Karst et al. evalúa grafo y marginales, no ACF.

---

## KQ2. ABM / microsimulación de sistemas de pago y liquidez en bancos centrales: ¿qué enseñan sobre flujos correlacionados y timing intradiario?

### Takeaway
Los ABM de RTGS (BoE, Banca d'Italia, Bank of Canada) modelan el **mismo trade-off que una política de prefondeo**: liquidez comprometida al inicio del día (costosa) vs. costo de demorar pagos cuando se agota; la demanda de pagos es un flujo aleatorio exógeno y la decisión endógena es cuánto fondear y cuándo liberar. Para una billetera, eso se traduce 1:1 a "cuánto prefondear en cada partner y qué pasa cuando no alcanza". Los stress tests oficiales (TARGET2, Lynx) toman la **demanda real** y shockean la **capacidad** (colateral, reglas), no la demanda; un simulador de población invierte eso y shockea la demanda, que es lo que a una billetera le falta.

### Cited Findings
- Galbiati & Soramäki, BoE Working Paper 352 (2008), publicado en *J. Economic Dynamics and Control* 35(6), 859–875 (2011): modelo multiagente y multiperíodo de un RTGS. Al inicio del día cada banco elige cuánta **liquidez costosa** comprometer; los pagos llegan como **flujo aleatorio exógeno**; si la liquidez se agota los pagos quedan en cola hasta que otros bancos envíen liquidez y el banco demorado carga un **costo de demora**. Derivan una **curva de demanda de liquidez** en función del costo de demora y conclusiones de eficiencia de configuraciones alternativas — [BoE WP 352](https://www.bankofengland.co.uk/working-paper/2008/an-agent-based-model-of-payment-systems); [JEDC 2011 (EconPapers)](https://econpapers.repec.org/RePEc:eee:dyncon:v:35:y:2011:i:6:p:859-875)
- Versión previa (arXiv 2007, "A competitive multi-agent model of interbank payment systems"): aprendizaje por *fictitious play*; prueban un incidente operativo y reglas de throughput; con costos de demora suficientemente bajos, los bancos aumentan liquidez bajo una regla de throughput — [arXiv 0705.3050](https://arxiv.org/abs/0705.3050)
- Arciero, Biancotti, D'Aurizio e Impenna (JASSS 12(1), 2009): ABM exploratorio de un RTGS estilo BI-REL con **mercado monetario explícito**; las decisiones de los bancos son **cuánto colateral postear y cuándo enviar las órdenes de pago** (dimensión de timing). Un evento disruptivo produce un "sumidero de liquidez", luego falsa sensación de espesamiento del mercado con más demoras, y después un salto en defaults — [JASSS 12/1/2](https://www.jasss.org/12/1/2.html)
- Stress test de liquidez de TARGET2 (ECB, Arciero et al., 2017): shockean el **valor del colateral** (recorta líneas de crédito intradía y por ende capacidad de pago) sobre un período de mantenimiento 2008–2013 usando el simulador TARGET2 con datos transaccionales reales; en el peor caso (caída de colateral del 70 %) se habría liquidado el **80–90 % del turnover** — [CORE / ECB](https://core.ac.uk/works/2680421)
- Bank of Canada, Castro, Desai, Du, Garratt y Rivadeneyra, SWP 2021-7: **aprendizaje por refuerzo** para aproximar cómo bancos en un sistema de alto valor estilizado fijan liquidez y reglas de pago, con políticas estimadas a partir de **datos del LVTS canadiense**; en un setting simplificado de dos agentes los agentes RL aprenden la política óptima que minimiza el costo de procesar pagos — [BoC SWP 2021-7](https://www.bankofcanada.ca/wp-content/uploads/2021/02/swp2021-7.pdf)
- Bank of Canada, Rivadeneyra y Zhang, SDP 2020-9: simulación del nuevo sistema Lynx construida desde la descripción del vendor, alimentada con **datos de pago reales del LVTS y manteniendo fijo el timing de los participantes**; con liquidez inicial comparable a lo que hoy pignoran los participantes, Lynx con *FIFO bypass* requeriría más liquidez que LVTS o un RTGS plain-vanilla con liquidez pooled — [BoC SDP 2020-9](https://www.bankofcanada.ca/2020/09/staff-discussion-paper-2020-9/)
- CHAPS: el BoE publica **datos diarios** de volumen y valor por tipo de mensaje ISO 20022 (serie en su base estadística, actualizada mensualmente); valores diarios promedio £399.457 M en Q1 2026 (vs £387.890 M Q4 2025 y £359.554 M Q3 2025); "CHAPS liquida el PBI anual del Reino Unido cada nueve días hábiles"; horario 06:00–18:00 días hábiles — [BoE payment statistics](https://www.bankofengland.co.uk/payments/payment-and-settlement-statistics); [BoE CHAPS daily data](https://www.bankofengland.co.uk/statistics/details/further-details-about-chaps-daily-settlement-data)
- Días pico de CHAPS (fuente secundaria): £485 bn el 30-11-2020, récord previo £479 bn el 18-03-2020 — [Clear Junction CHAPS guide](https://clearjunction.com/blog/chaps-payments-guide/)

### Inferences
- La traducción directa a billetera: **liquidez inicial del banco ≡ prefondeo por partner**, **costo de demora ≡ costo de fallar/retrasar un pago al usuario o al partner**, **cola ≡ backlog de egresos no cubiertos**. La "curva de demanda de liquidez vs costo de demora" de Galbiati–Soramäki es el gráfico que el tesorero quiere ver: prefondeo óptimo como función del costo de quedarse corto.
- Los modelos de banco central muestran que la **coordinación/timing** (cuándo se libera el pago) cambia la liquidez necesaria tanto como el volumen; para la billetera, el equivalente es el cut-off del partner y si el egreso cae antes o después (ver KQ4).
- Con pico/promedio de CHAPS ≈ £485 bn / ~£400 bn ≈ 1,2× (fuente secundaria vs promedio 2026, períodos distintos), un sistema de alto valor tiene colas relativamente contenidas; una billetera minorista con paydays y campañas tendrá picos relativos mayores (ver Pix en KQ3), así que no conviene copiar la calma de CHAPS.

### Gaps
- No pude leer el cuerpo del WP 352 ni del SWP 2021-7 (fetch devolvió PDF binario): número de bancos/períodos, formas funcionales de costo y distribución exacta de llegadas no quedaron confirmados.
- No encontré una distribución intradía publicada de liquidación CHAPS por hora.
- No encontré ningún paper de banco central con ABM **minorista** (billeteras/PSP) de liquidez; todo lo encontrado es RTGS de alto valor.

---

## KQ3. Estructura generativa para una población de billetera: arquetipos, procesos de actividad, montos, calendario y factor macro compartido; CV/ACF realistas

### Takeaway
La evidencia pública respalda tres piezas: (a) **el calendario domina**: en Brasil los récords de Pix caen sistemáticamente alrededor del quinto día hábil (pago de salarios CLT) y en Argentina la LCT obliga a pagar sueldos dentro de 4 días hábiles, con >40 % de asalariados moviendo el sueldo a billeteras en 48 h; (b) **efectos de día de semana/mes son reales pero de magnitud moderada en elección de medio de pago**, y la ACF diaria de totales de pago muestra patrón semanal y estacionalidad anual fuerte; (c) para que el agregado no sea √n-suave hace falta una **intensidad aleatoria compartida (proceso de Cox / "common shock")**, cuya teoría da directamente el índice de dispersión 1 + Var[Λ]/E[Λ]. **No encontré ningún CV ni ACF publicado de volúmenes diarios de Pix, CHAPS o redes de tarjeta**: hay que estimarlos de las series públicas o del propio histórico de la billetera.

### Cited Findings

**Payday clustering (evidencia empírica)**
- Tecnoblog: los récords diarios de Pix "siguen un patrón" y ocurren en fechas cercanas al día 5, vinculadas al cobro de salario — [Tecnoblog](https://tecnoblog.net/noticias/com-um-mes-de-diferenca-pix-bate-novo-recorde-de-transacoes/)
- Pix: 313,3 M de transacciones en 24 h el viernes 5-12-2025 (R$ 179,9 bn); el BCB señaló que el pago a trabajadores CLT suele caer en el quinto día hábil, coincidente con ese viernes; récord previo 5-9-2025 con 290 M y R$ 164,8 bn — [Forbes Brasil](https://forbes.com.br/forbes-money/2025/12/pix-bate-recorde-com-313-milhoes-de-transacoes-em-um-dia/)
- Pix: 318.073.816 operaciones y R$ 186,89 bn el 4-9-2026 (SPI vía Valor; fuente secundaria) — [Let's Money](https://www.letsmoney.com.br/noticias/pix-recorde-diario-transacoes/)
- Black Friday 2025: 297,4 M de operaciones Pix en un día (pico no-salarial, por campaña comercial) — [TecMundo](https://www.tecmundo.com.br/mercado/408966-pix-bate-recorde-com-2974-milhoes-de-operacoes-na-black-friday-de-2025.htm)
- Base legal Brasil: CLT art. 459, salario mensual se deposita hasta el quinto día hábil del mes siguiente — [Seu Crédito Digital](https://seucreditodigital.com.br/pix-bate-recorde-318-milhoes-transacoes/)
- Argentina: la Ley de Contrato de Trabajo fija **4 días hábiles** para pagar la remuneración mensual o quincenal (lunes a viernes, sin feriados) — [Naranja X blog](https://www.naranjax.com/blog/cuando-te-tienen-que-pagar-el-sueldo-la-ley-te-banca-y-nosotros-tambien)
- Argentina: según la Cámara Argentina Fintech, **más del 40 % de los trabajadores que cobran en cuenta bancaria transfieren el salario a billeteras virtuales dentro de las primeras 48 horas** (fuente secundaria) — [MDZ](https://www.mdzol.com/dinero/adios-al-banco-4-cada-10-argentinos-mueven-su-sueldo-billeteras-virtuales-apenas-cobran-n1466121)
- Argentina: la habilitación para cobrar sueldos directamente en billeteras quedó **fuera** de la reforma laboral (feb. 2026); las billeteras siguen excluidas como canal de pago de haberes — [Descubre.vc](https://www.descubre.vc/noticia/reforma-laboral-impide-a-mercado-pago-y-billeteras-digitales-cobrar-sueldos-2026-02-10)
- Argentina, mix de cuentas: en octubre 2025 las transferencias en pesos fueron hechas 54,5 % desde CBU y 45,5 % desde CVU; en agosto 2025 el 76,1 % de las transferencias inmediatas *push* tuvo CVU en origen o destino; en noviembre 2025 había 84 billeteras interoperables registradas — [BCRA Informe Pagos Minoristas oct-2025](https://www.bcra.gob.ar/Pdfs/PublicacionesEstadisticas/Informe-Mensual-de-Pagos-Minoristas-octubre-2025.pdf); [BCRA ago-2025](https://www.bcra.gob.ar/publicaciones/informe-de-pagos-minoristas-agosto-de-2025/); [BCRA dic-2025](https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/informes/informe-pagos-minoristas-2025-12.pdf)

**Efectos de calendario (magnitud y ACF)**
- Wang & Wolman (Fed Richmond, ~2.000 M de transacciones minoristas): estiman patrones de día de semana y día de mes en la **elección** de medio de pago (efectivo/débito/crédito/cheque); los efectos son "interesantes pero pequeños en magnitud" — [Wolman & Wang presentation](https://www.suomenpankki.fi/globalassets/en/research/seminars-and-conferences/conferences-and-workshops/documents/retailpayments2015/wolman_wang_presentation.pdf)
- ISI 2019 (pagos en efectivo en 670 sucursales bancarias): la **función de autocorrelación de totales diarios muestra patrón semanal y una componente estacional de 52 semanas fuerte**; ajustan un modelo autorregresivo estacional con un coeficiente por día de la semana — [ISI 2019 STS vol. 4](https://isi2019.org/proceeding/2.STS/STS%20VOL%204/files/basic-html/page104.html)
- Banco de Portugal WP 2010-12: efectos de calendario en retiros diarios de ATM, incluyendo día de semana y **semana del mes** — [Banco de Portugal wp201012](https://www.bportugal.pt/sites/default/files/anexos/papers/wp201012.pdf)
- JFQA, "Daily cash forecasting and seasonal resolution": compara especificaciones **multiplicativas y mixtas** de día-de-mes × día-de-semana contra aditivas; trata colinealidad, feriados y distorsión por longitud del mes — [Cambridge JFQA](https://resolve.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/daily-cash-forecasting-and-seasonal-resolution-alternative-models-and-techniques-for-using-the-distribution-approach/02B3BB748F6D4BA83949302C8E90CACF)

**Factor común / sobredispersión**
- Proceso de Cox (Poisson doblemente estocástico): Poisson con intensidad aleatoria; condicional a la trayectoria de la intensidad es un Poisson inhomogéneo. Para un conjunto B, el **índice de dispersión = 1 + Var[Λ(B)]/E[Λ(B)]**, igual a 1 solo si la intensidad es determinista — [Beneš et al.](https://ias-iss.org/ojs/IAS/article/viewFile/829/732)
- La heterogeneidad ambiental compartida "puede generar sobredispersión pero también dependencia" entre unidades; la dependencia también puede modelarse con cópulas — [arXiv 2304.06916](https://arxiv.org/abs/2304.06916)

**Herramientas Hawkes**
- `tick` (X-DataInitiative; JMLR 18, 2018): módulo `tick.hawkes` con `SimuHawkes`, `SimuHawkesExpKernels`, `SimuHawkesSumExpKernels`, `SimuHawkesMulti` (simulaciones paralelas), kernels `HawkesKernelExp`/`HawkesKernelPowerLaw`, núcleo C++ multicore; **no está activamente mantenido** — [tick API](https://x-datainitiative.github.io/tick/modules/api.html); [JMLR](https://www.jmlr.org/beta/papers/v18/17-381.html)
- Alternativa liviana: `HawkesPyLib` (PyPI 0.1.1) — [GitHub Simbold/HawkesPyLib](https://github.com/Simbold/HawkesPyLib)

### Inferences
- **Intensidad por usuario = base del arquetipo × m_dow(t) × m_dom(t) × m_payday(t, cohorte de cobro) × M_t (factor macro)**. Con n usuarios independientes de intensidad λ, el CV del conteo agregado es 1/√(nλ) (para 50k usuarios y λ≈0,5/día: ≈0,6 %), absurdamente suave. Con M_t lognormal de desvío σ_M, el CV del agregado tiene **piso ≈ σ_M** (por la fórmula de Cox: Var/E² ≈ 1/(nλ) + Var[M]/E[M]²). Esto es derivación propia a partir de la fórmula de dispersión citada.
- Para la ACF: si log M_t sigue un AR(1) con φ≈0,6–0,8, el agregado hereda autocorrelación diaria positiva además del patrón semanal determinista, lo cual coincide cualitativamente con la ACF semanal + estacional reportada para totales diarios de sucursales (ISI 2019). Los valores de φ y σ_M son **parámetros a calibrar**, no datos.
- La magnitud del payday es grande en Pix (los récords son siempre quinto día hábil o Black Friday) mientras los efectos de calendario en *elección de medio* son chicos (Wang–Wolman): en el simulador el payday debe entrar como **multiplicador de intensidad de egresos** 1,5–3× (orden de magnitud sugerido, no citado) en los días hábiles 1–5 para la cohorte asalariada, no como cambio de mix.
- Para Argentina, la cadena es "sueldo cae en CBU (días hábiles 1–4) → transferencia a CVU en 48 h → egresos de la billetera (pagos, inversión, dólar/crypto) concentrados en días hábiles 2–7". El 54,5/45,5 CBU/CVU y el 76,1 % con CVU en algún extremo son los anclajes públicos para el mix.
- Hawkes (auto-excitación) es útil para **sesiones** (una transferencia dispara otra en minutos) y para clusters de pánico FX; a escala diaria y 50k usuarios, un **Cox con factor macro AR(1)** da la misma varianza agregada con 1/100 del costo. Reservar Hawkes para el escenario FX si se quiere timing intradía.

### Gaps
- **No encontré ningún número publicado de CV ni de autocorrelación de volúmenes diarios de Pix, CHAPS, Visa/Mastercard ni COELSA.** Las series diarias existen (BoE CHAPS daily; BCB SPI) y se pueden descargar para estimarlas, pero no lo hice en esta sesión. Mientras tanto, cualquier σ_M es supuesto.
- No encontré estadísticas públicas del BCRA/COELSA por **día** (los informes son mensuales); el patrón de pico 1–7 del mes en Argentina se infiere de la LCT y del 40 %-en-48 h, no de una serie observada.
- No encontré estudios de **adopción de productos por arquetipo** (p. ej., % de usuarios de billetera que usan FCI, crypto, pago de servicios) con desglose demográfico; los arquetipos del diseño son supuestos a validar con datos internos.

---

## KQ4. Ruteo acción → producto → partner → fecha de liquidación: lags, cut-offs, netting, fines de semana

### Takeaway
Los lags de liquidación en Argentina están normados y son heterogéneos por rail: transferencias inmediatas acreditan en línea (ventana hábil 8–18, fuera de ella pasan a la franja siguiente), débito acredita al comercio el **día hábil siguiente**, crédito entre **8–18 días hábiles** según tamaño del comercio y norma vigente. Esto obliga a modelar la fecha de liquidación como `next_business_day(t + lag, calendar_partner)` con cut-off, y a producir la serie por partner como suma de eventos **por fecha de liquidación**, no por fecha de evento.

### Cited Findings
- BCRA: los comercios tienen acreditadas al **siguiente día hábil** las ventas con tarjeta de débito (desde julio 2021; antes la ley 25.065 fijaba 3 días hábiles y un acuerdo previo 2) — [BCRA noticia débito](https://www.bcra.gob.ar/noticias/los-comercios-tendran-acreditadas-al-siguiente-dia-habil-las-ventas-con-tarjetas-de-debito/); [El Cronista](https://www.cronista.com/finanzas-mercados/desde-hoy-los-pagos-con-debito-a-los-comercios-se-acreditaran-en-un-dia)
- BCRA Com. "A" 6680 (2019): plazo máximo de **10 días hábiles** desde la compra para acreditar ventas con tarjeta de crédito — [BCRA noticia crédito](https://www.bcra.gob.ar/noticias/tarjetas-de-credito-beneficio-para-los-comercios/)
- Com. "A" 7305: nuevos plazos máximos para crédito, con **18 días hábiles** "para los demás casos" y plazos menores para micro/pequeños comercios (otra fuente habla de 8 días hábiles para MiPyME). Fecha y régimen vigente no confirmados — [Abogados.com.ar](https://abogados.com.ar/index.php/modifican-los-plazos-maximos-para-acreditar-las-transacciones-con-tarjetas-de-credito-compra-y-debito-que-cambio/28703); [iProfesional](https://www.iprofesional.com/finanzas/280111-Por-que-los-comercios-en-Argentina-pierden-con-las-tarjetas-de-credito-y-debito)
- Transferencias inmediatas: el BCRA exige acreditación inmediata en línea los **días hábiles entre 8 y 18**; operaciones fuera de ese horario se acreditan en la franja siguiente — [BBVA Argentina](https://www.bbva.com/es/ar/salud-financiera/cuanto-demora-una-transferencia-bancaria-en-argentina-todo-lo-que-necesitas-saber/)
- En el modelo de Galbiati–Soramäki y en Lynx, la liquidez requerida depende de **reglas de cola/FIFO bypass y del timing de envío**, no solo del volumen — [BoC SDP 2020-9](https://www.bankofcanada.ca/2020/09/staff-discussion-paper-2020-9/); [BoE WP 352](https://www.bankofengland.co.uk/working-paper/2008/an-agent-based-model-of-payment-systems)

### Inferences (síntesis propia)
- Tabla de partners mínima: `partner_id, rail, lag_business_days, cutoff_hour, settles_on_weekends (bool), nets_inflows (bool), holiday_calendar`. Ejemplos defendibles: transferencias inmediatas (T+0, cut-off 18:00, 7×24 para el usuario pero fondeo del partner en horario hábil), adquirencia débito (T+1 hábil), adquirencia crédito (T+8/T+10/T+18 hábil según comercio), pago de servicios/recaudadoras (T+1/T+2 hábil), FCI/rescates (T+0 o T+1 hábil según fondo), crypto/stablecoin on-ramp (T+0 24/7 pero con prefondeo en exchange).
- Regla de fecha: `settle_date = add_business_days(event_date + (event_time > cutoff), lag, calendar)`; si el partner no liquida fines de semana, viernes post-cut-off y sábado/domingo se acumulan al lunes (**efecto lunes**: la serie por partner tendrá picos de 3 días comprimidos; esto es un resultado del ruteo, no un parámetro).
- Netting: si `nets_inflows`, el requerimiento diario es `max(0, outflows_d - inflows_d)`; si no, se prefondea el bruto. El prototipo debería exponer ambos para que el tesorero vea cuánto "vale" el neteo por partner.
- La serie por partner es `groupby(partner_id, settle_date).sum(amount)`; la correlación entre partners aparece sola porque comparten M_t y payday, pero con **desfasaje** por los lags distintos (débito T+1 vs crédito T+10 del mismo payday). Eso es una propiedad a reportar: la correlación cruzada entre partners debería ser alta a lag 0 para rails rápidos y aparecer a lag ≈ diferencia de plazos para los lentos.

### Gaps
- No confirmé la **norma vigente a 2026** para plazos de crédito (10 vs 8 vs 18 días hábiles y por categoría de comercio); las fuentes son 2019–2021 y una nota sin fecha clara. Verificar en el texto ordenado del BCRA.
- No encontré documentación pública de cut-offs y calendarios de recaudadoras (Pago Fácil/Rapipago), FCI o exchanges para parametrizar lags reales; usar valores de contrato internos.

---

## KQ5. Diseño de escenarios y estrés: campaña, cohorte, payday shift, salto FX, caída de partner; plantillas regulatorias (BCBS LCR, EBA/ECB)

### Takeaway
Los reguladores definen el estrés de liquidez como **tasas de salida (run-off) por bucket a 30 días** (Basel LCR: 5 % depósitos minoristas estables, 3 % opcional, 10 % piso para menos estables) o como **horizonte de supervivencia** bajo escenarios adverso/extremo con outflows crecientes (ECB LiST 2019). Ambos son plantillas directamente reutilizables como multiplicadores de intensidad/monto por arquetipo. La evidencia argentina de pánicos FX (salida del cepo abril 2025, elecciones 2023) muestra picos de compra de stablecoins de **~3× el promedio diario** y récords por hora: el escenario FX debe ser un salto multiplicativo en la intensidad del arquetipo "dolarizador" concentrado en horas, no un drift suave.

### Cited Findings
- Basel LCR (LCR40): depósitos minoristas **estables** reciben run-off de **5 %** (totalmente asegurados); jurisdicciones pueden aplicar **3 %** si el esquema de garantía cumple criterios adicionales (p. ej., prefondeado por aportes periódicos); depósitos **menos estables**: piso de **10 %**, con buckets superiores a criterio del supervisor; las tasas son **mínimos** — [BIS Basel Framework LCR40](https://www.bis.org/committees/bcbs/basel-framework/81471/chapter.pdf)
- Si un banco no puede identificar qué depósitos están asegurados, debe colocar el total en el bucket menos estable — [SAMA rulebook (reproduce texto Basel)](https://rulebook.sama.gov.sa/en/entiresection/3761)
- ECB (Macroprudential Bulletin dic-2023): las tasas LCR (5 % retail estable, 10 % retail menos estable) cubrieron la mayoría de los episodios de salida neta 2016–2023, pero las salidas de **SVB y First Republic en marzo 2023 estuvieron muy por encima** de esos supuestos — [ECB MPB 2023](https://www.ecb.europa.eu/pub/financial-stability/macroprudential-bulletin/focus/2023/html/ecb.mpbu202312_focus02.el.html)
- ECB LiST 2019: análisis de sensibilidad de riesgo de liquidez idiosincrático sobre ~100 bancos significativos; **cuatro escenarios** (baseline = flujos contractuales sin nuevo negocio; adverso y extremo con shock creciente); métrica = **horizonte de supervivencia** (días que el banco opera con caja y colateral sin acceso a mercados); el escenario extremo corresponde al del FSAP 2019 — [ECB SSM LiST 2019 annex](https://www.bankingsupervision.europa.eu/press/pr/date/2019/html/ssm.pr191007_annex%7E537c259b6d.en.pdf)
- S&P sobre LiST 2019 (fuente secundaria): incluso los depósitos minoristas estables se asumieron cayendo **más de 10 %**, con supuestos más duros para otros depósitos; la posición neta de liquidez mediana se volvía negativa **después de 80 días** en el escenario extremo — [S&P brief](https://www.allnews.ch/sites/default/files/20191010_SP_ECB_2019_Stress_Test_Eurozone_Banks_Liquidity.pdf)
- Argentina, salida del cepo (abril 2025): en Lemon el volumen de USDT operado superó **US$ 5,7 M en 24 h** y hubo **récord histórico de compra de stablecoins por hora** — [Forbes Argentina](https://www.forbesargentina.com/money/el-dolar-cripto-debuto-cepo-argentina-record-operaciones-uso-arbitrar-n70700); [La Nación](https://www.lanacion.com.ar/economia/IA/con-la-incertidumbre-sobre-el-nuevo-valor-del-dolar-las-stablecoins-registraron-un-auge-nid14042025)
- Argentina, elecciones 2023: Lemon marcó máximo histórico de volumen diario de compra de stablecoins, **triplicando su nivel promedio** y 3 % por encima del pico post-renuncia de Guzmán (2022) — [CriptoNoticias](https://criptonoticias.com/finanzas/aumenta-compra-dolar-cripto-argentina-elecciones)
- Brecha USDT vs mayorista llegó a **6,6 %** en P2P en una semana de declaraciones sobre corrida cambiaria — [CriptoNoticias](https://www.criptonoticias.com/mercados/dolar-cripto-1600-pesos-argentina-brecha-oficial/)
- Movimientos de USDT/DAI **anticipan** al blue cuando el mercado informal está cerrado (fines de semana, feriados, noches electorales) — [El Cronista](https://www.cronista.com/infotechnology/finanzas-digitales/alerta-por-el-dolar-hoy-cual-es-el-precio-que-anticipan-en-las-cuevas-virtuales)
- Caída de partner / incidente operativo: el ABM BoE (versión 2007) ya probaba "un incidente operativo" como escenario, y el stress TARGET2 muestra que con -70 % de colateral se liquida 80–90 % del turnover — [arXiv 0705.3050](https://arxiv.org/abs/0705.3050); [CORE/ECB](https://core.ac.uk/works/2680421)
- Black Friday como shock de campaña: 297,4 M de Pix en un día (2025) — [TecMundo](https://www.tecmundo.com.br/mercado/408966-pix-bate-recorde-com-2974-milhoes-de-operacoes-na-black-friday-de-2025.htm)

### Inferences (síntesis propia: plantillas de escenario como parámetros)
- **Campaña de marketing**: `lift_intensity ∈ [1,2, 2,0]` sobre arquetipos jóvenes/heavy, forma triangular o "pulso con decaimiento" de duración D días, con `lift_amount` opcional (p. ej., cashback que sube ticket). Black Friday de Pix justifica pulsos de 1 día con lift grande; una campaña propia es más larga y menor.
- **Cohorte de onboarding**: agregar N_new usuarios por día durante W días con `activation_curve` (p. ej., 40 % activos día 1, decae a 15 % en 30 días — supuesto); sus egresos iniciales son "retiros de bono/prueba" de monto chico; efecto en prefondeo = más volumen en rails T+0.
- **Payday shift**: mover la masa de `m_payday` (ej. de días hábiles 1–4 a 1–2, o un feriado que empuja todo al día 5) y observar cuánto sube el máximo diario por partner; en Brasil el quinto día hábil cayendo viernes produjo récord, así que el shift más adverso es "payday + viernes + cut-off" (tres días de egresos comprimidos para partners que no liquidan fin de semana).
- **FX panic**: multiplicador 3× (anclado en Lemon 2023) sobre intensidad y monto del arquetipo dolarizador en crypto/stablecoin/dólar MEP, 1–3 días, con **re-ruteo** desde consumo hacia inversión en divisa (los pesos salen por otro rail); opcional Hawkes intradía para el clustering por hora.
- **Partner outage**: partner A fuera por H horas; fracción `reroute_share` de su volumen se mueve a partner B (mismo producto, otro rail/lag) y el resto se **difiere** al reinicio (pico de cola, cf. "liquidity sink" de Arciero). Medir el déficit de prefondeo en B y el backlog en A.
- **Plantilla regulatoria**: traducir run-off LCR a billetera como "fracción de saldos que sale en 30 días": 5 %/10 % es demasiado benigno para un wallet (SVB superó eso en horas); usar LCR como **escenario base**, LiST "extremo" (>10 % retail estable) como adverso, y el 3× de Lemon como idiosincrático-FX.

### Gaps
- No encontré las tablas de outflow por bucket del documento metodológico LiST 2019 (solo prensa/S&P).
- No encontré datos de **duración/lift típicos** de campañas de billeteras (ni en Argentina ni en Brasil); los rangos propuestos son supuestos.
- No encontré un caso documentado de **caída de un partner de billetera** con cifras de re-ruteo; el escenario se diseña por analogía con incidentes RTGS.
- No encontré datos del volumen agregado de dólar MEP/crypto en billeteras por día para calibrar el 3× más allá de un exchange (Lemon).

---

## KQ6. Calibración y validación: agregados públicos, marginales, ACF, zero-inflation, correlación cruzada; por qué lo sintético subestima colas

### Takeaway
La práctica publicada combina (1) **matching de agregados** (AMLworld vs Fed/IRS; PaySim/MoMTSim vs logs del operador), (2) **tests de marginales** (KS, SSE, Bland-Altman), (3) **utilidad downstream**, y, en JPM, (4) **calibración automática por optimización bayesiana o adversarial** sobre series de salida. Evidencia reciente (TabQueryBench 2026) muestra que los generadores neuronales recuperan solo ~41 % de los valores raros en consultas ultra-cola y que métricas globales pueden verse bien mientras fallan localmente: para tesorería, lo que importa es el **percentil 99 del egreso diario por partner**, así que hay que validar colas y ACF explícitamente, no solo medias.

### Cited Findings
- MoMTSim valida con **KS, SSE y Bland-Altman** y propone calibración **iterativa** (corrige, agrega y descarta parámetros) — [DOAJ MoMTSim](https://doaj.org/article/86e345aafb184c23872fb4de1f71f742)
- AMLworld calibra a **transacciones/cuenta (Fed)**, **salarios/pensiones (IRS)**, **mix de medios de pago** y tasa de lavado contra un estudio real — [alphaXiv AMLworld](https://alphaxiv.org/overview/2306.16424v3)
- JPM: pipeline "métricas sobre real → generador → comparar → refinar" — [J.P. Morgan Synthetic Data](https://www.jpmorgan.com/technology/artificial-intelligence/initiatives/synthetic-data); calibración por optimización bayesiana a partir de series de salida — [arXiv 2112.03874](https://arxiv.org/abs/2112.03874); calibración adversarial de simuladores multiagente — [arXiv 2108.00664](https://arxiv.org/abs/2108.00664)
- Karst et al. 2024: **ningún** generador neuronal reproduce la estructura de grafo; las métricas de rendimiento inconsistentes dificultan comparar algoritmos — [arXiv 2412.14730](https://arxiv.org/abs/2412.14730)
- TabQueryBench (jul. 2026, 49 datasets, 11 modelos): la fidelidad cae a medida que las consultas se adentran en la cola; el mejor modelo recupera **~41 % de los valores raros reales** en consultas ultra-raras; el mejor en fidelidad query-céntrica (RealTabFormer) llega a **0,75 ± 0,15** vs 1,00 del real; los modelos puntúan bien en métricas de distancia y fallan en consultas locales y de alta cardinalidad — [EmergentMind arXiv 2607.03926](https://www.emergentmind.com/papers/2607.03926)
- Kapar, Koenen y Jullum (2025): las métricas comunes "dan resultados contradictorios y no señalan las debilidades específicas"; proponen un clasificador real-vs-sintético con XAI para localizar divergencias — [arXiv 2504.20687](https://arxiv.org/abs/2504.20687)
- ECB: los run-offs LCR cubrieron la mayoría de los episodios 2016–2023 pero no SVB/First Republic — ejemplo de que supuestos calibrados al "promedio de estrés" subestiman la cola — [ECB MPB 2023](https://www.ecb.europa.eu/pub/financial-stability/macroprudential-bulletin/focus/2023/html/ecb.mpbu202312_focus02.el.html)
- Fuentes públicas para anclar agregados: BoE CHAPS diario (volumen y valor por tipo ISO 20022) — [BoE](https://www.bankofengland.co.uk/statistics/details/further-details-about-chaps-daily-settlement-data); BCRA Informe Mensual de Pagos Minoristas (mix CBU/CVU, push/pull, billeteras registradas) — [BCRA dic-2025](https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/informes/informe-pagos-minoristas-2025-12.pdf); récords diarios de Pix por fecha (prensa, trazables al SPI) — [Forbes Brasil](https://forbes.com.br/forbes-money/2025/12/pix-bate-recorde-com-313-milhoes-de-transacoes-em-um-dia/)
- Índice de dispersión de un Cox: 1 + Var[Λ]/E[Λ] (chequeo directo de que el agregado no es Poisson-suave) — [Beneš et al.](https://ias-iss.org/ojs/IAS/article/viewFile/829/732)

### Inferences (síntesis propia: checklist de validación para tesorería)
1. **Marginales por usuario**: KS de montos por producto vs histórico (si hay); si no, chequear que la mediana y el p99 del ticket por producto coincidan con los que el negocio conoce.
2. **Zero-inflation**: fracción de usuarios con 0 egresos en el día y en el mes (billeteras tienen cola larga de inactivos); con Poisson puro la fracción de ceros diaria es exp(-λ) — si el real tiene más ceros, usar mezcla "activo/inactivo" (hurdle) por arquetipo.
3. **Agregado diario**: CV del total y por partner tras quitar el patrón semanal/mensual; **índice de dispersión** del conteo diario ≫ 1; ACF a lags 1, 7, 30; el ratio pico/mediana mensual (en Pix los récords caen en el quinto día hábil, así que el día hábil 5 debe ser el máximo del mes en la simulación).
4. **Cross-partner**: matriz de correlación de egresos diarios por partner; esperar alta a lag 0 entre rails rápidos y desplazada por la diferencia de lags para los lentos (KQ4).
5. **Colas**: p95/p99/máximo del egreso diario por partner vs lo observado; comparar en escenario base contra el histórico más alto conocido (payday + viernes); si el máximo simulado nunca supera el histórico, σ_M es demasiado chico (es el error que el ECB documenta con SVB).
6. **Calibración**: con histórico, ajustar (σ_M, φ, m_payday, m_dow) por optimización bayesiana sobre {CV, ACF1, ACF7, ratio pico/mediana} como hace JPM; sin histórico, fijar σ_M para que el máximo del año simulado supere al payday base en ≥ 1,3× y documentarlo como supuesto.

### Gaps
- No encontré un estudio que cuantifique **cuánto** subestiman las colas los simuladores basados en reglas/agentes (TabQueryBench evalúa generadores neuronales); el riesgo en un ABM es el inverso: colas que dependen enteramente de σ_M elegido a mano.
- No encontré CV/ACF publicados de ninguna serie diaria de pagos para fijar objetivos numéricos (repetido de KQ3).

---

## KQ7. Práctica: librerías, rendimiento para ~50k usuarios × 365 días, reproducibilidad y plan de 2–3 h con pseudocódigo

### Takeaway
Para 50k × 365 no hace falta un framework ABM orientado a objetos: Mesa clásico se vuelve impráctico con "unos pocos miles de agentes" y la propia comunidad empuja a `mesa-frames` (agentes en DataFrames Polars/pandas, hasta ~10× más rápido en sus benchmarks). La solución de horas es **numpy/polars vectorizado por día** (365 iteraciones sobre arrays de 50k), con `numpy.random.default_rng(seed)` para reproducibilidad y Faker/`tick`/HawkesPyLib solo si hace falta identidad sintética o clustering intradía.

### Cited Findings
- Mesa clásico guarda cada agente como objeto Python, lo que "rápidamente se vuelve un cuello de botella a escala"; un proyecto GSoC 2024 señala que incluso modelos "de unos pocos miles de agentes" resultan imprácticos — [mesa discussion #1939](https://github.com/projectmesa/mesa/discussions/1939); [GSoC 2024](https://summerofcode.withgoogle.com/archive/2024/projects/kQGgzwon)
- `mesa-frames` (Polars): agentes en DataFrames columnares, actualizaciones vectorizadas (SIMD); benchmarks propios: hasta **10×** en Boltzmann Wealth y ~2× en Sugarscape; no apto si el modelo depende de secuenciación estricta por agente o métodos no vectorizables — [GitHub adamamer20/mesa-frames](https://github.com/adamamer20/mesa-frames)
- `tick.hawkes`: simuladores `SimuHawkesExpKernels`, `SimuHawkesMulti` (paralelo), kernels exp/power-law, núcleo C++; **no mantenido activamente** — [tick API](https://x-datainitiative.github.io/tick/modules/api.html); alternativa `HawkesPyLib` — [GitHub](https://github.com/Simbold/HawkesPyLib)
- Sparkov expone `-seed <INT>` para Faker y paraleliza por chunks de clientes; TabFormer corre sobre dependencias viejas (Python 3.7) — [Sparkov README](https://github.com/namebrandon/Sparkov_Data_Generation); [arXiv 2011.01843](https://arxiv.org/abs/2011.01843)
- ABIDES es un DES de propósito general con decenas de miles de agentes — opción si se quiere **tiempo continuo intradía** con colas y latencias — [arXiv 1904.12066](https://arxiv.org/abs/1904.12066)
- PersonaLedger muestra que un **motor de reglas que mantiene estado por usuario** (saldo, factibilidad) es la pieza que da consistencia contable, independiente de quién proponga las transacciones — [arXiv 2601.03149](https://arxiv.org/abs/2601.03149)

### Inferences — DISEÑO PROPUESTO (síntesis propia, no citada)

**Orden de magnitud**: 50k usuarios × 365 días × ~0,4 egresos/día ≈ 7 M eventos. En numpy, 365 iteraciones de Poisson + lognormal + categorical sobre arrays de 50k tardan segundos; el `groupby` final en polars/pandas también. SimPy/Mesa no aportan nada aquí salvo que se quiera colas intradía.

**Entidades (tablas)**
- `archetypes`: `name, share, base_rate (egresos/día), amount_mu, amount_sigma (log), product_mix (vector), payday_type (none|monthly_d1-4|biweekly|benefit_fixed_day), dow_profile (7), activity_prob (hurdle)`
  - Propuesta inicial (supuestos, ajustar con datos internos): salaried_formal 30 %, informal 25 %, benefit_recipient 15 %, young_heavy 12 %, merchant_sme 8 %, investor 6 %, crypto_dollarizer 4 %.
- `products`: `product_id, partner_id, lag_bd, cutoff_h, weekend_settle, nets_inflows` (transfer_out, qr_payment, bill_pay, card_debit, card_credit, fci_redeem, crypto_buy, mep_buy, cash_out).
- `partners`: calendario de feriados AR + horario.
- `users`: `user_id, archetype, signup_day, payday_offset (0–3 días hábiles), balance (opcional), bills (lista de (día_vencimiento, monto, product))`.
- `scenarios`: lista de modificadores `(type, start, end, params)`.

**Núcleo generativo por día t**
```
# Own synthesis. Vectorized core, one iteration per calendar day.
rng = np.random.default_rng(seed)
logM = 0.0                                    # shared macro factor, AR(1) in logs
for t in days:                                # 365 iterations
    logM = phi*logM + sigma_M*rng.normal()    # phi≈0.7, sigma_M≈0.15 (to calibrate)
    M_t  = np.exp(logM - sigma_M**2/(2*(1-phi**2)))   # mean-one correction

    # calendar multipliers per user (all arrays of length n_users)
    m_dow    = DOW[arch, weekday(t)]
    m_payday = payday_mult(arch, business_day_index(t), payday_offset)  # 1.0 or 1.5–3.0
    m_dom    = DOM[arch, day_of_month(t)]
    m_scn    = scenario_mult(t, arch, product=None)       # campaign/cohort/FX lifts
    active   = (signup_day <= t) & (rng.random(n) < activity_prob[arch])

    lam = base_rate[arch] * m_dow * m_payday * m_dom * m_scn * M_t * active
    k   = rng.poisson(lam)                                # egresos por usuario hoy
    idx = np.repeat(np.arange(n), k)                      # expand to events

    # product choice and amount
    prod = vectorized_categorical(product_mix[arch[idx]] * scenario_product_tilt(t), rng)
    amt  = rng.lognormal(amount_mu[arch[idx], prod] + infl_drift*t, amount_sigma[arch[idx], prod])
    hour = rng.choice(24, size=len(idx), p=HOUR_PROFILE[prod])

    # deterministic items: recurring bills due today, scheduled transfers
    bills_today = bills[(bills.due_dom == day_of_month(t)) & active[bills.user]]
    events_t = concat(stochastic(idx, prod, amt, hour), bills_today)

    # routing to settlement date
    partner  = PRODUCT_TO_PARTNER[events_t.prod]          # outage scenario rewrites this
    late     = events_t.hour >= cutoff_h[partner]
    settle   = add_business_days(t + late, lag_bd[partner], calendar[partner],
                                 weekend_ok=weekend_settle[partner])
    append(events_t with partner, settle)

events = concat_all()
partner_daily = events.groupby(['partner','settle']).amount.sum()   # the series to prefund
if nets_inflows: partner_daily -= inflows_daily (same routing)
```

**Escenarios como funciones puras sobre (t, arch, product)**
- `campaign(start, D, lift, target_archs)`: `m_scn = 1 + (lift-1)*tri(t; start, D)`.
- `cohort(start, W, N_per_day, activation_curve)`: agrega usuarios con `signup_day`, `activity_prob` que decae según la curva.
- `payday_shift(new_window)`: cambia `payday_mult` (ej. todo en día hábil 1–2, o feriado que empuja al 5).
- `fx_panic(start, D, mult=3)`: `m_scn` × 3 para `crypto_dollarizer`/`investor`, `product_tilt` hacia crypto_buy/mep_buy, `amount_mu` + log(1,5); opcional Hawkes intradía con `SimuHawkesExpKernels` para horas.
- `partner_outage(partner, t0, hours, reroute_share, alt_partner)`: eventos de `partner` en la ventana → fracción a `alt_partner` (hereda su lag), resto `settle` = primer día hábil post-reinicio.

**Métricas de salida para el tesorero**
- Por partner: serie `settle → monto`, p50/p95/p99/máx, día del máximo, ratio máx/mediana, ACF(1,7), CV residual, correlación cruzada con otros partners (lag 0 y lag = diferencia de plazos).
- Para la política de prefondeo P(partner, día): `shortfall_d = max(0, outflow_d − P_d)`, días con shortfall, shortfall máximo, costo de sobre-prefondeo = Σ max(0, P_d − outflow_d) × tasa diaria. Esto reproduce la curva "liquidez vs costo de demora" de Galbiati–Soramäki para cada escenario.

**Plan de 2–3 h (hackathon)**
1. (20 min) `config.yaml` con arquetipos, productos, partners, feriados AR 2026 (lista hardcodeada), semilla.
2. (40 min) `generate_users(n, rng)` + `simulate(days, users, config, scenarios, rng)` vectorizado como arriba; salida parquet `events` (user, t, hour, product, partner, amount, settle).
3. (20 min) `route.py`: `add_business_days` con calendario y cut-off; `partner_daily`.
4. (20 min) `scenarios.py`: las cinco funciones puras; cada corrida = `(seed, scenario_list)`.
5. (20 min) `validate.py`: CV, dispersion index, ACF, zero-fraction, cross-partner corr, p99; asserts mínimos (`dispersion > 1.5`, `argmax mensual ∈ días hábiles 1–5` para la cohorte asalariada, `ACF7 > ACF3`).
6. (20 min) `policy.py`: evaluar P fija, P = media móvil, P = cuantil por día-tipo; tabla shortfall/costo por escenario.
7. (resto) notebook con 5 escenarios × 3 políticas, gráficos por partner.

Reproducibilidad: una sola `default_rng(seed)`; semillas derivadas por escenario con `rng.spawn()` para que base y estrés compartan los mismos usuarios y el mismo M_t (comparación "ceteris paribus"). Guardar `config + seed + git hash` en el parquet de salida.

### Gaps
- No ejecuté benchmark alguno; la afirmación "segundos" para 50k × 365 es estimación propia por tamaño (≈7 M eventos), consistente con los límites de Mesa reportados pero no medida.
- No encontré una librería Python mantenida y específica para **calendarios de liquidación por rail** (business-day + cut-off + netting); `pandas.offsets.CustomBusinessDay` con feriados AR es suficiente pero no está documentado para este uso.
- No verifiqué el estado 2026 de `tick` (último dato: "no mantenido activamente"); si falla la instalación, `HawkesPyLib` o un Ogata thinning propio de 30 líneas.
