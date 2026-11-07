"""Prefoundly keynote, v2: a plain everyday case first, one idea per slide, no company names."""
import json, re, random
from pathlib import Path

here = Path(__file__).parent
S = here.parent
orig = (here / 'markup.html').read_text()
logic = (here / 'logic.js').read_text()
run = json.loads((S / 'run_1009_swift.json').read_text())
us = next(p for p in run['partners'] if p['partner'] == 'usd_acquirer')

LOGO = 'c24a7d0c-25cf-4510-9f21-d04aca0edf6c'
MARBLE = '996a71f1-9e8f-4fae-9e40-e19efba10e60'
RIBBON = '5f483ce0-42a2-4bef-9e7e-84d76d1b110f'
COLS, ROWS = 6, 4
FIXED, PRE_BANK = 797469, 600286  # US$, reports/experiments/exante_buffer.csv (intl, k-means, fixed set ahead)
USERS = 20000

def n(x): return f"{x:,.0f}".replace(',', '.')
def icon(name, size=40): return f'<x-import component-from-global-scope="ProfoundlyAIDesignSystem_bb6bcd.Icon" name="{name}" size="{size}px" hint-size="{size}px,{size}px"></x-import>'

BG = {'light': ('pf-grain', 'background:var(--pf-grey-50)'), 'dark': ('', 'background:var(--pf-petrol-900)'),
      'deep': ('', 'background:var(--pf-petrol-950)'), 'mint': ('', 'background:var(--pf-mint-200)')}
INK = {'light': 'var(--pf-petrol-900)', 'mint': 'var(--pf-petrol-900)', 'dark': '#fff', 'deep': '#fff'}
SOFT = {'light': 'var(--pf-teal-700)', 'mint': 'var(--pf-teal-700)', 'dark': 'var(--pf-mint-200)', 'deep': 'var(--pf-mint-200)'}
NOTE = {'light': 'var(--pf-grey-500)', 'mint': 'var(--pf-petrol-800)', 'dark': 'var(--pf-mint-300)', 'deep': 'var(--pf-mint-300)'}

def H(text, color, size=124, b=0, d=300, fx='blur'):
    return (f'<h2 data-b="{b}" data-fx="{fx}" data-d="{d}" style="margin:0;font-size:{size}px;line-height:1.04;font-weight:600;'
            f'letter-spacing:-0.045em;color:{color};text-wrap:balance">{text}</h2>')

def P(text, color, size=46, b=0, d=700, fx='up'):
    return (f'<p data-b="{b}" data-fx="{fx}" data-d="{d}" style="margin:0;font-size:{size}px;line-height:1.25;font-weight:500;'
            f'letter-spacing:-0.015em;color:{color};text-wrap:balance">{text}</p>')

def BIG(text, color, size=300, b=0, d=300, count=None):
    attrs = ''
    if count:
        attrs = ' ' + ' '.join(f'data-{k}="{v}"' for k, v in count.items())
    return (f'<span data-b="{b}" data-fx="stamp" data-d="{d}"{attrs} style="font-size:{size}px;line-height:.9;font-weight:600;'
            f'letter-spacing:-0.06em;color:{color};white-space:nowrap">{text}</span>')

def SRC(text, color, b=0, d=1200):
    return f'<p data-b="{b}" data-fx="fade" data-d="{d}" style="position:absolute;left:140px;right:140px;bottom:60px;margin:0;font-size:22px;color:{color}">{text}</p>'

def center(*parts, gap=40, align='center', pad='0 170px'):
    return (f'<div style="position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;align-items:{align};'
            f'text-align:{"center" if align == "center" else "left"};gap:{gap}px;padding:{pad}">' + ''.join(parts) + '</div>')

def marble(css, b=0, d=0):
    return f'<div data-b="{b}" data-fx="zoom" data-d="{d}" class="pf-marble" style="position:absolute;border-radius:var(--radius-organic);{css}"></div>'

