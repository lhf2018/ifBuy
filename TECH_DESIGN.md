# IfBuy 技术方案设计

| 属性 | 内容 |
|------|------|
| 对应 PRD | v1.6 |
| 文档版本 | v1.1 |
| 状态 | Draft |
| 更新日期 | 2026-11-07 |

---

## 1. 目标与约束

### 1.1 目标

落地一套**本地 / 自托管**的个人模拟交易站：

- 真实行情 + K 线交易页（A 股 / 美股 / 可选黄金标的）
- **本地模拟成交**，无券商实盘通道
- **一个账本多币种现金**，账本内可手动换汇（不自动）
- 持仓盈亏、流水备注、数据导出/导入

### 1.2 非目标（与 PRD 对齐）

- 历史回溯下单、实盘、基金（延后）、港股/期权/期货、多租户 SaaS、Level-2

### 1.3 关键设计决策（已拍板）

| 决策 | 选择 | 理由 |
|------|------|------|
| 账本币种 | **1 Account = 多币种钱包** | 现金按币种分桶；买卖扣标的币种；总权益按 base 折算 |
| 成交 | 本地立即全成（市价/确认价） | MVP 简单可信 |
| 行情 | Provider 插件化 + 本地缓存 | 多市场、可换源、可降级手填 |
| 图表 | Lightweight Charts | 专为金融 K 线、体积小 |
| 存储 | SQLite | 单人零运维 |
| 后端 | **FastAPI (Python)** | AKShare/Tushare 生态更顺；若团队更熟 Node 可对等替换，接口契约不变 |

> 若坚持全 TS 栈：后端可用 NestJS/Fastify，A 股行情通过子进程调 Python 或 HTTP 微适配器；下文 API 与表结构仍适用。

---

## 2. 总体架构

```
┌──────────────────────────────────────────────────────────┐
│  Web (React + Vite + TS)                                 │
│  首页 / 关注 / 交易页(K线) / 持仓 / 流水 / 复盘 / 设置     │
└───────────────────────────┬──────────────────────────────┘
                            │ REST
┌───────────────────────────▼──────────────────────────────┐
│  API (FastAPI)                                           │
│  accounts · instruments · quotes · bars · orders         │
│  positions · watchlist · notes · export · import         │
├──────────────┬────────────────────┬──────────────────────┤
│ Trading      │ Market Data        │ Portfolio            │
│ Engine       │ Gateway            │ Service              │
│ (撮合/费用/  │ (Provider 路由、   │ (持仓均价、浮动、     │
│  币种校验)   │  缓存、限流)       │  资产快照)           │
└──────┬───────┴─────────┬──────────┴──────────┬───────────┘
       │                 │                     │
       ▼                 ▼                     ▼
   SQLite (业务)    SQLite/文件 (bars 缓存)   外部行情 API
                                              (无交易 API)
```

**硬约束：** 代码库中不存在 `BrokerOrder` / 券商下单客户端；CI 可扫依赖黑名单（可选）。

---

## 3. 技术栈与仓库结构

### 3.1 推荐栈

| 层 | 选型 |
|----|------|
| 前端 | React 18+、TypeScript、Vite、React Router、TanStack Query |
| UI | 自研轻量样式即可；避免重型后台模板感 |
| K 线 | `lightweight-charts` |
| 后端 | Python 3.11+、FastAPI、Pydantic v2、SQLAlchemy 2 / SQLModel、Alembic（迁移） |
| DB | SQLite + WAL |
| 包管理 | 前端 pnpm；后端 uv 或 poetry |
| 部署 | `docker compose`：`web` + `api` + volume `./data` |

### 3.2 目录建议

```
IfBuy/
  apps/
    web/                 # React
    api/                 # FastAPI
  packages/              # 可选：共享类型 / OpenAPI client
  data/                  # gitignore：sqlite、导出
  PRD.md
  TECH_DESIGN.md
  docker-compose.yml
```

