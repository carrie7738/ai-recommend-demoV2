# V2 Acceptance Report

日期：2026-09-04。**总体状态：本轮 DeepSeek 技术验收通过，业务场景 6/6。**

本报告统一记录 DeepSeek Provider、Live Intent、UI 和韧性证据。用户已确认 Fruit 两阶段验收口径，
修正后重新执行完整六场景并通过。范围包括真实 API 与程序化 UI 验证；不等同于人工浏览器签署或生产认证。

## 1. 验收模型与版本边界

| 项目 | 本轮锁定值 |
| --- | --- |
| Provider / API endpoint | DeepSeek / `https://api.deepseek.com` |
| 配置模型 / 所有最终实际响应模型 | `deepseek-v4-flash` / `deepseek-v4-flash` |
| temperature / thinking | 0.3 / disabled |
| structured max tokens | 16384 |
| 工作区基线 HEAD | `029d81309c1d15a188b24e2fc2cc32b525fe3315` |
| 最终六场景开始时间 | 2026-09-04 07:17:48 UTC |

验收显式指定模型，不使用 `deepseek-chat` 别名。`.env.example` 已锁定上述模型；本机已有
`.env` 配置相同，未改动密钥。默认代码中的兼容配置仍可被环境变量覆盖，验收不能依赖未核对的默认值。
模型、Prompt、数据或参数改变后必须重新验收，不能沿用此表结果。模型名不是不可变的供应商权重快照，
本轮只证明响应中的 model 字段一致，不证明后端版本永远不变。

本轮只调用 DeepSeek，未运行 Gemini、GLM 或跨 Provider A/B；原 adapters、A/B 脚本保留。
用户已明确授权本轮 Demo 请求、六个门店上下文字段及现有 V2 安全决策上下文向 DeepSeek 出站。
沙箱连接失败和首次自动审批拒绝均不算模型验收；获得具体出站授权后的调用才形成真实证据。

本轮没有修改 Candidate、Optimizer、Validator、Provider、V1 fallback、正式 Excel、
Evaluation Parameters 或场景映射；仅按用户确认修正 Fruit 验收断言，并让 A/B runner 传递相同库存证据。
没有安装或更新依赖。

## 2. Live Intent 修复与复验

`store_context` 仍严格要求模型输出 `{}`，六个可信字段由本地补入；不能通过放宽 Schema 解决问题。
最初独立 C001 调用已经通过：实际模型 `deepseek-v4-flash`，原始 `store_context={}`，
完整 Schema 通过、预算 1000、高客流、可信身份 C001、Intent source 为 live；延迟 7149.5 ms，
输入/输出 token 1742/619。这一调用在下述进一步修复前完成，不代替最终版本复验。

完整场景执行进一步暴露两个 Prompt 缺口：

1. 第一轮 0/6：`objective` 仅描述为 uppercase business objective，模型返回
   `STOCKOUT_PREVENTION`、`PROMOTION_SUPPORT`、`REPLENISHMENT`，与本地枚举冲突，Intent 降级。
2. 补齐 objective/occasion 枚举后的第二轮 5/6：Fruit 的 `soft_preferences` 出现非法 `operator`，
   说明只维护文字摘要仍可能遗漏嵌套合同。该轮 Low Budget 发生一次合法 constrained retry；
   这与 SDK transport retry 是不同层次。
3. 最终将已有 `INTENT_JSON_SCHEMA` 原样附加到 Intent 系统消息，明确所有 required、enum 和
   additionalProperties 约束；保持 Schema、归一化、fallback 和校验逻辑不变。

最终六场景 **6/6 原始 Intent 完整 Schema 通过、`store_context={}`、Intent source=live**。
C001 最终 UI 流程的原始 Intent 也通过，见第 4 节。新增测试校验实际发往 JSON-object provider
的枚举与完整 Schema；旧 Prompt 在该回归测试上失败，当前版本通过。

## 3. 完整六场景结果

使用原 `load_scenario_bindings`；`_scenario_contract_violations` 的 Fruit 分支按用户确认改为
模型软偏好与库存约束下的执行结果两个阶段。其他场景门槛、Schema、Validator 和预算检查不变。
全部场景绑定 C051 / V2 Target Cafe；除 Christmas 为 2026-12-10，其余 evaluation date 均为
2026-06-02。场景文本中的 Cafe Store 001 是现有视频文本，不等于 harness 的可信身份。
01 与 06 都映射 V2-001，是原有设计。

| 场景 | ScenarioId | 业务验收 | 最终行数 | 金额 NZD | 余额 NZD | 模型调用延迟合计 ms |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 01_high_traffic | V2-001 | PASS | 6 | 538 | 462 | 12538.7 |
| 02_holiday_promo | V2-018 | PASS | 2 | 1000 | 0 | 14409.5 |
| 03_low_budget | V2-004 | PASS | 2 | 290 | 10 | 19664.2 |
| 04_long_shelf | V2-006 | PASS | 6 | 538 | 462 | 14227.1 |
| 05_fruit_focus | V2-008 | PASS | 6 | 506 | 294 | 12711.5 |
| 06_no_budget | V2-001 | PASS | 6 | 538 | 不适用 | 11935.4 |

