// ── DATA ──────────────────────────────────────────────────────
let stocks = [];
let sectorFlowData = [];
let rsHistory = {};
let historyChart = null;

const SEPA_LABELS = {
  rs70:         'RS≥70',
  above_150ma:  '站上150MA',
  above_200ma:  '站上200MA',
  ma200_up:     '200MA向上',
  ma150_gt_200: '150MA>200MA',
  near_52w_high:'靠近52週高點',
};

async function fetchData() {
  try {
    const [dataRes, histRes] = await Promise.all([
      fetch('rs_data.json?t=' + Date.now()),
      fetch('rs_history.json?t=' + Date.now()).catch(() => ({ ok: false })),
    ]);
    if (!dataRes.ok) throw new Error('HTTP ' + dataRes.status);
    const data = await dataRes.json();
    stocks = data.stocks || [];
    sectorFlowData = (data.sectors || []).map(s => ({
      name: s.name, c1: s.c1 ?? 0, c5: s.c5 ?? 0, c1m: s.c1m ?? 0,
      flow: s.flow ?? (s.avg_rs * 1.1), flow5: s.flow5 ?? 0,
      weeks: s.weeks || [],
    }));
    rsHistory = histRes.ok ? await histRes.json() : {};
    return { updatedAt: data.updated_at, live: true };
  } catch (e) {
    console.warn('rs_data.json 未找到，使用示意資料。請執行 rs_calculator.py', e.message);
    stocks = DEMO_STOCKS;
    sectorFlowData = DEMO_SECTORS;
    return { updatedAt: null, live: false };
  }
}

