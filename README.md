# 📈 美股全市場 RS Ranking（S&P 500 + Nasdaq-100）

每天美股收盤後自動計算 Minervini RS Score，結果部署至 GitHub Pages，手機電腦隨時可看。
本專案改寫自台股版 [Taiwan-RS-ranking](https://github.com/martin81213/Taiwan-RS-ranking)，標的換成美股、基準指數換成 S&P 500。

---

## 📁 專案結構

```
us-rs-ranking/
├── .github/
│   └── workflows/
│       └── daily_rs.yml       ← GitHub Actions 自動排程
├── docs/
│   ├── index.html             ← 前端介面（GitHub Pages 服務這個）
│   ├── style.css              ← 樣式
│   ├── app.js                 ← 前端邏輯（含示意資料 fallback）
│   └── rs_data.json           ← 每日自動更新的計算結果（首次部署後產生）
├── rs_calculator.py           ← RS 計算主程式
├── requirements.txt
├── .gitignore
└── README.md
```

> 說明：`docs/` 內若還沒有 `rs_data.json`，前端會自動顯示**示意資料**（標的為真實美股名稱、數值為示意值），並在右上角標示「請執行 rs_calculator.py」。等 Actions 跑完產生真實 `rs_data.json` 後，就會自動切換成即時資料。

---

## 🚀 三步驟上線

### 步驟一：建立 GitHub Repository
1. 登入 [github.com](https://github.com) → 右上角 **+** → **New repository**
2. Repository name：`us-rs-ranking`（可自訂）
3. 選 **Public**（GitHub Pages 免費方案需公開）
4. 點 **Create repository**

### 步驟二：上傳所有檔案
```bash
cd us-rs-ranking
git init
git branch -M main
git remote add origin https://github.com/你的帳號/us-rs-ranking.git
git add .
git commit -m "初始化美股 RS Ranking 系統"
git push -u origin main
```

### 步驟三：開啟 GitHub Pages + Actions

**確認 Actions 權限：**
1. 進入 repo → **Settings** → **Actions** → **General**
2. 滾到底部 **Workflow permissions** → 選 **Read and write permissions** → **Save**

**手動觸發第一次計算（產生 `docs/rs_data.json`）：**
1. 進入 repo → **Actions** → **每日美股 RS 排行自動更新**
2. 右側 **Run workflow** → **Run workflow**
3. 等待約 5–10 分鐘（首次需建立快取，會久一點）

**開啟 GitHub Pages：**
1. 進入 repo → **Settings** → 左側 **Pages**
2. Source 選 **Deploy from a branch**
3. Branch 選 **main** → 資料夾選 **/docs** → **Save**

完成後網址就是：
```
https://你的帳號.github.io/us-rs-ranking/
```

---

## ⏰ 自動排程時間

| 觸發時間 | 說明 |
| --- | --- |
| 週一~週五 21:30 UTC | 美股收盤後自動計算（≈ 美東 17:30 EDT / 16:30 EST） |
| 手動觸發 | Actions 頁面 → Run workflow |

> 美國有日光節約時間，收盤對應的 UTC 會在 20:00 / 21:00 間切換。排程設在 21:30 UTC，兩種時區下都在收盤之後，不影響結果。

---

## 📊 RS Score 公式（Minervini）

```
RS Score = Q1×50% + Q2×25% + Q3×15% + Q4×10%
```

| 季度 | 說明 | 權重 |
| --- | --- | --- |
| Q1 | 近 3 個月相對漲幅 | 50% |
| Q2 | 前 4–6 個月 | 25% |
| Q3 | 前 7–9 個月 | 15% |
| Q4 | 前 10–12 個月 | 10% |

最終分數為全市場百分位排名（1–99），**RS≥70** 才值得關注。

### SEPA 技術面條件
RS≥70 且符合至少 4 項：站上 150MA、站上 200MA、200MA 向上、150MA>200MA、靠近 52 週高點。

### 市值分級（美元）
| 分級 | 門檻 |
| --- | --- |
| 大型 | 市值 ≥ $100 億（$10B） |
| 中型 | $20 億 – $100 億 |
| 小型 | < $20 億 |

---

## 🖥️ 本地預覽

```bash
cd docs
python -m http.server 8000
# 瀏覽器開 http://localhost:8000
```
若 `docs/` 內沒有 `rs_data.json`，會顯示示意資料；要看真實資料，先在專案根目錄跑：
```bash
pip install -r requirements.txt
python rs_calculator.py            # 完整 S&P500 + Nasdaq100
python rs_calculator.py --limit 50 # 只算前 50 檔（快速測試）
```

---

## ❓ 常見問題

**Q：Actions 執行失敗？** → 進 Actions 頁面看 log，最常見是 yfinance rate limit，重新手動觸發即可（有快取會快很多）。

**Q：想換股票池？** → 編輯 `rs_calculator.py` 的 `fetch_universe()`。目前抓 S&P 500 + Nasdaq-100；可只留其一，或加入其他維基百科成分股清單（如 Russell 1000）。

**Q：市值怎麼來的？** → 用 yfinance `fast_info` 取得即時市值，再依門檻分大/中/小。

**Q：股票代號含點（如 BRK.B）？** → 程式會自動轉成 yfinance 格式（BRK-B）。

---

> ⚠️ 本工具僅供學習研究，非投資建議。RS Score 基於公開市場資料計算，不保證準確性。
