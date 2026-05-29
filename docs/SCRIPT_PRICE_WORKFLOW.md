# 当前阶段：脚本采价与反向票操作流程

更新时间：2026-05-29

本文档说明当前阶段如何用浏览器脚本获取携程/飞猪页面可见价格，并把这些价格导入 ReverseFlightTickets 做比价、排序和快照记录。旧的规划文档继续保留在 `docs/IMPLEMENTATION_PLAN.md`，provider 细节集中在 `docs/PROVIDERS.md`。

## 当前结论

现阶段已经把“反向票”的操作流程厘清为一条可执行链路：

1. 明确同一行程的查询条件：出发地、目的地、日期、乘客、舱位。
2. 在不同页面或销售入口人工打开同一条件的搜索结果。
3. 用脚本采集页面已经渲染出的真实可见报价。
4. 导出 JSON/CSV，通过 CLI 或 Web UI 导入项目统一模型。
5. 在本地完成排序、风险标记、快照记录和后续对比。
6. 订购前仍由人打开原始链接核验价格、退改签、行李、中转和出票条件。

这条链路证明了核心业务流程不依赖某一个具体 API：只要能得到“价格、航司、航班号、起降时间、经停/中转、链接”等字段，就可以进入统一比价和快照系统。后续拿到官方/合作 API 时，只需要把 API 响应归一化为同样的 `Offer` 模型即可。

## 反向票概念边界

本项目里的反向票/外站票，是指围绕同一旅行需求，比较不同销售地、币种、OTA、航司入口、行程表达方式或多城市组合下的总价差异。

它不是默认的 hidden-city/弃程票策略。Hidden-city 风险更高，可能违反承运条款，项目默认排除。

脚本采价阶段重点解决的是“把不同页面上的价格带回本地统一比较”。因此当前流程强调：

- 同一行程条件要先人工确认一致。
- 报价来自页面可见结果，不代表最终可出票价格。
- 所有浏览器导入报价都标记 `manual_check_required` 和 `provider_unverified`。
- 排序结果是辅助决策，不是自动购买指令。

## 脚本采价流程

安装脚本：

1. 打开 `src/userscripts/flight_offer_collector.user.js`。
2. 将脚本安装到 Tampermonkey 或 Violentmonkey。
3. 打开携程或飞猪机票搜索结果页。
4. 等页面结果渲染出来后，使用右下角 `ReverseFlightTickets` 面板。

采集模式：

- `采集当前屏幕`：最保守，只读取当前可视区域内的航班卡片。
- `采集已渲染列表`：读取当前页面 DOM 中已经存在的航班卡片。
- `智能滚动采集`：手动触发后在当前搜索结果列表内逐屏滚动、等待渲染、采集、去重，可随时停止。

导出方式：

- 复制 JSON。
- 复制 CSV。
- 下载 JSON。
- 下载 CSV。

推荐优先使用 JSON，因为它会保留 `collection_mode`、`collection`、`page_url`、`captured_at`、`request` 和每条报价的结构化字段。

## 导入与比价

Web UI 导入：

1. 启动本地服务：

   ```bash
   rft serve --host 127.0.0.1 --port 8001
   ```

2. 打开 `http://127.0.0.1:8001/`。
3. 在 `Import Browser Offers` 区块选择导出的 JSON/CSV 文件，或直接粘贴导出内容。
4. 可选填写目标币种并勾选 `Snapshot`。
5. 点击 `Import offers`，导入结果会显示在同一个 Offers 表和 Recommendations 区块。

Web UI 中 `Snapshot` 默认勾选。保存后，同一航线、同一出发/返程日期、同一乘客数和舱位的后续搜索，会自动把 SQLite 中已经保存的脚本报价与当前 provider 返回结果合并展示。合并时不要求销售地、币种或 provider 完全相同，因此飞猪/携程脚本快照可以和 Duffel、Amadeus、Skyscanner deep link 等来源一起出现在 Offers 表与 Recommendations 区块。

