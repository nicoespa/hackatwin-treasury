// First-visit product tour and hover explanations for the Prefoundly console.
// Targets are the [data-tour] / [data-tip] elements of the page; the stage is scaled to fit the window,
// so everything here is positioned from getBoundingClientRect (screen pixels).
(() => {
  const KEY = 'pf-tour-v1';
  const STEPS = [
    { target: 'hero', title: 'Reposición de hoy', body: 'Acá ves cuánto se le envió al partner y si la reposición ya se acreditó. Prefoundly toma en cuenta el saldo que ya tiene el partner y calcula cuánto más necesita para cubrir los pagos hasta la próxima reposición.' },
    { target: 'kpis', title: 'Cómo viene el día', body: 'Mirá cuánto saldo queda, cuánto se pagó hoy y si los pagos vienen por encima o por debajo de lo previsto. Con cada actualización, Prefoundly estima cuánto habrá que reponer mañana.' },
    { target: 'chart', title: 'Pagos hora a hora', body: 'La línea continua muestra el monto pagado en cada hora. La punteada muestra cuánto se esperaba pagar en esa misma hora.' },
    { target: ['agent', 'm-agent'], title: 'Agente en vivo', body: 'Acá ves en tiempo real lo que el agente detecta y las acciones que realiza. Cada evento queda registrado con su hora.' },
    { target: ['ask', 'm-agent'], title: 'Hablá con el agente', body: 'Preguntale «¿Alcanza el saldo hasta la próxima reposición?» o pedile «Subí el objetivo de cobertura al 99,5 %».' },
    { target: ['partners', 'm-partners'], title: 'Monitoreo por partner', body: 'Elegí un partner para ver sus pagos, su saldo y cuánto se estima reponerle mañana.' },
    { target: ['history', 'm-history'], title: 'Historial de reposiciones', body: 'Revisá cuánto se repuso, cuánto se pagó y qué saldo quedó al cierre de cada día. También podés ver qué tan cerca estuvo el pronóstico.' },
    { target: ['mcp', 'm-mcp'], title: 'Conectá tu agente', body: 'Accedé a Prefoundly desde Claude Code, Claude Desktop o tu propio agente mediante MCP.' },
  ];
  const TIPS = {
    hero: 'Lo que mandó el agente a las 09:00: lo que hace falta con la cobertura elegida, menos lo que ya había en el partner.',
    bal: 'Lo que queda ahora en el partner para cubrir pagos: lo que había a las 09:00 más la reposición, menos lo pagado desde entonces.',
    cons: 'Lo que pagaron los usuarios desde las 00:00.',
    dev: 'Cuánto se apartan los pagos de lo que esperaba el modelo hasta esta hora.',
    next: 'Lo que habría que mandar mañana a las 09:00 si el día sigue así. Se recalcula con cada pago.',
    chart: 'Monto pagado en cada hora, en millones de pesos. Continua: lo pagado. Punteada: lo esperado.',
    ask: 'Preguntá en lenguaje natural o dale una orden. El agente decide solo; las órdenes solo lo limitan.',
    partners: 'Elegí un partner para ver su reposición y su pronóstico.',
    'h-total': 'Suma de lo que repuso el agente en los últimos 14 días.',
    'h-short': 'Días en que el saldo del partner llegó a quedar negativo.',
    'h-close': 'Saldo promedio que quedó en el partner al final de cada día.',
    'h-mape': 'Diferencia promedio entre el pronóstico de cada día y lo que se pagó.',
    'h-bars': 'Por día: lo que repuso el agente y lo que se pagó.',
    'h-table': 'El detalle de cada día. «Preguntar al agente» explica esa reposición.',
  };

  const css = `
  .pft-layer{position:fixed;inset:0;z-index:2147483000;font-family:var(--font-sans, Figtree, system-ui, sans-serif);-webkit-font-smoothing:antialiased}
  .pft-layer svg{position:absolute;inset:0;width:100%;height:100%}
  .pft-hole,.pft-ring{transition:x .38s cubic-bezier(.2,.7,.2,1),y .38s cubic-bezier(.2,.7,.2,1),width .38s cubic-bezier(.2,.7,.2,1),height .38s cubic-bezier(.2,.7,.2,1)}
  .pft-dim{fill:rgba(9,38,36,.62);animation:pft-in .3s ease-out both}
  .pft-ring{fill:none;stroke:#9EDDC2;stroke-width:2}
  .pft-card{position:absolute;left:0;top:0;width:372px;max-width:calc(100vw - 24px);box-sizing:border-box;padding:22px 24px 18px;border-radius:20px;background:#fff;color:#4F5A57;box-shadow:0 18px 48px rgba(9,38,36,.28),0 2px 6px rgba(9,38,36,.12);transition:transform .38s cubic-bezier(.2,.7,.2,1),opacity .2s;outline:none}
  .pft-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
  .pft-count{font-size:12px;font-weight:600;letter-spacing:.02em;color:#2C7366;background:#D6F2E5;border-radius:999px;padding:4px 10px}
  .pft-bars{display:flex;gap:4px}
  .pft-bars i{width:14px;height:4px;border-radius:2px;background:#E2E7E5}
  .pft-bars i.on{background:#154E4B}
  .pft-title{margin:0 0 6px;font-size:19px;line-height:1.25;font-weight:600;color:#154E4B;letter-spacing:-.01em}
  .pft-body{margin:0;font-size:15px;line-height:1.5}
  .pft-foot{display:flex;align-items:center;justify-content:space-between;margin-top:18px}
  .pft-skip{border:0;background:none;padding:6px 0;font:inherit;font-size:14px;color:#6E7976;cursor:pointer}
  .pft-skip:hover{color:#154E4B}
  .pft-nav{display:flex;gap:8px}
  .pft-btn{height:40px;padding:0 18px;border-radius:999px;font:inherit;font-size:15px;font-weight:600;cursor:pointer;transition:background .15s,border-color .15s}
  .pft-prev{border:1px solid #C7CCCA;background:#fff;color:#154E4B}
  .pft-prev:hover{border-color:#154E4B}
  .pft-next{border:0;background:#154E4B;color:#fff}
  .pft-next:hover{background:#0E3836}
  .pft-btn:focus-visible,.pft-skip:focus-visible,.pft-help:focus-visible{outline:2px solid #4FA28E;outline-offset:2px}
  .pft-tip{position:fixed;z-index:2147482000;max-width:300px;padding:10px 13px;border-radius:12px;background:#0E3836;color:#fff;font:500 13.5px/1.45 var(--font-sans, Figtree, system-ui, sans-serif);box-shadow:0 10px 28px rgba(9,38,36,.25);pointer-events:none;opacity:0;transform:translateY(4px);transition:opacity .16s,transform .16s}
  .pft-tip.on{opacity:1;transform:none}
  .pft-tip b{display:block;margin-bottom:2px;font-weight:600;color:#9EDDC2}
  .pft-help{position:fixed;left:18px;bottom:18px;z-index:2147481000;display:inline-flex;align-items:center;gap:8px;height:38px;padding:0 14px 0 10px;border-radius:999px;border:1px solid #DEE1DF;background:#fff;color:#154E4B;font:600 13.5px var(--font-sans, Figtree, system-ui, sans-serif);cursor:pointer;box-shadow:0 2px 8px rgba(9,38,36,.08)}
  .pft-help:hover{border-color:#9EDDC2;background:#F2FBF7}
  .pft-help i{width:20px;height:20px;border-radius:50%;background:#154E4B;color:#fff;display:grid;place-items:center;font-style:normal;font-size:12px;font-weight:700}

  .pfs{position:fixed;inset:0;z-index:2147483500;overflow:hidden;color:#fff;font-family:var(--font-sans, Figtree, system-ui, sans-serif);-webkit-font-smoothing:antialiased;
    background:#0E3836;display:grid;place-items:center;transition:opacity .7s cubic-bezier(.2,.7,.2,1),transform .7s cubic-bezier(.2,.7,.2,1)}
  .pfs.out{opacity:0;transform:scale(1.03);pointer-events:none}
  .pfs-bg{position:absolute;inset:-4%;background:url("assets/marble-full.jpg") center/cover;animation:pfs-zoomin 1.6s cubic-bezier(.2,.7,.2,1) both,pfs-drift 24s 1.6s ease-in-out infinite alternate}
  .pfs-bg::after{content:"";position:absolute;inset:0;background-image:var(--cross-pattern, none);background-size:14px 14px;opacity:.55}
  .pfs-shade{position:absolute;inset:0;background:radial-gradient(60% 55% at 50% 50%, rgba(9,38,36,.42) 0%, rgba(9,38,36,.12) 60%, transparent 100%)}
  .pfs-inner{position:relative;display:flex;flex-direction:column;align-items:center;text-align:center;gap:clamp(20px,2.6vw,40px);padding:0 24px}
  .pfs-kicker{margin:0;font-size:clamp(18px,1.9vw,30px);font-weight:500;color:#D6F2E5;text-shadow:0 2px 14px rgba(9,38,36,.35);animation:pfs-up .8s .5s cubic-bezier(.2,.7,.2,1) both}
  .pfs-card{padding:clamp(28px,3.2vw,56px) clamp(36px,4.4vw,80px);border-radius:clamp(24px,2.6vw,48px);background:#F4F5F4;box-shadow:0 30px 80px rgba(9,38,36,.35);animation:pfs-blur 1.1s .8s cubic-bezier(.2,.7,.2,1) both}
  .pfs-logo{display:block;width:min(56vw,1120px);height:auto}
  .pfs-tag{margin:0;max-width:26em;font-size:clamp(19px,2.2vw,36px);line-height:1.25;font-weight:500;letter-spacing:-.01em;color:#fff;text-wrap:balance;text-shadow:0 2px 16px rgba(9,38,36,.45);animation:pfs-up .9s 1.5s cubic-bezier(.2,.7,.2,1) both}
  .pfs-start{margin-top:clamp(6px,1vw,16px);height:60px;padding:0 44px;border:0;border-radius:999px;background:#fff;color:#154E4B;font:inherit;font-size:19px;font-weight:700;cursor:pointer;box-shadow:0 14px 34px rgba(9,38,36,.35);transition:transform .2s cubic-bezier(.2,.7,.2,1),box-shadow .2s,background .2s;animation:pfs-up .8s 2s cubic-bezier(.2,.7,.2,1) both}
  .pfs-start:hover{transform:translateY(-2px);background:#D6F2E5;box-shadow:0 18px 40px rgba(9,38,36,.4)}
  .pfs-start:focus-visible{outline:2px solid #fff;outline-offset:4px}
  @keyframes pfs-zoomin{from{opacity:0;transform:scale(1.12)}to{opacity:1;transform:none}}
  @keyframes pfs-drift{from{transform:none}to{transform:scale(1.06) translate(-1.5%,1%)}}
  @keyframes pfs-blur{from{opacity:0;filter:blur(14px);transform:scale(.96)}to{opacity:1;filter:blur(0);transform:none}}
  @keyframes pfs-up{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
  @media (max-width:899px){.pft-help{top:12px;bottom:auto;left:auto;right:96px;width:32px;height:32px;box-shadow:none;padding:0;justify-content:center;font-size:0;gap:0}.pft-help i{width:24px;height:24px;font-size:13px}}
  @media (max-width:600px){.pfs-logo{width:78vw}}
  @media (prefers-reduced-motion: reduce){.pfs,.pfs *,.pfs-bg{animation:none !important;transition:none !important}}
  @keyframes pft-in{from{opacity:0}to{opacity:1}}
  @media (prefers-reduced-motion: reduce){.pft-layer *,.pft-tip{animation:none !important;transition:none !important}}
  `;
  const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
  const store = { get() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }, set() { try { localStorage.setItem(KEY, '1'); } catch (e) { /* private mode */ } } };
  // a step may name several targets (desktop, then phone); the first one on screen wins
  const target = (names) => [].concat(names).map((n) => document.querySelector(`[data-tour="${n}"]`))
    .find((e) => e && e.getBoundingClientRect().width > 0) || null;

  let layer = null, card = null, i = 0, active = false;

  function close() {
    active = false; store.set();
    if (layer) layer.remove(); layer = null;
    document.removeEventListener('keydown', onKey, true);
    window.removeEventListener('resize', place);
  }
  function onKey(e) {
    if (!active) return;
    if (e.key === 'Escape') { e.preventDefault(); close(); }
    else if (e.key === 'ArrowRight' || (e.key === 'Enter' && document.activeElement && !document.activeElement.classList.contains('pft-btn'))) { e.preventDefault(); go(i + 1); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); go(i - 1); }
  }
  function start() {
    if (active) return;
    active = true; i = 0;
    layer = el('div', 'pft-layer');
    layer.setAttribute('role', 'dialog'); layer.setAttribute('aria-modal', 'true'); layer.setAttribute('aria-labelledby', 'pft-title');
    layer.innerHTML = `<svg aria-hidden="true"><defs><mask id="pft-mask"><rect width="100%" height="100%" fill="#fff"/><rect class="pft-hole" rx="18" fill="#000" x="50%" y="50%" width="0" height="0"/></mask></defs>
      <rect class="pft-dim" width="100%" height="100%" mask="url(#pft-mask)"/><rect class="pft-ring" rx="18" x="50%" y="50%" width="0" height="0"/></svg>`;
    layer.addEventListener('click', (e) => { if (e.target === layer || e.target.closest('svg')) e.stopPropagation(); });
    document.body.appendChild(layer);
    document.addEventListener('keydown', onKey, true);
    window.addEventListener('resize', place);
    go(0);
  }
  function go(n) {
    if (n < 0) return;
    if (n >= STEPS.length) { close(); return; }
    i = n;
    if (card) card.remove();
    const s = STEPS[i], total = STEPS.length;
    layer.querySelector('.pft-dim').style.mask = '';
    card = el('div', 'pft-card');
    card.innerHTML = `<div class="pft-top"><span class="pft-count">${i + 1} de ${total}</span><span class="pft-bars">${Array.from({ length: total }, (_, k) => `<i class="${k <= i ? 'on' : ''}"></i>`).join('')}</span></div>
      <h3 class="pft-title" id="pft-title">${s.title}</h3><p class="pft-body">${s.body}</p>
      <div class="pft-foot"><button class="pft-skip" data-a="skip">Saltar recorrido</button><div class="pft-nav">${i > 0 ? '<button class="pft-btn pft-prev" data-a="prev">Anterior</button>' : ''}<button class="pft-btn pft-next" data-a="next">${i === total - 1 ? 'Terminar' : 'Siguiente'}</button></div></div>`;
    card.style.opacity = '0';
    card.tabIndex = -1;
    card.addEventListener('click', (e) => {
      const a = e.target.closest('[data-a]'); if (!a) return;
      e.stopPropagation();
      if (a.dataset.a === 'next') go(i + 1); else if (a.dataset.a === 'prev') go(i - 1); else close();
    });
    layer.appendChild(card);
    place();
    requestAnimationFrame(() => { card.style.opacity = '1'; const b = card.querySelector('.pft-next'); if (b) b.focus({ preventScroll: true }); });
  }
  function setHole(r) {
    const hole = layer.querySelector('.pft-hole'), ring = layer.querySelector('.pft-ring');
    for (const node of [hole, ring]) {
      if (!r) { node.setAttribute('width', 0); node.setAttribute('height', 0); continue; }
      node.style.x = r.x + 'px'; node.style.y = r.y + 'px'; node.style.width = r.w + 'px'; node.style.height = r.h + 'px';
      node.setAttribute('rx', r.rx);
    }
    ring.style.opacity = r ? '1' : '0';
  }
  function place() {
    if (!active || !card) return;
    const s = STEPS[i];
    const t = target(s.target); if (!t) { go(i + 1); return; }
    if (t.getBoundingClientRect().bottom > window.innerHeight || t.getBoundingClientRect().top < 0) t.scrollIntoView({ block: 'center' });
    const b = t.getBoundingClientRect(), pad = 8;
    const r = { x: b.left - pad, y: b.top - pad, w: b.width + pad * 2, h: b.height + pad * 2, rx: Math.min(22, Math.max(10, parseFloat(getComputedStyle(t).borderTopLeftRadius) * (b.width / t.offsetWidth || 1) + pad)) };
    setHole(r);
    const W = window.innerWidth, H = window.innerHeight, cw = card.offsetWidth, ch = card.offsetHeight, gap = 18;
    const room = { right: W - (r.x + r.w), left: r.x, below: H - (r.y + r.h), above: r.y };
    let x, y;
    if (room.right >= cw + gap + 12) { x = r.x + r.w + gap; y = r.y + r.h / 2 - ch / 2; }
    else if (room.left >= cw + gap + 12) { x = r.x - cw - gap; y = r.y + r.h / 2 - ch / 2; }
    else if (room.below >= ch + gap + 12) { x = r.x + r.w / 2 - cw / 2; y = r.y + r.h + gap; }
    else if (room.above >= ch + gap + 12) { x = r.x + r.w / 2 - cw / 2; y = r.y - ch - gap; }
    else { x = r.x + r.w / 2 - cw / 2; y = r.y + r.h / 2 - ch / 2; }
    x = Math.max(12, Math.min(W - cw - 12, x)); y = Math.max(12, Math.min(H - ch - 12, y));
    card.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
  }

  // hover explanations
  let tip = null, timer = null, current = null;
  function showTip(node) {
    const key = node.dataset.tip, text = TIPS[key]; if (!text || active) return;
    if (!tip) { tip = el('div', 'pft-tip'); tip.setAttribute('role', 'tooltip'); document.body.appendChild(tip); }
    tip.textContent = text;
    const b = node.getBoundingClientRect(), tw = Math.min(300, tip.offsetWidth || 300), th = tip.offsetHeight;
    let x = b.left + 16, y = b.top - th - 10;
    if (y < 8) y = b.top + 12;
    x = Math.max(8, Math.min(window.innerWidth - tw - 8, x));
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
    requestAnimationFrame(() => tip && tip.classList.add('on'));
  }
  function hideTip() { clearTimeout(timer); current = null; if (tip) tip.classList.remove('on'); }
  document.addEventListener('mouseover', (e) => {
    const node = e.target.closest && e.target.closest('[data-tip]');
    if (node === current) return;
    hideTip();
    if (!node || active) return;
    current = node; timer = setTimeout(() => showTip(node), 450);
  });
  document.addEventListener('mouseleave', hideTip, true);
  window.addEventListener('scroll', hideTip, true);


  // first-visit welcome screen, the deck's "Por eso hicimos" slide; "Comenzar" fades it out and starts the tour
  function splash() {
    const root = el('div', 'pfs');
    root.setAttribute('role', 'dialog'); root.setAttribute('aria-modal', 'true'); root.setAttribute('aria-label', 'Bienvenida a Prefoundly');
    root.innerHTML = `<div class="pfs-bg"></div><div class="pfs-shade"></div>
      <div class="pfs-inner">
        <p class="pfs-kicker">Bienvenido a</p>
        <div class="pfs-card"><img class="pfs-logo" src="assets/logo.png" alt="Prefoundly AI"></div>
        <p class="pfs-tag">Para que tu billetera nunca se quede sin plata donde la necesita</p>
        <button class="pfs-start" type="button">Comenzar</button>
      </div>`;
    document.body.appendChild(root);
    const leave = (then) => {
      document.removeEventListener('keydown', onSplashKey, true);
      root.classList.add('out');
      setTimeout(() => { root.remove(); then(); }, 650);
    };
    const begin = () => leave(() => whenReady(start));
    const skip = () => { store.set(); leave(() => {}); };
    function onSplashKey(e) { if (e.key === 'Escape') { e.preventDefault(); skip(); } else if (e.key === 'Enter') { e.preventDefault(); begin(); } }
    root.querySelector('.pfs-start').addEventListener('click', begin);
    document.addEventListener('keydown', onSplashKey, true);
    setTimeout(() => root.querySelector('.pfs-start').focus({ preventScroll: true }), 2000);
  }
  function whenReady(fn) {
    const wait = setInterval(() => {
      const hero = target('hero');
      if (hero && hero.getBoundingClientRect().width > 0 && !/^\s*–\s*$/.test(hero.querySelector('span:nth-child(2)')?.textContent || '')) {
        clearInterval(wait); setTimeout(fn, 250);
      }
    }, 150);
  }

  function boot() {
    const style = el('style'); style.textContent = css; document.head.appendChild(style);
    const help = el('button', 'pft-help', '<i>?</i>Ver recorrido');
    help.type = 'button'; help.addEventListener('click', () => { hideTip(); start(); });
    document.body.appendChild(help);
    if (!store.get()) splash();
  }
  if (document.readyState === 'complete') boot(); else window.addEventListener('load', boot);
})();
