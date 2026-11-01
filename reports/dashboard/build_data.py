"""Turns the experiment CSVs into the dashboard's datasets."""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]/'experiments'
OUT=Path(sys.argv[1])
FX,REF_N=1513.0,100000
def num(x,d=0): return f"{x:,.{d}f}".replace(',','#').replace('.',',').replace('#','.')
def m(x): return '$'+num(x/1e6)+' M'
def usd(x):
    v=x/FX/1e6
    return 'USD '+num(v,1 if v<100 else 0)+' M'
def p(x): return '$'+num(round(x,-3))
def pct(x,d=0): return num(100*x,d)+' %'
s=pd.read_csv(ROOT/'scaling.csv')
s['fee_rate']=s.fees/(s.n_days*s.daily_outflow)
g=s.groupby(['n_users','rail','cell'])
esc=g.agg(corridas=('seed','nunique'),capital=('capital','mean'),capital_min=('capital','min'),capital_max=('capital','max'),dias=('cover_days','mean'),faltantes=('shortfall_rate','mean'),buffer_dias=('buffer_days','mean'),activos=('active_users','mean'),egreso_dia=('daily_outflow','mean'),fee_rate=('fee_rate','mean')).reset_index()
esc['por_usuario']=esc.capital/esc.activos
esc['gasto_mes']=esc.egreso_dia/esc.activos*30
esc=esc.replace({np.nan:None})
(OUT/'escala.json').write_text(json.dumps(esc.to_dict('records')))
res=[]
for n,d in esc.groupby('n_users'):
    c=lambda r,k:d[(d.rail==r)&(d.cell==k)].iloc[0]
    hoy,ban,refs,st=c('wire','reference_matched'),c('wire','proposed'),c('stablecoin','reference_matched'),c('stablecoin','proposed')
    res.append(dict(n_users=int(n),usuarios=num(n),corridas=int(hoy.corridas),
      hoy=m(hoy.capital),banco=m(ban.capital),stable_fijo=m(refs.capital),stable=m(st.capital),
      hoy_usd=usd(hoy.capital),stable_usd=usd(st.capital),
      libera=m(hoy.capital-st.capital),libera_usd=usd(hoy.capital-st.capital),ahorro=pct(1-st.capital/hoy.capital),ahorro_banco=pct(1-ban.capital/hoy.capital),ahorro_stable=pct(1-st.capital/refs.capital),
      hoy_usuario=p(hoy.por_usuario),banco_usuario=p(ban.por_usuario),stable_usuario=p(st.por_usuario),
      dias_hoy=num(hoy.dias,1),dias_banco=num(ban.dias,1),dias_stable_fijo=num(refs.dias,1),dias_stable=num(st.dias,1),
      v_hoy=hoy.capital,v_banco=ban.capital,v_stable_fijo=refs.capital,v_stable=st.capital))
