# IfBuy — PRD / 技术方案 评审意见

| 评审对象 | PRD.md v1.5（Draft）、TECH_DESIGN.md v1.0（Draft） |
|---------|--------------------------------------------------|
| 评审日期 | 2026-11-07 |
| 结论 | **可以进开发，但有 12 个必须先定死的口径**；否则 M2 之后大概率返工，且会出现「算错钱」类问题 |
| 落地状态 | 已按本文意见改入 PRD v1.6 / TECH_DESIGN v1.1；symbol 最终采用 `600519.SH` 后缀形式 |

---

## 0. 总评

写得比多数个人项目的文档好：**非目标明确**、**边界表有**、**币种门禁**、**手填价兜底**、**Provider 抽象**、**验收清单**都已具备，方向没有跑偏。

问题集中在三类：

1. **可执行性**：大量需求写成「同 v1.2 / 同前 / 保留」，但仓库里没有 v1.2。实现者（或 AI）拿不到这些需求，等于这部分没有写。
2. **口径没定死**：费用（买卖不对称）、复权、时区、数量精度、估值基准价——这五项任何一项含糊，都会直接算错持仓和盈亏。
3. **少量自相矛盾**：多账本到底是不是 MVP、K 线第二周期、手填价写不写缓存、slippage 与「按现价成交」冲突。

下面按严重度列。🔴＝开工前必须改；🟡＝强烈建议；🟢＝细节顺手改。

---

## 1. 🔴 必须改（开工前定死）

### 1.1 文档引用悬空：v1.2 不存在

