# IfBuy

个人网页**模拟交易台**：真实行情 + K 线，本地假钱买卖。  
支持 **A 股 / 港股 / 美股 / 场外基金 / 期货商品 / 加密货币 / 黄金 ETF / 自定义资产（如房产）**，无券商、无实盘通道。

一个账本可同时持有 **人民币 + 美元** 现金，买卖扣对应币种，账本内可换汇。

---

## 能做什么

| 模块 | 能力 |
|------|------|
| **账本** | 多账本切换、多币种现金、出入金、换汇、总权益 / 总收益、资产曲线、持仓、流水 |
| **行情** | A股 / 港股 / 美股 / 基金 / 期货 / 加密 / 黄金 / 自定义（房产等） |
| **公司行动** | 手动登记分红入账、拆股调仓 |
| **风险提示** | 现金占比、最大回撤、单票集中度、浮亏告警 |
| **交易** | 日 K / 周 K、现价刷新、模拟买卖、手填价兜底、买卖点标注 |
| **费率** | A股 / 美股 / 基金 / 黄金（国内·美股）分市场规则，见设置页 |
| **数据** | 设置页导出 JSON 备份 |

---

## 技术栈

- **前端**：React + Vite + TanStack Query + Lightweight Charts  
- **后端**：FastAPI + SQLite + SQLAlchemy  
- **行情**：AKShare（A 股 / 场外基金净值 / 国内黄金 ETF）、yfinance（美股 / GLD 等）

```
IfBuy/
├── apps/web/          # 前端
├── apps/api/          # 后端 API + 静态托管
├── data/              # SQLite（默认 ifbuy.db）
├── scripts/           # 本地一键部署
├── PRD.md
└── TECH_DESIGN.md
```

---

## 快速开始（开发）

### 前置

- Python 3.10+（建议用 [uv](https://github.com/astral-sh/uv)）
- Node.js + pnpm

### 1. 启动 API（:8000）

```powershell
cd apps/api
uv venv .venv
.\.venv\Scripts\activate
uv pip install -e ".[dev]"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

数据库默认：`data/ifbuy.db`（仓库根目录下）。

### 2. 启动 Web（:5173）

```powershell
cd apps/web
pnpm install
pnpm dev
```

打开 http://127.0.0.1:5173  
开发服务器已将 `/api` 代理到 `http://127.0.0.1:8000`。

---

## 本地一体部署（推荐体验）

构建前端并由 FastAPI 同进程提供 API + 静态页：

```powershell
.\scripts\deploy-local.ps1
```

访问 **http://127.0.0.1:8080**

如有 Docker：

```powershell
docker compose up --build
```

同样映射 `127.0.0.1:8080`。

---

## 环境变量（可选）

| 变量 | 说明 |
|------|------|
| `IFBUY_DB` | SQLite 路径（默认仓库 `data/ifbuy.db`） |
| `IFBUY_TOKEN` | 若设置，则 `/api/*`（除 health）需 `Authorization: Bearer <token>` |
| `IFBUY_TUSHARE_TOKEN` | 预留；当前主路径为 AKShare / yfinance |
| `IFBUY_CORS_ORIGINS` | CORS 来源列表 |

---

## 常用脚本

```powershell
# 写入演示成交 / 持仓 / K 线（开发用）
cd apps/api
.\.venv\Scripts\python.exe scripts\seed_demo_trades.py

# 后端单测
cd apps/api
.\.venv\Scripts\pytest.exe
```

---

## 使用提示

1. 打开 **账本** → 新建账本（分别填人民币 / 美元本金）  
2. **行情** 搜标的 → 进交易页模拟买卖  
3. 美股扣美元、A 股扣人民币；不够可在账本页 **换汇** 或 **出入金**  
4. Yahoo / AKShare 可能限流；失败时可能用本地 K 线收盘价兜底（会标过期）

---

## 文档

- [PRD.md](./PRD.md) — 产品需求  
- [TECH_DESIGN.md](./TECH_DESIGN.md) — 技术方案  

---

## 非目标（当前不做）

实盘下单、券商对接、限价单 / Level-2、「如果当时买了」历史回溯、场外基金、港股 / 期权 / 期货、多人 SaaS。