---

## 4. 核心领域模块

### 4.1 币种与账本（Account）

**规则：**

1. 创建账本时选定 `base_currency` ∈ {`CNY`, `USD`}（汇总展示 / 收益率折算基准），并分别注入 CNY / USD 开户本金（至少一种 > 0）。
2. 现金存在 `wallet_balances(account_id, currency)`；买卖只增减标的 `instrument.currency` 对应钱包。
3. **不做自动换汇**；用户通过 `POST /accounts/{id}/fx` 手动换汇（可跟参考汇率或手填）。
4. 首页展示各币种现金；`total_equity` / `return_pct` 按 `base_currency` 折算；**禁止**跨账本汇总。
5. 开户本金按币种各写 `cash_flows(type=initial, currency=…)`；净入金只计 initial/deposit/withdraw（忽略 fx_in/fx_out），再折算到 base。

**可交易矩阵（MVP）：**

| 钱包币种 | 可交易 |
|----------|--------|
| CNY | A 股、人民币计价黄金相关（如国内黄金 ETF） |
| USD | 美股、美元计价黄金相关（如 GLD） |

### 4.2 Trading Engine（模拟撮合）

输入：`account_id`, `client_order_id`（幂等）, `symbol`, `side`, `qty`, 可选 `manual_price`, `expected_price`, `note`, `emotion_tag`

流程：

```
1. BEGIN IMMEDIATE 事务（SQLite 单写者，见 §5.3）
2. 幂等：orders UK(account_id, client_order_id)；重复则直接返回原回执
3. 加载 instrument → 校验存在、currency 一致、qty 满足 lot_size（A 股整手；卖出全部持仓可零股；美股可小数）
4. 定价：
   - 若传 manual_price → 校验 0<price 且为 tick_size 整数倍（A 股 0.01）；超出最近 api 价 10× 需二次确认 → source=manual
   - 否则取 QuoteGateway.latest(symbol) → source=api
   - 无价 → 400 QUOTE_UNAVAILABLE「暂无行情，请手填价格」
5. 价格漂移：若传 expected_price 且 |fill - expected|/expected > 0.5%（可配）→ 返回 PRICE_MOVED（当前价 + 偏差），前端二次确认后再提交
6. 计算费用（FeeRule by market + instrument_type + 买卖侧）
7. buy：cash >= notional+fee；扣现金；更新/创建 position（移动加权含费）
8. sell：qty <= position.qty；增现金；结算已实现；减仓或删仓
9. 写 order(status=filled) + trade + cash_ledger（资金变动）+ 可选 note
10. COMMIT；返回成交回执（含 fill_price、price_source、fee 明细）
```

**不做：** 部分成交、撤单队列（限价为 V1）、实盘报送、滑点（MVP 成交价即确认价/最新价）。

### 4.3 Market Data Gateway

```python
class MarketDataProvider(Protocol):
    def search(self, keyword: str) -> list[InstrumentDraft]: ...
    def get_quote(self, symbol: str) -> Quote: ...
    def get_bars(self, symbol: str, interval: str, adjust: str, limit: int) -> list[Bar]: ...
```

> 所有 provider 调用走**线程池 / 普通 `def` 路由**并带 3～5s 超时（AKShare/yfinance 是同步阻塞 HTTP，塞进 `async def` 会卡死事件循环）。

**路由：**

| instrument_type / market | Provider（建议） |
|--------------------------|------------------|
| equity·etf / CN | AkshareProvider 或 TushareProvider |
| equity / US | YahooProvider（yfinance 等） |
| etf / US（黄金 ETF） | YahooProvider |
| spot（金价符号，V1） | 另接报价源（MetalProvider） |

**复权口径（必须显式传参）：** AKShare 日 K 默认前复权、yfinance 默认 `auto_adjust=True`。Provider 实现必须强制 `adjust`（`none` 时传 `qfq=false` / `auto_adjust=False`），并写入 `bars.adjust`；同一 `symbol+interval+ts+adjust` 是独立记录，禁止混口径。

