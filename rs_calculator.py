#!/usr/bin/env python3
"""
美股全市場 Minervini RS 計算器（S&P 500 + Nasdaq-100 + 更多 NASDAQ）
====================================================================
- 自動抓取成分股清單（S&P 500 CSV 主來源 + Nasdaq 擴充，best-effort）
- 計算 RS Score、RS Line、SEPA 條件
- 真實量價「資金流向」= Σ(日漲跌幅 × 成交量 × 收盤價)
- 板塊資金流向 + 軟體/硬體細分
- 市值分級（大/中/小/未知）
- 輸出 docs/rs_data.json（供 GitHub Pages 使用）

RS Score = Q1×50% + Q2×25% + Q3×15% + Q4×10%
基準指數：^GSPC（S&P 500）
"""

import os
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import json, time, sys, warnings, argparse, pickle, threading
from datetime import datetime, timezone, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

warnings.filterwarnings("ignore")

try:
    from zoneinfo import ZoneInfo
    US_TZ = ZoneInfo("America/New_York")
except Exception:
    US_TZ = timezone(timedelta(hours=-5))

# ── 參數 ──────────────────────────────────────────────────────
BENCHMARK   = "^GSPC"
WORKERS     = 10
MIN_DAYS    = 252
SLEEP       = 0.08
OUTPUT_DIR  = "docs"
OUTPUT_FILE   = f"{OUTPUT_DIR}/rs_data.json"
HISTORY_FILE  = f"{OUTPUT_DIR}/rs_history.json"
CACHE_FILE    = "price_cache.pkl"
HISTORY_DAYS  = 180
HISTORY_MIN_RS = 50

CAP_LARGE = 10e9      # 大型 ≥ $10B（$100 億）
CAP_MID   = 2e9       # 中型 ≥ $2B（$20 億）

# 股票池擴大：NASDAQ 擴充清單門檻與上限（控制執行時間、避免限流）
NASDAQ_MIN_CAP = 2e9  # 只納入市值 ≥ $2B 的 NASDAQ 上市股
MAX_UNIVERSE   = 1400 # 全體上限

GICS_MAP = {
    "Information Technology": "資訊科技", "Health Care": "醫療保健",
    "Financials": "金融", "Consumer Discretionary": "非必需消費",
    "Communication Services": "通訊服務", "Industrials": "工業",
    "Consumer Staples": "必需消費", "Energy": "能源",
    "Utilities": "公用事業", "Real Estate": "房地產", "Materials": "原物料",
}
# NASDAQ 官方 sector 名稱 → 中文
NASDAQ_SECTOR_MAP = {
    "Technology": "資訊科技", "Health Care": "醫療保健", "Finance": "金融",
    "Consumer Discretionary": "非必需消費", "Consumer Staples": "必需消費",
    "Industrials": "工業", "Energy": "能源", "Basic Materials": "原物料",
    "Real Estate": "房地產", "Utilities": "公用事業",
    "Telecommunications": "通訊服務", "Miscellaneous": "其他",
}

# ── 收盤價/量快取（值為含 Close, Volume 的 DataFrame）─────────────
_price_cache: dict = {}
_cache_lock = threading.Lock()

def load_price_cache():
    global _price_cache
    if not os.path.exists(CACHE_FILE):
        return
    try:
        with open(CACHE_FILE, "rb") as f:
            _price_cache = pickle.load(f)
        print(f"  ✓ 快取載入：{len(_price_cache)} 支股票")
    except Exception as e:
        print(f"  ⚠ 快取讀取失敗，將重新下載：{e}")
        _price_cache = {}

def save_price_cache():
    try:
        with open(CACHE_FILE, "wb") as f:
            pickle.dump(_price_cache, f)
    except Exception as e:
        print(f"  ⚠ 快取儲存失敗：{e}")


# ════════════════════════════════════════════════════════════════
#  Step 1：抓取成分股清單
# ════════════════════════════════════════════════════════════════
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RS-Ranking/1.0)"}