slides = []
def slide(title, bg, inner): slides.append((title, bg, inner))

# 1 · Portada
slide('Portada', 'light', marble('right:-150px;top:-170px;width:560px;height:400px') + marble('left:-170px;bottom:-190px;width:600px;height:420px', d=200)
      + center(f'<img data-b="0" data-fx="wipe" data-d="400" src="{LOGO}" alt="Prefoundly AI" style="display:block;width:1240px;height:auto">',
               P('Para que tu billetera nunca se quede sin plata donde la necesita', 'var(--pf-petrol-900)', 52, d=1300, fx='blur'), gap=56))

# 2 · Paying a bill
phone = f'''<div data-b="0" data-fx="up" data-d="500" style="position:absolute;right:230px;top:110px;width:430px;height:860px;border-radius:70px;background:var(--pf-petrol-950);padding:18px;box-sizing:border-box;box-shadow:0 40px 80px rgba(0,0,0,.25)">
  <div style="position:relative;width:100%;height:100%;border-radius:54px;background:#fff;overflow:hidden;display:flex;flex-direction:column;align-items:center;padding:80px 34px 40px;box-sizing:border-box;gap:20px">
    <span style="font-size:26px;font-weight:600;color:var(--pf-grey-600)">Pagar factura</span>
    <span style="display:grid;place-items:center;width:150px;height:150px;border-radius:50%;background:var(--pf-mint-100);color:var(--pf-petrol-900)">{icon('lightbulb', 84)}</span>
    <span style="font-size:30px;color:var(--pf-grey-700)">Luz · octubre</span>
    <span style="font-size:88px;font-weight:600;letter-spacing:-0.04em;color:var(--pf-petrol-900);font-family:var(--font-mono)">$ 25.000</span>
    <span style="margin-top:auto;width:100%;height:84px;border-radius:24px;background:var(--pf-petrol-900);color:#fff;display:grid;place-items:center;font-size:28px;font-weight:600">Pagar</span>
    <div data-b="1" data-fx="fade" style="position:absolute;inset:0;background:var(--pf-green-600);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:24px;color:#fff">
      <span data-b="1" data-fx="stamp" data-d="150" style="display:grid;place-items:center;width:150px;height:150px;border-radius:50%;background:#fff;color:var(--pf-green-600)">{icon('check', 90)}</span>
      <span style="font-size:46px;font-weight:600">Pagado</span></div>
  </div></div>'''
slide('Pagás la luz', 'light', center(H('Pagás la luz desde tu billetera.', 'var(--pf-petrol-900)', 112),
                                      P('Un toque, y listo.', 'var(--pf-teal-700)', 46, b=1, d=300), align='flex-start', pad='0 820px 0 140px', gap=30) + phone)

# 3 · Who really pays
def node(label, sub, ic, bg, fg, b, d=0):
    return (f'<div data-b="{b}" data-fx="up" data-d="{d}" style="width:400px;display:flex;flex-direction:column;align-items:center;gap:22px;text-align:center">'
            f'<span style="display:grid;place-items:center;width:200px;height:200px;border-radius:50%;background:{bg};color:{fg}">{icon(ic, 96)}</span>'
            f'<span style="font-size:44px;font-weight:600;letter-spacing:-0.02em;color:var(--pf-petrol-900)">{label}</span>'
            f'<span style="font-size:30px;line-height:1.3;color:var(--pf-grey-600)">{sub}</span></div>')
def arrow(label, b, d=0):
    return (f'<div data-b="{b}" data-fx="grow" data-d="{d}" style="flex:1;display:flex;flex-direction:column;align-items:center;gap:14px;margin-top:70px">'
            f'<span style="font-size:28px;font-weight:600;color:var(--pf-teal-700);white-space:nowrap">{label}</span>'
            f'<span style="width:100%;height:6px;border-radius:6px;background:var(--pf-teal-500)"></span></div>')
