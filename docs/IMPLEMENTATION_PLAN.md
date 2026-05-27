# ReverseFlightTickets 实施方案

## 目标

建设一个基于 Python 的反向票查询与订购辅助工具，核心能力是把航空公司、GDS/NDC 聚合商、第三方 OTA 与人工搜索工具的价格结果统一归一化、比价、追踪，并为用户输出可执行的购买建议。

第一阶段重点是查价聚合与反向票识别，不直接自动付款出票。订购能力应先做成“跳转购买/人工确认/订单记录”，等 API 合作资质、支付、出票、退改签和风控流程清楚后再扩展。

## 概念边界

- 反向票/外站票：从不同销售地、币种、语言站点、出发地组合或多城市组合中寻找更低总价。
- Multi-city 拼票：用多段搜索发现特定组合价，可能是同一出票源的多段行程，也可能是分开出票。
- 自转机/分开出票：不同票号之间不保证保护衔接，误机、行李直挂、退改签风险更高。
- Hidden-city/弃程票：与反向票不是一类策略。风险更高，通常不应作为本项目默认搜索策略。

## 调研结论

| 来源 | 用途判断 | 接入方式 | 风险/限制 |
| --- | --- | --- | --- |
| Google Flights | 人工验证、趋势和价格图参考；可借鉴 multi-city 交互 | 无官方公开查价 API；可研究开源封装，但稳定性和合规性需评估 | 页面/非官方接口易变；不建议作为唯一生产数据源 |
| Skyscanner Multi-city | 适合人工拼外站票，也有官方 Flights Live Prices API 文档 | 优先走官方 Partner/API | 需要申请权限；不同市场返回内容可能不同 |
| Kiwi Nomad | 自动调整多城市顺序，适合发现拼接思路 | 若可获得合作 API 则接入；否则作为人工对照 | 常出现自转机/分开出票，必须显式标记风险 |
| punitarani/fli | Google Flights CLI/MCP/Python 库，最适合作为原型研究对象之一 | 可作为 connector 原型或参考 | 非官方 Google Flights 封装，稳定性需压测 |
| LetsFG/LetsFG | 航班搜索/订票代理方向，提供 CLI/MCP 思路 | 可研究其工具层和接口抽象 | 覆盖范围、出票链路和 API 可用性需实测 |
| borski/travel-hacking-toolkit | 聚合多个 travel hacking 来源的思路参考 | 作为策略/connector 参考 | 含 Skiplagged 等高风险来源，应分级隔离 |
| ravinahp/flights-mcp | Duffel API 的 MCP 封装，适合学习 Duffel 查询方式 | 可参考 MCP 工具设计，生产接入应直接对 Duffel API | Duffel 需要账号、权限和商业条款 |
| flightclaw | 偏价格追踪 | 可参考监控和告警模型 | 不适合作为核心查价源 |
| Trip.com | 第三方购票平台，适合作为 OTA 价格源 | 优先申请 Trip.com Group/Partner API | 需要合作资质；反爬不可作为默认方案 |
| 飞猪旅行 | 国内 OTA/平台，适合作为中国市场价格源 | 优先走飞猪开放平台或商务合作接口 | API 权限、品类接口和出票责任边界需确认 |
| Duffel | NDC/航司内容聚合，适合 API 化查价和订单流程 | 官方 API | 需要账号、测试/生产资质、支付出票流程设计 |
| Amadeus | GDS/API 聚合，适合全球航班查价和订购 | 官方 API | 生产权限和限额需要申请 |

## 总体设计树

```text
ReverseFlightTickets
├── Interfaces
│   ├── CLI
│   ├── REST API
│   └── MCP Server
├── Search Orchestrator
│   ├── itinerary expansion
│   ├── market/currency expansion
│   ├── concurrent provider query
│   ├── normalization
│   ├── deduplication
│   └── ranking
├── Providers
│   ├── airlines
│   │   ├── direct airline API/NDC
│   │   └── manual/deep-link fallback
│   ├── aggregators
│   │   ├── Duffel
│   │   ├── Amadeus
│   │   └── Skyscanner
│   ├── OTA
│   │   ├── Trip.com
│   │   ├── Fliggy
│   │   └── future providers
│   └── research connectors
│       ├── Google Flights via fli
│       ├── Kiwi/Nomad
│       └── LetsFG/toolkit experiments
├── Domain Model
│   ├── SearchRequest
│   ├── Segment
│   ├── Passenger
│   ├── Offer
│   ├── FareComponent
│   ├── BaggageRule
│   ├── ChangeRefundRule
│   ├── ProviderQuote
│   └── RiskFlag
├── Pricing Engine
│   ├── currency conversion
│   ├── fee/tax normalization
│   ├── payment method fee
│   ├── baggage cost
│   ├── refund/change penalty
│   └── total comparable price
├── Reverse Ticket Strategy Engine
│   ├── market point-of-sale comparison
│   ├── multi-city construction
│   ├── split-ticket detection
│   ├── sale-country/currency arbitrage
│   ├── date flexibility window
│   └── risk scoring
├── Persistence
│   ├── searches
│   ├── quotes
│   ├── price snapshots
│   ├── provider credentials
│   └── user watchlists
├── Booking Assistant
│   ├── provider deep link
│   ├── checkout handoff
│   ├── manual confirmation checklist
│   ├── order record
│   └── post-booking tracking
└── Compliance & Safety
    ├── provider terms registry
    ├── robots/API policy registry
    ├── risk labeling
    ├── audit log
    └── hidden-city exclusion by default
```