FALLBACK = [
    ("AAPL","Apple","資訊科技"),("MSFT","Microsoft","資訊科技"),
    ("NVDA","NVIDIA","資訊科技"),("AVGO","Broadcom","資訊科技"),
    ("AMZN","Amazon","非必需消費"),("TSLA","Tesla","非必需消費"),
    ("GOOGL","Alphabet A","通訊服務"),("META","Meta Platforms","通訊服務"),
    ("NFLX","Netflix","通訊服務"),("JPM","JPMorgan Chase","金融"),
    ("V","Visa","金融"),("MA","Mastercard","金融"),
    ("LLY","Eli Lilly","醫療保健"),("UNH","UnitedHealth","醫療保健"),
    ("JNJ","Johnson & Johnson","醫療保健"),("XOM","Exxon Mobil","能源"),
    ("CVX","Chevron","能源"),("COST","Costco","必需消費"),
    ("WMT","Walmart","必需消費"),("PG","Procter & Gamble","必需消費"),
    ("HD","Home Depot","非必需消費"),("CAT","Caterpillar","工業"),
    ("GE","GE Aerospace","工業"),("NEE","NextEra Energy","公用事業"),
    ("AMT","American Tower","房地產"),("LIN","Linde","原物料"),
]
NASDAQ100_EXTRA = [
    ("ASML","ASML Holding","資訊科技"), ("AZN","AstraZeneca","醫療保健"),
    ("ARM","Arm Holdings","資訊科技"),  ("PDD","PDD Holdings","非必需消費"),
    ("MELI","MercadoLibre","非必需消費"),("GFS","GlobalFoundries","資訊科技"),
    ("TEAM","Atlassian","資訊科技"),    ("MDB","MongoDB","資訊科技"),
]
SP500_CSV_URLS = [
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv",
]
NASDAQ_JSON_URLS = [
    "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nasdaq/nasdaq_full_tickers.json",
]

def classify_group_from_gics(sub_industry: str) -> str:
    """S&P 用 GICS 細產業判斷軟體/硬體（僅資訊科技有意義）。"""
    s = (sub_industry or "").lower()
    if not s:
        return ""
    if ("software" in s or "internet services" in s or "it consulting" in s
            or "interactive" in s):
        return "軟體"
    if ("semiconductor" in s or "hardware" in s or "communications equipment" in s
            or "electronic" in s or "technology distributors" in s):
        return "硬體"
    return ""

def classify_group_from_industry(sector_zh: str, industry: str) -> str:
    """NASDAQ 擴充用產業字串判斷軟體/硬體（僅資訊科技）。"""
    if sector_zh != "資訊科技":
        return ""
    s = (industry or "").lower()
    if ("software" in s or "internet" in s or "cloud" in s or "computer software" in s
            or "consulting" in s):
        return "軟體"
    if ("semiconductor" in s or "hardware" in s or "computer" in s or "electronic" in s
            or "communication" in s or "component" in s):
        return "硬體"
    return ""

def fetch_sp500_csv() -> dict:
    """S&P 500 主來源。回傳 {ticker:(name, sector_zh, group)}"""
    import io, csv
    for url in SP500_CSV_URLS:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.text))
            out = {}
            for row in reader:
                sym = (row.get("Symbol") or "").strip().upper()
                name = (row.get("Security") or row.get("Name") or sym).strip()
                sec_en = (row.get("GICS Sector") or row.get("Sector") or "").strip()
                sub = (row.get("GICS Sub-Industry") or "").strip()
                sec_zh = GICS_MAP.get(sec_en, "其他")
                grp = classify_group_from_gics(sub) if sec_zh == "資訊科技" else ""
                if sym:
                    out[sym] = (name, sec_zh, grp)
            if len(out) >= 100:
                print(f"  ✓ S&P 500（CSV）：{len(out)} 檔")
                return out
        except Exception as e:
            print(f"  ⚠ S&P 500 CSV 失敗：{e}")
    return {}

def _read_wiki_tables(url: str):
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    import io
    return pd.read_html(io.StringIO(resp.text))