flow = ('<div style="width:1640px;display:flex;align-items:flex-start;gap:20px">'
        + node('Tu billetera', 'carga plata antes', 'wallet', 'var(--pf-petrol-900)', '#fff', 1)
        + arrow('días antes', 1, 300)
        + node('Un intermediario', 'tiene esa plata', 'landmark', 'var(--pf-mint-200)', 'var(--pf-petrol-900)', 1, 500)
        + arrow('al instante', 2)
        + node('La empresa de luz', 'cobra', 'lightbulb', 'var(--pf-grey-100)', 'var(--pf-petrol-900)', 2, 300) + '</div>')
slide('Quién paga', 'light', center(H('Pero no le paga tu billetera.', 'var(--pf-petrol-900)', 104), flow, gap=90))

# 4 · Prepaid analogy
tank = f'''<div data-b="0" data-fx="up" data-d="600" style="width:1400px;display:flex;flex-direction:column;gap:22px">
  <div style="display:flex;justify-content:space-between;font-size:32px;font-weight:600;color:var(--pf-mint-200)"><span>Saldo cargado en el intermediario</span><span data-b="1" data-fx="fade">cada pago lo baja</span></div>
  <div style="position:relative;height:150px;border-radius:40px;background:var(--pf-petrol-800);overflow:hidden">
    <div data-b="0" data-fx="grow" data-d="900" style="position:absolute;left:0;top:0;bottom:0;width:72%;background:linear-gradient(90deg,var(--pf-mint-300),var(--pf-mint-200));border-radius:40px"></div>
    <div data-b="1" data-fx="fade" style="position:absolute;left:46%;top:0;bottom:0;width:26%;background:var(--pf-petrol-800)"></div>
  </div></div>'''
slide('Prepaga', 'dark', center(H('Es como una tarjeta prepaga.', '#fff', 112), P('La billetera la carga para todos sus usuarios a la vez.', 'var(--pf-mint-100)', 46), tank, gap=48))

# 5 · Dilemma
split = f'''<div style="position:absolute;inset:0;display:grid;grid-template-columns:1fr 1fr">
  <div data-b="0" data-fx="left" data-d="300" style="background:var(--pf-red-100);display:flex;flex-direction:column;justify-content:center;gap:28px;padding:0 120px">
    <span style="display:grid;place-items:center;width:120px;height:120px;border-radius:50%;background:#fff;color:var(--pf-red-600)">{icon('triangle-alert', 60)}</span>
    <span style="font-size:130px;line-height:.95;font-weight:600;letter-spacing:-0.05em;color:var(--pf-red-600)">Si se vacía</span>
    <span style="font-size:50px;line-height:1.2;font-weight:500;color:var(--pf-petrol-900)">tu pago se rechaza.</span></div>
  <div data-b="1" data-fx="right" style="background:var(--pf-petrol-900);display:flex;flex-direction:column;justify-content:center;gap:28px;padding:0 120px">
    <span style="display:grid;place-items:center;width:120px;height:120px;border-radius:50%;background:var(--pf-mint-200);color:var(--pf-petrol-900)">{icon('lock', 60)}</span>
    <span style="font-size:130px;line-height:.95;font-weight:600;letter-spacing:-0.05em;color:#fff">Si sobra</span>
    <span style="font-size:50px;line-height:1.2;font-weight:500;color:var(--pf-mint-100)">es plata parada que no rinde.</span></div></div>'''
slide('Se vacía o sobra', 'light', split)

# 6 · The question
slide('La pregunta', 'deep', marble('left:-160px;top:-170px;width:480px;height:340px') + center(H('¿Cuánto hay que cargar?', '#fff', 140)))

