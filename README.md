# ReverseFlightTickets

基于 Python 的反向票查询与订购辅助工具。

## 项目简介

ReverseFlightTickets 是一个用于反向票查询与订购流程辅助的 Python 工具。项目目标是整合查询、筛选、下单辅助与状态跟踪能力，让反向票相关操作更自动化、可配置、可追踪。

## 功能规划

- CLI 查价聚合：支持命令行参数和 JSON 请求输入。
- 官方/API provider：已支持 Duffel sandbox 和 Amadeus Self-Service test API。
- 人工核验 deep link：已支持 Skyscanner、Trip.com、飞猪、Google Flights research、Kiwi research。
- 浏览器可见报价导入：提供携程/飞猪结果页油猴脚本，只读取已渲染航班卡片，导出 JSON/CSV 后可导入本项目比价、排序和保存快照。
- 搜索扩展：支持销售地/币种组合、可配置日期弹性窗口和 stopover multi-city 候选。
- 价格归一化：支持静态汇率表、Frankfurter 外部汇率源、本地汇率缓存、支付费和行李费估算，并在排序前计算可比价和“省钱金额 vs 风险”建议。
- 风险标记：支持人工核验、provider 未验证、split-ticket、自转机、退改签风险权重、hidden-city 默认排除等标签。
- 快照与追踪：支持 SQLite 搜索快照、SQLite watchlist、一次性 watchlist run、简单定时循环、降价阈值告警和趋势摘要。
- REST/Web UI：提供 FastAPI REST 服务和内置本地 Web UI。
- MCP server：提供 stdio JSON-RPC MCP 工具服务，暴露 provider 列表和查票工具。
- 合规基础：内置 provider terms registry 和内存 audit log，用于记录 provider 查询访问方式。
- 订购辅助：支持 booking handoff、购买前检查清单、人工确认订单记录、订单状态和票号字段。

## 实施方案

项目任务单、架构设计树、数据源接入优先级和风控边界见 [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)。
当前完成状态快照见 [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md)。
Provider、凭据和后续 API 接入说明见 [docs/PROVIDERS.md](docs/PROVIDERS.md)。
当前阶段脚本采价与反向票操作流程见 [docs/SCRIPT_PRICE_WORKFLOW.md](docs/SCRIPT_PRICE_WORKFLOW.md)。

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

浏览器可见报价采集脚本位于 `src/userscripts/flight_offer_collector.user.js`。把它安装到 Tampermonkey/Violentmonkey 后，访问携程或飞猪机票结果页时会出现 `ReverseFlightTickets` 小面板，可选择：

- `采集当前屏幕`：只采集当前可视区域内已经渲染的航班卡片。
- `采集已渲染列表`：扫描页面 DOM 中已经存在的航班卡片，不限当前屏幕。
- `智能滚动采集`：手动触发后在当前结果列表内逐屏滚动、等待渲染、采集并去重，可随时停止。

该脚本只读取浏览器页面 DOM，不自动登录、不处理验证码/滑块、不请求网站内部接口、不遍历日期/航线，也不会把 cookies、token 或报价发送到外部服务器。
更完整的脚本采价、导入、反向票操作流程和 API 替换路径见 [docs/SCRIPT_PRICE_WORKFLOW.md](docs/SCRIPT_PRICE_WORKFLOW.md)。

当前默认 provider、API provider、research provider、凭据和测试航司过滤说明见 [docs/PROVIDERS.md](docs/PROVIDERS.md)。

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

导入油猴脚本导出的 JSON/CSV 并排序：

```bash
rft import-browser path/to/rft-ctrip-2026-05-29.json --output table
```

导入并保存为 SQLite 快照：

```bash
rft import-browser path/to/rft-fliggy-2026-05-29.csv --save-snapshot
```

导入的浏览器报价会标记为 `manual_check_required` 和 `provider_unverified`，用于提醒这些数据来自页面可见信息，需要人工核验后再订购。

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

启动本地 REST API 和 Web UI：

```bash
rft serve --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/` 使用网页界面；REST 端点包括 `GET /health`、`GET /api/providers` 和 `POST /api/search`。

启动 MCP stdio server：

```bash
rft mcp
```

也可以直接使用脚本入口：

```bash
rft-mcp
```

当前 MCP 工具包括 `list_providers` 和 `search_flights`。`search_flights` 返回与 REST/CLI 相同的规范化报价、provider 状态、推荐和风险标签结构。

## 安全边界

- REST API 不接受请求体中的额外字段，快照只写入本地配置的 SQLite 数据库。
- 本地持久化层只接受 SQLite URL，不接受网络数据库 URL。
- 外部汇率源只允许 HTTPS base URL，静态汇率会优先于外部请求。
- Web UI 使用 DOM 文本节点渲染结果，避免把 provider 返回字段当作 HTML 执行。
- 油猴脚本只采集当前浏览器页面已经渲染的可见/列表 DOM；智能滚动模式仍限定在当前搜索结果列表，不做自动登录、验证码处理、接口调用、批量日期/航线遍历或外部上传。
- 自动下单仍未实现；所有购买入口仍是人工核验或 API provider 返回的报价信息。

## 项目结构

```text
ReverseFlightTickets/
├── .github/
│   └── workflows/
│       └── ci.yml
├── src/
│   ├── reverse_flight_tickets/
│       ├── api.py
│       ├── cli.py
│       ├── config.py
│       ├── mcp_server.py
│       ├── domain/
│       ├── providers/
│       ├── search/
│       ├── pricing/
│       ├── booking/
│       ├── storage/
│       ├── monitoring/
│       └── importers/
│           └── browser_exports.py
│   └── userscripts/
│       └── flight_offer_collector.user.js
├── tests/
├── docs/
│   ├── IMPLEMENTATION_PLAN.md
│   ├── PROJECT_STATUS.md
│   ├── PROVIDERS.md
│   └── SCRIPT_PRICE_WORKFLOW.md
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

本项目不会提交真实 API 凭据；请只在本地 `.env` 中填写。可用变量、provider 状态和后续 API 接入步骤见 [docs/PROVIDERS.md](docs/PROVIDERS.md)。

## License

待定。