## 推荐技术栈

- Python 3.11+
- `httpx`：异步 HTTP 请求（已加入依赖，真实 API provider 待接入）
- `pydantic`：领域模型和 provider 响应校验（已用于核心模型）
- `typer`：CLI（已用于 `rft search`）
- `fastapi`：后续 REST API
- `sqlalchemy` + SQLite/PostgreSQL：搜索和价格快照存储（已支持 SQLite 快照）
- `apscheduler` 或 `celery`：价格追踪任务
- `pytest` + `respx`：connector 单元测试和 HTTP mock（已加入依赖）
- `ruff` + `mypy`：代码质量（已配置）

## 模块结构建议

```text
src/reverse_flight_tickets/
├── cli.py # 输入: 命令行参数或 SearchRequest JSON; 输出: 表格/JSON 搜索结果, 将 SearchRequest 交给 SearchOrchestrator
├── config.py # 输入: 环境变量/.env 中的默认市场、币种、provider token; 输出: AppConfig、ProviderContext credentials
├── domain/
│   ├── itinerary.py # 输入: 用户行程、日期、乘客、舱位、市场/币种偏好; 输出: SearchRequest、Segment、Passenger
│   ├── offer.py # 输入: provider 原始报价归一化字段; 输出: Offer、ProviderQuote、FareComponent、BaggageRule、ChangeRefundRule
│   └── risk.py # 输入: 策略引擎/provider 标记的风险事实; 输出: RiskFlag 枚举供排序、展示、订购清单使用
├── providers/
│   ├── base.py # 输入: SearchRequest + ProviderContext; 输出: list[Offer] 或 ProviderError; 定义 FlightProvider.search 接口和 ProviderCapability
│   ├── duffel.py # 输入: SearchRequest + DUFFEL_API_TOKEN; 输出: Duffel sandbox/API 报价归一化后的 Offer
│   ├── amadeus.py # 输入: SearchRequest + AMADEUS_CLIENT_ID/SECRET; 输出: Amadeus Self-Service 报价归一化后的 Offer
│   ├── skyscanner.py # 输入: SearchRequest; 输出: Skyscanner 人工核验 deep link Offer, 后续可替换官方 API 报价
│   ├── trip.py # 输入: SearchRequest; 输出: Trip.com 人工核验 deep link Offer, 后续可替换 Partner API 报价
│   ├── fliggy.py # 输入: SearchRequest; 输出: 飞猪人工核验 deep link Offer, 后续可替换开放平台/商务 API 报价
│   └── research/
│       ├── fli_google.py # 输入: SearchRequest; 输出: Google Flights/fli 研究核验链接 Offer; 默认不进入生产路径
│       ├── kiwi.py # 输入: SearchRequest; 输出: Kiwi/Nomad 研究核验链接 Offer; 用于自转机/拼接策略研究
│       └── letsfg.py # 输入: SearchRequest + 研究工具上下文; 输出: 研究型 Offer 或 ProviderNotConfigured; 默认隔离
├── search/
│   ├── orchestrator.py # 输入: SearchRequest + providers; 输出: SearchRunResult(offers, provider_runs, warnings), 并发调用并隔离失败
│   ├── expansion.py # 输入: SearchRequest; 输出: SearchVariant 列表, 扩展销售地/币种/后续 multi-city 候选
│   ├── normalize.py # 输入: provider 返回的 Offer; 输出: 补齐默认航段和统一字段后的 Offer
│   ├── filters.py # 输入: normalized Offer + 本地过滤条件; 输出: 排除测试航司/指定航司后的 Offer 与过滤告警
│   ├── rank.py # 输入: normalized Offer; 输出: 按价格、风险、provider 排序后的 Offer
│   └── reverse_strategy.py # 输入: SearchRequest + Offer 风险事实; 输出: StrategyPolicy、risk_score, 默认排除 hidden-city
├── pricing/
│   ├── currency.py # 输入: 金额、源币种、目标币种、汇率表/未来汇率源; 输出: 目标币种金额
│   ├── fees.py # 输入: 税费、服务费、支付费、行李费估算; 输出: FeeBreakdown.total
│   └── compare.py # 输入: 原始价格 + 汇率转换器 + 费用拆分; 输出: comparable_amount
├── booking/
│   ├── handoff.py # 输入: Offer; 输出: BookingHandoff(provider, booking_link, manual_check_required, checklist)
│   └── checklist.py # 输入: Offer.risk_flags、行李/退改签信息; 输出: 购买前人工确认清单
├── storage/
│   ├── models.py # 输入: SearchRequest + Offer; 输出: SearchSnapshot、OfferSnapshot
│   └── repository.py # 输入: SearchSnapshot; 输出: snapshot_id 或快照对象; 当前内存实现, 后续接 SQLite/PostgreSQL
└── monitoring/
    ├── watchlist.py # 输入: SearchRequest + 目标价格/币种; 输出: WatchlistItem
    └── alerts.py # 输入: 最新 Offer + 降价阈值; 输出: PriceDropAlert 或 None
```

