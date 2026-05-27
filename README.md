# ReverseFlightTickets

基于python的反向票查询订购工具。

## 项目简介

ReverseFlightTickets 是一个用于反向票查询与订购流程辅助的 Python 工具。项目目标是整合查询、筛选、下单辅助与状态跟踪能力，让反向票相关操作更自动化、可配置、可追踪。

## 功能规划

- 反向票信息查询
- 查询条件配置与结果筛选
- 航司、GDS/NDC 聚合商与第三方 OTA 价格聚合
- 订购流程辅助
- 订单状态记录与追踪
- 日志输出与异常处理

## 实施方案

项目任务单、架构设计树、数据源接入优先级和风控边界见 [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)。

## 环境要求

- Python 3.11 或更高版本
- Git

## 快速开始

```bash
git clone <repo-url>
cd ReverseFlightTickets
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

macOS / Linux:

```bash
source .venv/bin/activate
```

安装依赖：

```bash
pip install -r requirements.txt
```

## 使用方式

运行一次基础搜索：

```bash
rft search --origin PVG --destination LAX --departure-date 2026-10-01
```

输出 JSON：

```bash
rft search --origin PVG --destination LAX --departure-date 2026-10-01 --output json
```

保存 SQLite 快照：

```bash
rft search --origin PVG --destination LAX --departure-date 2026-10-01 --save-snapshot
```

默认快照数据库为 `data/reverse_flight_tickets.sqlite3`，也可以用 `--db-url sqlite:///path/to/file.sqlite3` 覆盖。

当前默认接入的是 Skyscanner、Trip.com、飞猪的人工核验 deep link provider，不抓取页面。Duffel、Amadeus 等 API provider 的接口边界已经预留，配置凭据后可按 `FlightProvider.search()` 协议继续实现；无凭据时会返回结构化错误，不会中断整个搜索。

## 使用范例

单程查询，输出人工核验链接表格：

```bash
rft search --origin PVG --destination LAX --departure-date 2026-10-01
```

往返查询，并比较多个销售地和币种：

```bash
rft search --origin PVG --destination LAX --departure-date 2026-10-01 --return-date 2026-10-15 --markets US,CN --currencies USD,CNY --output json
```

只查询指定 provider：

```bash
rft search --origin PVG --destination LAX --departure-date 2026-10-01 --provider skyscanner --provider trip
```

包含研究型人工核验入口：

```bash
rft search --origin PVG --destination LAX --departure-date 2026-10-01 --include-research
```

保存 SQLite 快照到自定义数据库：

```bash
rft search --origin PVG --destination LAX --departure-date 2026-10-01 --save-snapshot --db-url sqlite:///data/example.sqlite3
```

使用 JSON 请求文件：

```json
{
  "origin": "PVG",
  "destination": "LAX",
  "departure_date": "2026-10-01",
  "return_date": "2026-10-15",
  "passenger_count": 2,
  "cabin": "business",
  "allowed_markets": ["US", "CN"],
  "allowed_currencies": ["USD", "CNY"]
}
```

```bash
rft search --json-input examples/search_request.json --output json
```

验证缺凭据 API provider 的错误隔离：

```bash
rft search --origin PVG --destination LAX --departure-date 2026-10-01 --provider duffel --output json
```

该命令在未配置 `DUFFEL_API_TOKEN` 时会返回 `ProviderNotConfigured`，但 CLI 不会崩溃。

## 项目结构

```text
ReverseFlightTickets/
├── src/
│   └── reverse_flight_tickets/
│       ├── cli.py
│       ├── config.py
│       ├── domain/
│       ├── providers/
│       ├── search/
│       ├── pricing/
│       ├── booking/
│       ├── storage/
│       └── monitoring/
├── tests/
├── docs/
│   └── IMPLEMENTATION_PLAN.md
├── pyproject.toml
├── README.md
└── requirements.txt
```

## 开发说明

建议在提交代码前执行：

```bash
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
```

## API 凭据

本项目当前不会申请或填入真实 API 凭据。需要你后续手动处理的变量：

- `DUFFEL_API_TOKEN`
- `AMADEUS_CLIENT_ID`
- `AMADEUS_CLIENT_SECRET`
- `SKYSCANNER_API_KEY`
- `TRIP_API_KEY`
- `FLIGGY_APP_KEY`
- `FLIGGY_APP_SECRET`

## License

待定。
