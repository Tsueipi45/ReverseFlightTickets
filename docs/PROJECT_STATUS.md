# ReverseFlightTickets 当前状态

更新时间：2026-05-27

## 已完成

- 项目工程化：`pyproject.toml`、`src/` 包结构、`.env.example`、`ruff`、`mypy`、`pytest`、GitHub Actions CI。
- CLI：`rft search` 支持命令行参数、JSON 输入、表格/JSON 输出、provider 选择、research provider、SQLite 快照保存。
- 领域模型：`SearchRequest`、`Segment`、`Passenger`、`Offer`、`ProviderQuote`、`RiskFlag`、行李/退改签/中转信息。
- Provider 抽象：统一 `FlightProvider` 协议、capability、provider context、并发查询、超时和失败隔离。
- API provider：Duffel sandbox/API connector、Amadeus Self-Service test API connector。
- Deep link provider：Skyscanner、Trip.com、飞猪、Google Flights research、Kiwi research。
- 搜索扩展：销售地/币种组合、可配置日期弹性窗口。
- 结果处理：归一化、去重、指定航司过滤、基础排序、`lowest_price` / `lowest_risk` / `best_value` 推荐。
- 风险策略：默认标记 hidden-city 排除；统一处理 split-ticket 和 self-transfer 风险标签。
- 持久化：SQLite 搜索快照保存和读取。
- 价格追踪基础：watchlist 模型、内存 watchlist 仓库、降价阈值告警判断。
- 订购辅助基础：booking handoff、购买前检查清单、人工确认订单记录、订单状态和票号字段。
- 测试：覆盖领域模型、CLI、provider mock、Duffel、Amadeus、orchestrator、排序/风险、SQLite、订购/监控。

## 未完成

- Multi-city 候选生成仍未实现，目前只支持已有 segments 和销售地/币种/日期变体扩展。
- 真实汇率源和缓存未接入；费用、行李费、支付费和退改签风险权重仍是基础模型。
- Watchlist 还没有持久化仓库、定时重新查询和价格趋势报告。
- Skyscanner、Trip.com、飞猪仍是人工 deep link，没有接入官方/合作 API。
- FastAPI REST、MCP server、Web/Desktop UI 未实现。
- provider terms registry、凭据加密、审计日志未实现。
- 自动下单未实现；生产出票前仍必须明确 API 资质、支付、出票、退款和隐私责任边界。

## 当前验证

本地验证命令：

```bash
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
```

最近一次本地结果：

- `pytest`：26 passed
- `ruff`：passed
- `mypy`：passed