// ── 示意資料（fallback，真實標的名稱 + 示意數值） ───────────────
const _sd = (rs, ...flags) => {
  const keys = ['above_150ma','above_200ma','ma200_up','ma150_gt_200','near_52w_high'];
  const d = { rs70: rs >= 70 };
  keys.forEach((k, i) => d[k] = !!flags[i]);
  return d;
};
const DEMO_STOCKS = [
  {code:"NVDA", name:"NVIDIA",          sector:"資訊科技",   rs:98, q1:42.1,q2:30.2,q3:18.4,q4:12.1, rsHigh:true,  sepa:true,  cap:"大", c1:2.4,  c5:7.1,  c1m:21.4, sepa_detail:_sd(98,1,1,1,1,1)},
  {code:"AVGO", name:"Broadcom",        sector:"資訊科技",   rs:96, q1:38.4,q2:26.1,q3:15.2,q4:9.8,  rsHigh:true,  sepa:true,  cap:"大", c1:1.9,  c5:6.2,  c1m:18.8, sepa_detail:_sd(96,1,1,1,1,1)},
  {code:"META", name:"Meta Platforms",  sector:"通訊服務",   rs:94, q1:34.2,q2:22.8,q3:14.1,q4:10.4, rsHigh:true,  sepa:true,  cap:"大", c1:1.5,  c5:5.4,  c1m:16.2, sepa_detail:_sd(94,1,1,1,1,1)},
  {code:"NFLX", name:"Netflix",         sector:"通訊服務",   rs:92, q1:31.4,q2:20.1,q3:13.8,q4:8.2,  rsHigh:true,  sepa:true,  cap:"大", c1:1.2,  c5:4.8,  c1m:15.1, sepa_detail:_sd(92,1,1,1,1,1)},
  {code:"LLY",  name:"Eli Lilly",       sector:"醫療保健",   rs:91, q1:29.8,q2:19.4,q3:12.4,q4:11.2, rsHigh:true,  sepa:true,  cap:"大", c1:1.8,  c5:4.2,  c1m:14.4, sepa_detail:_sd(91,1,1,1,1,1)},
  {code:"AAPL", name:"Apple",           sector:"資訊科技",   rs:88, q1:26.4,q2:17.2,q3:11.1,q4:9.4,  rsHigh:true,  sepa:true,  cap:"大", c1:0.9,  c5:3.4,  c1m:12.8, sepa_detail:_sd(88,1,1,1,1,1)},
  {code:"JPM",  name:"JPMorgan Chase",  sector:"金融",       rs:87, q1:24.8,q2:16.4,q3:10.8,q4:8.1,  rsHigh:true,  sepa:true,  cap:"大", c1:0.8,  c5:3.1,  c1m:11.4, sepa_detail:_sd(87,1,1,1,1,1)},
  {code:"GE",   name:"GE Aerospace",    sector:"工業",       rs:86, q1:23.2,q2:15.8,q3:9.4, q4:7.8,  rsHigh:true,  sepa:true,  cap:"大", c1:1.1,  c5:2.8,  c1m:10.8, sepa_detail:_sd(86,1,1,1,1,1)},
  {code:"COST", name:"Costco",          sector:"必需消費",   rs:84, q1:21.4,q2:14.2,q3:9.1, q4:6.8,  rsHigh:true,  sepa:true,  cap:"大", c1:0.6,  c5:2.4,  c1m:9.8,  sepa_detail:_sd(84,1,1,1,0,1)},
  {code:"MA",   name:"Mastercard",      sector:"金融",       rs:82, q1:19.8,q2:13.1,q3:8.4, q4:7.2,  rsHigh:true,  sepa:true,  cap:"大", c1:0.7,  c5:2.1,  c1m:9.1,  sepa_detail:_sd(82,1,1,1,1,0)},
  {code:"V",    name:"Visa",            sector:"金融",       rs:81, q1:18.4,q2:12.4,q3:8.1, q4:6.4,  rsHigh:false, sepa:true,  cap:"大", c1:0.5,  c5:1.9,  c1m:8.4,  sepa_detail:_sd(81,1,1,1,1,0)},
  {code:"AMZN", name:"Amazon",          sector:"非必需消費", rs:79, q1:17.1,q2:11.8,q3:7.4, q4:8.1,  rsHigh:false, sepa:true,  cap:"大", c1:0.4,  c5:1.6,  c1m:7.8,  sepa_detail:_sd(79,1,1,1,1,0)},
  {code:"MSFT", name:"Microsoft",       sector:"資訊科技",   rs:78, q1:16.4,q2:11.2,q3:7.8, q4:6.1,  rsHigh:false, sepa:true,  cap:"大", c1:0.3,  c5:1.4,  c1m:7.2,  sepa_detail:_sd(78,1,1,1,1,0)},
  {code:"WMT",  name:"Walmart",         sector:"必需消費",   rs:77, q1:15.8,q2:10.4,q3:7.1, q4:5.8,  rsHigh:false, sepa:false, cap:"大", c1:0.5,  c5:1.2,  c1m:6.8},
  {code:"HD",   name:"Home Depot",      sector:"非必需消費", rs:75, q1:14.2,q2:9.8, q3:6.4, q4:6.2,  rsHigh:false, sepa:false, cap:"大", c1:0.2,  c5:1.1,  c1m:6.4},
  {code:"ORCL", name:"Oracle",          sector:"資訊科技",   rs:74, q1:13.4,q2:9.1, q3:6.8, q4:5.4,  rsHigh:false, sepa:false, cap:"大", c1:0.4,  c5:0.9,  c1m:6.1},
  {code:"GOOGL",name:"Alphabet A",      sector:"通訊服務",   rs:72, q1:12.8,q2:8.4, q3:6.1, q4:5.1,  rsHigh:false, sepa:false, cap:"大", c1:0.1,  c5:0.7,  c1m:5.4},
  {code:"AMD",  name:"AMD",             sector:"資訊科技",   rs:71, q1:12.1,q2:8.1, q3:5.4, q4:4.8,  rsHigh:false, sepa:false, cap:"大", c1:0.6,  c5:0.4,  c1m:5.1},
  {code:"UNH",  name:"UnitedHealth",    sector:"醫療保健",   rs:70, q1:11.4,q2:7.8, q3:5.1, q4:4.4,  rsHigh:false, sepa:false, cap:"大", c1:0.2,  c5:0.2,  c1m:4.8},
  {code:"XOM",  name:"Exxon Mobil",     sector:"能源",       rs:68, q1:10.2,q2:6.8, q3:4.8, q4:4.1,  rsHigh:false, sepa:false, cap:"大", c1:-0.2, c5:-0.1, c1m:4.2},
  {code:"PG",   name:"Procter & Gamble",sector:"必需消費",   rs:66, q1:9.4, q2:6.1, q3:4.2, q4:3.8,  rsHigh:false, sepa:false, cap:"大", c1:0.1,  c5:-0.2, c1m:3.8},
  {code:"CRM",  name:"Salesforce",      sector:"資訊科技",   rs:64, q1:8.4, q2:5.4, q3:3.8, q4:3.4,  rsHigh:false, sepa:false, cap:"大", c1:-0.4, c5:-0.6, c1m:3.2},
  {code:"CAT",  name:"Caterpillar",     sector:"工業",       rs:62, q1:7.8, q2:4.8, q3:3.4, q4:3.1,  rsHigh:false, sepa:false, cap:"大", c1:-0.3, c5:-0.8, c1m:2.8},
  {code:"ABBV", name:"AbbVie",          sector:"醫療保健",   rs:60, q1:7.1, q2:4.2, q3:3.1, q4:2.8,  rsHigh:false, sepa:false, cap:"大", c1:-0.1, c5:-1.1, c1m:2.4},
  {code:"NEE",  name:"NextEra Energy",  sector:"公用事業",   rs:58, q1:6.4, q2:3.8, q3:2.8, q4:2.4,  rsHigh:false, sepa:false, cap:"大", c1:-0.5, c5:-1.4, c1m:2.1},
  {code:"LIN",  name:"Linde",           sector:"原物料",     rs:56, q1:5.8, q2:3.4, q3:2.4, q4:2.1,  rsHigh:false, sepa:false, cap:"大", c1:-0.4, c5:-1.6, c1m:1.8},
  {code:"AMT",  name:"American Tower",  sector:"房地產",     rs:54, q1:5.1, q2:2.8, q3:2.1, q4:1.8,  rsHigh:false, sepa:false, cap:"大", c1:-0.6, c5:-1.8, c1m:1.4},
  {code:"INTC", name:"Intel",           sector:"資訊科技",   rs:52, q1:4.4, q2:2.4, q3:1.8, q4:1.4,  rsHigh:false, sepa:false, cap:"中", c1:-0.8, c5:-2.1, c1m:1.1},
  {code:"NKE",  name:"Nike",            sector:"非必需消費", rs:48, q1:3.4, q2:1.8, q3:1.2, q4:1.1,  rsHigh:false, sepa:false, cap:"大", c1:-1.1, c5:-2.4, c1m:-0.4},
  {code:"DIS",  name:"Walt Disney",     sector:"通訊服務",   rs:46, q1:2.8, q2:1.4, q3:0.8, q4:0.8,  rsHigh:false, sepa:false, cap:"大", c1:-0.9, c5:-2.8, c1m:-1.1},
  {code:"PEP",  name:"PepsiCo",         sector:"必需消費",   rs:44, q1:2.1, q2:0.8, q3:0.4, q4:0.4,  rsHigh:false, sepa:false, cap:"大", c1:-1.2, c5:-3.1, c1m:-1.8},
  {code:"PFE",  name:"Pfizer",          sector:"醫療保健",   rs:41, q1:1.4, q2:0.2, q3:-0.4,q4:0.1,  rsHigh:false, sepa:false, cap:"大", c1:-1.4, c5:-3.4, c1m:-2.4},
  {code:"VZ",   name:"Verizon",         sector:"通訊服務",   rs:38, q1:0.8, q2:-0.4,q3:-1.1,q4:-0.2, rsHigh:false, sepa:false, cap:"大", c1:-1.6, c5:-3.8, c1m:-3.1},
  {code:"CVX",  name:"Chevron",         sector:"能源",       rs:35, q1:-0.4,q2:-1.2,q3:-1.8,q4:-0.8, rsHigh:false, sepa:false, cap:"大", c1:-1.8, c5:-4.2, c1m:-3.8},
  {code:"MMM",  name:"3M",              sector:"工業",       rs:32, q1:-1.2,q2:-1.8,q3:-2.4,q4:-1.2, rsHigh:false, sepa:false, cap:"中", c1:-2.1, c5:-4.6, c1m:-4.4},
  {code:"KO",   name:"Coca-Cola",       sector:"必需消費",   rs:30, q1:-1.8,q2:-2.4,q3:-2.8,q4:-1.6, rsHigh:false, sepa:false, cap:"大", c1:-1.9, c5:-4.8, c1m:-4.8},
  {code:"MRK",  name:"Merck",           sector:"醫療保健",   rs:28, q1:-2.4,q2:-2.8,q3:-3.4,q4:-2.1, rsHigh:false, sepa:false, cap:"大", c1:-2.4, c5:-5.4, c1m:-5.4},
  {code:"T",    name:"AT&T",            sector:"通訊服務",   rs:25, q1:-3.4,q2:-3.4,q3:-3.8,q4:-2.8, rsHigh:false, sepa:false, cap:"大", c1:-2.6, c5:-5.8, c1m:-6.4},
  {code:"BA",   name:"Boeing",          sector:"工業",       rs:22, q1:-4.4,q2:-4.1,q3:-4.4,q4:-3.4, rsHigh:false, sepa:false, cap:"中", c1:-3.1, c5:-6.4, c1m:-8.1},
  {code:"INTU", name:"Intuit",          sector:"資訊科技",   rs:19, q1:-5.8,q2:-4.8,q3:-4.8,q4:-3.8, rsHigh:false, sepa:false, cap:"大", c1:-3.4, c5:-7.1, c1m:-9.4},
  {code:"SBUX", name:"Starbucks",       sector:"非必需消費", rs:16, q1:-7.1,q2:-5.8,q3:-5.4,q4:-4.4, rsHigh:false, sepa:false, cap:"大", c1:-3.8, c5:-7.8, c1m:-11.2},
  {code:"PYPL", name:"PayPal",          sector:"金融",       rs:13, q1:-8.8,q2:-6.8,q3:-6.1,q4:-5.1, rsHigh:false, sepa:false, cap:"中", c1:-4.2, c5:-8.4, c1m:-13.1},
  {code:"WBA",  name:"Walgreens",       sector:"必需消費",   rs:9,  q1:-11.4,q2:-8.4,q3:-7.4,q4:-6.2,rsHigh:false, sepa:false, cap:"小", c1:-4.8, c5:-9.4, c1m:-15.8},
  {code:"ENPH", name:"Enphase Energy",  sector:"資訊科技",   rs:6,  q1:-14.2,q2:-10.1,q3:-8.4,q4:-7.1,rsHigh:false, sepa:false, cap:"中", c1:-5.4, c5:-10.8,c1m:-18.4},
];

