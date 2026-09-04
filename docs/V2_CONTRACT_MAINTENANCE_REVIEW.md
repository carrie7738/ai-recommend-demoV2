# V2 合同维护审计（Task 15 / Task 17）

审计日期：2026-09-04  
范围：只读核对 `V2FeaturePolicy`、`OptimizerPolicy`、V2 评估参数文档、Structured Intent 与 V1 兼容字段消费者，以及六场景业务断言。  
运行边界：本轮保持现有 `INITIAL_EVAL_VALUE` 参数，不调值；没有运行真实模型 API 或 A/B；没有输出 `.env` 内容；不提交、不推送。

## 结论

当前运行时工作簿由 `config/settings.py` 默认指向 `data/AI_Demo_Data_Pack_V2_Large.xlsx`。该工作簿有 `V2FeaturePolicy`，没有名为 `OptimizerPolicy` 的工作表。`OptimizerPolicy` 是 `services/local_optimizer.py` 中的不可变代码配置，运行结果会把相同值写入 `evaluation_parameters`。

工作簿、代码和 `docs/V2_EVALUATION_PARAMETERS.md` 的参数值一致。可配置的评估项仍是 `INITIAL_EVAL_VALUE`；发现历史回看 12 个月和事件基线顺序属于已确认的 V2 语义。没有证据支持把其余参数标记为生产确认值。

Structured Intent 已是 V2 主链路的输入；V1 兼容字段仍由会话匹配、V1 fallback、旧推荐引擎和 AI Understanding 展示使用。当前不应在验收前做生产结构重构。提示词存在合同字段重复，且旧的 `store_context` 提示语义会诱导模型回填受 schema 禁止的门店字段；工作区当前提示已明确要求返回空对象并由本地附加可信门店信息。

## Task 15：参数与确认状态

### V2FeaturePolicy

只读读取 `data/AI_Demo_Data_Pack_V2_Large.xlsx` 的 `V2FeaturePolicy!A1:E10`，并通过 `V2FeaturePolicy.from_workbook` 完成类型和关系校验。工作簿行值如下：

| 工作簿行 | 参数 | 当前值 | 工作簿状态 |
| ---: | --- | ---: | --- |
| 2 | `purchase_frequency_window_days` | 90 | `INITIAL_EVAL_VALUE` |
| 3 | `purchase_frequency_high_threshold` | 8 | `INITIAL_EVAL_VALUE` |
| 4 | `purchase_frequency_low_threshold` | 1 | `INITIAL_EVAL_VALUE` |
| 5 | `stockout_high_risk_coverage_days` | 3 | `INITIAL_EVAL_VALUE` |
| 6 | `stockout_low_risk_coverage_days` | 14 | `INITIAL_EVAL_VALUE` |
| 7 | `discovery_history_lookback_months` | 12 | `CONFIRMED_V2` |
| 8 | `discovery_peer_ratio_threshold` | 0.30 | `INITIAL_EVAL_VALUE` |
| 9 | `recent_store_baseline_days` | 90 | `INITIAL_EVAL_VALUE` |
| 10 | `event_baseline_fallback_order` | `STORE_EVENT|PEER_EVENT|RECENT_STORE` | `CONFIRMED_V2` |

代码加载入口是 `services/v2_policy.py:14-79`：缺参数会失败关闭；低频阈值必须小于高频阈值，High/Low stockout coverage 阈值必须有序，事件 fallback 顺序必须严格匹配 `STORE_EVENT → PEER_EVENT → RECENT_STORE`。

### OptimizerPolicy

没有 `OptimizerPolicy` worksheet。`services/local_optimizer.py:15-35` 的 `OptimizerPolicy()` 默认值为：

| 代码字段 | 当前值 | `V2_EVALUATION_PARAMETERS.md` 对应项 | 状态 |
| --- | ---: | --- | --- |
| `demand_history_days` | 90 天 | Demand history | `INITIAL_EVAL_VALUE` |
| `coverage_period_days` | 14 天 | Target coverage | `INITIAL_EVAL_VALUE` |
| `intensity_factors["HIGH"]` | 1.25 | HIGH intensity factor | `INITIAL_EVAL_VALUE` |
| `intensity_factors["MEDIUM"]` | 1.00 | MEDIUM intensity factor | `INITIAL_EVAL_VALUE` |
| `intensity_factors["LOW"]` | 0.75 | LOW intensity factor | `INITIAL_EVAL_VALUE` |
| `discovery_trial_sales_units` | 1 Sales Unit | Discovery trial quantity | `INITIAL_EVAL_VALUE` |

