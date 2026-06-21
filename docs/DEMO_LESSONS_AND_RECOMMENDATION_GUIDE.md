# AI Procurement Assistant Demo 经验沉淀与推荐逻辑说明

## 1. 文档目的

这份文档用于沉淀当前 Demo 建设过程中的关键经验、产品判断和推荐逻辑边界。

它面向三类读者：

- 业务客户：理解 Demo 展示的采购决策能力。
- 产品和销售团队：统一演示话术和能力边界。
- 技术团队：理解当前规则引擎、AI 使用方式和后续优化方向。

## 2. 核心产品经验

### 2.1 Demo 要服务业务决策，不要像测试工具

早期界面包含场景选择、示例按钮和内部测试状态，适合验证功能，但不适合客户演示。

当前 Demo 的体验目标是：

```text
Home
↓
Enter Demo
↓
Dashboard: AI Procurement Assistant
```

业务用户应该一进入 Dashboard 就看到：

- AI Procurement Request
- AI Understanding
- Recommended Replenishment
- Growth Opportunities
- Inventory Risks
- Procurement Plan

这个路径让客户关注推荐、决策和行动，而不是测试场景本身。

### 2.2 测试场景不能污染真实体验

Excel 中的 `ConversationContext` 用于 demo 数据匹配和测试，但它不应该成为真实业务输入的默认条件。

最典型的例子是预算：

- 如果用户输入预算，采购计划必须严格遵守该预算。
- 如果用户没有输入预算，系统不应该自动使用测试场景中的预算。
- 无预算时，系统应该生成不受预算约束的采购建议，并明确显示 `No Budget Constraint`。

这样可以避免客户误以为 AI 编造了预算或隐藏约束。

### 2.3 AI 应该提供结构化理解，而不是直接替代推荐引擎

DeepSeek 在当前 Demo 中的主要角色是自然语言理解。

它负责把用户输入转成结构化采购意图：

- Budget
- TrafficLevel
- PromotionFlag
- ShelfLifePreference
- PreferredCategory
- ExcludedCategory
- TimeRange
- ExpectedIntent

推荐商品、采购数量、预算合规和排序仍由本地推荐引擎计算。

当前职责边界：

```text
DeepSeek AI: 理解用户想要什么
Recommendation Engine: 计算应该买什么、买多少、为什么推荐、是否符合预算
UI: 把结果呈现为采购决策报告
```

这个架构比直接展示 AI 文本更稳定、更可解释，也更适合 B2B 决策场景。

### 2.4 Procurement Plan 应该像采购决策报告

采购经理不是来和系统聊天的，而是来判断是否可以下单。

因此 Procurement Plan 的视觉和信息层级应优先展示：

- Procurement Summary
- Recommended Products Table
- Why Selected
- Procurement Notes

聊天式说明可以保留在输入和理解层，但不能成为采购计划的主体。

### 2.5 推荐必须可解释、可控、可验证

Demo 中每个推荐结果都应回答三个问题：

- 为什么推荐这个产品？
- 建议买多少？
- 如果有预算，是否超预算？

可解释性来自 `why`、库存覆盖、历史采购频率、价格趋势和业务上下文。

可控性来自预算约束、品类偏好、保质期偏好和优先级排序。

可验证性来自单元测试，例如：

- 有预算时采购计划不超过预算。
- 无预算时不套用测试场景预算。
- 高优先级补货优先于 Trial Buy。
- 价格走势可以影响采购建议。

## 3. 当前推荐逻辑总览

当前推荐链路：

```text
用户自然语言输入
↓
IntentParser 解析采购意图
↓
ContextEngine 匹配客户和场景数据
↓
用户输入覆盖测试场景字段
↓
ReplenishmentEngine 生成补货推荐
↓
GrowthEngine 生成增长机会
↓
RiskEngine 生成库存风险
↓
PriceTrendEngine 补充价格走势信号
↓
RecommendationEngine 生成 Procurement Plan
↓
UI 渲染采购决策报告
```

## 4. AI 作用边界

### 4.1 DeepSeek 负责的事情

DeepSeek 用于解析自然语言采购请求。

示例输入：

```text
Budget NZD 1000, high traffic next week, avoid short shelf-life products
```

可能解析为：

```text
Budget = 1000
TrafficLevel = HIGH
PromotionFlag = False
ShelfLifePreference = LONG
TimeRange = next_week
ExpectedIntent = Prepare for high traffic next week while avoiding short shelf-life products
```

这些字段会进入推荐引擎，影响推荐排序、数量和预算处理。

### 4.1.1 采购顾问式语义理解

DeepSeek 的目标不是只抽取字段，而是形成采购顾问式理解。

新的语义理解包含：