def fetch_sp500_wiki() -> dict:
    out = {}
    try:
        tables = _read_wiki_tables("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        df = tables[0]
        for _, row in df.iterrows():
            sym = str(row.get("Symbol", "")).strip().upper()
            name = str(row.get("Security", "")).strip()
            sec = str(row.get("GICS Sector", "")).strip()
            sub = str(row.get("GICS Sub-Industry", "")).strip()
            sec_zh = GICS_MAP.get(sec, "其他")
            grp = classify_group_from_gics(sub) if sec_zh == "資訊科技" else ""
            if sym:
                out[sym] = (name, sec_zh, grp)
        print(f"  ✓ S&P 500（維基）：{len(out)} 檔")
    except Exception as e:
        print(f"  ⚠ S&P 500 維基失敗：{e}")
    return out

def _parse_cap(v) -> float:
    if v is None:
        return 0.0
    try:
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).replace("$", "").replace(",", "").strip()
        if s == "" or s.upper() in ("NA", "N/A", "NAN"):
            return 0.0
        mult = 1.0
        if s[-1] in "KkMmBbTt":
            mult = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[s[-1].upper()]
            s = s[:-1]
        return float(s) * mult
    except Exception:
        return 0.0

def fetch_nasdaq_extra(existing: set) -> list[dict]:
    """股票池擴大（best-effort）：抓 NASDAQ 上市、市值≥門檻的股票。失敗回 []（不影響）。"""
    data = None
    for url in NASDAQ_JSON_URLS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=45)
            r.raise_for_status()
            data = r.json()
            break
        except Exception as e:
            print(f"  ⚠ NASDAQ 擴充清單抓取失敗：{e}")
    if not isinstance(data, list):
        print("  ⚠ NASDAQ 擴充略過（不影響現有清單）")
        return []
    out = []
    for it in data:
        if not isinstance(it, dict):
            continue
        sym = str(it.get("symbol") or it.get("Symbol") or it.get("ticker") or "").strip().upper()
        if not sym or sym in existing or not sym.isalpha():
            continue
        mc = _parse_cap(it.get("marketCap") or it.get("market_cap") or it.get("Market Cap"))
        if mc < NASDAQ_MIN_CAP:
            continue
        name = str(it.get("name") or it.get("Name") or sym).strip()
        sec_en = str(it.get("sector") or it.get("Sector") or "").strip()
        ind = str(it.get("industry") or it.get("Industry") or "").strip()
        sec_zh = NASDAQ_SECTOR_MAP.get(sec_en, "其他")
        grp = classify_group_from_industry(sec_zh, ind)
        out.append({"code": sym, "yf": sym.replace(".", "-"), "name": name,
                    "sector": sec_zh, "group": grp, "mc": mc})
    out.sort(key=lambda x: x["mc"], reverse=True)   # 市值大的優先
    print(f"  ✓ NASDAQ 擴充（市值≥${NASDAQ_MIN_CAP/1e9:.0f}B）：{len(out)} 檔")
    return out

def fetch_universe() -> list[dict]:
    # 1) S&P 500（CSV 主，維基備援）
    sp = fetch_sp500_csv()
    if len(sp) < 100:
        sp = fetch_sp500_wiki()

    stocks_map = {}   # code -> dict
    for sym, (name, sec, grp) in sp.items():
        stocks_map[sym] = {"code": sym, "yf": sym.replace(".", "-"),
                           "name": name, "sector": sec, "group": grp, "mc": 0.0}

    # 2) Nasdaq-100 非 S&P 成分股
    for t, n, s in NASDAQ100_EXTRA:
        stocks_map.setdefault(t, {"code": t, "yf": t.replace(".", "-"),
                                  "name": n, "sector": s,
                                  "group": classify_group_from_industry(s, ""), "mc": 0.0})

    # 3) 保險：清單太小才用備援
    if len(stocks_map) < 50:
        print("  ⚠ 線上來源皆失敗，使用備援清單")
        for t, n, s in FALLBACK:
            stocks_map.setdefault(t, {"code": t, "yf": t.replace(".", "-"),
                                      "name": n, "sector": s, "group": "", "mc": 0.0})

    # 4) 股票池擴大：NASDAQ 擴充（best-effort，不會弄壞前面）
    extra = fetch_nasdaq_extra(set(stocks_map.keys()))
    for e in extra:
        if len(stocks_map) >= MAX_UNIVERSE:
            break
        stocks_map.setdefault(e["code"], e)

    stocks = list(stocks_map.values())
    print(f"  ✓ 最終股票池共 {len(stocks)} 檔")
    return stocks