const DEMO_SECTORS = [
  {name:"資訊科技",   c1:1.24, c5:3.42, c1m:11.8, flow:84.2, flow5:268.4, weeks:[60,64,68,72,70,75,78,80,82,84,83,84]},
  {name:"通訊服務",   c1:0.98, c5:2.84, c1m:9.4,  flow:76.4, flow5:213.6, weeks:[55,58,62,65,64,68,70,72,73,75,76,76]},
  {name:"金融",       c1:0.62, c5:2.14, c1m:7.8,  flow:71.2, flow5:184.2, weeks:[52,55,58,61,60,64,66,68,69,70,71,71]},
  {name:"工業",       c1:0.42, c5:1.68, c1m:6.4,  flow:64.8, flow5:152.4, weeks:[50,52,55,58,57,60,62,63,64,65,65,64]},
  {name:"醫療保健",   c1:0.28, c5:1.12, c1m:4.8,  flow:58.4, flow5:118.6, weeks:[48,50,52,54,53,56,57,58,59,60,59,58]},
  {name:"必需消費",   c1:0.14, c5:0.68, c1m:3.4,  flow:52.1, flow5:84.2,  weeks:[50,51,52,53,52,54,54,53,53,52,53,52]},
  {name:"非必需消費", c1:-0.18,c5:-0.42,c1m:2.1,  flow:46.8, flow5:62.4,  weeks:[48,49,50,51,50,51,50,49,48,47,46,46]},
  {name:"原物料",     c1:-0.42,c5:-1.24,c1m:0.8,  flow:42.4, flow5:38.2,  weeks:[46,46,45,47,46,47,46,45,44,43,42,42]},
  {name:"房地產",     c1:-0.68,c5:-1.84,c1m:-1.4, flow:38.2, flow5:14.8,  weeks:[45,44,43,44,43,44,43,42,41,40,39,38]},
  {name:"能源",       c1:-1.24,c5:-3.24,c1m:-4.8, flow:32.4, flow5:-48.4, weeks:[44,42,40,38,36,35,34,32,30,28,26,24]},
  {name:"公用事業",   c1:-0.84,c5:-2.14,c1m:-2.8, flow:36.8, flow5:-12.4, weeks:[46,45,44,43,42,42,41,40,39,38,37,36]},
];