- Business Intent：采购目的和紧急程度。
- Decision Signals：需求变化、需求驱动、预算严格度、缺货敏感度、损耗敏感度。
- Uncertainty：哪些字段是用户明确输入，哪些是推断，哪些缺失。
- Missing Information：缺失信息的重要性和对推荐的影响。
- Recommendation Readiness：是否可以生成推荐、是否应该追问、当前推荐可信度。

系统采用混合追问模式：

- 高风险缺失信息显示追问并降低可信度，但不阻塞当前推荐。
- 普通缺失信息只提示，不阻塞推荐。
- 可选缺失信息只作为上下文说明。

UI 面向英文 demo 展示，因此模块名称保留英文；内部开发文档统一使用中文说明。

### 4.2 DeepSeek 不负责的事情

DeepSeek 不直接决定：

- 最终推荐哪个产品
- 每个产品采购多少
- 是否超预算
- 库存覆盖天数
- 价格趋势信号
- 产品优先级排序

这些由本地推荐引擎和 Excel 数据计算完成。

### 4.3 Fallback 策略

如果没有配置 DeepSeek API key，或者 AI 调用失败，系统会使用本地关键词解析器。

Fallback 可以识别基础字段：

- budget / NZD / $
- traffic / busy / rush
- holiday / promotion
- short shelf / long shelf
- avoid / no
- prefer / focus

Fallback 能保证 Demo 可运行，但自然语言理解能力弱于 DeepSeek。

## 5. 业务上下文规则

系统最终使用的上下文来自两部分：

- Excel 场景数据：客户、历史订单、库存、商品、行业趋势等。
- 用户输入：预算、客流、促销、保质期、品类偏好等。

合并原则：

- 用户输入字段优先。
- 用户没有输入的非预算字段，可以沿用匹配场景，避免空结果。
- 用户没有输入预算时，不使用测试场景预算。
- 预算只在用户明确输入时作为采购计划约束。

## 6. 补货推荐逻辑

补货推荐主要面向客户历史购买过、且当前有库存记录的商品。

评分维度：

- 购买频率：20%
- 采购周期是否到点：20%
- 当前库存覆盖天数：20%
- 保质期匹配：15%
- 节假日相关性：15%
- 收藏或常用品：10%

上下文调整：

- 高客流：提升推荐分数。
- 促销或节假日：提升推荐分数。
- 偏好品类：提升推荐分数。
- 排除品类：降低推荐分数。
- 长保质期偏好：Frozen / Dry 加分，Fresh 减分。

推荐强度：

- Very High
- High
- Medium
- Low

## 7. 推荐数量逻辑

基础目标覆盖天数：

- Fresh: 7 天
- Chilled: 10 天
- Frozen: 21 天
- Dry: 30 天

核心公式：

```text
库存缺口数量 = max(目标覆盖天数 × 日均需求 - 当前库存, 0)

初步推荐数量 = max(历史平均采购量, 库存缺口数量)
```

上下文影响：

- 高客流会提高目标覆盖天数。
- 促销或节假日会提高目标覆盖天数。
- 长保质期偏好会限制 Fresh / Chilled 的放大幅度。

预算影响：

```text
如果用户输入预算：
推荐数量 <= Remaining Budget / Unit Cost

如果用户未输入预算：
推荐数量不做预算裁剪
```

## 8. 增长机会逻辑

Growth Opportunities 用于发现客户尚未充分采购、但行业中表现较好的商品。

主要信号：

- 同行业覆盖率
- 行业流行度
- 趋势方向
- 毛利率
- 当前客户是否尚未购买或购买较少

高分增长机会会以 `Trial Buy` 方式进入采购计划。

Trial Buy 的产品意图是：

- 小规模试采
- 降低新品引入风险
- 验证客户真实需求

## 9. 库存风险逻辑

Inventory Risks 用于提示采购经理关注库存侧风险。

当前风险类型：

- 缺货风险
- 过量库存
- 临期风险

风险判断会参考：

- 当前库存
- 历史日均需求
- 库存覆盖天数
- 批次过期时间
- 库存场景标签

## 10. 价格走势逻辑

PriceTrendEngine 从 Excel 的 `PriceHistory` sheet 读取历史价格。

当前用于判断：

- 当前价格是否接近 90 天低点。
- 当前价格是否接近 90 天高点。
- 当前价格是否接近历史均值。
- 当前是否存在促销价格。

价格信号：

- Buy Now：当前价格有优势。
- Fair Price：当前价格接近近期均值。
- Wait：当前价格偏高，除非库存风险很高，否则控制采购。

价格走势对推荐的影响：

- 非 Fresh 产品在价格优势明显时，可以适度增加采购数量。
- Fresh 产品即使价格好，也不会盲目放大数量，避免损耗风险。
- 价格高时，系统会提示控制采购或观察价格。