运行结果的回显位置是 `services/local_optimizer.py:166-170`。文档 `docs/V2_EVALUATION_PARAMETERS.md:27-42` 对应一致，并且 `docs/V2_EVALUATION_PARAMETERS.md:56-60` 仍要求在生产使用前取得业务确认。参数没有被调整。

### 只读验证

使用 `python -B -m unittest tests.test_v2_decision_features tests.test_v2_scenario_contract tests.test_v2_optimizer_scenarios tests.test_v2_scenario_scripts tests.test_intent_parser` 运行离线测试，结果为 `Ran 32 tests ... OK`。这些测试从本地工作簿读取数据，模型路径使用 offline/fake client 或 patch；本轮没有调用真实 provider。

## Task 17：合同字段消费者

### 数据流

`IntentParser` 通过 `ProcurementUnderstandingBuilder` 同时产出旧的 CamelCase 顶层字段和 `StructuredIntent`。`services/procurement_understanding.py:12-90` 显示，`Budget`、`TrafficLevel`、`Objective`、`HardConstraints`、`SoftPreferences`、`ExplicitProducts` 等旧字段会被归一化或映射到 V2 的小写合同字段。

V2 主链路在 `services/v2_preparation.py:40-79` 只把 `intent["StructuredIntent"]` 送入候选池和安全特征构建，随后由以下组件消费：

| V2 字段/对象 | 真实消费者 | 作用证据 |
| --- | --- | --- |
| `hard_constraints` | `CandidatePoolBuilder` | `services/candidate_pool.py:103-175` 过滤不可售、无供应和硬约束不满足的产品 |
| `explicit_products` | `CandidatePoolBuilder`、`V2PreparationPipeline` | `services/candidate_pool.py:81,199-222`；准备阶段还按产品目录补齐文本提及 |
| `soft_preferences`、`category_preference` | `DecisionFeatureBuilder`、`DecisionTrace` | `services/decision_features.py:46-47,193-203` 生成 category relevance；`services/decision_trace.py:38-69` 生成 Why Selected |
| `occasion` | `EventNormalizer`、`DecisionFeatureBuilder`、`LocalOptimizer` | `services/v2_preparation.py:47-54`；`services/decision_features.py:47`；`services/local_optimizer.py:184-223` 选择事件基线 |
| `budget` | `LocalOptimizer`、`HardValidator` | `services/local_optimizer.py:76,125-165`；`services/hard_validator.py:184-205` |
| `objective`、`traffic_expectation` | `AIDecisionLayer` | `services/ai_decision.py:137-140,323-330` 转为允许的策略信号并随安全上下文传入模型 |

### V1 兼容字段的实际消费者

| 旧字段组 | 真实消费者 | 结论 |
| --- | --- | --- |
| `Budget`、`TrafficLevel`、`PromotionFlag`、`ShelfLifePreference`、`PreferredCategory`、`ExcludedCategory`、`TimeRange`、`ExpectedIntent` | `ContextEngine._intent_match_score`（`services/context_engine.py:82-123`）用于选会话；`engines/replenishment_engine.py:164-321` 和 `engines/growth_engine.py:46-58` 用于 V1 评分、过滤和数量；`services/ui.py:1008-1095,1616-1620` 用于旧理解卡片和理由 | 仍是运行时字段，不能直接删除 |
| `Budget` 以及上述旧字段整体 | `app.py:333-347` 在 V2 失败被记录后调用 `RecommendationEngine`；`engines/recommendation_engine.py:48-65,154-163` 合并 `context_override` 并建立 V1 fallback 上下文 | V1 fallback 仍依赖旧字段 |
| `BusinessIntent`、`DecisionSignals`、`Uncertainty`、`MissingInformation`、`RecommendationReadiness` | `services/ui.py:979-988` 的 `render_ai_understanding` | 当前主要是解释性 UI 数据，不是 V2 候选/数量规则 |
| `StoreContext`、`StoreConsiderations` | `app.py:73-84` 用 `StoreContext` 选择可信 `CustomerId`；`engines/recommendation_engine.py:63-65` 与 `services/ui.py:987-988,1473-1475` 使用/展示门店上下文；`StoreConsiderations` 由解析结果传递并展示 | `StoreContext` 应继续由本地可信数据填充，`StoreConsiderations` 不应成为 V2 规则输入 |
| `AIAnalysisStatus`、`AIAnalysisSource` | `app.py:300-301,323-326`、`services/ui.py:985-986`；`AIAnalysisStatus` 还驱动 `V2DecisionPipeline` 的 intent fallback 状态和脚本断言 | 是状态/验收信号，不是采购业务特征 |
| `Objective`、`Occasion`、`HardConstraints`、`SoftPreferences`、`ExplicitProducts` | 主要由 `ProcurementUnderstandingBuilder`（`services/procurement_understanding.py:24-90`）接收并转换为 `StructuredIntent`；现有直接业务消费集中在转换后的字段 | 可作为过渡输入保留，后续应逐步收敛到一个内部规范对象 |