# ════════════════════════════════════════════════════════════════
#  Step 2：下載收盤價 + 成交量
# ════════════════════════════════════════════════════════════════
def _fetch_yf(ticker: str, period: str, timeout: int = 20) -> pd.DataFrame | None:
    """回傳含 Close, Volume 的 DataFrame，或 None。"""
    try:
        df = yf.download(ticker, period=period, auto_adjust=True,
                         progress=False, timeout=timeout)
        if df is None or df.empty:
            return None
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.squeeze()
        if "Volume" in df:
            vol = df["Volume"]
            if isinstance(vol, pd.DataFrame):
                vol = vol.squeeze()
        else:
            vol = pd.Series(0.0, index=close.index)
        out = pd.DataFrame({"Close": close, "Volume": vol}).dropna(subset=["Close"])
        out["Volume"] = out["Volume"].fillna(0.0)
        return out if not out.empty else None
    except Exception:
        return None

def download_ohlcv(ticker: str, period: str = "580d") -> pd.DataFrame | None:
    today = date.today()
    with _cache_lock:
        cached = _price_cache.get(ticker)

    if cached is not None:
        try:
            last_date = cached.index[-1].date()
        except Exception:
            last_date = today
        if last_date >= today:
            return cached if len(cached) >= MIN_DAYS else None
        new_data = _fetch_yf(ticker, period="5d", timeout=10)
        if new_data is not None and not new_data.empty:
            merged = pd.concat([cached, new_data])
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
            with _cache_lock:
                _price_cache[ticker] = merged
            return merged if len(merged) >= MIN_DAYS else None
        return cached if len(cached) >= MIN_DAYS else None

    for attempt in range(2):
        df = _fetch_yf(ticker, period=period)
        if df is not None and len(df) >= MIN_DAYS:
            with _cache_lock:
                _price_cache[ticker] = df
            return df
        if attempt == 0:
            time.sleep(1)
    return None

def get_market_cap(ticker: str) -> float:
    """取市值（美元）。用直接索引觸發 fast_info 即時計算；失敗以股數×股價備援。"""
    try:
        fi = yf.Ticker(ticker).fast_info
    except Exception:
        return 0.0
    for key in ("market_cap", "marketCap"):
        try:
            v = fi[key]
            if v:
                return float(v)
        except Exception:
            pass
    try:
        sh, px = fi["shares"], fi["last_price"]
        if sh and px:
            return float(sh) * float(px)
    except Exception:
        pass
    return 0.0


# ════════════════════════════════════════════════════════════════
#  Step 3：核心計算
# ════════════════════════════════════════════════════════════════
def safe_pct(a, b) -> float:
    try:
        a, b = float(a), float(b)
        if b == 0 or np.isnan(a) or np.isnan(b):
            return 0.0
        return round((a / b - 1) * 100, 2)
    except Exception:
        return 0.0

def calc_rs_raw(s: pd.Series, b: pd.Series) -> dict | None:
    s, b = s.align(b, join="inner")
    s, b = s.dropna(), b.dropna()
    if len(s) < MIN_DAYS:
        return None

    def qpct(ser, end_idx, start_idx):
        n = len(ser)
        return safe_pct(ser.iloc[min(end_idx, n-1)], ser.iloc[min(start_idx, n-1)])

    q1s = qpct(s, -1, -63)
    q2s = qpct(s, -63, -126)
    q3s = qpct(s, -126, -189)
    q4s = qpct(s, -189, -252)
    raw = q1s*0.5 + q2s*0.25 + q3s*0.15 + q4s*0.10

    c1  = safe_pct(s.iloc[-1], s.iloc[-2])  if len(s) >= 2  else 0.0
    c5  = safe_pct(s.iloc[-1], s.iloc[-6])  if len(s) >= 6  else 0.0
    c1m = safe_pct(s.iloc[-1], s.iloc[-22]) if len(s) >= 22 else 0.0

    return dict(rs_raw=round(raw, 3),
                q1=round(q1s,2), q2=round(q2s,2), q3=round(q3s,2), q4=round(q4s,2),
                c1=round(c1,2), c5=round(c5,2), c1m=round(c1m,2),
                price=round(float(s.iloc[-1]), 2))