## 11. Procurement Plan 预算逻辑

采购计划采用分层预算分配，而不是简单按推荐分数排序。

优先级层级：

```text
Tier 1: Order Now
处理缺货风险和高优先级补货

Tier 2: Buy on Price Advantage
处理当前价格处于有利窗口的采购机会

Tier 3: Trial Buy
处理增长机会的小规模试采

Tier 4: Monitor Price
处理价格偏高或风险较低的观察项
```

有预算时：

```text
可负担数量 = Remaining Budget // Unit Cost
最终采购数量 = min(推荐数量, 可负担数量)
```

系统会跳过当前预算无法购买的商品，最终 `Total Investment` 不会超过用户输入预算。

无预算时：

```text
不使用测试场景 Budget
不执行预算裁剪
按业务优先级输出采购建议
显示 No Budget Constraint
```

## 12. Demo 数据策略

当前 Demo 使用 Excel 作为数据源，适合早期演示和快速迭代。

优势：

- 容易调整客户、商品、库存和价格数据。
- 方便向客户解释数据来源。
- 不需要提前接入复杂 ERP / POS 系统。
- 可以快速设计不同演示场景。

局限：

- 数据不是实时同步。
- 不适合多人并发编辑。
- 数据规模扩大后性能和维护成本会上升。

后续可迁移到：

- PostgreSQL / MySQL
- ERP API
- POS API
- Supplier price feed
- Public price feed

## 13. 演示话术建议

推荐开场：

```text
This is not a generic chatbot. It is an AI procurement assistant that converts a business request into a structured procurement decision.
```

推荐输入：

```text
Budget NZD 1000, high traffic next week, avoid short shelf-life products
```

演示重点：

- AI Understanding：证明系统理解了业务条件。
- Recommended Replenishment：证明系统知道哪些商品需要补货。
- Growth Opportunities：证明系统不只补货，也能发现增长空间。
- Inventory Risks：证明系统能解释风险。
- Procurement Plan：证明系统能生成采购经理可审阅的决策报告。

预算演示：

```text
Budget NZD 100, high traffic next week, avoid short shelf-life products
```

说明重点：

- 系统会减少数量或保留更高优先级产品。
- 最终 Total Investment 不会超过用户预算。

无预算演示：

```text
high traffic next week, avoid short shelf-life products
```

说明重点：

- 系统不会套用测试场景预算。
- 采购计划显示 No Budget Constraint。
- 推荐仍然按业务优先级生成。

## 14. 当前能力边界

当前 Demo 已具备：

- 自然语言采购请求解析。
- DeepSeek AI + fallback parser。
- 补货推荐。
- 增长机会推荐。
- 库存风险提示。
- Excel 版价格走势信号。
- 预算约束采购计划。
- 无预算约束采购计划。
- Streamlit Dashboard。
- 腾讯云 CVM 部署。

当前 Demo 尚未覆盖：

- 实时 ERP / POS 数据接入。
- 实时供应商价格 API。
- 多用户权限。
- 采购审批流。
- 订单提交到供应商。
- 推荐结果人工反馈学习。
- 商品替代品推荐。
- 多供应商比价。

## 15. 后续优化方向

### 15.1 数据侧

- 接入真实历史订单。
- 接入实时库存。
- 接入供应商报价。
- 增加商品替代关系。
- 增加损耗率和退货率。

### 15.2 推荐侧

- 引入需求预测。
- 引入安全库存模型。
- 引入供应商交期。
- 引入毛利和库存周转目标。
- 引入品类预算分配。
- 支持客户反馈修正推荐。

### 15.3 产品侧

- 增加采购计划导出。
- 增加采购审批状态。
- 增加一键生成供应商订单。
- 增加产品解释弹窗。
- 增加客户级配置。

### 15.4 AI 侧

- 增加多轮澄清能力。
- 支持更复杂的业务限制解析。
- 生成客户可读的采购说明。
- 根据历史反馈生成更好的解释。
- 增加 AI 调用日志和可观测性。

## 16. 关键设计原则

### 原则 1：业务输入优先于测试场景

用户明确输入的条件必须覆盖测试场景。

### 原则 2：不编造约束

用户没有输入预算时，不展示默认预算。

### 原则 3：AI 做理解，规则做决策

AI 负责解析语义，本地引擎负责可解释的推荐计算。

### 原则 4：采购计划优先于聊天体验

采购经理需要的是决策报告，而不是聊天记录。

### 原则 5：每个推荐都要能解释

推荐结果必须说明原因、数量和业务价值。

### 原则 6：Demo 要能稳定运行

必须保留 fallback parser、测试覆盖、systemd 服务和部署文档。