# 7 · Why it is hard
probs = [('calendar-days', 'Cada día se paga distinto.', 'Cobro de sueldos, fines de semana, feriados.'),
         ('trending-down', 'El peso se mueve.', 'Cuando cae, la gente gasta distinto.'),
         ('globe', 'Si la cuenta está afuera, cargarla tarda.', 'Una transferencia bancaria internacional, de 2 a 5 días hábiles.'),
         ('calendar-x', 'Hay feriados en dos países.', 'La plata solo avanza cuando abren los bancos de los dos.'),
         ('ban', 'Y en Brasil se cerró el atajo.', 'Desde octubre de 2026 no se pueden usar stablecoins para esto.')]
items = ''.join(f'<div data-b="{i + 1}" data-fx="left" style="display:grid;grid-template-columns:96px 1fr;align-items:center;gap:34px">'
                f'<span style="display:grid;place-items:center;width:96px;height:96px;border-radius:50%;background:var(--pf-mint-200);color:var(--pf-petrol-900)">{icon(ic, 46)}</span>'
                f'<div style="display:flex;flex-direction:column;gap:4px"><span style="font-size:48px;font-weight:600;letter-spacing:-0.02em;color:#fff">{t}</span>'
                f'<span style="font-size:32px;color:var(--pf-mint-200)">{d}</span></div></div>' for i, (ic, t, d) in enumerate(probs))
slide('Por qué es difícil', 'dark', f'<div style="position:absolute;left:150px;top:96px">{H("¿Por qué es tan difícil?", "#fff", 96)}</div>'
      f'<div style="position:absolute;left:150px;right:150px;top:260px;display:flex;flex-direction:column;gap:26px">{items}</div>'
      + SRC('Plazos según bancos argentinos. Banco Central de Brasil, Resolución 561, vigente desde el 1 de octubre de 2026', 'var(--pf-mint-300)'))

# 8 · Today
slide('Hoy', 'light', center(P('Por eso hoy se usa una regla fija:', 'var(--pf-teal-700)', 52, d=200),
      BIG('11 días', 'var(--pf-petrol-900)', count={'count': 11, 'suffix': ' días'}),
      P('de pagos cargados, por las dudas.', 'var(--pf-petrol-900)', 52, d=900), gap=36)
      + SRC('Días de pago que necesita una regla fija para no quedarse nunca sin saldo, calibrada con las 16 semanas anteriores: 11,6 en pesos y 10,8 con cuentas afuera', 'var(--pf-grey-500)'))

# 10 · Scale
slide('3,39 millones', 'light', center(BIG('3,39 M', 'var(--pf-petrol-900)', count={'count': 3.39, 'dec': 2, 'suffix': ' M'}),
      P('argentinos viajaron a Brasil en 2025. Uno de cada tres turistas que recibió.', 'var(--pf-petrol-900)', 50, d=900), gap=40)
      + SRC('Dato oficial de turismo de Brasil, enero de 2026', 'var(--pf-grey-500)'))

# 11 · One wallet
slide('US$ 150 millones', 'mint', marble('right:-120px;top:-150px;width:520px;height:380px') + center(
    BIG('US$ 150 M', 'var(--pf-petrol-900)', 260, count={'count': 150, 'prefix': 'US$ ', 'suffix': ' M'}),
    P('pagó una sola billetera argentina en Brasil, en cinco semanas.', 'var(--pf-petrol-900)', 50, d=900),
    P('Todo con plata cargada antes.', 'var(--pf-teal-700)', 50, b=1, d=0), gap=36)
      + SRC('Prensa especializada, marzo de 2025', 'var(--pf-petrol-800)'))

# 12 · Reveal
slide('Prefoundly', 'deep', f'<div data-b="0" data-fx="zoom" style="position:absolute;inset:0;background:url(&quot;{MARBLE}&quot;) center/cover;opacity:.28"></div>'
      + center(P('Por eso hicimos', 'var(--pf-mint-200)', 48, d=300),
               f'<div data-b="0" data-fx="blur" data-d="900" style="padding:56px 80px;border-radius:48px;background:var(--pf-grey-50)"><img src="{LOGO}" alt="Prefoundly AI" style="display:block;width:1120px;height:auto"></div>',
               P('Calcula cuánto cargar en cada cuenta, todos los días.', 'var(--pf-mint-100)', 46, b=1, d=0), gap=48))

