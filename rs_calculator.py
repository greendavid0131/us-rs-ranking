#!/usr/bin/env python3
"""
美股全市場 Minervini RS 計算器（S&P 500 + Nasdaq-100）
====================================================
自動抓取 S&P 500 與 Nasdaq-100 成分股清單
計算 RS Score、RS Line、SEPA 條件
輸出 docs/rs_data.json（供 GitHub Pages 使用）

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
BENCHMARK   = "^GSPC"   # S&P 500 指數
WORKERS     = 10        # 並行執行緒
MIN_DAYS    = 252       # 最少交易日（約 1 年）
SLEEP       = 0.10      # 每次下載後等待秒數（降低 rate-limit 風險）
OUTPUT_DIR  = "docs"    # GitHub Pages 預設目錄
OUTPUT_FILE   = f"{OUTPUT_DIR}/rs_data.json"
HISTORY_FILE  = f"{OUTPUT_DIR}/rs_history.json"
CACHE_FILE    = "price_cache.pkl"   # 收盤價快取（不入 git）
HISTORY_DAYS  = 180   # 保留最近幾天
HISTORY_MIN_RS = 50   # 只記錄 RS >= 50 的股票

# 市值分級門檻（美元）
CAP_LARGE = 10e9      # 大型股 ≥ $100 億（$10B）
CAP_MID   = 2e9       # 中型股 ≥ $20  億（$2B）

# GICS 英文板塊 → 中文顯示名稱（共 11 大類股）
GICS_MAP = {
    "Information Technology": "資訊科技",
    "Health Care":           "醫療保健",
    "Financials":            "金融",
    "Consumer Discretionary":"非必需消費",
    "Communication Services":"通訊服務",
    "Industrials":           "工業",
    "Consumer Staples":      "必需消費",
    "Energy":                "能源",
    "Utilities":             "公用事業",
    "Real Estate":           "房地產",
    "Materials":             "原物料",
}

# ── 收盤價快取 ────────────────────────────────────────────────
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
#  Step 1：抓取 S&P 500 + Nasdaq-100 成分股清單
# ════════════════════════════════════════════════════════════════
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RS-Ranking/1.0)"}

# 萬一所有線上來源都失敗時的最小備援清單（大型權值股）
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

# Nasdaq-100 中常見、但不在 S&P 500 的成分股（多為外國企業）
NASDAQ100_EXTRA = [
    ("ASML","ASML Holding","資訊科技"), ("AZN","AstraZeneca","醫療保健"),
    ("ARM","Arm Holdings","資訊科技"),  ("PDD","PDD Holdings","非必需消費"),
    ("MELI","MercadoLibre","非必需消費"),("GFS","GlobalFoundries","資訊科技"),
    ("TEAM","Atlassian","資訊科技"),    ("MDB","MongoDB","資訊科技"),
]

# S&P 500 成分股 CSV（穩定、不易被擋；raw.githubusercontent 在 Actions 上可靠）
SP500_CSV_URLS = [
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv",
]

def fetch_sp500_csv() -> dict:
    """主來源：從 GitHub 上的 S&P 500 CSV 取清單。回傳 {ticker:(name,sector_zh)}"""
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
                sec = (row.get("GICS Sector") or row.get("Sector") or "").strip()
                if sym:
                    out[sym] = (name, GICS_MAP.get(sec, "其他"))
            if len(out) >= 100:
                print(f"  ✓ S&P 500（CSV）：{len(out)} 檔")
                return out
        except Exception as e:
            print(f"  ⚠ S&P 500 CSV 失敗：{e}")
    return {}

def _read_wiki_tables(url: str):
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return pd.read_html(resp.text)

def fetch_sp500() -> dict:
    """備援來源：維基百科 S&P 500。回傳 {ticker:(name,sector_zh)}"""
    out = {}
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        tables = _read_wiki_tables(url)
        df = tables[0]
        for _, row in df.iterrows():
            sym = str(row.get("Symbol", "")).strip().upper()
            name = str(row.get("Security", "")).strip()
            sec = str(row.get("GICS Sector", "")).strip()
            if not sym:
                continue
            out[sym] = (name, GICS_MAP.get(sec, "其他"))
        print(f"  ✓ S&P 500（維基）：{len(out)} 檔")
    except Exception as e:
        print(f"  ⚠ S&P 500 維基抓取失敗：{e}")
    return out

def fetch_nasdaq100() -> dict:
    """Nasdaq-100：維基百科。回傳 {ticker:(name,sector_zh)}"""
    out = {}
    try:
        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        tables = _read_wiki_tables(url)
        target = None
        for df in tables:
            cols = [str(c) for c in df.columns]
            if any("Ticker" in c or "Symbol" in c for c in cols) and \
               any("Compan" in c or "Securit" in c for c in cols):
                target = df
                break
        if target is not None:
            cols = {str(c): c for c in target.columns}
            tcol = next((cols[c] for c in cols if "Ticker" in c or "Symbol" in c), None)
            ncol = next((cols[c] for c in cols if "Compan" in c or "Securit" in c), None)
            scol = next((cols[c] for c in cols if "GICS Sector" in c or c == "Sector"), None)
            for _, row in target.iterrows():
                sym = str(row[tcol]).strip().upper()
                name = str(row[ncol]).strip() if ncol else sym
                sec = str(row[scol]).strip() if scol else ""
                if not sym or sym == "NAN":
                    continue
                out[sym] = (name, GICS_MAP.get(sec, "其他"))
        print(f"  ✓ Nasdaq-100（維基）：{len(out)} 檔")
    except Exception as e:
        print(f"  ⚠ Nasdaq-100 維基抓取失敗：{e}")
    return out

def fetch_universe() -> list[dict]:
    # 1) S&P 500：CSV 主來源，失敗才退維基百科
    merged = fetch_sp500_csv()
    if len(merged) < 100:
        wiki = fetch_sp500()
        for sym, val in wiki.items():
            merged.setdefault(sym, val)

    # 2) Nasdaq-100：維基百科（有就補，沒有也沒關係）
    for sym, val in fetch_nasdaq100().items():
        if sym not in merged:
            merged[sym] = val
        elif merged[sym][1] == "其他" and val[1] != "其他":
            merged[sym] = val

    # 3) 補上 Nasdaq-100 非 S&P 成分股
    for t, n, s in NASDAQ100_EXTRA:
        merged.setdefault(t, (n, s))

    # 4) 最後保險：清單太小才用備援
    if len(merged) < 50:
        print("  ⚠ 線上來源皆失敗，使用備援清單")
        for t, n, s in FALLBACK:
            merged.setdefault(t, (n, s))

    stocks = []
    for sym, (name, sector) in merged.items():
        # 維基百科/CSV 用 . 表示特別股（BRK.B），yfinance 用 -（BRK-B）
        yf_ticker = sym.replace(".", "-")
        stocks.append({"code": sym, "yf": yf_ticker, "name": name, "sector": sector})
    print(f"  ✓ 合併去重後共 {len(stocks)} 檔")
    return stocks


# ════════════════════════════════════════════════════════════════
#  Step 2：下載收盤價
# ════════════════════════════════════════════════════════════════
def _fetch_yf(ticker: str, period: str, timeout: int = 20) -> pd.Series | None:
    try:
        df = yf.download(ticker, period=period, auto_adjust=True,
                         progress=False, timeout=timeout)
        if df.empty:
            return None
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.squeeze()
        return close.dropna()
    except Exception:
        return None

def download_close(ticker: str, period: str = "580d") -> pd.Series | None:
    today = date.today()

    with _cache_lock:
        cached = _price_cache.get(ticker)

    if cached is not None:
        last_date = cached.index[-1].date()
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
        close = _fetch_yf(ticker, period=period)
        if close is not None and len(close) >= MIN_DAYS:
            with _cache_lock:
                _price_cache[ticker] = close
            return close
        if attempt == 0:
            time.sleep(1)
    return None

def get_market_cap(ticker: str) -> float:
    """取市值（美元）。用直接索引觸發 fast_info 的即時計算；失敗再以股數×股價備援。"""
    try:
        fi = yf.Ticker(ticker).fast_info
    except Exception:
        return 0.0
    # 1) 直接索引 market_cap（用 [] 才會即時計算，.get() 會回 None）
    for key in ("market_cap", "marketCap"):
        try:
            v = fi[key]
            if v:
                return float(v)
        except Exception:
            pass
    # 2) 備援：流通股數 × 最新股價
    try:
        sh, px = fi["shares"], fi["last_price"]
        if sh and px:
            return float(sh) * float(px)
    except Exception:
        pass
    return 0.0


# ════════════════════════════════════════════════════════════════
#  Step 3：核心計算（與台股版相同的 Minervini 邏輯）
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
        ei = min(end_idx, n-1)
        si = min(start_idx, n-1)
        return safe_pct(ser.iloc[ei], ser.iloc[si])

    q1s = qpct(s, -1, -63)
    q2s = qpct(s, -63, -126)
    q3s = qpct(s, -126, -189)
    q4s = qpct(s, -189, -252)

    raw = q1s*0.5 + q2s*0.25 + q3s*0.15 + q4s*0.10

    c1  = safe_pct(s.iloc[-1], s.iloc[-2])  if len(s) >= 2  else 0.0
    c5  = safe_pct(s.iloc[-1], s.iloc[-6])  if len(s) >= 6  else 0.0
    c1m = safe_pct(s.iloc[-1], s.iloc[-22]) if len(s) >= 22 else 0.0
    c3m = safe_pct(s.iloc[-1], s.iloc[-63]) if len(s) >= 63 else 0.0

    return dict(rs_raw=round(raw, 3),
                q1=round(q1s,2), q2=round(q2s,2),
                q3=round(q3s,2), q4=round(q4s,2),
                c1=round(c1,2),  c5=round(c5,2),
                c1m=round(c1m,2), c3m=round(c3m,2),
                price=round(float(s.iloc[-1]), 2))

def calc_rs_line_high(s: pd.Series, b: pd.Series, window: int = 252) -> bool:
    s, b = s.align(b, join="inner")
    s, b = s.dropna(), b.dropna()
    if len(s) < 63:
        return False
    rs_line = s / b
    w = min(window, len(rs_line))
    peak = float(rs_line.rolling(w).max().iloc[-1])
    cur  = float(rs_line.iloc[-1])
    return cur >= peak * 0.999

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
    w52    = min(252, n)
    high52 = float(close.rolling(w52).max().iloc[-1])
    d["above_150ma"]   = price > ma150
    d["above_200ma"]   = price > ma200
    d["ma200_up"]      = ma200 > ma200_prev
    d["ma150_gt_200"]  = ma150 > ma200
    d["near_52w_high"] = price >= high52 * 0.75
    return d

def raw_to_percentile(raws: list[float]) -> list[int]:
    arr = np.array(raws, dtype=float)
    result = []
    for v in arr:
        pct = np.sum(arr <= v) / len(arr) * 98 + 1
        result.append(int(round(pct)))
    return result


# ════════════════════════════════════════════════════════════════
#  Step 4：單一股票完整計算（供多執行緒呼叫）
# ════════════════════════════════════════════════════════════════
def process_stock(stock: dict, bench: pd.Series, verbose: bool = False) -> dict | None:
    yf_ticker = stock["yf"]

    close = download_close(yf_ticker)
    if close is None:
        if verbose:
            print(f"  ⚠  {stock['code']} 資料不足，跳過")
        return None

    rs_data = calc_rs_raw(close, bench)
    if rs_data is None:
        return None

    rs_high  = calc_rs_line_high(close, bench)
    sepa_det = check_sepa(close)

    mc = get_market_cap(yf_ticker)
    if mc >= CAP_LARGE:   cap = "大"
    elif mc >= CAP_MID:   cap = "中"
    elif mc > 0:          cap = "小"
    else:                 cap = "—"

    time.sleep(SLEEP)

    return dict(
        code    = stock["code"],
        name    = stock["name"],
        sector  = stock["sector"],
        cap     = cap,
        rs_raw  = rs_data["rs_raw"],
        q1=rs_data["q1"], q2=rs_data["q2"],
        q3=rs_data["q3"], q4=rs_data["q4"],
        c1=rs_data["c1"], c5=rs_data["c5"],
        c1m=rs_data["c1m"], c3m=rs_data["c3m"],
        price   = rs_data["price"],
        rsHigh  = rs_high,
        sepa_detail = sepa_det,
    )


# ════════════════════════════════════════════════════════════════
#  Step 5：板塊彙整
# ════════════════════════════════════════════════════════════════
def build_sectors(results: list[dict]) -> list[dict]:
    grp = defaultdict(list)
    for r in results:
        grp[r["sector"]].append(r)

    out = []
    for sector, items in grp.items():
        rs_vals = [i["rs"] for i in items]
        out.append(dict(
            name    = sector,
            count   = len(items),
            avg_rs  = round(float(np.mean(rs_vals)), 1),
            median_rs = round(float(np.median(rs_vals)), 1),
            rs90_count = sum(1 for r in rs_vals if r >= 90),
            rs70_count = sum(1 for r in rs_vals if r >= 70),
            c1      = round(float(np.mean([i["c1"]  for i in items])), 2),
            c5      = round(float(np.mean([i["c5"]  for i in items])), 2),
            c1m     = round(float(np.mean([i["c1m"] for i in items])), 2),
            flow    = round(float(np.mean(rs_vals)) * 1.1, 1),
            flow5   = round(float(np.mean([i["c5"] for i in items])) * 40, 1),
            weeks   = [],
        ))
    out.sort(key=lambda x: x["avg_rs"], reverse=True)
    return out


# ════════════════════════════════════════════════════════════════
#  主程式輔助函式
# ════════════════════════════════════════════════════════════════
def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers",       type=int,  default=WORKERS)
    parser.add_argument("--output",        type=str,  default=OUTPUT_FILE)
    parser.add_argument("--verbose",       action="store_true")
    parser.add_argument("--backfill",      action="store_true", help="強制回填歷史 RS")
    parser.add_argument("--backfill-days", type=int,  default=180, help="回填天數")
    parser.add_argument("--limit",         type=int,  default=0, help="只計算前 N 檔（測試用）")
    return parser.parse_args()


def load_benchmark() -> pd.Series:
    print(f"\n▶ [1/4] 下載基準指數 {BENCHMARK}（S&P 500）...")
    bench = download_close(BENCHMARK)
    if bench is None:
        print("  ❌ 無法下載 S&P 500 指數，中止")
        sys.exit(1)
    print(f"  ✓ {len(bench)} 筆交易日資料")
    return bench


def run_parallel(stocks: list[dict], bench: pd.Series,
                 workers: int, verbose: bool) -> list[dict]:
    print(f"\n▶ [3/4] 計算 RS（{len(stocks)} 檔 × {workers} 執行緒）...")
    print(f"  預估時間：約 {int(len(stocks) * SLEEP / workers / 60) + 2} 分鐘\n")

    raw_results = []
    done = failed = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(process_stock, s, bench, verbose): s
            for s in stocks
        }
        for future in as_completed(futures):
            done += 1
            result = future.result()
            if result:
                raw_results.append(result)
            else:
                failed += 1

            pct     = done / len(stocks) * 100
            bar     = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            elapsed = time.time() - start_time
            eta     = elapsed / done * (len(stocks) - done) if done > 0 else 0
            print(f"  [{bar}] {pct:4.0f}%  {done}/{len(stocks)}  "
                  f"成功:{len(raw_results)}  失敗:{failed}  "
                  f"ETA:{int(eta//60)}:{int(eta%60):02d}",
                  end="\r", flush=True)

    elapsed_total = time.time() - start_time
    print(f"\n\n  ✓ 完成，耗時 {int(elapsed_total//60)}分{int(elapsed_total%60)}秒")
    return raw_results


def finalize_results(raw_results: list[dict]) -> list[dict]:
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


def write_output(final: list[dict], sectors: list[dict],
                 now: datetime, output_path: str):
    rs90   = sum(1 for r in final if r["rs"] >= 90)
    rs70   = sum(1 for r in final if r["rs"] >= 70)
    sepa_n = sum(1 for r in final if r["sepa"])
    high_n = sum(1 for r in final if r["rsHigh"])
    top    = final[0] if final else {}

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output = dict(
        updated_at = now.strftime("%Y-%m-%d %H:%M"),
        total      = len(final),
        summary    = dict(rs90=rs90, rs70=rs70, sepa=sepa_n, rs_line_high=high_n),
        stocks     = final,
        sectors    = sectors,
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
  ║  RS線新高 ：{high_n:<5} 檔               ║
  ║  🏆 最強  ：{top.get('code','')} {top.get('name','')[:8]:<8} RS {top.get('rs','')}   ║
  ║  輸出檔案 ：{output_path:<28} ║
  ║  檔案大小 ：{size_kb:.0f} KB                     ║
  ╚══════════════════════════════════════╝
""")


