# Provider 与数据源说明

更新时间：2026-05-29

本文档集中说明 ReverseFlightTickets 当前的数据源、provider 状态、凭据配置和后续 API 接入方式。原有规划文档仍保留在 `docs/IMPLEMENTATION_PLAN.md`，当前状态快照仍保留在 `docs/PROJECT_STATUS.md`。

## 当前接入层级

| 类型 | 当前状态 | 用途 | 注意事项 |
| --- | --- | --- | --- |
| 浏览器可见报价脚本 | 已支持携程/飞猪结果页 DOM 采集 | 当前阶段用于采集真实页面可见价格，导入后比价、排序、保存快照 | 只读已渲染页面，不请求内部接口；导入报价标记 `manual_check_required` 和 `provider_unverified` |
| 人工核验 deep link provider | 已支持 Skyscanner、Trip.com、飞猪 | 生成可打开的人工核验入口 | 不抓取页面，不返回真实实时价格 |
| API provider | 已支持 Duffel sandbox/API connector、Amadeus Self-Service test API connector | 在有凭据时返回结构化 API 报价 | 生产可用性取决于账号权限、限额、支付出票流程和商业条款 |
| Research provider | Google Flights research、Kiwi research、LetsFG research | 用于研究拼接思路和人工对照 | 默认不进入生产路径，需要显式 `--include-research` |

## 浏览器可见报价

当前阶段，携程/飞猪真实页面价格通过 `src/userscripts/flight_offer_collector.user.js` 采集。脚本安装到 Tampermonkey/Violentmonkey 后，会在结果页注入 `ReverseFlightTickets` 面板。

支持三种采集模式：

- `采集当前屏幕`：只读取当前可视区域已渲染航班卡片。
- `采集已渲染列表`：扫描页面 DOM 中已经存在的航班卡片，不限当前屏幕。
- `智能滚动采集`：手动触发后在当前结果列表内逐屏滚动、等待渲染、采集并去重，可随时停止。

导入并排序：

```bash
rft import-browser path/to/rft-ctrip-2026-05-29.json --output table
```

导入并保存 SQLite 快照：

```bash
rft import-browser path/to/rft-fliggy-2026-05-29.csv --save-snapshot
```

浏览器导入的数据会进入统一 `Offer` 模型，参与已有排序、风险标记、推荐和快照流程。详细操作流程见 `docs/SCRIPT_PRICE_WORKFLOW.md`。

## Deep Link Provider

当前默认接入的是 Skyscanner、Trip.com、飞猪的人工核验 deep link provider。它们的定位是“把同一个查询条件转成可打开的核验链接”，不是页面抓取器。

只查询指定 provider：

```bash
rft search --origin PVG --destination LAX --departure-date 2026-10-01 --provider skyscanner --provider trip
```

包含研究型人工核验入口：

```bash
rft search --origin PVG --destination LAX --departure-date 2026-10-01 --include-research
```

## API Provider

Duffel sandbox/API 和 Amadeus Self-Service test API 已有 connector。无凭据时会返回结构化错误，不会中断整个搜索。

Duffel sandbox 查价：

```bash
rft search --origin LHR --destination JFK --departure-date 2026-10-01 --provider duffel
```

查看 Duffel sandbox 原始测试航司结果：

```bash
rft search --origin LHR --destination JFK --departure-date 2026-10-01 --provider duffel --include-test-carriers
```

往返 Duffel sandbox 查价：

```bash
rft search --origin LHR --destination JFK --departure-date 2026-10-01 --return-date 2026-10-15 --provider duffel --output json
```

Amadeus Self-Service test API 查价：

```bash
rft search --origin PVG --destination LAX --departure-date 2026-10-01 --return-date 2026-10-15 --provider amadeus --output json
```

验证缺凭据 API provider 的错误隔离：

```bash
rft search --origin PVG --destination LAX --departure-date 2026-10-01 --provider duffel --output json
```

该命令在未配置 `DUFFEL_API_TOKEN` 时会返回 `ProviderNotConfigured`，但 CLI 不会崩溃。

## 测试航司和本地过滤

Duffel sandbox 会返回测试航司 Duffel Airways，IATA 代码为 `ZZ`。CLI 默认在本地过滤 `ZZ` 航班，避免把 sandbox 测试航班当成真实候选；需要调试原始 Duffel sandbox 结果时，可加 `--include-test-carriers`。

本地排除指定航司：

```bash
rft search --origin LHR --destination JFK --departure-date 2026-10-01 --provider duffel --exclude-carrier BA
```

也可以追加多个排除项：

```bash
rft search --origin LHR --destination JFK --departure-date 2026-10-01 --exclude-carrier BA --exclude-carrier UA
```

## API 凭据

本项目不会提交真实 API 凭据；请只在本地 `.env` 中填写。仍需要你后续手动处理的变量：

- `AMADEUS_CLIENT_ID`
- `AMADEUS_CLIENT_SECRET`
- `SKYSCANNER_API_KEY`
- `TRIP_API_KEY`
- `FLIGGY_APP_KEY`
- `FLIGGY_APP_SECRET`

`DUFFEL_API_TOKEN` 已可用于本地 Duffel sandbox 查询；`AMADEUS_CLIENT_ID` 和 `AMADEUS_CLIENT_SECRET` 已可用于 Amadeus Self-Service test API 查询。`.env` 不会进入版本库。

可选运行配置：

- `RFT_EXCHANGE_RATES`：静态汇率表，例如 `USD:CNY=7.20,CNY:USD=0.14`；静态值会优先于外部汇率源。
- `RFT_EXCHANGE_RATE_SOURCE`：汇率来源，默认 `static`；可设为 `frankfurter` 启用外部汇率查询。
- `RFT_EXCHANGE_RATE_CACHE_PATH`：外部汇率 JSON 缓存路径，默认 `data/exchange_rates_cache.json`。
- `RFT_EXCHANGE_RATE_CACHE_TTL_SECONDS`：汇率缓存有效期，默认 `86400`。
- `RFT_EXCHANGE_RATE_API_BASE_URL`：Frankfurter API base URL，默认 `https://api.frankfurter.dev/v2`。
- `RFT_EXCHANGE_RATE_TIMEOUT_SECONDS`：外部汇率请求超时秒数，默认 `5`。
- `RFT_PAYMENT_FEE_RATE`：支付手续费率，例如 `0.03`。
- `RFT_BAGGAGE_FEE_AMOUNT`：每个报价统一加上的行李费估算金额。

## 后续 API 接入方式

后续拿到 Skyscanner、Trip.com、飞猪或其他官方/合作 API 后，不需要推翻现有流程。建议按现有 provider 抽象接入：

1. 在 `src/reverse_flight_tickets/providers/` 新增或替换 connector，实现 `FlightProvider.search(request, context)`。
2. 把 API 响应归一化为 `Offer`、`Segment`、`Layover`、`FareComponent`、`ProviderQuote`。
3. 保留 provider 原始关键字段到 `ProviderQuote.raw`，但不要保存 cookie、token 或无关个人资料。
4. 通过 `SearchOrchestrator` 进入现有归一化、汇率、费用、排序、推荐和快照链路。
5. 为成功、缺凭据、超时、异常响应和字段缺失补测试。
6. 在 `compliance/terms.py` 中登记访问方式、生产资质和风险说明。

脚本采价和 API 采价最终都汇入同一套 `SearchRunResult`，区别只在数据源可信度和自动化程度。API 接入后，浏览器脚本仍可作为人工核验或 fallback。