**缓存策略：**

| 数据 | TTL | 存储 |
|------|-----|------|
| Quote | 5～15s（内存，单进程） | 进程内 |
| bars 1d（已收盘） | 至日终 | `bars` 表 |
| bars 1w（已收盘） | 6h | `bars` 表 |
| bars 当前未收盘柱（日/周最后一根） | 不缓存（交易时段每次重取，或 ≤30s） | `bars` 表 + `finalized` 标记 |
| search | 24h | 内存/表 |

**运行约束：** 实时现价优先用「全市场快照」接口一次拉全表、本地按 symbol 查（单票 10s 轮询易被 AKShare 限流）；持仓/首页用批量报价接口（见 §6.2）。

限流：令牌桶按 provider；失败熔断短时间直接走缓存或返回 stale + `stale=true`。

**时区：** 所有 `*_at` 存 UTC ISO8601；`bars.ts` 日/周线用 `YYYY-MM-DD`（交易日），分钟线用 UTC epoch 秒（Lightweight Charts 要求）；`quote.as_of`＝行情源数据时间，`quote.fetched_at`＝本地抓取时间，UI 展示 `as_of`。**不自行维护节假日日历**，交易时段提示直接展示 provider 的 `session`（regular/pre/post/closed）。

### 4.4 Portfolio Service

- 持仓列表：join 最新 quote 算浮动盈亏与市值；行情不可用时用「最后已知 api 价 + stale 标记」，无任何价则显示「—」且不计入总资产（避免 0 元市值）
- `equity_snapshots` 写 `UNIQUE(account_id, snapshot_date)` + upsert；快照记录 `valuation_basis`（api/manual），手填估值不写入长期曲线（或单独标注）
- 收益率：`(equity - net_deposit) / net_deposit`，`net_deposit = initial_cash + deposits - withdraws`；`net_deposit <= 0` 时不显示收益率

### 4.5 黄金「可选」实现

- 黄金 ETF：`instrument_type=etf` + `theme` 含 `gold`（或 `asset_class=gold` 作对外分类），`market=CN|US` 跟着交易所走；金价符号/期货 = `instrument_type=spot`（V1，另接报价源）  
- 搜索：keyword 命中名称/代码；另提供 `GET /instruments?asset_class=gold`（或 `?theme=gold`）列表，从 preset JSON + 搜索结果合并  
- **不**维护「全局唯一黄金」；用户自选多个  
- 币种仍跟标的走，受账本约束  

---

## 5. 数据模型（逻辑 Schema）

> 物理 DDL 可另出 `schema.sql`；此处为实现依据。

### 5.1 表一览

| 表 | 用途 |
|----|------|
| users | 单用户即可，可一行默认 |
| accounts | 账本，含 base currency |
| wallet_balances | 账本多币种现金余额 |
| fx_trades | 账本内换汇记录 |
| cash_flows | 出入金 / 换汇流水（含 currency） |
| cash_ledger | 每笔资金变动（含 currency） |
| instruments | 标的元数据 |
| bars | K 线缓存（quotes 用内存，不落表） |
| watchlist_items | 关注 |
| orders | 订单（MVP 即成即 filled；含 client_order_id） |
| trades | 成交 |
| positions | 持仓 |
| position_adjustments | 手动调仓（拆股/分红/送转等） |
| notes | 理由/复盘 |
| fee_rules | 费率（按 market + instrument_type + 买卖侧） |
| equity_snapshots | 资产曲线 |
| settings | 可省略；MVP 行情 Key 走环境变量 |

### 5.2 关键字段

**accounts**

- `id`, `name`, `currency`（base / 展示基准）, `initial_cash_cents`（冗余）, `cash_balance_cents`（冗余=base 钱包）
- `status` (`active`|`archived`), `created_at`, `note`

**wallet_balances**

