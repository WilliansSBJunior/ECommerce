"""Gera o dashboard HTML (arquivo unico, abre offline no navegador)."""

import json
from datetime import datetime

from .models import MARKETPLACE_LABELS
from .scoring import ProductScore


def build_payload(scores: list[ProductScore], strategy: str) -> dict:
    return {
        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "strategy": strategy,
        "labels": MARKETPLACE_LABELS,
        "rows": [s.to_dict() for s in scores],
    }


def render_dashboard(scores: list[ProductScore], output_path: str, strategy: str = "median") -> str:
    data = json.dumps(build_payload(scores, strategy), ensure_ascii=False, default=str)
    html = TEMPLATE.replace("__DATA__", data.replace("</", "<\\/"))
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return output_path


TEMPLATE = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Garimpo de Produtos</title>
<style>
:root{
  color-scheme:light;
  --bg:#f4f4f2; --surface:#fcfcfb; --surface-2:#f0efec; --border:#e2e1dc;
  --text:#0b0b0b; --text-2:#52514e; --muted:#7a7974; --grid:#e8e7e2;
  --s-ml:#2a78d6; --s-shopee:#eb6834; --s-tiktok:#1baf7a;
  --good:#1a7f37; --warn:#9a6700; --bad:#c62828;
  --bar:#2a78d6; --bar-track:#e3e9f2;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --bg:#121211; --surface:#1a1a19; --surface-2:#232321; --border:#33332f;
    --text:#f0efec; --text-2:#c3c2b7; --muted:#8f8e86; --grid:#2c2c29;
    --s-ml:#3987e5; --s-shopee:#d95926; --s-tiktok:#199e70;
    --good:#4ac26b; --warn:#d4a72c; --bad:#f47067;
    --bar:#3987e5; --bar-track:#26303d;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#121211; --surface:#1a1a19; --surface-2:#232321; --border:#33332f;
  --text:#f0efec; --text-2:#c3c2b7; --muted:#8f8e86; --grid:#2c2c29;
  --s-ml:#3987e5; --s-shopee:#d95926; --s-tiktok:#199e70;
  --good:#4ac26b; --warn:#d4a72c; --bad:#f47067;
  --bar:#3987e5; --bar-track:#26303d;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:24px 16px 48px}
header{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:8px;margin-bottom:20px}
h1{font-size:22px;margin:0}
.sub{color:var(--text-2);font-size:13px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:16px}
.kpi .label{color:var(--text-2);font-size:12px}
.kpi .value{font-size:26px;font-weight:650;font-variant-numeric:tabular-nums;margin-top:2px}
.kpi .hint{color:var(--muted);font-size:12px}
.filters{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:16px}
.chip{border:1px solid var(--border);background:var(--surface);color:var(--text);border-radius:999px;padding:6px 12px;cursor:pointer;font:inherit;display:inline-flex;align-items:center;gap:6px}
.chip[aria-pressed="true"]{background:var(--surface-2);border-color:var(--text-2);font-weight:600}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block;flex:none}
.filters input[type=search],.filters select{font:inherit;color:var(--text);background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:6px 10px}
.filters input[type=search]{min-width:200px;flex:1}
.grid2{display:grid;grid-template-columns:1fr;gap:16px;margin-bottom:16px}
h2{font-size:15px;margin:0 0 4px}
.chart-wrap{position:relative}
svg text{fill:var(--text-2);font-size:11px}
.axis-title{fill:var(--text-2);font-size:12px}
.tip{position:absolute;pointer-events:none;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:8px 10px;font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.15);display:none;min-width:180px;z-index:5}
.tip b{display:block;margin-bottom:2px;color:var(--text)}
.tip .row{display:flex;justify-content:space-between;gap:12px;color:var(--text-2)}
.tip .row span:last-child{color:var(--text);font-variant-numeric:tabular-nums}
.legend{display:flex;gap:14px;flex-wrap:wrap;color:var(--text-2);font-size:12px;margin:6px 0 4px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{padding:8px 10px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}
th{font-size:12px;color:var(--text-2);font-weight:600;cursor:pointer;user-select:none;position:sticky;top:0;background:var(--surface)}
th:first-child,td:first-child,th.l,td.l{text-align:left}
tbody tr.main{cursor:pointer}
tbody tr.main:hover{background:var(--surface-2)}
.pname{font-weight:600;white-space:normal;min-width:180px}
.psub{color:var(--muted);font-size:12px}
.scorebar{display:flex;align-items:center;gap:8px;justify-content:flex-end}
.scorebar .track{width:70px;height:8px;border-radius:4px;background:var(--bar-track);overflow:hidden}
.scorebar .fill{height:100%;background:var(--bar);border-radius:0 4px 4px 0}
.neg{color:var(--bad)} .pos{color:var(--good)}
.flag{display:inline-block;font-size:11px;color:var(--warn);margin-right:6px}
.flag.bad{color:var(--bad)}
.badge{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--text-2)}
tr.detail td{background:var(--surface-2);text-align:left;white-space:normal}
.detail-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}
.detail h3{font-size:13px;margin:0 0 6px}
.kv{display:grid;grid-template-columns:1fr auto;gap:2px 12px;font-size:12px}
.kv span:nth-child(odd){color:var(--text-2)}
.kv span:nth-child(even){text-align:right;font-variant-numeric:tabular-nums}
.kv .total{font-weight:650;border-top:1px solid var(--border);padding-top:3px}
.mini th,.mini td{padding:4px 6px;font-size:12px}
.mini td.l{max-width:340px;overflow:hidden;text-overflow:ellipsis}
a{color:var(--s-ml)}
.empty{padding:40px;text-align:center;color:var(--text-2)}
.note{color:var(--muted);font-size:12px;margin-top:10px}
.theme{background:none;border:1px solid var(--border);color:var(--text-2);border-radius:8px;padding:4px 10px;cursor:pointer;font:inherit}
@media (min-width:980px){.grid2{grid-template-columns:3fr 2fr}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Garimpo de Produtos</h1>
      <div class="sub" id="meta"></div>
    </div>
    <button class="theme" id="themeBtn" type="button">Alternar tema</button>
  </header>

  <section class="kpis" id="kpis"></section>

  <section class="filters" aria-label="Filtros">
    <div id="mkChips" style="display:flex;gap:8px;flex-wrap:wrap"></div>
    <input type="search" id="q" placeholder="Buscar produto ou fornecedor">
    <label class="sub">Score mínimo
      <select id="minScore"><option value="0">todos</option><option value="40">40+</option><option value="60">60+</option><option value="75">75+</option></select>
    </label>
    <label class="sub"><input type="checkbox" id="onlyProfit"> só com lucro</label>
  </section>

  <section class="grid2">
    <div class="card">
      <h2>Lucro por unidade × demanda do mercado</h2>
      <div class="sub">Cada ponto é um produto em um marketplace. Melhor quadrante: canto superior direito.</div>
      <div class="legend" id="legend"></div>
      <div class="chart-wrap" id="scatterWrap"><svg id="scatter" width="100%" height="340" role="img" aria-label="Gráfico de dispersão de lucro por unidade contra unidades vendidas por mês"></svg><div class="tip" id="tip"></div></div>
    </div>
    <div class="card">
      <h2>Top 10 por lucro mensal esperado</h2>
      <div class="sub">Unidades que você venderia (fatia conservadora do mercado) × lucro por unidade.</div>
      <div class="chart-wrap" id="barsWrap"><svg id="bars" width="100%" height="340" role="img" aria-label="Barras de lucro mensal esperado"></svg><div class="tip" id="tip2"></div></div>
    </div>
  </section>

  <section class="card">
    <h2>Ranking de viabilidade</h2>
    <div class="sub">Clique numa linha para ver custos, taxas e os anúncios concorrentes usados no cálculo. Clique no cabeçalho para ordenar.</div>
    <div class="table-wrap"><table id="tbl"><thead></thead><tbody></tbody></table></div>
    <div class="note" id="note"></div>
  </section>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
  "use strict";
  var DATA = JSON.parse(document.getElementById("data").textContent);
  var rows = DATA.rows || [];
  var LABELS = DATA.labels || {};
  var COLORS = {ml:"var(--s-ml)", shopee:"var(--s-shopee)", tiktok:"var(--s-tiktok)"};
  var state = {mk:new Set(Object.keys(LABELS)), q:"", min:0, onlyProfit:false, sort:"score", dir:-1, open:null};

  var brl = new Intl.NumberFormat("pt-BR",{style:"currency",currency:"BRL"});
  var brl0 = new Intl.NumberFormat("pt-BR",{style:"currency",currency:"BRL",maximumFractionDigits:0});
  var int = new Intl.NumberFormat("pt-BR",{maximumFractionDigits:0});
  function money(v){return v==null?"—":brl.format(v)}
  function money0(v){return v==null?"—":brl0.format(v)}
  function num(v){return v==null?"—":int.format(v)}
  function pct(v){return v==null?"—":(v*100).toLocaleString("pt-BR",{maximumFractionDigits:1})+"%"}
  function dec(v,d){return v==null?"—":v.toLocaleString("pt-BR",{minimumFractionDigits:d,maximumFractionDigits:d})}
  function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})}

  // tema
  document.getElementById("themeBtn").onclick=function(){
    var r=document.documentElement, cur=r.getAttribute("data-theme");
    var dark = cur? cur==="dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    r.setAttribute("data-theme", dark?"light":"dark");
    try{localStorage.setItem("garimpo-theme", dark?"light":"dark")}catch(e){}
  };
  try{var t=localStorage.getItem("garimpo-theme"); if(t) document.documentElement.setAttribute("data-theme",t)}catch(e){}

  var strategyLabel = {median:"preço mediano do mercado", p25:"preço do 1º quartil (mais barato que 75%)", min:"menor preço do mercado"}[DATA.strategy] || DATA.strategy;
  document.getElementById("meta").textContent = "Gerado em "+DATA.generated_at+" · preço de venda simulado: "+strategyLabel;

  // chips de marketplace (só os presentes)
  var present = Object.keys(LABELS).filter(function(k){return rows.some(function(r){return r.marketplace===k})});
  state.mk = new Set(present);
  var chips = document.getElementById("mkChips");
  present.forEach(function(k){
    var b=document.createElement("button"); b.type="button"; b.className="chip"; b.setAttribute("aria-pressed","true");
    b.innerHTML='<span class="dot" style="background:'+COLORS[k]+'"></span>'+esc(LABELS[k]);
    b.onclick=function(){ if(state.mk.has(k)){ if(state.mk.size>1) state.mk.delete(k);} else state.mk.add(k);
      b.setAttribute("aria-pressed", state.mk.has(k)?"true":"false"); render(); };
    chips.appendChild(b);
  });
  document.getElementById("legend").innerHTML = present.map(function(k){return '<span><span class="dot" style="background:'+COLORS[k]+'"></span>'+esc(LABELS[k])+'</span>'}).join("");
  document.getElementById("q").oninput=function(e){state.q=e.target.value.toLowerCase(); render()};
  document.getElementById("minScore").onchange=function(e){state.min=+e.target.value; render()};
  document.getElementById("onlyProfit").onchange=function(e){state.onlyProfit=e.target.checked; render()};

  function filtered(){
    return rows.filter(function(r){
      if(!state.mk.has(r.marketplace)) return false;
      if(r.score < state.min) return false;
      if(state.onlyProfit && !(r.unit_profit>0)) return false;
      if(state.q && (r.product_name+" "+(r.supplier_name||"")+" "+(r.sku||"")).toLowerCase().indexOf(state.q)<0) return false;
      return true;
    });
  }

  function kpis(list){
    var viable = list.filter(function(r){return r.score>=60 && r.unit_profit>0});
    var best = list.slice().sort(function(a,b){return (b.expected_profit_month||-1e9)-(a.expected_profit_month||-1e9)})[0];
    var withMargin = list.filter(function(r){return r.margin!=null});
    var avgMargin = withMargin.length? withMargin.reduce(function(s,r){return s+r.margin},0)/withMargin.length : null;
    var products = new Set(list.map(function(r){return r.supplier_product_id})).size;
    var html = [
      ["Produtos analisados", num(products), list.length+" combinações produto × marketplace"],
      ["Produtos viáveis", num(new Set(viable.map(function(r){return r.supplier_product_id})).size), viable.length+" de "+list.length+" combinações com score 60+ e lucro"],
      ["Margem média", pct(avgMargin), "lucro ÷ preço de venda"],
      ["Melhor lucro mensal esperado", best? money0(best.expected_profit_month):"—", best? esc(best.product_name)+" · "+esc(LABELS[best.marketplace]):""]
    ].map(function(k){return '<div class="card kpi"><div class="label">'+k[0]+'</div><div class="value">'+k[1]+'</div><div class="hint">'+k[2]+'</div></div>'}).join("");
    document.getElementById("kpis").innerHTML = html;
  }

  // ---------- scatter ----------
  function niceTicks(min,max,n){
    var span=max-min||1, step=Math.pow(10,Math.floor(Math.log10(span/n))), err=n/span*step;
    if(err<=.15) step*=10; else if(err<=.35) step*=5; else if(err<=.75) step*=2;
    var out=[], v=Math.ceil(min/step)*step; for(;v<=max+1e-9;v+=step) out.push(+v.toFixed(10)); return out;
  }
  function showTip(tip, wrap, evt, html){
    tip.innerHTML=html; tip.style.display="block";
    var rect=wrap.getBoundingClientRect(), x=evt.clientX-rect.left+14, y=evt.clientY-rect.top+14;
    if(x+tip.offsetWidth>rect.width) x=evt.clientX-rect.left-tip.offsetWidth-14;
    if(y+tip.offsetHeight>rect.height) y=rect.height-tip.offsetHeight-4;
    tip.style.left=Math.max(0,x)+"px"; tip.style.top=Math.max(0,y)+"px";
  }
  function tipHtml(r){
    return "<b>"+esc(r.product_name)+"</b>"+
      '<div class="row"><span>Marketplace</span><span>'+esc(LABELS[r.marketplace])+'</span></div>'+
      '<div class="row"><span>Score</span><span>'+r.score.toFixed(0)+'</span></div>'+
      '<div class="row"><span>Lucro/un</span><span>'+money(r.unit_profit)+'</span></div>'+
      '<div class="row"><span>Margem</span><span>'+pct(r.margin)+'</span></div>'+
      '<div class="row"><span>Mercado/mês</span><span>'+num(r.market_units_month)+' un</span></div>'+
      '<div class="row"><span>Lucro mensal esperado</span><span>'+money0(r.expected_profit_month)+'</span></div>';
  }
  var NS="http://www.w3.org/2000/svg";
  function el(tag,attrs,parent){var e=document.createElementNS(NS,tag); for(var k in attrs) e.setAttribute(k,attrs[k]); if(parent) parent.appendChild(e); return e}

  var W;
  function scatter(list){
    var svg=document.getElementById("scatter"), wrap=document.getElementById("scatterWrap"), tip=document.getElementById("tip");
    svg.innerHTML="";
    W=svg.clientWidth||600; var H=340, m={l:62,r:16,t:12,b:44};
    var pts=list.filter(function(r){return r.unit_profit!=null && r.market_units_month!=null});
    if(!pts.length){ el("text",{x:W/2,y:H/2,"text-anchor":"middle"},svg).textContent="Sem produtos com dados de vendas ainda"; return; }
    var xs=pts.map(function(r){return r.market_units_month}), ys=pts.map(function(r){return r.unit_profit});
    var xmax=Math.max.apply(null,xs), ymin=Math.min(0,Math.min.apply(null,ys)), ymax=Math.max.apply(null,ys);
    var lx=function(v){return Math.log10(1+v)}, lxmax=lx(xmax)*1.05||1;
    var X=function(v){return m.l+lx(v)/lxmax*(W-m.l-m.r)};
    var pad=(ymax-ymin)*0.08||5; var y0=ymin-(ymin<0?pad:0), y1=ymax+pad;
    var Y=function(v){return H-m.b-(v-y0)/(y1-y0)*(H-m.t-m.b)};
    var g=el("g",{},svg);
    niceTicks(y0,y1,5).forEach(function(t){
      el("line",{x1:m.l,x2:W-m.r,y1:Y(t),y2:Y(t),stroke:"var(--grid)","stroke-width":t===0?1.5:1},g);
      el("text",{x:m.l-8,y:Y(t)+4,"text-anchor":"end"},g).textContent=brl0.format(t);
    });
    [0,10,100,1000,10000,100000].filter(function(t){return t<=xmax*1.1}).forEach(function(t){
      el("line",{x1:X(t),x2:X(t),y1:m.t,y2:H-m.b,stroke:"var(--grid)"},g);
      el("text",{x:X(t),y:H-m.b+16,"text-anchor":"middle"},g).textContent=int.format(t);
    });
    el("text",{x:(W+m.l)/2,y:H-6,"text-anchor":"middle","class":"axis-title"},g).textContent="Unidades vendidas por mês no mercado (escala log)";
    var yt=el("text",{x:14,y:(H-m.b+m.t)/2,"text-anchor":"middle","class":"axis-title",transform:"rotate(-90 14 "+((H-m.b+m.t)/2)+")"},g); yt.textContent="Lucro por unidade";
    pts.slice().sort(function(a,b){return a.score-b.score}).forEach(function(r){
      var cx=X(r.market_units_month), cy=Y(r.unit_profit);
      el("circle",{cx:cx,cy:cy,r:5.5,fill:COLORS[r.marketplace],stroke:"var(--surface)","stroke-width":2},svg);
      var hit=el("circle",{cx:cx,cy:cy,r:12,fill:"transparent",style:"cursor:pointer"},svg);
      hit.addEventListener("mousemove",function(e){showTip(tip,wrap,e,tipHtml(r))});
      hit.addEventListener("mouseleave",function(){tip.style.display="none"});
      hit.addEventListener("click",function(){state.open=r.supplier_product_id+"|"+r.marketplace; renderTable(filtered()); var row=document.querySelector('[data-key="'+state.open+'"]'); if(row) row.scrollIntoView({behavior:"smooth",block:"center"})});
    });
    // rotulo direto nos 3 melhores
    pts.slice().sort(function(a,b){return b.score-a.score}).slice(0,3).forEach(function(r){
      var px=X(r.market_units_month), right=px>W*0.6;
      var t=el("text",{x:right?px-9:px+9,y:Y(r.unit_profit)-8,"text-anchor":right?"end":"start",style:"fill:var(--text);font-size:11px;font-weight:600"},svg);
      t.textContent=r.product_name.length>26? r.product_name.slice(0,25)+"…" : r.product_name;
    });
  }

  function bars(list){
    var svg=document.getElementById("bars"), wrap=document.getElementById("barsWrap"), tip=document.getElementById("tip2");
    svg.innerHTML="";
    var top=list.filter(function(r){return r.expected_profit_month!=null && r.expected_profit_month>0})
      .sort(function(a,b){return b.expected_profit_month-a.expected_profit_month}).slice(0,10);
    var W=svg.clientWidth||400, H=340;
    if(!top.length){ el("text",{x:W/2,y:H/2,"text-anchor":"middle"},svg).textContent="Nenhum produto com lucro esperado positivo"; return; }
    var labelW=Math.min(170, W*0.42), valW=72, bh=Math.min(24,(H-10)/top.length-6), gap=(H-10-bh*top.length)/top.length;
    var max=top[0].expected_profit_month;
    top.forEach(function(r,i){
      var y=5+i*(bh+gap);
      var name=r.product_name.length>24? r.product_name.slice(0,23)+"…" : r.product_name;
      el("text",{x:0,y:y+bh/2+4,style:"fill:var(--text);font-size:12px"},svg).textContent=name;
      var w=Math.max(4,(W-labelW-valW)*r.expected_profit_month/max);
      el("path",{d:"M"+labelW+","+y+"h"+(w-4)+"a4,4 0 0 1 4,4v"+(bh-8)+"a4,4 0 0 1 -4,4h"+(-(w-4))+"z",fill:COLORS[r.marketplace]},svg);
      el("text",{x:labelW+w+6,y:y+bh/2+4,style:"fill:var(--text-2);font-size:12px"},svg).textContent=money0(r.expected_profit_month);
      var hit=el("rect",{x:0,y:y-gap/2,width:W,height:bh+gap,fill:"transparent"},svg);
      hit.addEventListener("mousemove",function(e){showTip(tip,wrap,e,tipHtml(r))});
      hit.addEventListener("mouseleave",function(){tip.style.display="none"});
    });
  }

  // ---------- tabela ----------
  var COLS=[
    {k:"product_name",t:"Produto",l:true},
    {k:"marketplace",t:"Canal",l:true},
    {k:"score",t:"Score"},
    {k:"unit_profit",t:"Lucro/un"},
    {k:"margin",t:"Margem"},
    {k:"suggested_price",t:"Preço venda"},
    {k:"unit_costs",t:"Custo total"},
    {k:"market_units_month",t:"Mercado/mês"},
    {k:"n_sellers",t:"Vendedores"},
    {k:"expected_profit_month",t:"Lucro/mês esperado"},
    {k:"flags",t:"Alertas",l:true}
  ];
  function renderHead(){
    document.querySelector("#tbl thead").innerHTML="<tr>"+COLS.map(function(c){
      var arrow= state.sort===c.k ? (state.dir<0?" ▼":" ▲") : "";
      return '<th class="'+(c.l?"l":"")+'" data-k="'+c.k+'" scope="col">'+c.t+arrow+'</th>'}).join("")+"</tr>";
    document.querySelectorAll("#tbl th").forEach(function(th){ th.onclick=function(){
      var k=th.getAttribute("data-k"); if(state.sort===k) state.dir*=-1; else {state.sort=k; state.dir= (k==="product_name"||k==="marketplace")?1:-1;} render(); }});
  }
  function detailHtml(r){
    var fees='<div class="kv">'+
      '<span>Preço de venda simulado</span><span>'+money(r.suggested_price)+'</span>'+
      '<span>(−) Comissão do marketplace</span><span>'+money(r.fee_commission)+'</span>'+
      '<span>(−) Taxa fixa / programa de frete</span><span>'+money(r.fee_fixed)+'</span>'+
      '<span>(−) Imposto ('+pct(r.tax_rate)+')</span><span>'+money(r.tax_amount)+'</span>'+
      '<span>(−) Custo do produto</span><span>'+money(r.cost_price)+'</span>'+
      '<span>(−) Frete do fornecedor</span><span>'+money(r.shipping_in)+'</span>'+
      '<span>(−) Embalagem</span><span>'+money(r.packaging_cost)+'</span>'+
      '<span class="total">Lucro por unidade</span><span class="total '+(r.unit_profit<0?"neg":"pos")+'">'+money(r.unit_profit)+'</span>'+
      '</div>';
    var market='<div class="kv">'+
      '<span>Faixa de preço</span><span>'+money(r.price_min)+' a '+money(r.price_max)+'</span>'+
      '<span>Preço mediano</span><span>'+money(r.price_median)+'</span>'+
      '<span>Preço de equilíbrio (lucro zero)</span><span>'+money(r.breakeven)+'</span>'+
      '<span>Markup sobre o custo</span><span>'+pct(r.markup)+'</span>'+
      '<span>Vendas do mercado por dia</span><span>'+(r.market_sales_per_day==null?"—":r.market_sales_per_day.toLocaleString("pt-BR",{maximumFractionDigits:1}))+'</span>'+
      '<span>Faturamento do mercado/mês</span><span>'+money0(r.market_revenue_month)+'</span>'+
      '<span>Fatia do líder</span><span>'+pct(r.top_listing_share)+'</span>'+
      '<span>Sua fatia estimada</span><span>'+pct(r.expected_share)+' · '+num(r.expected_units_month)+' un/mês</span>'+
      '</div>';
    var comps='<div class="kv">'+
      '<span>Margem ('+r.score_margin.toFixed(0)+' × 35%)</span><span>'+dec(r.score_margin*.35,1)+'</span>'+
      '<span>Demanda ('+r.score_demand.toFixed(0)+' × 30%)</span><span>'+dec(r.score_demand*.30,1)+'</span>'+
      '<span>Concorrência ('+r.score_competition.toFixed(0)+' × 20%)</span><span>'+dec(r.score_competition*.20,1)+'</span>'+
      '<span>Lucro/un ('+r.score_unit_profit.toFixed(0)+' × 15%)</span><span>'+dec(r.score_unit_profit*.15,1)+'</span>'+
      '<span class="total">Score</span><span class="total">'+dec(r.score,1)+'</span></div>';
    var methodLabel={historico:"histórico",sold_30d:"30 dias",idade_anuncio:"idade do anúncio",sem_dado:"sem dado"};
    var lis=(r.listings||[]).slice(0,12).map(function(x){
      var title=esc(x.title); if(x.permalink) title='<a href="'+esc(x.permalink)+'" target="_blank" rel="noopener">'+title+'</a>';
      return '<tr><td class="l" title="'+esc(x.title)+'">'+title+'</td><td class="l">'+esc(x.seller||"—")+'</td><td>'+money(x.price)+'</td><td>'+num(x.sold_quantity)+'</td><td>'+(x.sales_per_day==null?"—":x.sales_per_day.toLocaleString("pt-BR",{maximumFractionDigits:1}))+'</td><td class="l">'+(methodLabel[x.method]||x.method)+'</td></tr>';
    }).join("");
    return '<div class="detail-grid detail">'+
      '<div><h3>Conta por unidade</h3>'+fees+'</div>'+
      '<div><h3>Mercado</h3>'+market+'</div>'+
      '<div><h3>Composição do score</h3>'+comps+'</div>'+
      '</div><h3 style="margin-top:14px;font-size:13px">Anúncios concorrentes ('+r.n_listings+')</h3>'+
      '<div class="table-wrap"><table class="mini"><thead><tr><th class="l">Anúncio</th><th class="l">Vendedor</th><th>Preço</th><th>Vendidos</th><th>Vendas/dia</th><th class="l">Fonte da estimativa</th></tr></thead><tbody>'+lis+'</tbody></table></div>';
  }
  function renderTable(list){
    renderHead();
    var k=state.sort, d=state.dir;
    list=list.slice().sort(function(a,b){
      var va=a[k], vb=b[k];
      if(k==="flags"){va=a.flags.length; vb=b.flags.length}
      if(va==null) return 1; if(vb==null) return -1;
      return (typeof va==="string"? va.localeCompare(vb) : va-vb)*d;
    });
    var tb=document.querySelector("#tbl tbody");
    if(!list.length){ tb.innerHTML='<tr><td colspan="'+COLS.length+'" class="empty">Nenhum produto com esses filtros.</td></tr>'; return; }
    tb.innerHTML=list.map(function(r){
      var key=r.supplier_product_id+"|"+r.marketplace;
      var flags=r.flags.map(function(f){var bad=/negativa|acima/.test(f); return '<span class="flag'+(bad?" bad":"")+'">'+(bad?"✖ ":"⚠ ")+esc(f)+'</span>'}).join("");
      var main='<tr class="main" data-key="'+key+'" aria-expanded="'+(state.open===key)+'">'+
        '<td class="l"><div class="pname">'+esc(r.product_name)+'</div><div class="psub">'+esc(r.supplier_name||"")+(r.sku?" · "+esc(r.sku):"")+'</div></td>'+
        '<td class="l"><span class="badge"><span class="dot" style="background:'+COLORS[r.marketplace]+'"></span>'+esc(LABELS[r.marketplace])+'</span></td>'+
        '<td><div class="scorebar"><span>'+r.score.toFixed(0)+'</span><span class="track"><span class="fill" style="display:block;width:'+r.score+'%"></span></span></div></td>'+
        '<td class="'+(r.unit_profit<0?"neg":"")+'">'+money(r.unit_profit)+'</td>'+
        '<td class="'+(r.margin<0?"neg":"")+'">'+pct(r.margin)+'</td>'+
        '<td>'+money(r.suggested_price)+'</td>'+
        '<td>'+money(r.unit_costs)+'</td>'+
        '<td>'+num(r.market_units_month)+'</td>'+
        '<td>'+num(r.n_sellers)+'</td>'+
        '<td>'+money0(r.expected_profit_month)+'</td>'+
        '<td class="l" style="white-space:normal;min-width:160px">'+flags+'</td></tr>';
      var det= state.open===key ? '<tr class="detail"><td colspan="'+COLS.length+'">'+detailHtml(r)+'</td></tr>' : '';
      return main+det;
    }).join("");
    tb.querySelectorAll("tr.main").forEach(function(tr){ tr.onclick=function(){
      var key=tr.getAttribute("data-key"); state.open = state.open===key? null : key; renderTable(filtered()); }});
  }

  function render(){
    var list=filtered();
    kpis(list); scatter(list); bars(list); renderTable(list);
    document.getElementById("note").textContent = rows.length
      ? "Estimativas: vendas por dia vêm do histórico de coletas quando há 2+ snapshots, senão das vendas em 30 dias informadas pela fonte, senão do total vendido ÷ idade do anúncio. Sua fatia = 1 ÷ (vendedores + 1), limitada a 20%. Taxas e impostos conforme a tabela do projeto; confira na central do vendedor."
      : "Sem dados ainda. Importe a tabela de fornecedores, colete concorrentes e rode o comando dashboard de novo.";
  }
  render();
  var rt; window.addEventListener("resize",function(){clearTimeout(rt); rt=setTimeout(function(){var l=filtered(); scatter(l); bars(l)},150)});
})();
</script>
</body>
</html>
"""