最终一轮共 13 次真实模型调用，均返回锁定模型、API/JSON 成功且未截断。六场景均为
`V2=SUCCESS`、`Validator=PASS`，repair=0、V1 fallback=false、Intent fallback=false。
Low Budget 使用一次合同允许的 constrained retry，重新决策、优化和校验后通过；其他场景 retry=0。
这是业务层重试的真实成功证据，不证明 SDK transport retry 行为。

已通过的断言包括预算、高客流定性强度、Christmas Store Event baseline、低预算高优先级保留、
长保质期选择与理由，以及无预算模式不产生预算余额/预算截断。该单次最终执行不构成随机稳定性统计。

### Fruit 已关闭：用户确认的两阶段验收

最终原始 Intent 正确包含 Fruit category preference 和 CATEGORY soft preference，未作为硬过滤。
模型推荐了 P206、P207，但 Optimizer 将它们标为 `NO_EXECUTABLE_QUANTITY`：

| Fruit SKU | 基线来源 | 需求基线 | 当前库存 | 库存缺口 | HIGH / MEDIUM / LOW 请求量 |
| --- | --- | ---: | ---: | ---: | --- |
| P206 | RECENT_STORE | 9.333333333333332 | 10 | 0 | 0 / 0 / 0 |
| P207 | RECENT_STORE | 9.333333333333332 | 10 | 0 | 0 / 0 / 0 |

依据现有 Optimizer，`max(baseline - current_stock, 0) × intensity` 必须为零。
第三轮的旧验收要求偏好类别出现在最终采购单、且其最终入选率不低于非偏好类别，曾得到以下失败（保留历史，不重标为 PASS）：

- `PREFERRED_CATEGORY_NOT_SELECTED`
- `PREFERRED_CATEGORY_SELECTION_RATE_LOWER high=0.000, low=0.600`

这不是连接、模型身份、store_context、预算或 Validator 错误；反复调用模型不能解决零库存缺口。
不能为了通过而让模型输出数量、抬高参数、减少库存或忽略断言。

**用户已确认并实施**：保持业务计算与正式数据，分别验证：

1. 模型至少推荐一个偏好类别候选，且偏好类别的模型推荐率不低于非偏好类别；不要求不必要的采购。
2. 从正式 workbook、可信 store_id 和 effective_as_of_date 复核需求基线与当前库存。
   零库存缺口的偏好候选不得出现在采购单；若模型推荐它，Optimizer 必须明确返回 `NO_EXECUTABLE_QUANTITY`。
   推荐候选有正库存缺口却不进入采购单时仍失败。缺少 workbook 证据不能豁免。
3. 仅当全部推荐项都是已证明零缺口的偏好商品时允许合法空方案；不是任意放过空结果。

最终 Fruit 场景：P206/P207 都被模型推荐，偏好类别推荐率 2/2，非偏好类别推荐率 10/10；
二者零采购且原因正确。其他商品的最终采购共 6 行、NZD 506，剩余 NZD 294。
原脚本和 A/B runner 共用修正后的检查，不调用模型生成数量、不改库存、不改参数。
新增 8 项回归分别覆盖正常零缺口、忽略偏好、推荐率逆转、零缺口误采购、缺少原因、正缺口遗漏、
缺少 workbook，以及全部推荐项零缺口的合法空方案。

## 4. C001 UI 验证

同一最终产品代码使用 `AppTest.from_file(app.py)` 执行真实 Streamlit 主函数、提交真实请求、调用真实
DeepSeek Intent 和 Decision；观察器仅记录响应/metrics，不替换响应或预注入采购结果。

请求：`For Cafe Store 001, high traffic is expected next week. Budget is NZD 1000.`

- StoreResolver / StructuredIntent 均为 C001；与 C051 harness 独立报告。
- 首屏无采购数据；提交后无 AppTest exception 或 UI error。
- 原始 `store_context={}`，Schema 通过，可信身份由本地保留，Intent=live。
- Intent：5821.0 ms，3708 输入 / 618 输出 tokens。
- Decision：7169.6 ms，3521 输入 / 1703 输出 tokens。
- 两次实际响应模型均为 `deepseek-v4-flash`，无截断，API/JSON 成功。
- V2 SUCCESS、Validator PASS、无 V1/Intent fallback。
- HTML 采购表及 Validated 标记显示，12 行，NZD 242，余额 NZD 758；模型及 Intent live 状态可见。

最初 UI 观察脚本误用 dataframe 数量判断采购表，而本项目实际输出 HTML table。
该观察断言已按现有渲染代码纠正；没有修改 UI 代码。最终流程重新真实执行并通过所有观察断言。