def calc_flow(close: pd.Series, vol: pd.Series) -> tuple[float, float]:
    """真實量價資金流：日流向 = 日漲跌幅 × 成交量 × 收盤價（帶正負號）。
    回傳 (1日流向, 5日流向)，單位：百萬美元。"""
    close = close.dropna()
    if len(close) < 2:
        return 0.0, 0.0
    v = vol.reindex(close.index).fillna(0.0)
    ret = close.pct_change().fillna(0.0)
    dayflow = ret * v * close        # 美元
    f1 = float(dayflow.iloc[-1])
    f5 = float(dayflow.iloc[-5:].sum())
    return round(f1/1e6, 2), round(f5/1e6, 2)

def calc_rs_line_high(s: pd.Series, b: pd.Series, window: int = 252) -> bool:
    s, b = s.align(b, join="inner")
    s, b = s.dropna(), b.dropna()
    if len(s) < 63:
        return False
    rs_line = s / b
    w = min(window, len(rs_line))
    peak = float(rs_line.rolling(w).max().iloc[-1])
    return float(rs_line.iloc[-1]) >= peak * 0.999

def check_sepa(close: pd.Series) -> dict:
    n = len(close)
    d = dict(rs70=False, above_150ma=False, above_200ma=False,
             ma200_up=False, ma150_gt_200=False, near_52w_high=False)
    if n < 200:
        return d
    price  = float(close.iloc[-1])
    ma150  = float(close.rolling(150).mean().iloc[-1])
    ma200  = float(close.rolling(200).mean().iloc[-1])
    ma200_prev = float(close.rolling(200).mean().iloc[-22]) if n >= 222 else ma200
    high52 = float(close.rolling(min(252, n)).max().iloc[-1])
    d["above_150ma"]   = price > ma150
    d["above_200ma"]   = price > ma200
    d["ma200_up"]      = ma200 > ma200_prev
    d["ma150_gt_200"]  = ma150 > ma200
    d["near_52w_high"] = price >= high52 * 0.75
    return d

def raw_to_percentile(raws: list[float]) -> list[int]:
    arr = np.array(raws, dtype=float)
    return [int(round(np.sum(arr <= v) / len(arr) * 98 + 1)) for v in arr]


# ════════════════════════════════════════════════════════════════
#  Step 4：單一股票完整計算
# ════════════════════════════════════════════════════════════════
def process_stock(stock: dict, bench: pd.Series, verbose: bool = False) -> dict | None:
    df = download_ohlcv(stock["yf"])
    if df is None:
        if verbose:
            print(f"  ⚠  {stock['code']} 資料不足，跳過")
        return None

    close = df["Close"]
    rs_data = calc_rs_raw(close, bench)
    if rs_data is None:
        return None

    rs_high  = calc_rs_line_high(close, bench)
    sepa_det = check_sepa(close)
    flow1, flow5 = calc_flow(close, df["Volume"])

    mc = stock.get("mc") or 0.0
    if mc <= 0:
        mc = get_market_cap(stock["yf"])
    if mc >= CAP_LARGE:   cap = "大"
    elif mc >= CAP_MID:   cap = "中"
    elif mc > 0:          cap = "小"
    else:                 cap = "未知"

    time.sleep(SLEEP)

    return dict(
        code=stock["code"], name=stock["name"], sector=stock["sector"],
        group=stock.get("group", ""), cap=cap,
        rs_raw=rs_data["rs_raw"],
        q1=rs_data["q1"], q2=rs_data["q2"], q3=rs_data["q3"], q4=rs_data["q4"],
        c1=rs_data["c1"], c5=rs_data["c5"], c1m=rs_data["c1m"],
        flow1=flow1, flow5s=flow5,
        price=rs_data["price"], rsHigh=rs_high, sepa_detail=sepa_det,
    )


# ════════════════════════════════════════════════════════════════
#  Step 5：板塊 / 軟硬體 彙整（真實資金流）
# ════════════════════════════════════════════════════════════════
def _agg_group(items: list[dict], name: str) -> dict:
    rs_vals = [i["rs"] for i in items]
    return dict(
        name=name, count=len(items),
        avg_rs=round(float(np.mean(rs_vals)), 1),
        rs90_count=sum(1 for r in rs_vals if r >= 90),
        rs70_count=sum(1 for r in rs_vals if r >= 70),
        c1=round(float(np.mean([i["c1"] for i in items])), 2),
        c5=round(float(np.mean([i["c5"] for i in items])), 2),
        c1m=round(float(np.mean([i["c1m"] for i in items])), 2),
        flow=round(float(np.sum([i["flow1"] for i in items])), 1),    # 1日真實資金流（百萬$）
        flow5=round(float(np.sum([i["flow5s"] for i in items])), 1),  # 5日真實資金流（百萬$）
        weeks=[],
    )