# 13 · Groups
random.seed(7)
groups = [((420, 250), '#154E4B'), ((980, 180), '#4FA28E'), ((760, 520), '#9EDDC2'), ((1260, 470), '#2C7366')]
scat, clus = [], []
for (cx, cy), col in groups:
    for _ in range(26):
        scat.append(f'<circle cx="{random.uniform(80, 1520):.0f}" cy="{random.uniform(40, 640):.0f}" r="13" fill="#C7CCCA"></circle>')
        clus.append(f'<circle cx="{cx + random.gauss(0, 70):.0f}" cy="{cy + random.gauss(0, 55):.0f}" r="13" fill="{col}"></circle>')
dots = (f'<div style="position:relative;width:1600px;height:680px">'
        f'<svg data-b="0" data-hb="1" data-fx="fade" width="1600" height="680" sc-camel-view-box="0 0 1600 680" style="position:absolute;inset:0">{"".join(scat)}</svg>'
        f'<svg data-b="1" data-fx="fade" width="1600" height="680" sc-camel-view-box="0 0 1600 680" style="position:absolute;inset:0">{"".join(clus)}</svg></div>')
slide('Agrupa', 'light', f'<div style="position:absolute;left:140px;top:100px">{H("1. Mira cómo usa la billetera cada persona.", "var(--pf-petrol-900)", 84)}</div>'
      f'<div style="position:absolute;left:160px;top:300px">{dots}</div>'
      f'<div style="position:absolute;left:140px;bottom:80px">{P("Y arma grupos solo: los que pagan todo cuando cobran, los que gastan el fin de semana, los que casi no la usan.", "var(--pf-teal-700)", 38, b=1, d=300)}</div>')

# 13 · Predicts (plain)
q50, q99 = 155753590.65, 252716607.34  # reports/demo/agent_run.json, bills_aggregator, 2026-10-01
def mbar(label, value, color, tc, b, w):
    return (f'<div data-b="{b}" data-fx="up" style="display:grid;grid-template-columns:360px 1fr;align-items:center;gap:36px">'
            f'<span style="font-size:44px;font-weight:600;color:var(--pf-petrol-900)">{label}</span>'
            f'<div style="height:130px;border-radius:30px;background:var(--pf-grey-100)"><div data-b="{b}" data-fx="grow" data-d="300" style="width:{w:.0f}%;height:100%;border-radius:30px;background:{color};display:flex;align-items:center;padding:0 36px;box-sizing:border-box;white-space:nowrap">'
            f'<span style="font-family:var(--font-mono);font-size:54px;font-weight:500;color:{tc}">$ {q / 1e6:.0f} M</span></div></div></div>').replace('{q', '{q')
def mb(label, v, color, tc, b):
    return (f'<div data-b="{b}" data-fx="up" style="display:grid;grid-template-columns:360px 1fr;align-items:center;gap:36px">'
            f'<span style="font-size:44px;font-weight:600;color:var(--pf-petrol-900)">{label}</span>'
            f'<div style="height:130px;border-radius:30px;background:var(--pf-grey-100)"><div data-b="{b}" data-fx="grow" data-d="300" style="width:{100 * v / q99:.0f}%;height:100%;border-radius:30px;background:{color};display:flex;align-items:center;padding:0 36px;box-sizing:border-box;white-space:nowrap">'
            f'<span style="font-family:var(--font-mono);font-size:54px;font-weight:500;color:{tc}">$ {v / 1e6:.0f} M</span></div></div></div>')
