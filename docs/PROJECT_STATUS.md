# ReverseFlightTickets 当前状态

更新时间：2026-05-28

## 已完成

- 项目工程化：`pyproject.toml`、`src/` 包结构、`.env.example`、`ruff`、`mypy`、`pytest`、GitHub Actions CI。
- CLI：`rft search` 支持命令行参数、JSON 输入、表格/JSON 输出、provider 选择、research provider、SQLite 快照保存；`rft watchlist` 支持 add/list/run/schedule。
- 领域模型：`SearchRequest`、`Segment`、`Passenger`、`Offer`、`ProviderQuote`、`RiskFlag`、行李/退改签/中转信息。
- Provider 抽象：统一 `FlightProvider` 协议、capability、provider context、并发查询、超时和失败隔离。
- API provider：Duffel sandbox/API connector、Amadeus Self-Service test API connector。
- Deep link provider：Skyscanner、Trip.com、飞猪、Google Flights research、Kiwi research。
- 搜索扩展：销售地/币种组合、可配置日期弹性窗口、stopover multi-city 候选。
- 结果处理：归一化、去重、指定航司过滤、基础排序、`lowest_price` / `lowest_risk` / `best_value` 推荐，以及“省钱金额 vs 风险”的排序结果。
- 价格归一化：静态汇率表、可选 Frankfurter 外部汇率源、本地 JSON 汇率缓存、支付费率、行李费估算接入搜索链路，排序前计算可比价。
- 风险策略：默认标记 hidden-city 排除；统一处理 split-ticket、self-transfer 和退改签规则风险权重。
- 平台化基础：FastAPI REST 服务、`/api/search`、`/api/providers`、`/health`，以及内置本地 Web UI。
- 持久化：SQLite 搜索快照保存和读取。
- 价格追踪基础：watchlist 模型、内存和 SQLite watchlist 仓库、一次性 watchlist run、简单定时循环、降价阈值告警判断、价格趋势摘要。
- 订购辅助基础：booking handoff、购买前检查清单、人工确认订单记录、订单状态和票号字段。
- 合规基础：provider terms registry、provider 查询内存 audit log。
- 测试：覆盖领域模型、CLI、provider mock、Duffel、Amadeus、orchestrator、排序/风险、SQLite、订购/监控、watchlist、趋势报告、价格归一化和合规基础。

## 未完成

- Multi-city 候选生成已支持显式 stopover；自动 stopover/路线发现仍未实现。
- Watchlist 已有 SQLite 持久化、一次性 run 和本地 interval schedule；分布式后台调度仍未实现。
- Skyscanner、Trip.com、飞猪仍是人工 deep link，没有接入官方/合作 API。
- MCP server 未实现。
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

- `pytest`：49 passed
- `ruff`：passed
- `mypy`：passed