## 核心数据模型

```text
SearchRequest
- origin
- destination
- departure_date
- return_date
- segments
- passenger_count
- cabin
- allowed_markets
- allowed_currencies
- max_layover_hours
- include_split_ticket
- include_self_transfer
- include_hidden_city=false

Offer
- provider
- source_market
- currency
- total_amount
- comparable_amount
- segments
- ticketing_type
- baggage
- fare_rules
- booking_link
- expires_at
- risk_flags

RiskFlag
- self_transfer
- split_ticket
- no_checked_bag_transfer
- long_layover
- short_connection
- non_refundable
- provider_unverified
- hidden_city_excluded
```

## 搜索流程

1. 接收用户输入：出发地、目的地、日期、乘客、舱位、可接受市场和币种。
2. 生成候选策略：
   - 标准往返/单程。
   - 外站销售地和币种变体。
   - Multi-city 变体。
   - 可选分开出票变体。
3. 并发调用 provider connectors。
4. 将各 provider 响应归一化为统一 `Offer`。
5. 汇率、税费、行李、支付手续费归一化为可比价格。
6. 去重同航班/同票价组合。
7. 标记风险并排序。
8. 输出建议：
   - 最低价。
   - 最低风险价。
   - 与常规购票方式的差价。
   - 购买入口或人工检查清单。

## Provider 接入优先级

### P0：能稳定开发 MVP

- Duffel sandbox：API 化程度高，适合建立 Offer/Order 模型。
- Amadeus self-service：适合补全查价能力。
- 手动 deep link：对 Google Flights、Skyscanner、Trip.com、飞猪生成可点击查询链接，先不抓取页面。

### P1：需要申请权限

- Skyscanner Flights Live Prices API。
- Trip.com Partner/Flight API。
- 飞猪开放平台或商务合作接口。
- 航司 NDC/direct API。

### P2：研究型 connector

- punitarani/fli。
- LetsFG。
- travel-hacking-toolkit。
- ravinahp/flights-mcp。
- Kiwi/Nomad。

研究型 connector 默认不进入生产查询路径，除非完成稳定性、合规性、限流和测试评估。

## 任务单

### Milestone 0：项目工程化

- [x] 建立 `pyproject.toml`，配置包名、Python 版本、依赖和脚本入口。
- [x] 建立 `src/reverse_flight_tickets` 包结构。
- [x] 配置 `ruff`、`mypy`、`pytest`。
- [x] 建立 `.env.example`，声明 provider token 变量。
- [x] 增加基础 CI：lint、typecheck、test。

### Milestone 1：领域模型和 CLI

- [x] 定义 `SearchRequest`、`Segment`、`Offer`、`ProviderQuote`、`RiskFlag`。
- [x] 实现 `rft search` CLI。
- [x] 支持 JSON 输入和命令行参数输入。
- [x] 输出表格和 JSON 两种格式。
- [x] 增加模型序列化和校验测试。

### Milestone 2：Provider 抽象层

- [x] 定义 `FlightProvider` 协议：`search(request) -> list[Offer]`。
- [x] 定义 provider capability：是否支持 multi-city、market、currency、booking link、order。
- [x] 实现并发查询 orchestrator。
- [x] 实现 provider 超时和失败隔离；重试、限流待真实 API provider 接入时补充。
- [x] 为 provider 响应建立 fixture 测试。