def build_sectors(results: list[dict]) -> list[dict]:
    grp = defaultdict(list)
    for r in results:
        grp[r["sector"]].append(r)
    out = [_agg_group(items, sector) for sector, items in grp.items()]
    out.sort(key=lambda x: x["flow"], reverse=True)
    return out

def build_subsectors(results: list[dict]) -> list[dict]:
    """資訊科技 → 軟體/硬體 細分。"""
    grp = defaultdict(list)
    for r in results:
        if r["sector"] == "資訊科技" and r.get("group") in ("軟體", "硬體"):
            grp[r["group"]].append(r)
    out = [_agg_group(items, g) for g, items in grp.items()]
    out.sort(key=lambda x: x["flow"], reverse=True)
    return out


# ════════════════════════════════════════════════════════════════
#  主程式輔助
# ════════════════════════════════════════════════════════════════
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=WORKERS)
    p.add_argument("--output", type=str, default=OUTPUT_FILE)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--backfill", action="store_true")
    p.add_argument("--backfill-days", type=int, default=180)
    p.add_argument("--limit", type=int, default=0)
    return p.parse_args()

def load_benchmark() -> pd.Series:
    print(f"\n▶ [1/4] 下載基準指數 {BENCHMARK}（S&P 500）...")
    df = download_ohlcv(BENCHMARK)
    if df is None:
        print("  ❌ 無法下載 S&P 500 指數，中止")
        sys.exit(1)
    print(f"  ✓ {len(df)} 筆交易日資料")
    return df["Close"]

def run_parallel(stocks, bench, workers, verbose):
    print(f"\n▶ [3/4] 計算 RS（{len(stocks)} 檔 × {workers} 執行緒）...")
    print(f"  預估時間：約 {int(len(stocks) * SLEEP / workers / 60) + 2} 分鐘\n")
    raw_results, done, failed = [], 0, 0
    start = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(process_stock, s, bench, verbose): s for s in stocks}
        for fut in as_completed(futures):
            done += 1
            r = fut.result()
            if r: raw_results.append(r)
            else: failed += 1
            pct = done / len(stocks) * 100
            bar = "█" * int(pct/5) + "░" * (20 - int(pct/5))
            elapsed = time.time() - start
            eta = elapsed / done * (len(stocks) - done) if done else 0
            print(f"  [{bar}] {pct:4.0f}%  {done}/{len(stocks)}  成功:{len(raw_results)}  "
                  f"失敗:{failed}  ETA:{int(eta//60)}:{int(eta%60):02d}", end="\r", flush=True)
    print(f"\n\n  ✓ 完成，耗時 {int((time.time()-start)//60)}分{int((time.time()-start)%60)}秒")
    return raw_results

def finalize_results(raw_results):
    pcts = raw_to_percentile([r["rs_raw"] for r in raw_results])
    final = []
    for r, rs in zip(raw_results, pcts):
        r["rs"] = rs
        r["sepa_detail"]["rs70"] = rs >= 70
        other = [v for k, v in r["sepa_detail"].items() if k != "rs70"]
        r["sepa"] = r["sepa_detail"]["rs70"] and sum(other) >= 4
        final.append(r)
    final.sort(key=lambda x: x["rs"], reverse=True)
    return final