slide('Predice', 'light', center(H('2. Predice cuánto van a pagar mañana.', 'var(--pf-petrol-900)', 92),
      '<div style="width:1640px;display:flex;flex-direction:column;gap:34px">' + mb('Día normal', q50, 'var(--pf-petrol-900)', '#fff', 1)
      + mb('Día malo', q99, 'var(--pf-mint-300)', 'var(--pf-petrol-900)', 2) + '</div>',
      P('Se prepara para el día malo, no para el promedio.', 'var(--pf-teal-700)', 44, b=2, d=600), gap=60)
      + SRC('Pagos de facturas de los usuarios en un día. Día malo: el peor de cada 100 escenarios simulados', 'var(--pf-grey-500)'))

# 14 · Calculates (tank)
need, avail, load = 1022139190.67, 906583094.57, 115557000.0
calc = f'''<div style="width:1500px;display:flex;flex-direction:column;gap:26px">
  <div style="position:relative;height:170px;border-radius:44px;background:var(--pf-petrol-800);overflow:visible">
    <div data-b="0" data-fx="grow" data-d="500" style="position:absolute;left:0;top:0;bottom:0;width:{100 * avail / need * 0.88:.1f}%;border-radius:44px 0 0 44px;background:var(--pf-mint-200)"></div>
    <div data-b="1" data-fx="grow" data-d="200" style="position:absolute;left:{100 * avail / need * 0.88:.1f}%;top:0;bottom:0;width:{100 * load / need * 0.88:.1f}%;background:var(--pf-mint-300);border-left:4px solid var(--pf-petrol-900)"></div>
    <div style="position:absolute;left:88%;top:-30px;bottom:-30px;width:6px;border-radius:6px;background:#fff"></div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:30px">
    <div data-b="0" data-fx="up" style="display:flex;flex-direction:column;gap:6px"><span style="font-size:30px;font-weight:600;color:var(--pf-mint-200)">Hay cargado</span><span style="font-family:var(--font-mono);font-size:64px;color:#fff">$ {avail / 1e6:,.0f} M</span></div>
    <div data-b="1" data-fx="up" style="display:flex;flex-direction:column;gap:6px;align-items:center"><span style="font-size:30px;font-weight:600;color:var(--pf-mint-300)">Carga</span><span style="font-family:var(--font-mono);font-size:64px;color:var(--pf-mint-300)">+ $ {load / 1e6:,.0f} M</span></div>
    <div data-b="0" data-fx="up" style="display:flex;flex-direction:column;gap:6px;align-items:flex-end"><span style="font-size:30px;font-weight:600;color:#fff">Hace falta</span><span style="font-family:var(--font-mono);font-size:64px;color:#fff">$ {n(need / 1e6)} M</span></div>
  </div></div>'''
slide('Calcula', 'dark', center(H('3. Calcula cuánto le falta.', '#fff', 112), calc, gap=80)
      + SRC('Hace falta: lo que se puede pagar, en un día malo, hasta que llegue la próxima carga', 'var(--pf-mint-300)'))

# 15 · Sends it
tl = f'''<div style="position:relative;width:1500px;height:300px">
  <div style="position:absolute;left:40px;right:40px;top:58px;height:10px;border-radius:10px;background:var(--pf-grey-200)"></div>
  <div data-b="1" data-fx="grow" data-d="200" style="position:absolute;left:40px;right:40px;top:58px;height:10px;border-radius:10px;background:var(--pf-teal-500)"></div>
  <div style="position:absolute;left:0;top:20px;display:flex;flex-direction:column;gap:16px;align-items:flex-start"><span style="width:86px;height:86px;border-radius:50%;background:var(--pf-petrol-900);border:12px solid var(--pf-mint-200);box-sizing:border-box"></span><span style="font-size:44px;font-weight:600;color:var(--pf-petrol-900)">Hoy, 9:00</span><span style="font-size:30px;color:var(--pf-grey-600)">Manda $ 116 M</span></div>
  <div data-b="1" data-fx="stamp" data-d="1200" style="position:absolute;right:0;top:20px;display:flex;flex-direction:column;gap:16px;align-items:flex-end"><span style="display:grid;place-items:center;width:86px;height:86px;border-radius:50%;background:var(--pf-green-600);color:#fff">{icon('check', 48)}</span><span style="font-size:44px;font-weight:600;color:var(--pf-petrol-900)">Llega antes de que haga falta</span><span style="font-size:30px;color:var(--pf-grey-600)">Ningún pago se rechaza</span></div></div>'''