该证据产生于 Fruit 验收脚本修正之前；随后未改动产品代码，Intent 文件 hash 与最终六场景相同。
本轮是**真实 API + Streamlit AppTest**，不是新的浏览器截图/布局检查，也不代表用户人工 UI 签署。
历史浏览器曾验证布局可读，但当时 Intent fallback，不能将那次截图升级为当前全链路通过证据。

## 5. 本地回归与韧性范围

最终代码执行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

**177 tests，70.110 秒，OK，退出码 0**。未出现 import/path/file-not-found 错误。
必须使用已有虚拟环境；系统 Python 缺依赖的旧失败不属于本次完整测试结果。

保留的韧性证据：9 个 fake-client 回归覆盖缺 key、timeout、429、空内容、非法 JSON、
schema-capable Intent 仍本地校验、Intent transport 失败保留可信身份、非法 AvailableStock
按无库存处理、非法 AvgCost 拒绝优化。其他现有测试覆盖空候选、库存/供应/预算/SalesUnit、
repair 日期与可信成本、一轮 constrained retry、失败不展示可执行 V2 方案、V1 fallback 保留原始失败原因。

离线 AppTest 继续覆盖合法零方案、Validator 失败隐藏采购表、V1 fallback 状态及 HTML 转义。
这些测试不是网络异常实测。仍未验证：

- 真实 DeepSeek timeout/429/非法响应注入，以及 SDK transport retry、连接超时和 backoff 行为。
- provider 返回非 object JSON 时 metrics 分支的专门回归。
- 主函数真实异常后完整 V1 fallback 状态迁移的端到端异常注入；最终成功路径已真实执行。
- Gemini/GLM live、跨 Provider A/B、供应商配额恢复；均不属于本轮 DeepSeek 范围。
- 参数生产校准、重复运行统计可靠性、人工浏览器签署及部署实测。

## 6. 复现与证据保管

已有场景脚本可按已确认口径复现业务验收；模型输出具有随机性，重新执行须重新检查结果：

```powershell
.\.venv\Scripts\python.exe scripts\v2_scenario_regression.py --provider deepseek --model deepseek-v4-flash --summary
```

最终六场景 runner、manifest、完整结果和本地测试日志位于
`outputs/deepseek-acceptance/20260904-approved/`：`run.py`、`manifest.json`、`scenarios.json`、`unit-tests.log`。
C001 真实 UI 证据、Fruit 库存诊断及前面失败轮次仍在 `outputs/deepseek-acceptance/20260904-final/`，
没有用通过结果覆盖旧失败记录。两处均按仓库规则忽略、不纳入 Git。
报告摘要长期保留；本地输出不是远端仓库附件。API 密钥和请求 headers 未写入证据。

SHA-256（原始文件字节；换行转换会改变文本文件 hash）：

| 文件 | SHA-256 |
| --- | --- |
| 正式 Excel | `34d9c7c331ff973068ac14eddc275935cc13f8b2cd277a48247a3af9cc95bb8b` |
| 最终 services/intent_parser.py | `91493f98d59a75e327bca72096437b838b91be862c430d9233eed1b7ff2012d7` |
| V2_EVALUATION_PARAMETERS.md | `ea59cb10c4e4a79df902edaa2625a9e94ad57fdc865f51f2bcd1c0e15f608097` |
| 视频 scenarios.json | `b5f8bb9019ed9617f09af55e73878682283158b1d9e29d69f67a14320fb0b7fe` |
| 最终六场景证据 scenarios.json | `cb12016a3b000c7a17c21a5bd2e4bd36312814ff1381b58fa8ec66276f9f6da0` |
| 最终 live_ui.json | `4c59d73aef558bbbccac5fa7b77895c66e39b784f4aef4ba17677aa2fcd5b702` |
| fruit_diagnosis.json | `981ed75c56c2b128c3afd951441d15c6802121eda9854f3d86c21dea07aec2b6` |
| scripts/v2_scenario_regression.py | `f4b07e921bd1155b084797edbb5eb751ba835a71a2b9d0293c2246bde0ff5a07` |
| scripts/ab_evaluation.py | `7a47b94d2b1a3ebfea1aadc182f6fe41b2e16f1f7b0a7cf4149ac3ef165bed04` |

## 7. 文档收敛

有效结论、真实证据、失败历史和未验证边界均已汇入本报告。六场景和本地回归全部通过后，
按用户指令删除四份阶段文档：`V2_MODEL_PROVIDER_TESTING.md`、`V2_UI_ACCEPTANCE.md`、
`V2_RESILIENCE_REVIEW.md`、`V2_REMAINING_TASKS.md`。历史版本可从 Git 追溯。
Architecture Contract、Evaluation Parameters、正式 Demo 数据、脚本、全部既有测试继续保留。
本轮未提交或推送。