- `id`, `account_id`, `currency`, `balance_cents`；UK(`account_id`,`currency`)

**fx_trades**

- `from_currency`, `to_currency`, `from_amount_cents`, `to_amount_cents`, `rate_e6`, `rate_source`

**cash_ledger**

- `id`, `account_id`, `ts`, `type` (`initial`|`deposit`|`withdraw`|`buy`|`sell`|`fx_out`|`fx_in`|…)
- `currency`, `amount_cents`（正=流入，负=流出）, `ref_order_id` NULL, `balance_after_cents`, `note`

**position_adjustments**

- `id`, `account_id`, `symbol`, `ts`, `reason`（`split`|`dividend`|`manual`…）
- `qty_delta`, `cost_delta`, `note`

**instruments**

- `symbol` PK（规范 ID，含交易所：`600519.SH` / `000001.SZ` / `AAPL` / `518880.SH` / `GLD`）
- `ticker`（展示用原始代码，如 `600519` / `AAPL`）
- `name`, `instrument_type` (`equity`|`etf`|`spot`), `theme`（`gold` 等，可 JSON 多值）
- `asset_class`（对外分类：`equity_cn`|`equity_us`|`gold`|`fund`）
- `market` (`CN`|`US`), `currency` (`CNY`|`USD`)
- `lot_size`（A 股股票/ETF 100，卖出全部可零股；美股 1，支持小数）, `tick_size`, `provider`, `meta_json`, `updated_at`

**orders**

- `id`, `account_id`, `client_order_id`（UK，幂等）, `symbol`, `side`, `order_type` (`market`)
- `qty`, `limit_price` NULL（V1 前恒 NULL）, `status` (`filled`), `fee_amount`
- `expected_price` NULL, `fill_price`, `price_source` (`api`|`manual`)
- `client_note`, `emotion_tag`, `created_at`, `filled_at`

**trades**

- `id`, `order_id`, `account_id`, `symbol`, `side`
- `price`, `qty`, `fee`, `traded_at`, `price_source` (`api`|`manual`)

**positions**

- `account_id`, `symbol`, UK(`account_id`,`symbol`)
- `qty`, `avg_cost`, `opened_at`, `updated_at`
- 卖出只减数量、不改变剩余持仓的 `avg_cost`（移动加权）

**bars**

- UK(`symbol`,`interval`,`ts`,`adjust`)
- `open`,`high`,`low`,`close`,`volume`, `finalized`（最后一根是否已收盘）, `fetched_at`

**fee_rules**

- `scope` (`global`|`account`), `account_id` NULL
- `market` NULL（空=默认）, `instrument_type` NULL（空=默认）
- `buy` / `sell` 两侧各自：`commission_rate`, `min_commission`, `stamp_tax_rate`, `transfer_fee_rate`, `sec_fee_rate`
- 默认模板：A 股股票（双边佣金 万2.5/最低5元；卖出印花税 0.05%；双边过户费 0.001%）；场内 ETF（双边佣金 万2.5/最低5元；免印花税/过户费）；美股（佣金 0；可选卖出 SEC/TAF）

### 5.3 金额与精度

- 金额二选一，**必须定死**：① `INTEGER` 最小货币单位（分/美分；价格用 1/10000 单位）全整数运算；② `TEXT` 列存十进制字符串、应用层 `Decimal` 解析。**不要用 `DECIMAL(20,8)` 声明**——SQLite 会当作 NUMERIC 亲和性，写入时退化成 REAL 丢精度。
- 计算统一用 `decimal.Decimal`，禁止浮点累加；展示层四舍五入到币种小数位（CNY/USD 一般 2 位；股价按市场 2～4 位）。
- SQLite 必配：`PRAGMA foreign_keys=ON`（默认 OFF）、`PRAGMA busy_timeout=5000`、WAL；交易事务用 `BEGIN IMMEDIATE`。

---

## 6. API 设计（REST）