def save_history(final: list[dict], now: datetime):
    today = now.strftime("%Y-%m-%d")
    history: dict = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = {}

    for s in final:
        if s["rs"] < HISTORY_MIN_RS:
            continue
        code = s["code"]
        if code not in history:
            history[code] = []
        entries = history[code]
        if entries and entries[-1]["date"] == today:
            entries[-1]["rs"] = s["rs"]
        else:
            entries.append({"date": today, "rs": s["rs"]})
        history[code] = entries[-HISTORY_DAYS:]

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  ✓ 歷史記錄已更新：{HISTORY_FILE}（{len(history)} 支股票）")


def backfill_history(bench: pd.Series, stock_list: list[dict], days: int = 180):
    print(f"\n▶ 歷史 RS 回填（過去 {days} 個交易日）...")
    all_closes: dict[str, pd.Series] = {}
    for stock in stock_list:
        with _cache_lock:
            if stock["yf"] in _price_cache:
                all_closes[stock["code"]] = _price_cache[stock["yf"]]

    print(f"  快取命中：{len(all_closes)} 支股票")
    trade_dates = bench.index[-days:]
    history: dict = {}

    for i, dt in enumerate(trade_dates):
        date_str = dt.strftime("%Y-%m-%d")
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
        pcts  = raw_to_percentile([x[1] for x in raw_list])
        for code, rs in zip(codes, pcts):
            if rs < HISTORY_MIN_RS:
                continue
            history.setdefault(code, []).append({"date": date_str, "rs": rs})
        if (i + 1) % 20 == 0 or i == len(trade_dates) - 1:
            print(f"  {i + 1}/{len(trade_dates)} 日完成")

    for code in history:
        history[code].sort(key=lambda x: x["date"])
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, separators=(",", ":"))
    size_kb = os.path.getsize(HISTORY_FILE) / 1024
    print(f"  ✓ 回填完成：{len(history)} 支股票 × {days} 天 → {HISTORY_FILE} ({size_kb:.0f} KB)")