推荐区使用聚合后的 `aggregate_recommendations`。如果跨币种比较需要排序到同一目标币种，请在 `.env` 中配置静态汇率 `RFT_EXCHANGE_RATES`，或启用 `RFT_EXCHANGE_RATE_SOURCE=frankfurter`。缺少汇率时，外币历史报价仍会出现在聚合列表中，但不会被当作目标币种价格参与最低价推荐。

Web UI 还提供 `Currency Tool`，可以直接用当前项目配置换算单笔金额。命令行也可以使用同一套配置：

```bash
rft fx 2225 --from CNY --to USD
```

CLI 导入：

导入并输出表格：

```bash
rft import-browser path/to/rft-ctrip-2026-05-29.json --output table
```

导入并保存快照：

```bash
rft import-browser path/to/rft-fliggy-2026-05-29.csv --save-snapshot
```

保存到自定义 SQLite：

```bash
rft import-browser path/to/rft-ctrip-2026-05-29.json --save-snapshot --db-url sqlite:///data/browser_prices.sqlite3
```

导入后，项目会做这些事：

- 把浏览器导出转换成统一 `SearchRequest` 和 `Offer`。
- 提取价格、币种、航司/航班号、起降时间、经停/中转、链接。
- 按可比价格和风险标记排序。
- 给浏览器来源报价加上人工核验风险。
- 可选择保存 SQLite 快照，用于后续对比和趋势记录。

## 当前已经厘清的操作模型

脚本采价使反向票流程从“手工看页面”变成了“人工触发采集，本地结构化比较”：

- 查询条件由人控制，避免自动遍历日期/航线。
- 价格来自用户当前打开的真实结果页，避免直接调用未知内部接口。
- 数据离开浏览器后只进入本地项目，不上传外部服务器。
- 排序、快照、风险标记与 provider/API 来源共用同一套模型。
- 最终购买仍回到原页面或官方入口人工核验。

因此，当前阶段已经可以完成反向票概念验证：

1. 比较同一行程在不同 OTA 页面上的可见价格。
2. 把每次采集保存为本地快照。
3. 通过排序找出低价候选。
4. 通过 `risks` 字段识别人工核验、未验证来源、中转/分开出票等注意事项。
5. 形成可复查的价格记录，而不是只依赖截图或手工笔记。

## 安全和合规边界

脚本不会做这些事：

- 不自动登录。
- 不处理验证码/滑块。
- 不请求网站内部接口。
- 不批量遍历日期或航线。
- 不把 cookies、token 或报价发到外部服务器。
- 不自动下单或自动付款。

智能滚动只是在当前用户已打开的结果列表内滚动页面，目的是让前端继续渲染用户可见的列表内容。它不是后台抓取器，也不是接口爬虫。

## 后续 API 接入

如果后续拿到携程、飞猪、Trip.com、Skyscanner、Duffel、Amadeus 或其他官方/合作 API，可以在现有流程上替换“采价来源”，不用替换“比价流程”。

API 接入后的目标链路：

```text
SearchRequest
-> API provider connector
-> normalized Offer
-> SearchRunResult
-> ranking / recommendations
-> SearchSnapshot
-> manual booking handoff
```

脚本采价当前承担的是“可见价格采集”和“流程验证”角色。API 接入后，它可以继续作为人工核验、fallback 或跨来源对照工具。

## 使用建议

- 同一轮比较中，尽量保持日期、乘客、舱位、行李条件一致。
- 每次采集后尽快导入保存快照，避免页面价格刷新后无法复查。
- 低价候选必须回到原链接人工核验最终含税价、退改签、行李和中转责任。
- 如果同一航班在多个来源价格差异很大，优先检查币种、税费、是否分开出票、是否包含托运行李。
- 对自转机、分开出票、长中转和不可退改报价，不应只按低价排序直接决策。