**位置**：[PRD.md:122](PRD.md#L122)、[PRD.md:143](PRD.md#L143)、[PRD.md:257](PRD.md#L257)、[PRD.md:318](PRD.md#L318)、[PRD.md:110](PRD.md#L110-L116)

`F-ACC-01～04 同 v1.2`、`F-POS-01～03 同前`、`US-04～US-07（保留）`、`盈亏约定同 v1.2`、`费用默认值、T+1 等同 v1.2`——这些是本项目的**账本、持仓、盈亏、费用**，恰好是最核心的部分，却全部指向一份不存在的文档。

**影响**：核心业务规则无来源；「10 笔手工验算误差为 0」这条成功指标无法验收。

**建议**：把 v1.2 的有效内容**内联进 PRD**（哪怕就 30 行表格），或补一份 `PRD_v1.2_archive.md` 并在正文链接。删掉所有「同前」「同 v1.2」的措辞，文档应当自洽可读。

---

### 1.2 费用模型买/卖不对称，且会算错 ETF

**位置**：[TECH_DESIGN.md:242](TECH_DESIGN.md#L242-L247)、[PRD.md:57](PRD.md#L57)

`fee_rules` 只有 `commission_rate / min_commission / stamp_tax_rate / slippage_bps`，是**单一侧**的费率模型。真实规则是：

| 费项 | A 股股票 | 场内 ETF（含黄金 ETF） | 美股 |
|------|---------|----------------------|------|
| 佣金（含最低 5 元） | 双边 | 双边 | 多数 0 |
| 印花税 | **仅卖出** | **免** | 无 |
| 过户费 | 双边 | **免** | 无 |
| SEC/TAF 等 | 无 | 无 | **仅卖出** |

PRD 自己写了「黄金按所选标的类型配置」([PRD.md:57](PRD.md#L57))，但 schema 里**只有 `market` 一个维度**，没有 `asset_class/instrument_type`，结果就是 518880 会被套上股票费率（多扣印花税+过户费），已实现盈亏从第一笔就错。

**建议**：
- `fee_rules` 增加 `asset_class`（或 `instrument_type`）维度，与 `market` 组成匹配键；
- 费率拆成 `buy_*` / `sell_*` 两套，或改成一个 `fee_components` 子表（`name, side, rate, min, max, applies_to`）；
- 明确**费用计算顺序与取整**：`commission = max(min_commission, notional × rate)`，每项费用各自四舍五入还是总额取整，必须写死（否则 10 笔验算必然有 1 分钱差）。
- 补一句「费率随政策变动，默认值仅示例，用户可改」。

参考：[长城证券费用公示](http://sz2.cgws.com/cczq/gycc/fygs/)、[长江证券 2025 费用公示](https://www.gslb.95579.com/main/a/20250709/35761.shtml)。

---

### 1.3 没有账本不变量（缺少可对账的账务层）

**位置**：[TECH_DESIGN.md:124](TECH_DESIGN.md#L124-L138)

现在只有「改 `cash_balance` + 改 `position`」，没有任何东西能证明账没算错。一次异常（双击下单、事务半成功、手填价误输）就会让现金和持仓永久漂移，而且**无法发现**。

**建议**（成本很低，收益最大）：
1. 加 `cash_ledger`（或 `ledger_entries`）：每笔资金变动一行 `(account_id, ts, type, amount, ref_order_id, balance_after)`，`cash_balance` 由 ledger 派生或至少每日校验；
2. 加一个**对账不变量**，单测里跑：
   `cash = initial + Σdeposit - Σwithdraw - Σbuy_notional - Σbuy_fee + Σsell_notional - Σsell_fee`
   `Σposition.qty × avg_cost` 与流水口径一致；
3. `equity_snapshots` 加 `UNIQUE(account_id, snapshot_date)` + upsert，防重复补点。

这条也是「导出即备份」能否成立的前提。

---

### 1.4 公司行为（拆股/分红/送转）完全没提

**位置**：PRD 全文缺失；边界表 [PRD.md:310](PRD.md#L310-L318) 也没有

A 股送转、美股拆股（AAPL/NVDA/TSLA）很常见。不做处理的话，拆股当天持仓市值直接腰斩、均价翻倍，用户会认为「记账坏了」。

**建议**：MVP 可以不做自动处理，但必须**显式声明**，并给一条手动出口：
- PRD 边界表加一行：「拆股/分红/送转 → MVP 不自动处理，提供『持仓调整』（改数量 + 改成本）入口，调整写一条 `position_adjustment` 流水并在 UI 标注」；
- 技术方案加 `position_adjustments` 表（或复用 `cash_flows` + 调整记录）。

哪怕只做「手动调整」，也远好过完全没有。

---

### 1.5 复权口径会名不副实

**位置**：[PRD.md:127](PRD.md#L127)、[PRD.md:303](PRD.md#L303)、[TECH_DESIGN.md:237](TECH_DESIGN.md#L237-L240)

PRD 说「MVP 不复权」，但：
- AKShare 的 A 股日 K 默认多为**前复权**；
- yfinance 的 `history()` 默认 `auto_adjust=True`，返回的是**调整后**价格。

也就是说，不做任何事的话，默认拿到的就是复权数据，与「不复权」的声明相反。而 `bars` 表虽留了 `adjust` 字段，**Provider 参数却没有任何地方约束**，缓存里会混进不同口径的数据（同一 `symbol+interval+ts` 不同 `adjust` 是两条记录，但前端请求 `/bars` 没有 `adjust` 参数，见 [TECH_DESIGN.md:277](TECH_DESIGN.md#L277)）。

**建议**：
- Provider 接口显式带 `adjust`，实现里强制传 `adjust="none"` / `qfq=false` / `auto_adjust=False`；
- `/bars` 增加 `?adjust=none|forward`，默认 `none`；
- 写一条测试：同一标的请求 `none` 与 `forward`，断言 OHLC 不同且 `adjust` 落库正确。

---

### 1.6 时区与「bar 时间」没定义（A 股日 K 会错位一天）

**位置**：[TECH_DESIGN.md:239](TECH_DESIGN.md#L239)、[TECH_DESIGN.md:248](TECH_DESIGN.md#L248-L251)

`bars.ts`「柱开始时间」用什么时区？`as_of` 是交易所时间还是抓取时间？美股还有夏令时。Lightweight Charts 的 `time` 对日线要求是**交易日**（`YYYY-MM-DD`）或 **UTC 秒**，用本地时区时间戳会导致 A 股日 K 整体偏移一天。

**建议**（写进文档即可，不需要新功能）：
- 所有 `*_at` 一律 **UTC ISO8601** 存库；
- `bars.ts`：日/周线用 `YYYY-MM-DD`（business day）；分钟线用 **UTC epoch 秒**；
- `quote.as_of` 定义成「行情源给的数据时间」，另加 `fetched_at`（本地抓取时间），UI 展示 `as_of`；
- 交易时段提示**不要自己维护节假日日历**：直接展示 provider 返回的 `session`（regular/pre/post/closed）+ `as_of`，MVP 只做「数据时间 + 是否常规时段」的弱提示即可，否则美股的 DST 和 A 股节假日会让你维护一份永远不准的日历。

---

### 1.7 数量模型未定义（整手、碎股、金额下单）

**位置**：[PRD.md:180](PRD.md#L180)、[TECH_DESIGN.md:120](TECH_DESIGN.md#L120)、[TECH_DESIGN.md:223](TECH_DESIGN.md#L223)

- PRD 交易页画了「数量 / 金额」，技术方案的入参却只有 `qty`；
- A 股 `lot_size=100` 存了但**从未被使用**，买入 150 股会直接成交；
- 卖出零股、美股碎股（0.5 股）没定；
- `qty` 是 `INTEGER` 还是 `DECIMAL` 没写。

**建议**（三选一，写死）：
- 方案 A（简单）：`qty` 用 `DECIMAL(18,6)`；A 股 `qty % lot_size == 0`（卖出全部持仓时允许零股）；美股允许小数；不支持按金额下单，UI 去掉「金额」或只做只读换算。
- 方案 B：支持按金额下单，规则写死 `qty = floor(amount / (price × (1+fee_rate)) / lot) × lot`。

无论选哪个，都要加错误码 `LOT_SIZE_VIOLATION`。

---

### 1.8 手填价会污染全局估值

**位置**：[PRD.md:132](PRD.md#L132)、[PRD.md:213](PRD.md#L213)、[TECH_DESIGN.md:286](TECH_DESIGN.md#L286)

`POST /positions/{symbol}/manual-quote` 直接「写 quote 缓存」，但缓存在哪没定（`quotes` 表标着「可可选」）。更严重的是：**手填价会一路污染持仓估值、首页总资产、资产曲线**，而 PRD 又说「手填价仅作兜底并标注来源」——这两件事冲突。

**建议**：
- 手填价默认**只作用于本次成交**（`manual_price` 进 order，不写 quote）；
- 若要覆盖估值，单独一个 `valuation_override`（带 `expires_at`，默认当日收盘失效），UI 明确标「自填价」，且资产曲线快照记录 `valuation_basis=manual`；
- 加合理性校验：`0 < price < 10 × 最近一次 api 价`，且必须是 tick size 的整数倍（A 股 0.01），超限二次确认——防手滑把 100 输成 1000。

---

### 1.9 「立即全成」与 slippage 字段冲突

**位置**：[TECH_DESIGN.md:224](TECH_DESIGN.md#L224)、[TECH_DESIGN.md:246](TECH_DESIGN.md#L246)

`orders.slippage_amount` 和 `fee_rules.slippage_bps` 存在，但流程里成交价就是 `Quote.price`，slipage 从未被计算。二者必须二选一：

- **建议 MVP 直接删掉 slippage**（PRD 的定位是「按现在的价格买/卖」，加滑点反而让用户觉得价格对不上）；
- 若保留，写死 `fill_price = quote.price × (1 ± slippage_bps/10000)`，并在确认框显示滑点后的价格。

---

### 1.10 确认价与成交价会漂移，用户会「被成交」在别的价位

**位置**：[PRD.md:140](PRD.md#L140)、[TECH_DESIGN.md:127](TECH_DESIGN.md#L127)

10s 轮询下，用户看到 100.00 点确认，后端重新取价可能已经是 100.80。现在没有任何一致性校验，回执也不强调实际成交价。模拟盘里这是最伤信任的细节。

**建议**：下单 body 增加 `expected_price`（前端确认框里的价格）+ 服务端比对，偏差 > 0.5%（可配）返回 `PRICE_MOVED`，前端提示「价格已变动，当前 100.80，是否继续」。回执里明确返回 `fill_price` 与 `price_source`。

---

### 1.11 缺幂等：双击 / 重试会重复成交

**位置**：[TECH_DESIGN.md:283](TECH_DESIGN.md#L283)

`POST /orders` 无幂等键。网络重试、用户双击、React Query 重放都会产生两笔成交。虽然是假钱，但流水和持仓会被污染，只能手动改库。

**建议**：前端生成 `client_order_id`（UUID），后端 `UNIQUE(account_id, client_order_id)`，重复请求直接返回原回执。

---

### 1.12 多账本到底是不是 MVP —— PRD 与 TECH 互相矛盾

**位置**：[PRD.md:341](PRD.md#L341)（V1 才有「多账本」）vs [TECH_DESIGN.md:327](TECH_DESIGN.md#L327)（MVP 就有「当前账本切换器」）vs [PRD.md:54](PRD.md#L54)

PRD §8.2 把「多账本」放进 V1，§8.1 MVP 只写「账本 + 本金」；但技术方案从 M0 就做 accounts 多行 + 切换器，PRD §4.2 首页又叫「账本总览」。

**建议**：明确 **MVP 支持多账本**（因为币种门禁本身就要求 CNY/USD 两个账本才能同时练 A 股和美股），把 §8.2 里的「多账本」删掉；同时把首页文案从「账本总览」改成「账本列表（各自独立，不做跨币种加总）」，与技术方案的「禁止跨账本汇总」对齐。

---

### 1.13 附录 B 的黄金验收项在单账本下无法完成

**位置**：[PRD.md:393](PRD.md#L393)

验收写「至少能切换/选择 2 个不同黄金标的并分别交易」。如果用户选 518880（CNY）+ GLD（USD），在一个账本里**永远无法同时交易**——这恰好是 1.12 里「多账本就是 MVP」的佐证。

**建议**：验收项改为「在 CNY 账本交易 1 个国内黄金 ETF，在 USD 账本交易 1 个美股黄金 ETF」，把多账本纳入 MVP 验收。

---

## 2. 🟡 强烈建议优化

### 2.1 A 股实时价不要用 AKShare 逐票轮询

[TECH_DESIGN.md:462](TECH_DESIGN.md#L462-L467) 推荐 AKShare 起步。但 AKShare 的实时接口是**抓网页/东财接口**，按 10s 单票轮询极易被限流/封 IP；它更适合「全市场快照」和「历史 K 线」。

**建议**做成两条路：
- **K 线/搜索**：AKShare（或 Tushare，需注意积分门槛）；
- **实时现价**：用「全市场快照」接口一次拉全表（几千行，一次请求），本地按 symbol 查，10s 只发 1 个请求；或换轻量单票接口。这样持仓页 N 只票也不会变成 N 个请求。

### 2.2 缺批量行情接口 → 首页/持仓 N+1

[TECH_DESIGN.md:276](TECH_DESIGN.md#L276) 只有 `GET /quotes/{symbol}`。首页总资产 + 持仓页 20 只票 = 20 个请求。

**建议**：加 `GET /quotes?symbols=CN:600519,US:AAPL`（逗号分隔，上限 50），一次返回并带各自的 `stale`。这是 MVP 就该有的接口。

### 2.3 盘中「未收盘 bar」的缓存 TTL 是错的

[TECH_DESIGN.md:162](TECH_DESIGN.md#L162) 写 `bars 1d TTL 1h～至日终`。盘中最后一根日 K 一直在变，缓存 1h 会让图表最后一根停留在 10:30 的收盘价，与顶部现价差一大截（这是 K 线产品最常被吐槽的 bug）。

**建议**：
- `bars` 区分 `finalized`（已收盘）与 `partial`；
- 交易时段内最后一根**每次请求都重取**（或 30s TTL），历史部分走缓存；
- 周 K 同理：当前周那根永不缓存。

### 2.4 顶部现价与图表最后一根不一致

即使修了 2.3，`quote` 和 `bar.close` 仍来自不同请求/不同源。

**建议**：图表渲染时，若最后一根是 partial 且 `|bar.close - quote.price| / quote.price < 5%`，用 quote 覆盖最后一根 close（high/low 取 max/min），并在 UI 标注「最新价」。差异过大则不移除，只标「数据源不一致」。

### 2.5 SQLite 里 `DECIMAL(20,8)` 会退化成浮点

[TECH_DESIGN.md:250](TECH_DESIGN.md#L250)

SQLite 没有真正的 DECIMAL：声明 `DECIMAL(20,8)` 得到的是 **NUMERIC 亲和性**，写入 `"10.5"` 会被转成 REAL，精度就丢了。文档里「DECIMAL/TEXT…或 INTEGER」也自相矛盾。

**建议**写死一种：
- 首选 **INTEGER 最小单位**（分/美分，价格用 1/10000 单位），全整数运算，展示层除；或
- 备选 **TEXT 列**（列声明必须是 `TEXT`，不是 `DECIMAL`），应用层 `Decimal` 解析。

另外两个 SQLite 必配项文档里没写：`PRAGMA foreign_keys=ON`（默认是 **OFF**）、`PRAGMA busy_timeout=5000`。

### 2.6 「锁 account 行」在 SQLite 里不成立

[TECH_DESIGN.md:125](TECH_DESIGN.md#L125) 写「锁 account 行（SQLite 事务）」。SQLite 没有行锁，写事务会锁**整个库**。单人低并发没问题，但 FastAPI 多 worker + 后台 bars/quotes 写入会撞 `database is locked`。

**建议**：
- 交易事务用 `BEGIN IMMEDIATE`；
- 明确**单 worker**（uvicorn `--workers 1`），或把行情抓取放到独立进程/线程池且不在交易事务内写缓存；
- `busy_timeout` + WAL 一起写进文档。

### 2.7 AKShare/yfinance 是同步阻塞调用

FastAPI 里 `async def` 路由直接调 AKShare/yfinance 会**阻塞事件循环**，一个慢请求拖垮整站。

**建议**：行情路由写成普通 `def`（FastAPI 自动丢线程池），或显式 `run_in_threadpool`；并在文档里标注 provider 调用一律带 3～5s 超时。

### 2.8 内部 symbol 丢了交易所维度

[TECH_DESIGN.md:215](TECH_DESIGN.md#L215)、[TECH_DESIGN.md:467](TECH_DESIGN.md#L467) 用 `CN:600519`。A 股代码**沪深不唯一**（`000001` 既是平安银行 SZ，也是上证指数 SH），且沪/深在行情源、费率、板块上都不同。

**建议**：内部 ID 用 `CN:SH:600519` / `CN:SZ:000001`，或干脆沿用更标准的 `600519.SH`。展示层再格式化。这条改起来是破坏性的，越早越好。

### 2.9 设置里的 API Key 存储方案未定，且导出可能泄密

[TECH_DESIGN.md:387](TECH_DESIGN.md#L387) 说「存 settings 表或 secrets.json，文件权限 600」，但 Docker volume 下权限 600 没意义，加密密钥从哪来也没说。

**建议**：MVP 直接**只用环境变量**（`IFBUY_TUSHARE_TOKEN`），不做写盘 UI；`GET /export` 明确**排除 secrets 与缓存表（bars/quotes）**，只导业务数据 + `schema_version`。

### 2.10 默认无鉴权 + `ports: 5173:80` 有暴露风险

[TECH_DESIGN.md:406](TECH_DESIGN.md#L406) 映射到 `0.0.0.0`，而 MVP 无登录。用户把这套跑在 VPS 上，等于把「谁都能下单、能看你的账本」挂公网。

**建议**：compose 默认 `127.0.0.1:8080:80`；文档加一句「如非本机访问，必须设 `IFBUY_TOKEN` 并挂反代」。另外 `/quotes/{symbol}` 如果 symbol 直接拼进 provider URL，加个正则白名单（`^[A-Z]{2}:[A-Z0-9.:]+$`），避免 SSRF/参数注入。

### 2.11 没有数据库迁移工具

技术栈有 SQLAlchemy，但没提 Alembic。SQLite + 这种还在频繁改的 schema，手写 `ALTER TABLE` 会很快失控。

**建议**：M0 就把 Alembic 接上，`data/ifbuy.db` 带 `alembic_version`。

### 2.12 实施顺序：币种门禁拖到 M3 会返工

[TECH_DESIGN.md:414](TECH_DESIGN.md#L414-L424)

M1 只做一个 Provider 就能跑交易页，M3 才做「第二市场 + 币种门禁」。但 `account.currency` 是所有交易的前置校验，M2 写 Trading Engine 时不带它，M3 就要回头改引擎、改 UI、改测试。

**建议**：把「币种校验 + 多账本」提到 **M2**，与 Trading Engine 同一迭代；M3 只做第二个 Provider 与黄金。

### 2.13 导出是 P0，导入却是 V1 —— 备份不成立

[PRD.md:147](PRD.md#L147)、[PRD.md:342](PRD.md#L342)

「导出即备份」的前提是能导回来。换机器、重装、升级后没有导入，导出的 JSON 只能看不能用。

**建议**：MVP 就做 `POST /import`（同格式 JSON，`schema_version` 校验，导入到新账本），成本很低。它同时也是 1.3 对账不变量的验证手段。

### 2.14 备份方式会拿到不一致的 DB

[TECH_DESIGN.md:390](TECH_DESIGN.md#L390) 建议「定期复制 `data/ifbuy.db`」。WAL 模式下直接 copy 主库文件可能丢掉未 checkpoint 的页。

**建议**：文档改成 `sqlite3 ifbuy.db ".backup backup.db"` 或 `VACUUM INTO`，并提示先停写。

---

## 3. 🟢 细节清单（可直接改）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| 1 | [PRD.md:102](PRD.md#L102)、[PRD.md:126](PRD.md#L126)、[PRD.md:370](PRD.md#L370) | 第二周期写「周 K 或 60m 其一」，但 Q2 已定「日+周」，TECH 也只画了日/周 | 正文统一改成「日 K + 周 K」，删掉「或 60m」 |
| 2 | [PRD.md:289](PRD.md#L289)、[PRD.md:48](PRD.md#L48) | 黄金范围含「常见金价符号」，但验收只验 ETF；「以 Provider 能拿到为准」把范围交给了实现 | 明确 MVP 只支持黄金 **ETF**（518880/159934/GLD/IAU），金价符号放 V1 |
| 3 | [TECH_DESIGN.md:217](TECH_DESIGN.md#L217)、[TECH_DESIGN.md:246](TECH_DESIGN.md#L246) | `asset_class` 同时承担「资产类型」和「主题」，gold ETF 既像 equity 又像 gold | 拆成 `instrument_type(equity/etf/spot)` + `theme(gold/…)`，`market` 管交易所 |
| 4 | [TECH_DESIGN.md:196](TECH_DESIGN.md#L196)、[TECH_DESIGN.md:286](TECH_DESIGN.md#L286) | `quotes` 表标「可可选」，但 manual-quote 要写缓存 | 要么删掉 `quotes` 表（纯内存），要么设为必需，不能两头都留 |
| 5 | [TECH_DESIGN.md:192](TECH_DESIGN.md#L192) | 单用户还留 `users` 表 | 删掉，减一层 join |
| 6 | [TECH_DESIGN.md:49](TECH_DESIGN.md#L49) | 「REST (+ 可选 SSE 推价)」 | MVP 单人 10s 轮询足够，SSE 直接砍掉（YAGNI），避免连接管理 |
| 7 | [TECH_DESIGN.md:258](TECH_DESIGN.md#L258) | 只给了一个错误码示例 | 补错误码表：`INSUFFICIENT_CASH`、`INSUFFICIENT_POSITION`、`QUOTE_UNAVAILABLE`、`LOT_SIZE_VIOLATION`、`PRICE_MOVED`、`CURRENCY_MISMATCH`、`INSTRUMENT_NOT_FOUND` |
| 8 | [TECH_DESIGN.md:277](TECH_DESIGN.md#L277) | `/bars` 只有 `limit`，无 `from/to`，日 K 最多 250 根约 1 年 | 加 `from`/`to`，`limit` 上限放到 2000 |
| 9 | [TECH_DESIGN.md:276](TECH_DESIGN.md#L276) | `/quotes/{symbol}` 无 `prev_close` | 补 `prev_close` + `session`，涨跌额/幅不要由客户端反推 |
| 10 | [TECH_DESIGN.md:239](TECH_DESIGN.md#L239) | `interval` 枚举散落各处 | 集中定义 `1m/5m/15m/30m/60m/1d/1w/1M`，前后端共享 |
| 11 | [TECH_DESIGN.md:215](TECH_DESIGN.md#L215) | `CN:600519` 含冒号，若前端 `encodeURIComponent` 会变 `%3A`，nginx/代理偶发处理不一致 | 路由改 `/trade/:market/:ticker` 或 `CN-600519`；低优先级 |
| 12 | [TECH_DESIGN.md:266](TECH_DESIGN.md#L266) | `GET /accounts/{id}` 混合 DB + 外部行情，行情慢会拖慢首屏 | 拆成 `summary`（纯 DB + 缓存价）与独立 quotes 调用 |
| 13 | [PRD.md:181](PRD.md#L181) | 「约扣费用 ¥x」写死 ¥ | 按 `account.currency` 格式化 |
| 14 | [TECH_DESIGN.md:224](TECH_DESIGN.md#L224) | `orders.order_type` 只有 `market`，但表里有 `limit_price` | MVP 明确 `order_type` 枚举只含 `market`，`limit_price` 恒 NULL；或直接删字段到 V1 再加（SQLite 加列容易，删列麻烦） |
| 15 | [TECH_DESIGN.md:204](TECH_DESIGN.md#L204) | `settings` 表与 `secrets.json` 二选一未定 | 见 2.9，统一走环境变量 |
| 16 | [TECH_DESIGN.md:225](TECH_DESIGN.md#L225) | `orders.client_note` 与独立 `notes` 表职责重叠 | 定死：`orders.client_note`＝下单一句话理由；`notes`＝事后复盘长文（`order_id` 可空） |
| 17 | [TECH_DESIGN.md:172](TECH_DESIGN.md#L172) | 净入金 = initial + deposits - withdraws，但 `accounts.initial_cash` 与 `cash_flows` 可能重复计 | 定死：创建账本时**同时写一条 `cash_flows(type=initial)`**，`initial_cash` 只做展示冗余 |
| 18 | [TECH_DESIGN.md:172](TECH_DESIGN.md#L172) | 收益率分母为 0（初始 0 或全额取出）会炸 | 加保护：`net_deposit <= 0` 时收益率显示 `—` |
| 19 | [TECH_DESIGN.md:171](TECH_DESIGN.md#L171) | 行情挂掉时持仓/快照用什么价没定 | 定死：最后已知 api 价 → `stale=true` 展示；无任何价 → 显示「—」且不计入总资产（避免 0 元市值） |
| 20 | [TECH_DESIGN.md:205](TECH_DESIGN.md#L205) | `equity_snapshots` 无唯一键 | `UNIQUE(account_id, snapshot_date)` + upsert |
| 21 | [TECH_DESIGN.md:223](TECH_DESIGN.md#L223) | `trades` 索引未提 | 加 `(account_id, symbol, traded_at)`、`orders(account_id, created_at)`、`positions` UK 已有 |
| 22 | [TECH_DESIGN.md:394](TECH_DESIGN.md#L394-L410) | compose 里 api 不暴露端口，web 却要访问它；nginx 反代配置没写 | 补 `nginx.conf` 的 `location /api { proxy_pass http://api:8000; }` 与 healthcheck |
| 23 | [TECH_DESIGN.md:165](TECH_DESIGN.md#L165) | 「search 24h 内存/表」但 instrument 何时入库没定 | 定死：搜索/首次访问时 **lazy upsert** 到 `instruments`；`name` 建索引或 FTS5 |
| 24 | [PRD.md:296](PRD.md#L296) | 首屏 <2s 目标，但首次冷启动要走外部行情，AKShare 常常 >2s | 改成「有缓存 <1s；冷启动 <5s」，或首页预热关注列表前 N 只 |
| 25 | [PRD.md:356](PRD.md#L356) | 成功指标「误差在延迟范围内」不可测 | 改为「现价与公开源偏差 ≤ 1 分钟；日 K 收盘价与源一致」 |
| 26 | [PRD.md:166](PRD.md#L166) | `/review` 复盘页是 P0，但需求只有「理由 + 感想」，页面实质为空 | MVP 先做「流水 + 理由/感想」列表页，别做独立复杂页 |
| 27 | [PRD.md:313](PRD.md#L313) | 停牌时用最后价成交，价格已严重失真 | 建议停牌时**强制手动改价 + 黄条警告**，而不是静默按旧价成交 |
| 28 | [PRD.md:351](PRD.md#L351-L359) | 成功指标缺「算得对」的可执行验证 | 把「10 笔手工验算」固化成 fixture 测试（买卖各含最低佣金、ETF 免印花税、清仓四舍五入） |

---

## 4. 如果只改 5 件事

1. **把 v1.2 内容内联进 PRD**（1.1）——否则核心需求等于没写。
2. **费用模型加买卖两侧 + 品种维度**（1.2）——否则 ETF 从第一笔就错。
3. **定死五项口径**：复权、时区、数量精度、金额存储类型、估值基准价（1.5/1.6/1.7/2.5/2.9）。
4. **加幂等 + 价格漂移校验 + 手填价隔离**（1.8/1.10/1.11）——这三个是「模拟盘可信度」的地基。
5. **加账本不变量/对账测试 + 导入**（1.3/2.13）——否则数据坏了发现不了，也恢复不了。

---

## 5. 可以保留、不用改的部分

- 非目标写得很干净（[PRD.md:59](PRD.md#L59-L67)），「不做实盘」贯穿得也好；
- 一账本一币种 + 币种门禁的方向正确，比自动换汇省一个数量级的复杂度；
- Provider 路由 + 本地缓存 + stale 标记 + 手填兜底，这套降级链路是对的；
- 边界表、术语表、验收清单都有，比大多数个人项目完整；
- 技术选型（Vite + Lightweight Charts + FastAPI + SQLite）与「单人自托管」的场景是匹配的，不必换成更重的方案。