# ════════════════════════════════════════════════════════════════
#  主程式
# ════════════════════════════════════════════════════════════════
def main():
    args = parse_args()
    now  = datetime.now(US_TZ)

    print("=" * 62)
    print("  美股 RS Ranking 計算器（S&P 500 + Nasdaq-100）")
    print(f"  {now.strftime('%Y-%m-%d %H:%M')} (美東時間)")
    print("=" * 62)

    print(f"\n▶ [0/4] 載入收盤價快取...")
    load_price_cache()

    bench  = load_benchmark()

    print(f"\n▶ [2/4] 抓取成分股清單...")
    stocks = fetch_universe()
    if args.limit:
        stocks = stocks[:args.limit]
        print(f"  ⚠ 測試模式：只計算前 {len(stocks)} 檔")

    raw_results = run_parallel(stocks, bench, args.workers, args.verbose)

    save_price_cache()
    print(f"  ✓ 快取已儲存：{len(_price_cache)} 支股票")

    if not raw_results:
        print("  ❌ 沒有任何成功結果，中止")
        sys.exit(1)

    print(f"\n▶ [4/4] 換算百分位、判定 SEPA...")
    final   = finalize_results(raw_results)
    sectors = build_sectors(final)
    need_backfill = args.backfill or not os.path.exists(HISTORY_FILE)
    write_output(final, sectors, now, args.output)
    save_history(final, now)
    if need_backfill:
        backfill_history(bench, stocks, args.backfill_days)


if __name__ == "__main__":
    main()
