# ReverseFlightTickets 当前状态

更新时间：2026-05-29

## 已完成

- 项目工程化：`pyproject.toml`、`src/` 包结构、`.env.example`、`ruff`、`mypy`、`pytest`、GitHub Actions CI。
- CLI：`rft search` 支持命令行参数、JSON 输入、表格/JSON 输出、provider 选择、research provider、SQLite 快照保存；`rft watchlist` 支持 add/list/run/schedule。
- 领域模型：`SearchRequest`、`Segment`、`Passenger`、`Offer`、`ProviderQuote`、`RiskFlag`、行李/退改签/中转信息。
- Provider 抽象：统一 `FlightProvider` 协议、capability、provider context、并发查询、超时和失败隔离。
- API provider：Duffel sandbox/API connector、Amadeus Self-Service test API connector。
- Deep link provider：Skyscanner、Trip.com、飞猪、Google Flights research、Kiwi research。
- 浏览器可见报价采集：携程/飞猪油猴脚本，支持当前屏幕、已渲染列表、智能滚动采集，导出 JSON/CSV；飞猪 `searchJourney` URL 可解析往返城市和日期。
- 浏览器报价导入：`rft import-browser` 和 Web UI `Import Browser Offers` 支持导入脚本 JSON/CSV，归一化为 `Offer` 后参与排序、推荐和 SQLite 快照；导入器可从飞猪 `page_url` 兜底补齐缺失查询日期。
- Web UI 聚合：`/api/search` 和 `/api/import-browser` 会按同航线、日期、乘客和舱位读取 SQLite 历史快照，把已保存的脚本报价与当前 provider 结果合并展示和推荐。
- 搜索扩展：销售地/币种组合、可配置日期弹性窗口、stopover multi-city 候选。
- 结果处理：归一化、去重、指定航司过滤、基础排序、`lowest_price` / `lowest_risk` / `best_value` 推荐，以及“省钱金额 vs 风险”的排序结果。
- 价格归一化：静态汇率表、可选 Frankfurter 外部汇率源、本地 JSON 汇率缓存、支付费率、行李费估算接入搜索链路，排序前计算可比价。
- 汇率工具：`rft fx`、`/api/currency/convert` 和 Web UI `Currency Tool` 支持使用同一套汇率配置做手动换算。
- 风险策略：默认标记 hidden-city 排除；统一处理 split-ticket、self-transfer 和退改签规则风险权重。
- 平台化基础：FastAPI REST 服务、`/api/search`、`/api/import-browser`、`/api/providers`、`/health`，以及内置本地 Web UI。
- MCP server：提供 stdio JSON-RPC MCP 服务，包含 `list_providers` 和 `search_flights` 工具。
- 安全加固：API 请求禁止额外字段和客户端覆盖数据库 URL；SQLite 仓库限制本地 SQLite URL；外部汇率源强制 HTTPS；MCP 支持 Content-Length framing；Web UI 结果渲染避免直接拼接未信任 HTML。
- 持久化：SQLite 搜索快照保存和读取。
- 价格追踪基础：watchlist 模型、内存和 SQLite watchlist 仓库、一次性 watchlist run、简单定时循环、降价阈值告警判断、价格趋势摘要。
- 订购辅助基础：booking handoff、购买前检查清单、人工确认订单记录、订单状态和票号字段。
- 合规基础：provider terms registry、provider 查询内存 audit log。
- 测试：覆盖领域模型、CLI、provider mock、Duffel、Amadeus、orchestrator、排序/风险、SQLite、订购/监控、watchlist、趋势报告、价格归一化和合规基础。

## 未完成

- Multi-city 候选生成已支持显式 stopover；自动 stopover/路线发现仍未实现。
- Watchlist 已有 SQLite 持久化、一次性 run 和本地 interval schedule；分布式后台调度仍未实现。
- Skyscanner、Trip.com、飞猪仍是人工 deep link，没有接入官方/合作 API。
- 浏览器脚本采价是当前携程/飞猪真实页面可见价格的阶段性方案；后续拿到官方/合作 API 后应接入 provider connector，并保留脚本作为人工核验/fallback。
- 凭据加密和持久审计日志未实现。
- 自动下单未实现；生产出票前仍必须明确 API 资质、支付、出票、退款和隐私责任边界。

## 当前验证

本地验证命令：

```bash
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
```

最近一次本地结果：

- `pytest`：73 passed
- `ruff`：passed
- `mypy`：passed
