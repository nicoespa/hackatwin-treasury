"""Static datasets for the dashboard: assumptions table and simulated user vs public data."""
import json, sys
from pathlib import Path
import pandas as pd, yaml
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(sys.argv[1])
cfg = yaml.safe_load((ROOT/'config/policy.yaml').read_text())
rails = yaml.safe_load((ROOT/'config/rails.yaml').read_text())
arch = yaml.safe_load((ROOT/'config/archetypes.yaml').read_text())['archetypes']
params = json.loads((ROOT/'data/sim/base/params.json').read_text())

IPM='https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/Informes/informe-mensual-pagos-minoristas-2026-07.pdf'
IIF='https://www.bcra.gob.ar/archivos/Pdfs/publicacionesestadisticas/informes/informe-inclusion-financiera-2026-04.pdf'
PUB,RULE,OURS='Dato público','Regla o práctica','Supuesto nuestro'
names={'salaried_formal':'asalariado','informal':'informal','anses_beneficiary':'jubilado o AUH','young_heavy':'joven intensivo','investor':'inversor','crypto_active':'cripto','merchant':'comercio'}
shares=', '.join(f"{names[k]} {v['share']:.0%}" for k,v in arch.items())
def med(a,p): return arch[a]['products'][p]
rows=[
 # Mercado
 ('Mercado','Personas con cuenta en Argentina','37,8 millones (dic-2025)',PUB,'Referencia para comparar el gasto por persona.','BCRA, Informe de Inclusión Financiera',IIF),
 ('Mercado','Cuentas de pago de billeteras','67,3 millones; 14,7 millones con saldo (jun-2026)',PUB,'Muestra que la cuenta promedio mueve mucho menos que el usuario simulado.','BCRA, Informe de Pagos Minoristas',IPM),
 ('Mercado','Pagos con tarjeta por mes','Crédito 176,2 M por $10,6 billones; débito 163,7 M por $5,2 billones; prepaga 43,5 M por $0,78 billones (jun-2026)',PUB,'Ticket y gasto de referencia.','BCRA, Informe de Pagos Minoristas',IPM),
 ('Mercado','Pagos con QR por mes','116,9 M por $3,0 billones (jul-2026)',PUB,'Contexto de ticket. No se simula aparte.','BCRA, Informe de Pagos Minoristas',IPM),
 ('Mercado','Inflación','23,6 % acumulada a sep-2026, cerca de 2,4 % por mes',PUB,f"El simulador usa {params['inflation_monthly']:.0%} por mes.",'El Economista, 23-10-2026','https://eleconomista.com.ar/economia/el-banco-central-cambia-reglas-mercado-pago-uala-otras-billeteras-pasara-noviembre-n99145/amp'),
 ('Mercado','Rendimiento de la plata en pesos','TNA de 14 % a 24 % en fondos de billeteras',PUB,'Costo de oportunidad de la plata quieta. Default de la calculadora: 20 %.','El Economista, 23-10-2026','https://eleconomista.com.ar/economia/el-banco-central-cambia-reglas-mercado-pago-uala-otras-billeteras-pasara-noviembre-n99145/amp'),
 ('Mercado','Dólar mayorista','$1.513 (14-oct-2026)',PUB,'Solo para mostrar pesos en dólares.','Rava Bursátil','https://www.rava.com/cotizaciones/historico/dolar-mayorista/2026/10/14/'),
 # Calendario
 ('Calendario','Pago de sueldos','Hasta el 4.º día hábil, plazo máximo legal',PUB,'Por eso el cobro se reparte entre los días hábiles 1 y 4.','Ley de Contrato de Trabajo, art. 128','https://www.argentina.gob.ar/normativa/nacional/25552/actualizacion'),
 ('Calendario','Reparto del cobro dentro de esos días','10 %, 20 %, 30 % y 40 %',OURS,'Hipótesis del simulador. Se prueba con otras dos.','Sin dato público',None),
 ('Calendario','Sueldo que pasa a billeteras','Más de 40 % lo mueve en 48 horas',PUB,'Justifica el pico de pagos e inversión después de cobrar. Fuente secundaria.','Cámara Argentina Fintech, vía MDZ','https://www.mdzol.com/dinero/adios-al-banco-4-cada-10-argentinos-mueven-su-sueldo-billeteras-virtuales-apenas-cobran-n1466121'),
 ('Calendario','Pico de pagos el día de cobro','Pix: 313 M operaciones el 5.º día hábil, contra 200 a 220 M típicos',PUB,'Es la referencia de forma, porque Argentina no publica serie diaria. El rango típico es inferido.','Forbes Brasil','https://forbes.com.br/forbes-money/2025/12/pix-bate-recorde-com-313-milhoes-de-transacoes-em-um-dia/'),
 ('Calendario','Salto del dólar','Compra de stablecoins hasta 3 veces el promedio',PUB,'Referencia del escenario de pánico cambiario. Dato de un solo exchange.','CriptoNoticias, sobre Lemon','https://criptonoticias.com/finanzas/aumenta-compra-dolar-cripto-argentina-elecciones'),
 # Usuarios
 ('Usuarios','Tipos de usuario y participación',shares,OURS,'Define la mezcla de productos. No hay demografía pública por billetera.','Sin dato público',None),
 ('Usuarios','Ticket y frecuencia por producto',f"Ej. asalariado: tarjeta ${med('salaried_formal','card_purchase')['amount_median']:,} mediana, {med('salaried_formal','card_purchase')['base_rate_per_day']:.2f} compras por día".replace(',','.'),OURS,'Es lo que más pesa en la plata final. Se puede mover en la calculadora.','Elegidos a mano, comparados con BCRA abajo',None),
 ('Usuarios','Usuarios nuevos','60 % activos al inicio, 40 % entran por tandas mensuales',OURS,'Da el crecimiento de la base durante el año.','Sin dato público',None),
 ('Usuarios','Fuera del modelo','Transferencias a CBU o CVU, abandono de usuarios, fraude',OURS,'Las transferencias salen por COELSA, no de un saldo en partner. Ojo: sin abandono, la base solo crece.','Decisión de diseño',None),
 # Sorpresas
 ('Shock común','Sorpresa diaria compartida',f"Desvío {params['sigma_m']:.0%}, persistencia {params['phi']}",OURS,'Es lo que hace que todos los usuarios se muevan juntos. Lo más determinante para el colchón. No hay serie diaria pública para calibrarlo.','Sin dato público',None),
 # Partners
 ('Partners','Cuándo liquida cada partner','Servicios, FCI, cripto y remesas en el día; tarjeta y efectivo al día hábil siguiente',OURS,'Tarjeta débito T+1 sí está documentado. Los demás plazos son contractuales y no son públicos.','BCRA para débito; el resto supuesto','https://www.cronista.com/finanzas-mercados/desde-hoy-los-pagos-con-debito-a-los-comercios-se-acreditaran-en-un-dia'),
 ('Partners','Qué partner acepta stablecoin','Servicios, tarjeta y remesas sí. FCI y efectivo solo banco. Cripto solo stablecoin',OURS,'Por eso el escenario stablecoin no llega a todos los partners.','Sin dato público',None),
 # Rieles
 ('Rieles','Transferencia bancaria',f"{rails['wire']['lead_time_hours']} horas hábiles, corte {rails['wire']['instruct_cutoff_hour']}:00, acredita {rails['wire']['credit_hour']}:00",OURS,'Coincide con lo que contó el CPO entrevistado (hasta 48 horas).','Entrevista HackaTwin, 30-10',None),
 ('Rieles','Stablecoin',f"{int(rails['stablecoin']['lead_time_hours']*60)} minutos, todos los días",OURS,'Tiempo hasta que el partner puede usar la plata. Es optimista si hay que convertir a pesos, por eso se prueba con más horas.','Supuesto; matiz en Circle','https://www.circle.com/blog/the-economics-of-usdc-and-why-our-partners-win'),
 ('Rieles','Costo de usar stablecoin',f"{rails['stablecoin']['bps']} puntos básicos sobre lo enviado",OURS,'No se cotizó con un proveedor. Es lo que decide si conviene: mirá el punto de equilibrio.','Referencia: Tether cobra 0,1 % o más al redimir','https://stablecoininsider.org/how-to-redeem-a-stablecoin-for-dollars/'),
 ('Rieles','Comisión fija por transferencia',f"{rails['wire']['fixed_fee']} en banco y {rails['stablecoin']['fixed_fee']} en stablecoin",OURS,'Error nuestro: quedó en pesos cuando la pensamos en dólares. Por eso casi no pesa. Corregirla favorecería a stablecoin.','A corregir',None),
 # Política
 ('Política','Regla típica de la industria','Dejar un día de volumen en semana y tres el fin de semana',RULE,'Inspira la comparación contra un colchón fijo en días de gasto.','Marqeta, guía de fondeo','https://community.marqeta.com/t5/knowledge-base/program-funding-account-management-101-guide/ta-p/418'),
 ('Política','Nivel de protección de la regla propuesta',f"{cfg['alpha']:.0%} de los escenarios simulados",OURS,'En la práctica dio más seguridad que eso, porque la regla es conservadora.','Elección nuestra',None),
 ('Política','Costo de un pago rechazado',f"${cfg['cost_per_usd_rejected']} por cada peso rechazado",OURS,'Nadie publica este dato para billeteras. Cada empresa tiene que medirlo.','Proxy: 40 % no reintenta tras un rechazo (Forter)','https://paymentsnext.com/?p=12925'),
 ('Política','Costo de capital',f"{cfg['cost_of_capital_annual']:.0%} anual en el backtest; 20 % por default en la calculadora",OURS,'El 12 % queda bajo frente a lo que rinde un fondo en pesos.','Elección nuestra',None),
 ('Política','Reserva central','No se cuenta',OURS,'Límite importante: en ningún escenario se suma la plata que hay que tener lista antes de enviar.','Decisión de diseño',None),
]
assumptions=[dict(id=i+1,grupo=r[0],dato=r[1],valor=r[2],origen=r[3],uso=r[4],fuente=r[5],url=r[6]) for i,r in enumerate(rows)]
(OUT/'supuestos.json').write_text(json.dumps(assumptions,ensure_ascii=False,indent=0))