Base：`/api/v1`  
错误体：`{ "code": "INSUFFICIENT_CASH", "message": "USD 现金不够……可先在首页换汇。" }`

错误码（人话 `message` 直接展示）：

| code | 说明 |
|------|------|
| `INSTRUMENT_NOT_FOUND` | 标的不存在 |
| `INSUFFICIENT_CASH` | 标的计价币种钱包余额不足（可提示换汇） |
| `FX_UNSUPPORTED` / `FX_UNAVAILABLE` | 换汇币种不支持或汇率不可用 |
| `LOT_SIZE_VIOLATION` | 数量不满足整手/碎股规则 |
| `QUOTE_UNAVAILABLE` | 无行情，请手填价 |
| `PRICE_INVALID` | 手填价非法（0/负数/非 tick size/超限） |
| `PRICE_MOVED` | 价格已漂移，需二次确认（带当前价与偏差） |
| `INSUFFICIENT_CASH` / `INSUFFICIENT_POSITION` | 资金/持仓不足 |
| `IMPORT_INVALID` | 导入文件格式/版本不符 |

### 6.1 账本

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/accounts` | 列表 |
| POST | `/accounts` | `{ name, currency, initial_cash }` |
| GET | `/accounts/{id}` | 详情含现金、总权益（需行情） |
| POST | `/accounts/{id}/cash-flows` | 出入金 |
| PATCH | `/accounts/{id}` | 改名/归档；**不可改 currency** |

### 6.2 标的与行情

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/instruments/search?q=&asset_class=&theme=` | 搜索 |
| GET | `/instruments/{symbol}` | 详情（含 lot_size/tick_size/session） |
| GET | `/quotes?symbols=a,b,c`（批量，上限 50） | 最新价；每项带 `stale`、`session`、`as_of`、`prev_close` |
| GET | `/bars/{symbol}?interval=1d&adjust=none&from=&to=&limit=` | K 线；`adjust` 默认 `none` |

### 6.3 交易与持仓

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/accounts/{id}/orders` | 模拟下单（幂等，body 见下） |
| GET | `/accounts/{id}/orders` | 流水 |
| GET | `/accounts/{id}/positions` | 持仓+浮动（行情不可用时 stale/—） |

**下单 body 示例：**

```json
{
  "client_order_id": "uuid",
  "symbol": "600519.SH",
  "side": "buy",
  "qty": 100,
  "manual_price": null,
  "expected_price": 1678.5,
  "note": "突破买入",
  "emotion_tag": "plan"
}
```

### 6.4 其他

| 方法 | 路径 | 说明 |
|------|------|------|
| CRUD | `/watchlist` | 关注；添加时可不校验币种（仅交易校验） |
| CRUD | `/notes` | 笔记 |
| GET | `/accounts/{id}/snapshots` | 资产曲线 |
| GET | `/accounts/{id}/summary` | 首页聚合（现金/持仓/总权益，用缓存价） |
| GET | `/export` | JSON 全量导出（业务数据 + `schema_version`；**排除 secrets 与 bars/quotes 缓存**） |
| POST | `/import` | JSON 导入恢复（校验 `schema_version`，导入到新账本） |

---

## 7. 前端方案

### 7.1 路由

| 路径 | 页面 |
|------|------|
| `/` | 账本首页（当前账本切换器） |
| `/watchlist` | 关注 |
| `/trade/:symbol` | **交易页** |
| `/positions` | 持仓 |
| `/orders` | 流水 |
| `/review` | 复盘 |
| `/settings` | 设置 |

全局：当前 `accountId` 放 context + localStorage；切换账本刷新权益。

### 7.2 交易页结构

- 顶栏：名称、代码、现价、涨跌、更新时间、`模拟 · 非真实下单`
- 左/上：`KlineChart`（interval tabs：日 / 周）
- 右/下：`OrderForm`（买/卖、价格、数量、费用预览、确认）
- 底：本账本该标的持仓摘要

**数据：**

- `useQuote(symbol, { refetchInterval: 10_000, enabled: pageVisible })`（仅交易页单票；首页/持仓用批量 `/quotes?symbols=`）
- `useBars(symbol, interval, adjust)`
- 价格输入：`syncedToQuote` 标志；用户编辑后断开自动跟随，提供「恢复最新价」
- 确认下单：带上 `expected_price`；后端返回 `PRICE_MOVED` 时弹「价格已变，当前 X，是否继续」，同意后重发（同 `client_order_id`）
- K 线最后一根若 `finalized=false` 且与现价偏差 <5%，用现价覆盖 close（high/low 取 max/min）并标「最新价」

**现金 UI：** 交易页展示标的计价币种的可用现金；不足时提示回首页换汇。

### 7.3 状态与人话错误

- API `message` 直接展示 Toast；按 §6 错误码表映射处理（`PRICE_MOVED` 走二次确认，而非直接报错）  
- 空状态文案按 PRD  
- 金额格式：`Intl.NumberFormat` + 账本 currency  

---

## 8. 关键时序

### 8.1 交易页加载

```
Browser          API              Gateway           Provider
   |--GET instrument------------>|                  |
   |--GET quote----------------->|--cache miss----->|--HTTP-->|
   |<-quote----------------------|<--quote----------|<--------|
   |--GET bars?interval=1d------>|--cache hit------>|         |
   |<-bars-----------------------|                  |         |
   |  render chart + form        |                  |         |