### 提示词重复与当前根因

`services/intent_parser.py` 同时维护：

1. `INTENT_JSON_SCHEMA` 的完整顶层旧字段、顾问理解字段和 `structured_intent`（`services/intent_parser.py:16-217`）；
2. `INTENT_SYSTEM_PROMPT` 对这些字段的逐项文字说明、规则和完整 JSON 示例（`services/intent_parser.py:224-316`）；
3. 用户消息再次要求“完整 contracted JSON object”，并特别提醒不要把请求误当成示例（`services/intent_parser.py:353-360`）。

这会让同一事实在旧字段、顾问字段和 `structured_intent` 中重复表达，增加提示词长度和字段不一致风险。当前工作区还显示一个具体合同冲突：schema 的 `store_context` 只允许空对象（`services/intent_parser.py:214`），而旧提示曾只说不要改变 identity fields；实测 DeepSeek 会把 trusted profile 回填到 `store_context`，随后本地 schema 拒绝并转 rules fallback。当前提示已在 `services/intent_parser.py:248,312,347-350` 明确 `store_context` 必须为 `{}`，由应用本地附加可信 profile；这保持 schema 收紧，不把真实身份字段暴露给模型输出。

本轮不做生产重构。后续最小精简顺序建议为：

1. 先保留旧顶层字段作为 UI/V1 fallback 适配层，把 `StructuredIntent` 明确为唯一 V2 内部输入；不要同时修改 schema、V1 fallback 和 UI。
2. 补一个离线回归：模型输出非空 `store_context` 必须得到明确 schema fallback，输出 `{}` 时由本地 `StoreContext` 和 `structured_intent.store_id` 填充；再保留一条 provider-neutral 解析测试。
3. 验收稳定后再缩短 prompt：保留 DeepSeek 所需的 JSON 字段约束和规则，删除重复的逐项解释或完整示例中的冗余字段；每次只减少一组重复，跑现有 intent/schema 测试。
4. 最后再评估把旧字段生成移到本地 adapter；在 V1 fallback 和 UI 完成迁移前，不删除旧字段。

## 六场景业务断言与同条件对照

`videos/procurement-scenarios/media/scenarios.json:1-32` 的六条展示请求都写 `Cafe Store 001`。`scripts/v2_scenario_regression.py:21-35` 再按 slug 显式绑定 V2 行，`load_scenario_bindings` 会校验 `ScenarioId`、`CustomerId`、`AsOfDate` 和 `DecisionPath`（`scripts/v2_scenario_regression.py:68-163`）。当前绑定和业务断言为：

