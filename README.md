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
pip install -e .
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

当前默认接入的是 Skyscanner、Trip.com、飞猪的人工核验 deep link provider，不抓取页面。Duffel、Amadeus 等 API provider 的接口边界已经预留，配置凭据后可按 `FlightProvider.search()` 协议继续实现。

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

建议在提交代码前执行格式化、静态检查与测试。相关命令会随项目工程化配置补充。

## License

待定。