def write_output(final, sectors, subsectors, now, output_path):
    rs90 = sum(1 for r in final if r["rs"] >= 90)
    rs70 = sum(1 for r in final if r["rs"] >= 70)
    sepa_n = sum(1 for r in final if r["sepa"])
    high_n = sum(1 for r in final if r["rsHigh"])
    top = final[0] if final else {}
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output = dict(
        updated_at=now.strftime("%Y-%m-%d %H:%M"),
        total=len(final),
        summary=dict(rs90=rs90, rs70=rs70, sepa=sepa_n, rs_line_high=high_n),
        stocks=final, sectors=sectors, subsectors=subsectors,
    )
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))
    size_kb = os.path.getsize(output_path) / 1024
    print(f"""
  ╔══════════════════════════════════════╗
  ║        計算完成 ✅                   ║
  ╠══════════════════════════════════════╣
  ║  計算總數  ：{len(final):<5} 檔               ║
  ║  RS ≥ 90  ：{rs90:<5} 檔               ║
  ║  RS ≥ 70  ：{rs70:<5} 檔               ║
  ║  SEPA 入選：{sepa_n:<5} 檔               ║
  ║  🏆 最強  ：{top.get('code','')} {top.get('name','')[:8]:<8} RS {top.get('rs','')}   ║
  ║  檔案大小 ：{size_kb:.0f} KB                     ║
  ╚══════════════════════════════════════╝
""")

def save_history(final, now):
    today = now.strftime("%Y-%m-%d")
    history = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = {}
    for s in final:
        if s["rs"] < HISTORY_MIN_RS:
            continue
        code = s["code"]
        entries = history.setdefault(code, [])
        if entries and entries[-1]["date"] == today:
            entries[-1]["rs"] = s["rs"]
        else:
            entries.append({"date": today, "rs": s["rs"]})
        history[code] = entries[-HISTORY_DAYS:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  ✓ 歷史記錄已更新（{len(history)} 支）")

def backfill_history(bench, stock_list, days=180):
    print(f"\n▶ 歷史 RS 回填（過去 {days} 交易日）...")
    all_closes = {}
    for stock in stock_list:
        with _cache_lock:
            df = _price_cache.get(stock["yf"])
        if df is not None:
            all_closes[stock["code"]] = df["Close"]
    print(f"  快取命中：{len(all_closes)} 支")
    trade_dates = bench.index[-days:]
    history = {}
    for i, dt in enumerate(trade_dates):
        b_slice = bench.loc[:dt]
        if len(b_slice) < MIN_DAYS:
            continue
        raw_list = []
        for code, close in all_closes.items():
            rs_data = calc_rs_raw(close.loc[:dt], b_slice)
            if rs_data is not None:
                raw_list.append((code, rs_data["rs_raw"]))
        if not raw_list:
            continue
        codes = [x[0] for x in raw_list]
        pcts = raw_to_percentile([x[1] for x in raw_list])
        ds = dt.strftime("%Y-%m-%d")
        for code, rs in zip(codes, pcts):
            if rs >= HISTORY_MIN_RS:
                history.setdefault(code, []).append({"date": ds, "rs": rs})
        if (i + 1) % 20 == 0 or i == len(trade_dates) - 1:
            print(f"  {i+1}/{len(trade_dates)} 日完成")
    for code in history:
        history[code].sort(key=lambda x: x["date"])
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  ✓ 回填完成：{len(history)} 支 × {days} 天")


def main():
    args = parse_args()
    now = datetime.now(US_TZ)
    print("=" * 62)
    print("  美股 RS Ranking 計算器（S&P 500 + Nasdaq-100 + NASDAQ 擴充）")
    print(f"  {now.strftime('%Y-%m-%d %H:%M')} (美東時間)")
    print("=" * 62)

    print("\n▶ [0/4] 載入快取...")
    load_price_cache()
    bench = load_benchmark()

    print("\n▶ [2/4] 抓取成分股清單...")
    stocks = fetch_universe()
    if args.limit:
        stocks = stocks[:args.limit]
        print(f"  ⚠ 測試模式：只計算前 {len(stocks)} 檔")

    raw_results = run_parallel(stocks, bench, args.workers, args.verbose)
    save_price_cache()
    print(f"  ✓ 快取已儲存：{len(_price_cache)} 支")

    if not raw_results:
        print("  ❌ 沒有任何成功結果，中止")
        sys.exit(1)

    print("\n▶ [4/4] 換算百分位、判定 SEPA、彙整資金流...")
    final = finalize_results(raw_results)
    sectors = build_sectors(final)
    subsectors = build_subsectors(final)
    need_backfill = args.backfill or not os.path.exists(HISTORY_FILE)
    write_output(final, sectors, subsectors, now, args.output)
    save_history(final, now)
    if need_backfill:
        backfill_history(bench, stocks, args.backfill_days)


if __name__ == "__main__":
    main()