slide('La manda sola', 'light', center(H('4. Y la manda solo.', 'var(--pf-petrol-900)', 112), tl, P('Sin que nadie apriete un botón.', 'var(--pf-teal-700)', 44, b=2, d=0), gap=70))

# 16 · Limits
caps = ''.join(f'<div data-b="1" data-fx="up" data-d="{150 * i}" style="flex:1;display:flex;flex-direction:column;gap:18px;padding:44px 48px;border-radius:40px;background:{bg}">'
               f'<span style="font-size:28px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;color:{lc}">{lab}</span>'
               f'<span style="font-size:88px;line-height:1;font-weight:600;letter-spacing:-0.05em;color:{vc};white-space:nowrap">{val}</span></div>'
               for i, (lab, val, bg, lc, vc) in enumerate([('Tope por envío', '$ 500 M', 'var(--pf-petrol-800)', 'var(--pf-mint-300)', '#fff'),
                                                          ('Tope por día', '$ 750 M', 'var(--pf-petrol-800)', 'var(--pf-mint-300)', '#fff'),
                                                          ('Cuenta destino', 'Fija', 'var(--pf-mint-200)', 'var(--pf-teal-700)', 'var(--pf-petrol-900)')]))
slide('Con límites', 'dark', center(H('Con límites que no puede cambiar.', '#fff', 104), f'<div style="width:1640px;display:flex;gap:28px">{caps}</div>',
      P('Si hace falta más, manda hasta el tope y avisa a una persona.', 'var(--pf-mint-100)', 44, b=2, d=0), gap=64))

# 18 · Demo
slide('Demo', 'deep', f'<div data-b="0" data-fx="zoom" style="position:absolute;inset:0;background:url(&quot;{MARBLE}&quot;) center/cover;opacity:.55"></div>' + center(H('Demo', '#fff', 300)))

# 18 · Result
def card(big, label, sub, bg, fg, sc, b):
    return (f'<div data-b="{b}" data-fx="up" style="flex:1;display:flex;flex-direction:column;gap:22px;padding:56px 60px;border-radius:44px;background:{bg}">'
            f'<span data-b="{b}" data-count="{big}" data-prefix="−" data-suffix=" %" data-d="300" style="font-size:220px;line-height:.9;font-weight:600;letter-spacing:-0.06em;color:{fg}">−{big} %</span>'
            f'<span style="font-size:46px;font-weight:600;color:{fg}">{label}</span><span style="font-size:32px;color:{sc}">{sub}</span></div>')
slide('Resultado', 'light', center(H('Menos plata parada. Ningún pago rechazado.', 'var(--pf-petrol-900)', 92),
      '<div style="width:1640px;display:flex;gap:32px">'
      + card(23, 'Cuentas en pesos', '$ 4.709 M → $ 3.617 M', 'var(--pf-petrol-900)', '#fff', 'var(--pf-mint-200)', 0)
      + card(25, 'Cuentas afuera', 'US$ 797 mil → US$ 600 mil', 'var(--pf-mint-200)', 'var(--pf-petrol-900)', 'var(--pf-petrol-800)', 1)
      + '</div>', gap=64)
      + SRC('20.000 usuarios simulados, 8 semanas. Capital promedio contra una regla fija calibrada con las 16 semanas anteriores, con transferencia bancaria en los dos casos', 'var(--pf-grey-500)'))

# 21 · Zero
slide('Cero', 'mint', marble('left:-150px;bottom:-180px;width:560px;height:400px') + center(
    BIG('0', 'var(--pf-petrol-900)', 420),
    P('días sin saldo. Nunca se rechazó un pago.', 'var(--pf-petrol-900)', 54, d=900), gap=30))