```

### 8.2 模拟买入

```
Browser          API/TradingEngine           DB
   |--POST orders--------------->|             |
   |                             |--BEGIN------|
   |                             |--校验币种---|
   |                             |--取价/费用--|
   |                             |--更新现金/仓|
   |                             |--写单/成交--|
   |                             |--COMMIT-----|
   |<-filled receipt-------------|             |
```

---

## 9. 安全与配置

| 项 | MVP 做法 |
|----|----------|
| 鉴权 | 默认无登录；可选 `IFBUY_TOKEN` 环境变量，API Bearer |
| 行情 Key | **环境变量**（`IFBUY_TUSHARE_TOKEN` 等），不做写盘 UI；导出/日志不回显明文 |
| 暴露面 | compose 默认绑 `127.0.0.1`；非本机访问必须设 token + 反代 |
| 实盘 | 无相关依赖；文档与 UI 标明模拟 |
| CORS | 仅同源或 localhost |
| 参数校验 | `symbol` 白名单正则（A 股 `^[0-9]{6}\.(SH|SZ|BJ)$`；美股 `^[A-Z][A-Z0-9.-]{0,10}$`），防 SSRF/注入 |
| 备份 | 用户导出/导入 JSON；DB 备份用 `sqlite3 ".backup"`（WAL 下直接复制文件可能不一致） |

---

## 10. 部署

```yaml
# docker-compose 概念
services:
  api:
    build: ./apps/api
    volumes: ["./data:/data"]
    environment:
      IFBUY_DB: /data/ifbuy.db
  web:
    build: ./apps/web
    ports: ["127.0.0.1:8080:80"]
    depends_on: [api]