e=pd.read_parquet(ROOT/'data/sim/base/events.parquet',columns=['at','product','amount','direction','settle_at'])
u=pd.read_parquet(ROOT/'data/sim/base/users.parquet')
w=e[(e['at']>='2026-09-05')&(e['at']<'2026-11-01')]
days=(pd.Timestamp('2026-11-01')-pd.Timestamp('2026-09-05')).days
active=sum((u.activation_date<=d).sum() for d in pd.date_range('2026-09-05',periods=days))/days
cards=w[w['product']=='card_purchase']
out=w[w.direction==1]
pm=lambda x:x/active/days*30
daily=e[e.direction==1].groupby(e['at'].dt.normalize()).amount.sum()
daily=daily[(daily.index>='2026-01-01')&(daily.index<='2026-10-31')]
detr=daily/daily.rolling(28,center=True,min_periods=14).mean()
persons,accounts=37.8e6,67.3e6
card_total=(10.6+5.2+0.78)*1e12
card_ops=(176.2+163.7+43.5)*1e6
sim_vs=[
 dict(id='ticket',metrica='Ticket promedio de tarjeta',simulado=cards.amount.mean(),publico=5.2e12/163.7e6,unidad='pesos',referencia='Débito, BCRA jun-2026',lectura='Parecido a débito. Prepaga es cerca de $18.000 y crédito cerca de $60.000.'),
 dict(id='ops',metrica='Compras con tarjeta por mes, por usuario',simulado=pm(len(cards)),publico=card_ops/persons,unidad='veces',referencia='Todas las tarjetas sobre 37,8 M personas',lectura='Algo más que el promedio nacional.'),
 dict(id='gasto',metrica='Gasto mensual con tarjeta por usuario',simulado=pm(cards.amount.sum()),publico=card_total/persons,unidad='pesos',referencia='Todas las tarjetas sobre 37,8 M personas',lectura='Parecido al total por persona: el usuario simulado hace todo su gasto con esta billetera.'),
 dict(id='prepaga',metrica='Gasto mensual con tarjeta por cuenta de billetera',simulado=pm(cards.amount.sum()),publico=0.78e12/accounts,unidad='pesos',referencia='Prepaga sobre 67,3 M cuentas de pago',lectura='Mucho más que una cuenta promedio, que suele estar casi sin uso. Por eso la calculadora deja bajar el gasto.'),
 dict(id='pico',metrica='Día de pico contra día típico',simulado=float(detr.quantile(.99)),publico=313/210,unidad='veces',referencia='Pix: récord contra un día típico (inferido)',lectura='Parecido a Pix.'),
]
def _t(x,u):
    txt=f"{x:,.0f}".replace(',','.') if u=='pesos' else f"{x:.1f}".replace('.',',')
    return ('$'+txt) if u=='pesos' else (txt+' veces')
for r in sim_vs:
    r['simulado_txt'],r['publico_txt']=_t(r['simulado'],r['unidad']),_t(r['publico'],r['unidad'])
(OUT/'sim_vs_publico.json').write_text(json.dumps(sim_vs,ensure_ascii=False,indent=0))
print(json.dumps(sim_vs,ensure_ascii=False,indent=1)); print(len(assumptions),'assumptions; active',active,'outflow per user-month',pm(out.amount.sum()))