// ── HELPERS ──────────────────────────────────────────────────
function pct(v) {
  const s = v > 0 ? '+' : '';
  return `<span class="${v>0?'pos':v<0?'neg':'neu'}">${s}${v.toFixed(1)}%</span>`;
}
function rsColor(rs) {
  if (rs >= 90) return 'var(--rs90)';
  if (rs >= 80) return 'var(--rs80)';
  if (rs >= 70) return '#86efac';
  if (rs >= 50) return 'var(--rs50)';
  if (rs >= 30) return 'var(--rs30)';
  return 'var(--rs0)';
}
function rsBarColor(rs) {
  if (rs >= 90) return '#00ff88';
  if (rs >= 80) return '#10b981';
  if (rs >= 70) return '#86efac';
  if (rs >= 50) return '#64748b';
  if (rs >= 30) return '#f97316';
  return '#f43f5e';
}
function capBadge(cap) {
  return `<span class="cap-badge cap-${cap}">${cap}</span>`;
}
function tvLink(code) {
  // 不指定交易所，讓 TradingView 自動解析 NYSE / NASDAQ 標的
  return `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(code)}&interval=D`;
}
function makeSvgSparkline(data, w, h) {
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / range) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const last = data[data.length-1], prev = data[data.length-2];
  const color = last >= prev ? '#10b981' : '#f43f5e';
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg" style="display:block">
    <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>
  </svg>`;
}

function computePrevRankMap() {
  let latestDate = '';
  for (const entries of Object.values(rsHistory)) {
    if (entries.length && entries[entries.length - 1].date > latestDate) {
      latestDate = entries[entries.length - 1].date;
    }
  }
  if (!latestDate) return new Map();
  const prevRS = [];
  for (const [code, entries] of Object.entries(rsHistory)) {
    const prev = [...entries].reverse().find(e => e.date < latestDate);
    if (prev) prevRS.push({ code, rs: prev.rs });
  }
  prevRS.sort((a, b) => b.rs - a.rs);
  return new Map(prevRS.map((s, i) => [s.code, i + 1]));
}

function rankDelta(curr, prev) {
  if (prev == null) return `<span style="font-size:10px;color:var(--accent);font-family:var(--font-num)">NEW</span>`;
  const d = prev - curr;
  if (d === 0) return `<span style="color:var(--text3);font-family:var(--font-num);font-size:11px">—</span>`;
  const color = d > 0 ? 'var(--pos)' : 'var(--neg)';
  return `<span style="color:${color};font-family:var(--font-num);font-size:11px">${d > 0 ? '▲' : '▼'}${Math.abs(d)}</span>`;
}

// ── STATE ─────────────────────────────────────────────────────
let sortCol = 'rs', sortDir = -1;
let filterCap = 'all', filterSector = 'all', filterRS = 0, searchQuery = '';
let page = 1;
const PER_PAGE = 20;

// ── INIT ─────────────────────────────────────────────────────
async function init() {
  document.getElementById('update-time').textContent = '載入中…';
  const { updatedAt, live } = await fetchData();
  const timeEl = document.getElementById('update-time');
  if (live && updatedAt) {
    timeEl.innerHTML = `<span style="color:var(--pos)">●</span> ${updatedAt} ET 即時資料`;
  } else {
    timeEl.innerHTML = `<span style="color:var(--text3)">○</span> 示意資料 · <span style="color:var(--neg)">請執行 rs_calculator.py</span>`;
  }

  const sectors = [...new Set(stocks.map(s => s.sector))].sort();
  const sel = document.getElementById('sector-filter');
  sectors.forEach(sc => {
    const o = document.createElement('option');
    o.value = sc; o.textContent = sc; sel.appendChild(o);
  });

  const rs70 = stocks.filter(s => s.rs >= 70).length;
  const sepaCount = stocks.filter(s => s.sepa).length;
  const highCount = stocks.filter(s => s.rsHigh).length;
  document.getElementById('cnt-70').textContent = rs70;
  document.getElementById('cnt-total').textContent = stocks.length;
  document.getElementById('cnt-sepa').textContent = sepaCount;
  document.getElementById('cnt-high').textContent = highCount;
  document.getElementById('tab-cnt-all').textContent = stocks.length;
  document.getElementById('tab-cnt-sepa').textContent = sepaCount;

  const sectorRS = {};
  stocks.forEach(s => {
    if (!sectorRS[s.sector]) sectorRS[s.sector] = [];
    sectorRS[s.sector].push(s.rs);
  });
  let topSector = '', topAvg = 0;
  Object.entries(sectorRS).forEach(([sc, arr]) => {
    const avg = arr.reduce((a,b)=>a+b,0)/arr.length;
    if (avg > topAvg) { topAvg = avg; topSector = sc; }
  });
  document.getElementById('top-sector').textContent = topSector;

  renderTable(); renderSEPA(); renderFund(); renderSectorFlow();
  bindEvents();
}

function getFiltered() {
  const q = searchQuery.toLowerCase();
  return stocks.filter(s => {
    if (filterCap !== 'all' && s.cap !== filterCap) return false;
    if (filterSector !== 'all' && s.sector !== filterSector) return false;
    if (s.rs < filterRS) return false;
    if (q && !s.code.toLowerCase().includes(q) && !s.name.toLowerCase().includes(q)) return false;
    return true;
  }).sort((a, b) => {
    const av = a[sortCol], bv = b[sortCol];
    if (typeof av === 'boolean') return (bv - av) * sortDir * -1;
    return (av - bv) * sortDir;
  });
}

function renderTable() {
  const data = getFiltered();
  const total = data.length;
  const pages = Math.ceil(total / PER_PAGE);
  if (page > pages) page = 1;
  const slice = data.slice((page-1)*PER_PAGE, page*PER_PAGE);

  document.getElementById('result-count').textContent = `共 ${total} 檔`;

  const allByRS = [...stocks].sort((a,b) => b.rs - a.rs);
  const rankMap = new Map(allByRS.map((s, i) => [s.code, i + 1]));
  const prevRankMap = computePrevRankMap();
  const showDelta = prevRankMap.size > 0;
  document.querySelector('th.col-delta').style.display = showDelta ? '' : 'none';

  const tbody = document.getElementById('rs-tbody');
  tbody.innerHTML = slice.map((s) => {
    const rank = rankMap.get(s.code);
    return `<tr class="tr-clickable" onclick="showHistory('${s.code}','${s.name.replace(/'/g, "\\'")}')">
      <td class="td-rank">${rank}</td>
      ${showDelta ? `<td class="td-rank" style="width:40px;text-align:center">${rankDelta(rank, prevRankMap.get(s.code))}</td>` : ''}
      <td class="td-code"><a href="${tvLink(s.code)}" target="_blank" onclick="event.stopPropagation()">${s.code}</a></td>
      <td class="td-name">${s.name}${s.sepa?` <span class="sepa-badge">SEPA</span>`:''}</td>
      <td class="td-num rs-cell">
        <div class="rs-wrap">
          <div class="rs-bar-bg"><div class="rs-bar" style="width:${s.rs}%;background:${rsBarColor(s.rs)}"></div></div>
          <span class="rs-num" style="color:${rsColor(s.rs)}">${s.rs}</span>
        </div>
      </td>
      <td style="text-align:center">${s.rsHigh?`<span class="tag-high">◆ 52W新高</span>`:`<span class="tag-dash">—</span>`}</td>
      <td class="td-num" style="color:var(--text)">${s.price != null ? s.price.toFixed(2) : '—'}</td>
      <td class="td-num">${pct(s.q1)}</td>
      <td class="td-num">${pct(s.q2)}</td>
      <td class="td-num">${pct(s.q3)}</td>
      <td class="td-num">${pct(s.q4)}</td>
      <td class="td-num">${pct(s.c1)}</td>
      <td class="td-num">${pct(s.c5)}</td>
      <td class="td-num">${pct(s.c1m)}</td>
      <td>${capBadge(s.cap)}</td>
      <td class="td-sector">${s.sector}</td>
    </tr>`;
  }).join('');

  const pg = document.getElementById('pagination');
  pg.innerHTML = '';
  const addBtn = (label, targetPage, disabled, active) => {
    const b = document.createElement('button');
    b.className = 'page-btn' + (active?' active':'');
    b.textContent = label;
    b.disabled = disabled;
    if (!disabled) b.onclick = () => { page = targetPage; renderTable(); };
    pg.appendChild(b);
  };
  addBtn('«', 1, page===1, false);
  addBtn('‹', page-1, page===1, false);
  for (let p = Math.max(1,page-2); p <= Math.min(pages,page+2); p++) {
    addBtn(p, p, false, p===page);
  }
  addBtn('›', page+1, page===pages||pages===0, false);
  addBtn('»', pages, page===pages||pages===0, false);
}

function renderSEPA() {
  const sepa = stocks.filter(s => s.sepa).sort((a,b) => b.rs - a.rs);
  const tbody = document.getElementById('sepa-tbody');
  tbody.innerHTML = sepa.map((s, i) => {
    const detail = s.sepa_detail || {};
    const crits = Object.entries(SEPA_LABELS).map(([key, label]) => {
      const pass = detail[key] ?? false;
      return `<span class="crit ${pass?'crit-pass':'crit-fail'}">${pass?'✓':'✗'} ${label}</span>`;
    }).join('');
    return `<tr>
      <td class="td-rank">${i+1}</td>
      <td class="td-code"><a href="${tvLink(s.code)}" target="_blank">${s.code}</a></td>
      <td class="td-name">${s.name}</td>
      <td class="td-num rs-cell">
        <div class="rs-wrap">
          <div class="rs-bar-bg"><div class="rs-bar" style="width:${s.rs}%;background:${rsBarColor(s.rs)}"></div></div>
          <span class="rs-num" style="color:${rsColor(s.rs)}">${s.rs}</span>
        </div>
      </td>
      <td style="text-align:center">${s.rsHigh?`<span class="tag-high">◆ 52W新高</span>`:`<span class="tag-dash">—</span>`}</td>
      <td class="td-num">${pct(s.q1)}</td>
      <td class="td-num">${pct(s.q2)}</td>
      <td class="td-num">${pct(s.q3)}</td>
      <td class="td-num">${pct(s.q4)}</td>
      <td class="td-num">${pct(s.c1)}</td>
      <td class="td-num">${pct(s.c1m)}</td>
      <td class="td-num" style="color:var(--text)">${s.price != null ? s.price.toFixed(2) : '—'}</td>
      <td style="max-width:300px">${crits}</td>
      <td class="td-sector">${s.sector}</td>
    </tr>`;
  }).join('');
}

function renderFund() {
  const sepa = stocks.filter(s => s.sepa).sort((a,b) => b.rs - a.rs);
  const grid = document.getElementById('fund-grid');
  grid.innerHTML = sepa.map(s => {
    const detail = s.sepa_detail || {};
    const crits = Object.entries(SEPA_LABELS).map(([key, label]) => {
      const pass = detail[key] ?? false;
      return `<span class="crit ${pass?'crit-pass':'crit-fail'}">${pass?'✓':'✗'} ${label}</span>`;
    }).join('');
    return `<div class="fund-card">
      <div class="fund-header">
        <div>
          <div class="fund-code"><a href="${tvLink(s.code)}" target="_blank" style="color:inherit;text-decoration:none">${s.code}</a></div>
          <div class="fund-name">${s.name} · ${s.sector}</div>
        </div>
        <div class="fund-rs">
          <div class="fund-rs-num" style="color:${rsColor(s.rs)}">${s.rs}</div>
          <div class="fund-rs-label">RS Score</div>
        </div>
      </div>
      <div class="fund-criteria">${crits}</div>
      <div class="fund-stats">
        <div class="fund-stat"><div class="fund-stat-label">Q1</div><div class="fund-stat-val ${s.q1>0?'c-pos':'c-neg'}">${s.q1>0?'+':''}${s.q1.toFixed(1)}%</div></div>
        <div class="fund-stat"><div class="fund-stat-label">1日</div><div class="fund-stat-val ${s.c1>0?'c-pos':'c-neg'}">${s.c1>0?'+':''}${s.c1.toFixed(1)}%</div></div>
        <div class="fund-stat"><div class="fund-stat-label">1月</div><div class="fund-stat-val ${s.c1m>0?'c-pos':'c-neg'}">${s.c1m>0?'+':''}${s.c1m.toFixed(1)}%</div></div>
        <div class="fund-stat"><div class="fund-stat-label">市值</div><div class="fund-stat-val">${s.cap}</div></div>
      </div>
    </div>`;
  }).join('');
}

function renderSectorFlow() {
  const sorted = [...sectorFlowData].sort((a,b) => b.flow - a.flow);
  const maxFlow = sorted[0].flow;
  const tbody = document.getElementById('sector-tbody');
  tbody.innerHTML = sorted.map((sf, i) => {
    const barW = Math.abs(sf.flow / maxFlow * 100).toFixed(1);
    const barColor = sf.c1 >= 0 ? 'var(--pos)' : 'var(--neg)';
    const flow5Color = sf.flow5 >= 0 ? 'var(--pos)' : 'var(--neg)';
    const flow5W = Math.abs(sf.flow5 / 300 * 100).toFixed(1);
    const hasWeeks = sf.weeks && sf.weeks.length >= 2;
    return `<tr class="sector-row" data-idx="${i}">
      <td class="td-rank">${i+1}</td>
      <td style="font-weight:500">${sf.name}</td>
      <td>
        <div class="flow-bar-wrap">
          <div class="flow-bar-bg"><div class="flow-bar" style="width:${barW}%;background:${barColor}"></div></div>
          <span class="flow-num" style="color:${barColor}">${sf.flow.toFixed(1)}</span>
        </div>
      </td>
      <td>
        <div class="flow-bar-wrap">
          <div class="flow-bar-bg"><div class="flow-bar" style="width:${Math.min(flow5W,100)}%;background:${flow5Color}"></div></div>
          <span class="flow-num" style="color:${flow5Color}">${sf.flow5 > 0 ? '+' : ''}${sf.flow5.toFixed(0)}</span>
        </div>
      </td>
      <td class="td-num">${pct(sf.c1)}</td>
      <td class="td-num">${pct(sf.c5)}</td>
      <td class="td-num">${pct(sf.c1m)}</td>
    </tr>
    ${hasWeeks ? `<tr class="sparkline-row" id="spark-${i}">
      <td colspan="7">
        <div style="display:flex;align-items:center;gap:16px;padding:4px 0">
          <span style="font-size:11px;color:var(--text3);white-space:nowrap">12週 RS 曲線</span>
          ${makeSvgSparkline(sf.weeks, 320, 48)}
          <div style="font-family:var(--font-num);font-size:11px;color:var(--text3)">
            ${sf.weeks.map((v)=>`<span style="color:${v===Math.max(...sf.weeks)?'var(--pos)':v===Math.min(...sf.weeks)?'var(--neg)':'var(--text3)'}">${v}</span>`).join(' · ')}
          </div>
        </div>
      </td>
    </tr>` : ''}`;
  }).join('');

  tbody.querySelectorAll('.sector-row').forEach(row => {
    row.addEventListener('click', () => {
      const idx = row.dataset.idx;
      const el = document.getElementById(`spark-${idx}`);
      if (el) el.classList.toggle('open');
    });
  });
}

// ── EVENTS ────────────────────────────────────────────────────
function bindEvents() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    });
  });

  document.getElementById('cap-filter').querySelectorAll('.pill').forEach(pill => {
    pill.addEventListener('click', () => {
      document.getElementById('cap-filter').querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      filterCap = pill.dataset.cap;
      page = 1; renderTable();
    });
  });

  document.getElementById('sector-filter').addEventListener('change', e => {
    filterSector = e.target.value; page = 1; renderTable();
  });

  document.getElementById('rs-filter').querySelectorAll('.pill').forEach(pill => {
    pill.addEventListener('click', () => {
      document.getElementById('rs-filter').querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      filterRS = parseInt(pill.dataset.rs); page = 1; renderTable();
    });
  });

  document.querySelectorAll('thead th[data-col]').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.col;
      if (sortCol === col) sortDir *= -1;
      else { sortCol = col; sortDir = -1; }
      document.querySelectorAll('thead th').forEach(h => {
        h.classList.remove('sorted');
        const icon = h.querySelector('.sort-icon');
        if (icon) icon.textContent = '↕';
      });
      th.classList.add('sorted');
      const icon = th.querySelector('.sort-icon');
      if (icon) icon.textContent = sortDir === -1 ? '↓' : '↑';
      page = 1; renderTable();
    });
  });
}

// ── EXPORT ────────────────────────────────────────────────────
const SECTOR_EMOJI = {
  '資訊科技':'💻 ', '通訊服務':'📡 ', '金融':'🏦 ', '工業':'🏭 ',
  '醫療保健':'🏥 ', '必需消費':'🛒 ', '非必需消費':'🛍️ ', '能源':'⛽ ',
  '公用事業':'💡 ', '房地產':'🏢 ', '原物料':'⚗️ ', '其他':'📦 ',
};

function exportTV() {
  const threshold = parseInt(document.getElementById('rs-threshold').value) || 90;
  const list = stocks.filter(s => s.rs >= threshold).sort((a, b) => b.rs - a.rs);
  if (!list.length) { alert(`目前沒有 RS≥${threshold} 的股票`); return; }
  const today = new Date().toISOString().slice(0, 10);

  const bySector = {};
  list.forEach(s => {
    const sec = s.sector || '其他';
    if (!bySector[sec]) bySector[sec] = [];
    bySector[sec].push(s);
  });

  const content = Object.entries(bySector)
    .sort((a, b) => b[1][0].rs - a[1][0].rs)
    .map(([sec, items]) => {
      const emoji = SECTOR_EMOJI[sec] || '📌';
      // TradingView 觀察清單匯入：直接用股票代號（自動解析交易所）
      return `###${emoji}${sec}\n${items.map(s => s.code).join('\n')}`;
    }).join('\n\n');

  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `rs${threshold}_watchlist_${today}.txt`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── HISTORY MODAL ─────────────────────────────────────────────