```

> web 容器内 nginx 需加 `location /api { proxy_pass http://api:8000; }`，并配 healthcheck；`ports` 默认只绑回环地址。

本地开发：`api` `:8000`，`web` 代理 `/api` → api。

---

## 11. MVP 实施切片（建议顺序）

| 迭代 | 交付 |
|------|------|
| M0 | 仓库骨架、SQLite+Alembic、Account CRUD（含 currency、cash_ledger）、导出/导入空壳 |
| M1 | Instrument 搜索（一个 Provider）+ Quote + Bars（含 adjust/finalized）+ 交易页 K 线 |
| M2 | Trading Engine（币种校验 + 多账本 + 幂等 + 价格漂移）+ 持仓盈亏 + 流水备注 + 对账不变量 |
| M3 | 第二市场 Provider + 黄金 ETF（CN/US 各一类验证） |
| M4 | 关注、手填价（隔离）、环境变量 Key、日 K+周 K、批量报价、模拟水印与验收 |

并行：前端可先用 mock bars 画交易页，等 M1 接真数据。

---

## 12. 测试策略

| 类型 | 重点 |
|------|------|
| 单测 | 费用（买卖两侧、最低佣金、ETF 免印花税）、均价、收益率、币种校验、整手/碎股、卖超仓拒绝、手填价校验 |
| 不变量 | 每笔交易后 `cash_balance` 与 `cash_ledger` 对账；Σ持仓成本与流水一致 |
| 契约测 | OpenAPI 快照（先产出 spec 再测） |
| 集成 | Provider 用录制 fixture（VCR），避免 CI 打外网；含复权口径断言 |
| 手工 | PRD 附录 B 验收清单 |

---

## 13. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 免费行情不稳/被限流 | 缓存 + stale 展示 + 手填价；实时价用全市场快照而非逐票轮询；Provider 可替换 |
| AKShare/Yahoo API 变更与合规 | 适配器隔离 + fixture；yfinance/AKShare 属个人研究用途，公开部署需自担合规 |
| 多市场代码混乱 | A 股强制交易所后缀、美股裸代码，`symbol` 全站唯一 |
| 用户混用币种 | 账本创建强提示 + 下单硬校验 + 多账本 |
| 黄金分类噪声 | `instrument_type=etf` + `theme=gold` + 搜索；无效代码明确失败 |
| 拆股/分红导致数据失真 | 提供「持仓调整」手动改数量/成本（position_adjustments）并标注入口 |

---

## 14. 后续可演进（非 MVP）

- 限价单调度器、K 线买卖点、均线  
- 资产曲线图（表已留，前端图 P1）  
- 基金模块（新 `asset_class=fund` + 净值 Provider）  
- 严格 T+1 / 涨跌停模式  

---

## 15. 开放实现选择（可开工时再定）

| 项 | 选项 | 推荐 |
|----|------|------|
| 后端语言 | Python FastAPI / Node | **FastAPI** |
| A 股源 | AKShare / Tushare | 先 **AKShare**（无积分也可起步），稳定后可加 Tushare |
| 美股源 | yfinance | **yfinance** |
| 内部 symbol | 前缀 `CN:600519` vs 后缀 `600519.SH` | **A 股 `600519.SH`/`000001.SZ`，美股裸代码 `AAPL`**（后缀即交易所，展示层无需再转换） |
| 金额存储 | INTEGER 分 vs TEXT 十进制 | **INTEGER 最小货币单位**（价格用 1/10000 单位） |

---

## 附录 A. 与 PRD 功能映射

| PRD 能力 | 技术方案落点 |
|----------|--------------|
| 交易页 + K 线 | Web `/trade/:symbol` + bars API + Lightweight Charts |
| 真实行情非实盘 | MarketDataGateway；TradingEngine 无券商客户端 |
| A/美/黄金可选 | instruments + provider 路由 + asset_class |
| 一账本一币种 | accounts.currency + 下单校验 |
| 持仓盈亏 / 备注 / 导出 | portfolio + notes + export |
| 手填价兜底 | manual_price（仅作用于本次成交，不写 quote 缓存） |

## 附录 B. 下一步文档

1. `schema.sql` / SQLAlchemy models  
2. OpenAPI 初稿（可由 FastAPI 自动生成后裁剪）  
3. 交易页线框  

---

*v1.1：费用按品种+买卖侧、cash_ledger/对账不变量、position_adjustments、复权/时区/数量精度口径、symbol 后缀规范、批量报价/错误码/幂等/导入、SQLite 精度与事务、切片顺序调整。*
*本文档依据 PRD v1.6；币种规则变更或基金开做时需升版 TECH_DESIGN。*