# 21 · Scale
per_user = (4708922102.39 - 3616832310.76) / USERS
slide('Un millón de usuarios', 'dark', marble('right:-180px;top:-190px;width:560px;height:400px') + center(
    P('Con 1 millón de usuarios,', 'var(--pf-mint-200)', 56, d=300),
    BIG(f'$ {per_user * 1e6 / 1e9:.0f} mil M', '#fff', 260, d=900, count={'count': round(per_user * 1e6 / 1e9), 'prefix': '$ ', 'suffix': ' mil M'}),
    P('dejan de estar parados.', 'var(--pf-mint-300)', 64, d=1300), gap=36)
      + SRC('Pesos. Proyección desde 20.000 usuarios simulados: en la simulación, el capital creció en proporción a los usuarios desde 5.000', 'var(--pf-mint-300)'))

# 24 · Close
slide('Cierre', 'light', f'<div data-b="0" data-fx="zoom" style="position:absolute;inset:0;background:url(&quot;{RIBBON}&quot;) right center/cover no-repeat"></div>'
      + '<div style="position:absolute;left:140px;top:0;bottom:0;display:flex;flex-direction:column;justify-content:center;gap:48px;max-width:1080px">'
      + H('Cargá lo justo, cuando hace falta.', 'var(--pf-petrol-900)', 112, d=600)
      + f'<img data-b="0" data-fx="up" data-d="1400" src="{LOGO}" alt="Prefoundly AI" style="display:block;width:720px;height:auto;margin-left:-10px"></div>')

assert len(slides) <= COLS * ROWS, len(slides)

start = orig.find('<!-- 01 PORTADA -->')
end = orig.find('</section>\n\n</div>', orig.find('<!-- 07 CIERRE -->')) + len('</section>\n')
pos, body = [], []
for i, (title, bg, inner) in enumerate(slides):
    r, k = divmod(i, COLS)
    c = k if r % 2 == 0 else COLS - 1 - k
    pos.append((c, r, title))
    cls, bgcss = BG[bg]
    cls_attr = f' class="{cls}"' if cls else ''
    body.append(f'<!-- {i + 1:02d} {title} -->\n<section data-st="{i}" data-screen-label="{i + 1:02d} {title}"{cls_attr} '
                f'style="position:absolute;left:{c * 1920}px;top:{r * 1080}px;width:1920px;height:1080px;overflow:hidden;{bgcss}">\n{inner}\n</section>\n')
out = orig[:start] + '\n'.join(body) + orig[end:]
out = out.replace('width:7680px;height:2160px', f'width:{COLS * 1920}px;height:{ROWS * 1080}px')
out = out.replace('grid-template-columns:1fr 1fr;grid-auto-flow:column;grid-template-rows:repeat(4,auto);column-gap:80px;row-gap:12px',
                  'grid-template-columns:1fr 1fr 1fr;grid-auto-flow:column;grid-template-rows:repeat(8,auto);column-gap:40px;row-gap:6px')
out = out.replace('hint-placeholder-count="7"', f'hint-placeholder-count="{len(slides)}"')
out = out.replace('<span style="font-size:36px;font-weight:600;color:#fff">{{ it.t }}</span>', '<span style="font-size:30px;font-weight:600;color:#fff">{{ it.t }}</span>')
(here / 'markup_jobs.html').write_text(out)
st = ',\n    '.join("{ c: %d, r: %d, t: '%s' }" % (c, r, t) for c, r, t in pos)
lg = re.sub(r'ST = \[.*?\];', 'ST = [\n    ' + st + '\n  ];', logic, count=1, flags=re.S).replace('prefoundly-pitch-v3-pos', 'prefoundly-keynote-v2-pos')
(here / 'logic_jobs.js').write_text(lg)
print(len(slides), 'slides')