### Milestone 3：MVP 查价源

- [x] 接入 Duffel sandbox（需要本地 `.env` 中的 `DUFFEL_API_TOKEN`）。
- [x] 接入 Amadeus test API（需要 `AMADEUS_CLIENT_ID/SECRET`）。
- [x] 增加 Google Flights/Skyscanner/Trip.com/飞猪 deep-link 生成器。
- [x] 输出各来源原始价、统一价、查询时间和 provider 状态。
- [x] 对无 API 来源明确标记 `manual_check_required`。
- [x] 本地过滤 Duffel sandbox 测试航司 `ZZ`，并支持 CLI 开关查看原始测试结果。

### Milestone 4：反向票策略引擎

- [x] 支持销售地/币种变体搜索。
- [x] 支持 multi-city 候选生成。
- [x] 支持可配置日期弹性窗口。
- [x] 支持 split-ticket 检测和风险标记。
- [x] 默认排除 hidden-city；若未来支持，必须单独开关和强风险提示。
- [ ] 生成“省钱金额 vs 风险”的排序结果。

### Milestone 5：价格归一化和排序

- [ ] 接入汇率源并缓存。
- [ ] 建立税费、服务费、支付手续费字段。
- [ ] 建立行李费用估算模型。
- [ ] 建立退改签风险权重。
- [x] 输出 `lowest_price`、`best_value`、`lowest_risk` 三类推荐。

### Milestone 6：价格追踪

- [x] 存储查询快照。
- [x] 建立 watchlist。
- [ ] 支持定时重新查询。
- [x] 支持降价阈值告警。
- [x] 生成价格趋势报告。

### Milestone 7：订购辅助

- [x] 生成 provider booking link。
- [x] 输出购买前检查清单：行李、退改签、是否分开出票、是否自转机、付款币种。
- [x] 支持人工确认后记录订单。
- [x] 支持订单状态和票号字段。
- [ ] 在获得 API 权限后再实现自动下单。

### Milestone 8：平台化

- [ ] 提供 FastAPI REST 服务。
- [ ] 提供 MCP server，让 LLM/Agent 调用查票工具。
- [ ] 提供 Web UI 或桌面 UI。
- [ ] 增加用户配置、凭据加密和审计日志。

## 合规与风控要求

- 默认只使用官方 API、合作接口或人工 deep link。
- 不把网页反爬绕过作为默认实现方案。
- 每个 provider 维护 `terms.md` 或配置项，记录允许的调用方式、限流和数据使用边界。
- 默认排除 hidden-city 策略。
- 对 split-ticket、自转机、无托运行李保护、退改签不可退等情况必须在结果里显式标记。
- 自动下单前必须有人类确认；生产出票前必须明确出票责任、支付责任、退款责任和隐私数据处理方式。

## MVP 验收标准

- 用户可以运行 CLI 发起一个搜索请求。
- 系统至少返回一个 API provider 的规范化报价，另附多个第三方平台的人工核验链接。
- 输出能展示总价、币种、来源、航段、风险标记和购买入口。
- 同一搜索可保存为价格快照。
- 无凭据时系统给出明确错误，不崩溃。
- 单元测试覆盖领域模型、provider mock、排序和风险标记。

## 需要进一步确认的问题

- 优先市场：国内出发、国际出发，还是全球路线。
- 首批航司范围：是否聚焦中国大陆/亚洲航司。
- 是否需要真实订购，还是先做购买链接和订单记录。
- 预算：是否愿意申请 Duffel、Amadeus、Skyscanner、Trip.com、飞猪等 API 权限。
- 风险偏好：是否允许展示自转机/分开出票，hidden-city 是否永久排除。

## 参考来源

- Google Flights Help: https://support.google.com/travel/answer/2475306
- Skyscanner Developers: https://developers.skyscanner.net/docs/flights-live-prices/overview
- Skyscanner Multi-City API: https://developers.skyscanner.net/docs/flights-live-prices/multiCity
- Kiwi.com Nomad: https://www.kiwi.com/en/nomad/
- Trip.com Developers: https://developers.trip.com/
- 飞猪开放平台: https://open.fliggy.com/
- Duffel Flight API: https://duffel.com/flights
- Amadeus for Developers: https://developers.amadeus.com/
- IATA NDC: https://www.iata.org/en/programs/airline-distribution/retailing/ndc/
- punitarani/fli: https://github.com/punitarani/fli
- LetsFG/LetsFG: https://github.com/LetsFG/LetsFG
- borski/travel-hacking-toolkit: https://github.com/borski/travel-hacking-toolkit
- ravinahp/flights-mcp: https://github.com/ravinahp/flights-mcp