(OUT/'resumen.json').write_text(json.dumps(res,ensure_ascii=False))
bp=pd.read_csv(ROOT/'scaling_by_partner.csv')
bp=bp[bp.n_users==REF_N].groupby(['rail','cell','partner','rail_used']).capital.mean().reset_index()
bp=bp[bp.cell!='reference']
pname={'bills_aggregator':'Pago de servicios','card_network':'Tarjeta','fci_custodian':'Fondos (FCI)','crypto_exchange':'Cripto','cash_network':'Efectivo','remittance':'Remesas'}
cname={('wire','reference_matched'):'Regla fija + banco',('wire','proposed'):'Propuesta + banco',('stablecoin','reference_matched'):'Regla fija + stablecoin',('stablecoin','proposed'):'Propuesta + stablecoin'}
bp['partner_es']=bp.partner.map(pname); bp['escenario']=[cname[(a,b)] for a,b in zip(bp.rail,bp.cell)]
bp['id']=bp.escenario+'|'+bp.partner_es
bp['riel']=bp.rail_used.map({'wire':'banco','stablecoin':'stablecoin'})
(OUT/'partners.json').write_text(json.dumps(bp[['id','escenario','partner_es','riel','capital']].to_dict('records'),ensure_ascii=False))
f=pd.read_csv(ROOT/'frontier.csv')
fr=[dict(rail=r.rail,politica='Propuesta' if r.policy=='forecast' else 'Regla fija',parametro=(pct(r.param,1 if r.param==.995 else 0)+' de protección') if r.policy=='forecast' else (num(r.param)+' días de gasto'),capital=r.capital_total_mean,faltantes=r.shortfall_rate,id=f"{r.rail}|{r.policy}|{r.param}") for r in f.itertuples()]
(OUT/'frontera.json').write_text(json.dumps(fr,ensure_ascii=False))
a=pd.read_csv(ROOT/'ablation_pooled.csv')
mn={'seasonal_naive':'Igual que las últimas semanas','aggregate_drivers':'Por partner, con calendario y usuarios','aggregate_drivers_obligations':'Por partner, más débitos ya confirmados','segment_factor':'Por tipo de usuario, con shock común','segment_nofactor':'Por tipo de usuario, sin shock común'}
(OUT/'modelos.json').write_text(json.dumps([dict(modelo=mn[r.model],error=pct(r.wape_q50,1),cobertura=pct(r.cov_90),calibracion=num(r.pit_ks,3)) for r in a.itertuples()],ensure_ascii=False))
meta=esc[(esc.n_users==REF_N)&(esc.cell=='proposed')].iloc[0]
(OUT/'constantes.json').write_text(json.dumps([dict(clave='base',dolar=FX,dolar_txt='$'+num(FX),gasto_mes=meta.gasto_mes,gasto_txt=p(meta.gasto_mes),max_simulado=int(esc.n_users.max()),max_txt=num(esc.n_users.max()),n_ref=REF_N,n_ref_txt=num(REF_N))],ensure_ascii=False))
rows=[]
sp=ROOT/'sensitivity.csv'
if sp.exists():
    t=pd.read_csv(sp)
    lab={'macro_sigma':'Tamaño del shock común','payday':'Reparto del cobro de sueldos','stablecoin_lead_hours':'Horas hasta que el partner usa la stablecoin'}
    val={'late (base)':'Más al final, 4.º día (base)','uniform':'Parejo','bimodal':'1.º y 4.º día','0.05':'5 %','0.15 (base)':'15 % (base)','0.30':'30 %','0.5 (base)':'Media hora (base)','6':'6 horas','24':'24 horas','48':'48 horas'}
    for (ass,v),d in t.groupby(['assumption','value'],sort=False):
        q=lambda r,k:d[(d.rail==r)&(d.cell==k)]
        hoy,ban,st=q('wire','reference_matched'),q('wire','proposed'),q('stablecoin','proposed')
        rows.append(dict(id=f'{ass}|{v}',grupo=lab[ass],valor=val[str(v)],corridas=int(d.seed.nunique()),dias_hoy=num(hoy.cover_days.mean(),1),dias_banco=num(ban.cover_days.mean(),1),dias_stable=num(st.cover_days.mean(),1),ahorro=pct(1-st.capital.mean()/hoy.capital.mean()),v_ahorro=1-st.capital.mean()/hoy.capital.mean()))
(OUT/'sensibilidad.json').write_text(json.dumps(rows,ensure_ascii=False))
print(pd.DataFrame(res)[['usuarios','corridas','hoy','banco','stable','ahorro','ahorro_banco','hoy_usuario','stable_usuario','dias_hoy','dias_stable']].to_string()); print(len(rows),'sens rows; gasto',meta.gasto_mes,'fee',meta.fee_rate, esc[(esc.n_users==REF_N)&(esc.rail=='stablecoin')&(esc.cell=='proposed')].fee_rate.iloc[0])
