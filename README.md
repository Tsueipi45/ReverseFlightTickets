# ReverseFlightTickets

基于 Python 的反向票查询与订购辅助工具。

## 项目简介

ReverseFlightTickets 是一个用于反向票查询与订购流程辅助的 Python 工具。项目目标是整合查询、筛选、下单辅助与状态跟踪能力，让反向票相关操作更自动化、可配置、可追踪。

## 功能规划

- CLI 查价聚合：支持命令行参数和 JSON 请求输入。
- 官方/API provider：已支持 Duffel sandbox 和 Amadeus Self-Service test API。
- 人工核验 deep link：已支持 Skyscanner、Trip.com、飞猪、Google Flights research、Kiwi research。
- 搜索扩展：支持销售地/币种组合、可配置日期弹性窗口和 stopover multi-city 候选。
- 价格归一化：支持静态汇率表、支付费和行李费估算，并在排序前计算可比价。
- 风险标记：支持人工核验、provider 未验证、split-ticket、自转机、hidden-city 默认排除等标签。
- 快照与追踪：支持 SQLite 搜索快照、SQLite watchlist、一次性 watchlist run、简单定时循环、降价阈值告警和趋势摘要。
- 合规基础：内置 provider terms registry 和内存 audit log，用于记录 provider 查询访问方式。
- 订购辅助：支持 booking handoff、购买前检查清单、人工确认订单记录、订单状态和票号字段。

## 实施方案

项目任务单、架构设计树、数据源接入优先级和风控边界见 [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)。
当前完成状态快照见 [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md)。

## 环境要求

- Python 3.11 或更高版本
- Git

## 快速开始

```bash
git clone https://github.com/Tsueipi45/ReverseFlightTickets.git
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

当前默认接入的是 Skyscanner、Trip.com、飞猪的人工核验 deep link provider，不抓取页面。Duffel sandbox provider 和 Amadeus Self-Service test API provider 已支持真实 API 查价。无凭据时会返回结构化错误，不会中断整个搜索。

Duffel sandbox 会返回测试航司 Duffel Airways，IATA 代码为 `ZZ`。CLI 默认在本地过滤 `ZZ` 航班，避免把 sandbox 测试航班当成真实候选；需要调试原始 Duffel sandbox 结果时，可加 `--include-test-carriers`。也可以用 `--exclude-carrier BA --exclude-carrier UA` 追加本地排除的航司代码。

表格输出说明：

- `airlines`：承运/营销航司代码。
- `flights`：航司代码和航班号。
- `depart` / `arrive`：首段起飞时间和末段到达时间；人工核验链接没有结构化航班时间时显示 `-`。
- `travel_time`：总旅行时间，包含飞行和中转。
- `transfers`：中转机场代码。
- `layover_time`：各中转机场停留时间。
- `risks`：风险标签，用于提示人工核验、sandbox/非生产来源、自转机、分开出票等注意事项；它不是程序错误。`provider_unverified` 表示结果来自 sandbox、人工核验或尚未完成生产资质验证的来源。

## 使用范例

单程查询，输出人工核验链接表格：

```bash
rft search --origin PVG --destination LAX --departure-date 2026-10-01
```

往返查询，并比较多个销售地和币种：

```bash
rft search --origin PVG --destination LAX --departure-date 2026-10-01 --return-date 2026-10-15 --markets US,CN --currencies USD,CNY --output json
```

带日期弹性窗口查询：

```bash
rft search --origin PVG --destination LAX --departure-date 2026-10-01 --return-date 2026-10-15 --date-flexibility-days 2 --output json
```

生成 stopover multi-city 候选：

```bash
rft search --origin PVG --destination LAX --departure-date 2026-10-01 --stopover HND --provider duffel --output json
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

本地排除指定航司：

```bash
rft search --origin LHR --destination JFK --departure-date 2026-10-01 --provider duffel --exclude-carrier BA
```

添加 watchlist：

```bash
rft watchlist add --origin PVG --destination LAX --departure-date 2026-10-01 --target-amount 500 --target-currency USD --provider skyscanner
```

列出 watchlist：

```bash
rft watchlist list
```

执行一次 watchlist 查询并保存快照：

```bash
rft watchlist run
```

按固定间隔执行 watchlist；下面示例只跑 3 次：

```bash
rft watchlist schedule --interval-seconds 3600 --iterations 3
```

## 项目结构

```text
ReverseFlightTickets/
├── .github/
│   └── workflows/
│       └── ci.yml
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
│   └── PROJECT_STATUS.md
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

GitHub Actions 会在 push 和 pull request 上运行同样的 lint、typecheck 和 test。

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

- `RFT_EXCHANGE_RATES`：静态汇率表，例如 `USD:CNY=7.20,CNY:USD=0.14`。
- `RFT_PAYMENT_FEE_RATE`：支付手续费率，例如 `0.03`。
- `RFT_BAGGAGE_FEE_AMOUNT`：每个报价统一加上的行李费估算金额。

## License

待定。