| 展示 slug | V2 行 / 身份 | 当前业务断言 |
| --- | --- | --- |
| `01_high_traffic` | `V2-001 / C051 / 2026-06-02` | Structured Intent 为预算 1000、HIGH traffic；至少一个推荐项为 HIGH intensity（`scripts/v2_scenario_regression.py:47-49,226-231`） |
| `02_holiday_promo` | `V2-018 / C051 / 2026-12-10` | 预算 1000、HIGH traffic、CHRISTMAS；最终计划使用 `STORE_EVENT` baseline（`scripts/v2_scenario_regression.py:47-52,232-234`） |
| `03_low_budget` | `V2-004 / C051 / 2026-06-02` | 预算 300、`PREVENT_STOCKOUT`；保留 HIGH priority，不能有 HIGH priority 的预算冲突（`scripts/v2_scenario_regression.py:47-52,235-252`） |
| `04_long_shelf` | `V2-006 / C051 / 2026-06-02` | 长保质期 soft preference 反映在最终计划和 Why Selected（`scripts/v2_scenario_regression.py:47-55,253-267`） |
| `05_fruit_focus` | `V2-008 / C051 / 2026-06-02` | Fruit preference 被解析；至少选择一个高相关候选，High relevance 选择率不低于 Low relevance（`scripts/v2_scenario_regression.py:47-56,268-291`） |
| `06_no_budget` | `V2-001 / C051 / 2026-06-02` | 预算为 null、HIGH traffic；无 remaining budget，也不能出现 budget cap（`scripts/v2_scenario_regression.py:47-56,293-304`） |

这些是路径/行为断言，不构成同条件因果对照：

- High traffic 没有正常 traffic 对照。`01` 和 `06` 都是 HIGH traffic，且预算分别为 1000 和 null；两者共享 `V2-001` 基线，但不能隔离 traffic 因素。
- Long Shelf-life soft 没有无偏好对照。工作簿中的 `V2-006` 与 `V2-007` 是 soft 与 hard 的语义对比，不是“有偏好/无偏好”的同条件对比；`V2-006` 的 `P206`、`P207` 预期都保持 eligible，重点是“不被 soft preference 过滤”。
- Fruit soft 也没有无 category preference 对照。`V2-008` 与 `V2-009` 是 soft 与 hard 的语义对比，不能单独量化 soft preference 对选择率的增量。
- `V2-004` 中 `P204` 与 `P205` 的“同 demand facts、不同库存”是 stockout feature 对比，不能代替 high traffic 对照。

另有身份边界必须单独标注：脚本六场景明确绑定 `C051 / V2 Target Cafe`，而 UI 的 `StoreResolver` 只从 `ConversationContext` 中可用的门店集合解析；当前文本 `Cafe Store 001` 会进入 `C001`，`ConversationContext` 只有 C001–C005，C051 不能从 UI 入口选择。证据见 `services/store_resolver.py:32-40,55-65` 和 `docs/V2_REMAINING_TASKS.md:18-22`。因此 C051 harness 结果不能称为同一句 UI C001 请求的端到端验收。

### 便于后续执行的小范围方案

暂停 A/B 期间只增加离线控制，不改现有六个 slug、V2 绑定或生产逻辑：

1. 建一个独立的 control fixture/test（不要直接加到当前六 slug JSON，因为 `load_scenario_bindings` 目前要求 slug 集合完全匹配），固定同一 `CustomerId`、`AsOfDate`、模型参数和候选池。
2. 增加三组最小配对：`high traffic` vs 同预算同日期的 `normal traffic`；`prefer long shelf-life` vs 删除该短语；`focus on Fruit` vs 删除 category 短语。若目标是 UI 验收，配对请求统一写 `Cafe Store 001` 并使用 C001；若目标是现有脚本回归，明确标记为 C051 script-only。
3. 每组只记录对应差异：traffic 比较 HIGH intensity/数量信号；long shelf 比较候选集合不变且长保质期候选的优先级/理由变化；Fruit 比较高相关候选的优先级或选择率变化。硬约束、预算、Sales Unit、Available Stock 和 validator 结果继续按现有合同验收。
4. 先用 fake/offline decision client 验证控制逻辑，再在 DeepSeek 恢复后用相同请求、身份、日期和参数补真实 provider 证据；不要把旧 provider 报告或 C051 脚本结果当作当前 C001 UI 证据。

## 证据索引

- 参数文档：`docs/V2_EVALUATION_PARAMETERS.md:3-60`
- V2 合同：`docs/V2_ARCHITECTURE_CONTRACT.md:1-107`
- 运行时工作簿默认路径：`config/settings.py:16-25,48-62`
- V2 参数加载：`services/v2_policy.py:14-79`
- OptimizerPolicy 与回显：`services/local_optimizer.py:15-35,166-170`
- 展示场景和绑定：`videos/procurement-scenarios/media/scenarios.json:1-32`、`scripts/v2_scenario_regression.py:21-163`
- UI/脚本身份边界：`services/store_resolver.py:32-65`、`docs/V2_REMAINING_TASKS.md:18-22`