function showHistory(code, name) {
  const entries = rsHistory[code] || [];
  document.getElementById('modal-title').textContent = `${code} ${name} — RS 歷史走勢`;
  document.getElementById('modal-sub').textContent = entries.length ? `近 ${entries.length} 個交易日` : '';
  const noData = document.getElementById('modal-no-data');
  const canvas = document.getElementById('history-chart');

  if (entries.length < 2) {
    canvas.style.display = 'none';
    noData.style.display = 'block';
    noData.textContent = entries.length === 0
      ? '尚無歷史資料（明日計算後開始累積）'
      : `資料累積中（目前 ${entries.length} 筆，需至少 2 個交易日）`;
  } else {
    canvas.style.display = 'block';
    noData.style.display = 'none';
    if (historyChart) historyChart.destroy();
    historyChart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: entries.map(e => e.date.slice(5)),
        datasets: [{
          data: entries.map(e => e.rs),
          borderColor: '#06b6d4',
          backgroundColor: 'rgba(6,182,212,.08)',
          borderWidth: 2,
          pointRadius: entries.length > 60 ? 0 : 3,
          pointBackgroundColor: '#06b6d4',
          fill: true,
          tension: 0.3,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` RS ${ctx.parsed.y}` } } },
        scales: {
          x: { ticks: { color: '#4a5d7a', maxTicksLimit: 10 }, grid: { color: '#1f2d45' } },
          y: { min: 0, max: 99, ticks: { color: '#4a5d7a' }, grid: { color: '#1f2d45' } }
        }
      }
    });
  }
  document.getElementById('history-modal').classList.add('open');
}

function closeHistoryModal(e) {
  if (e && e.target !== document.getElementById('history-modal')) return;
  document.getElementById('history-modal').classList.remove('open');
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeHistoryModal(); });

function onSearch() {
  searchQuery = document.getElementById('search-input').value;
  page = 1; renderTable();
}

init();
