**Status: Outdated for V2 — pending rewrite**

# AI Procurement Assistant Demo 功能说明

## 1. Demo 定位

本 Demo 展示一个面向业务用户的 AI Procurement Assistant。它不是内部测试工具，也不是普通聊天机器人，而是帮助采购经理快速形成采购决策的 AI 工作台。

业务用户只需要输入自然语言采购请求，例如预算、客流变化、促销活动、保质期偏好等条件，系统会自动识别意图，并生成可执行的采购建议。

## 2. 演示入口

在当前项目目录下启动应用：

```bash
cd "/Users/carrie/Documents/ai/recommend demo"
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py --server.port 8501
```

如果已经安装过依赖，后续只需要运行：

```bash
cd "/Users/carrie/Documents/ai/recommend demo"
source .venv/bin/activate
streamlit run app.py --server.port 8501
```

启动成功后访问：

```bash
http://localhost:8501
```

页面打开后即进入核心 Dashboard，无需多层导航。客户可以在一个页面内完成从输入需求到查看采购计划的完整体验。

## 3. 推荐演示话术

可以使用以下输入作为演示请求：

```text
Budget NZD 1000, high traffic next week, avoid short shelf-life products
```

也可以演示预算约束能力：

```text
Budget NZD 100, high traffic next week, avoid short shelf-life products
```

系统会根据用户输入重新生成采购结果。若用户输入预算，最终采购计划会严格不超过该预算；若用户未输入预算，系统不会套用测试场景里的默认预算，而是生成不受预算约束的业务优先级采购建议。

## 4. 页面功能模块

### AI Procurement Request

这是业务用户的主要输入区。用户可以用自然语言描述采购目标，而不需要选择复杂参数。

当前支持识别的信息包括：

- Budget：采购预算
- Traffic：预计客流变化
- Promotion：是否存在促销或节假日需求
- Shelf Life：保质期偏好

### AI Understanding

系统会把用户输入解析成采购顾问视角的结构化理解，而不是只抽取字段。

该区域在 UI 中使用英文展示，包含：

- Business Intent：用户真正的采购目的，例如补货、防缺货、节日备货、预算优化或增长试采。
- Decision Signals：需求变化、需求驱动因素、预算模式和关键风险偏好。
- Risk Sensitivity：系统判断用户更关注缺货、损耗、价格还是增长机会。
- Missing Information：缺失但会影响推荐质量的信息。
- Recommendation Confidence：当前输入是否足够支持高质量推荐。

当前采用混合模式：

- 普通缺失信息不会阻塞推荐，例如用户未输入预算时，系统仍会生成无预算约束的采购建议。
- 高风险缺失信息会显示一个建议追问并降低推荐可信度，但不会阻塞当前推荐。

该区域用于向客户说明：AI 不只是生成文字回复，而是在像采购顾问一样判断业务意图、决策信号和推荐可信度。

### Procurement Plan

这是当前 Demo 的核心输出区域，面向采购经理 reviewing purchase decision。

该区域包括：

- Procurement Summary：预算、总投入、剩余预算、推荐产品数量
- Budget Status：有预算时显示 Within Budget 和 Budget Optimized / Budget Protected；无预算时显示 No Budget Constraint
- Recommended Products Table：采购决策表
- Why Selected：每个产品被推荐的关键原因
- Procurement Notes：面向管理层的一句话总结

重点说明：采购计划只在用户明确输入预算时强制遵守预算。如果预算较低，系统会减少采购数量或保留更高优先级产品，避免展示超预算方案。如果用户没有输入预算，系统不会使用测试场景预算，而是输出按业务优先级排序的采购建议。

### Recommended Replenishment

展示需要补货的重点商品。

该区域帮助客户理解：

- 哪些商品有缺货风险
- 建议采购数量
- 当前库存覆盖天数
- 推荐强度

### Growth Opportunities

展示潜在增长机会商品。

该区域用于说明系统不仅能处理补货，还能识别业务增长空间，例如同类客户常购但当前客户尚未充分采购的产品。

高分增长机会会生成低风险试采建议，并以 `Trial Buy` 的方式进入 Procurement Plan。这样采购计划不仅覆盖“需要补货的产品”，也能包含“值得小规模测试的新机会产品”。

### Inventory Risks

展示库存风险，包括缺货、过量库存和临期风险。

该区域帮助采购经理从风险角度理解为什么某些商品需要优先处理。

## 5. 推荐产品核心逻辑

当前 Demo 的推荐逻辑由四层组成：业务上下文理解、补货推荐、推荐数量计算和预算约束采购计划。

### AI 在 Demo 中的作用

DeepSeek AI 在当前 Demo 中主要承担自然语言理解的角色，用于把业务用户的采购请求解析成结构化条件。

例如用户输入：

```text
Budget NZD 1000, high traffic next week, avoid short shelf-life products
```

AI 会尝试识别出：

- Budget：1000
- TrafficLevel：HIGH
- ShelfLifePreference：LONG
- TimeRange：next_week
- PromotionFlag：是否存在促销或节假日信号

这些结构化条件会进入推荐引擎，影响后续的预算约束、推荐排序、推荐数量和保质期偏好。

需要强调的是：AI 不直接拍脑袋决定推荐哪些商品。最终推荐商品、采购数量和预算合规性由本地推荐引擎计算完成。

当前架构可以理解为：

```text
DeepSeek AI：理解用户想要什么

Recommendation Engine：计算应该买什么、买多少、是否超预算
```

如果没有配置 DeepSeek API Key，系统会使用本地 fallback parser，通过关键词识别预算、客流、保质期等基础信息。这样 Demo 仍然可以运行，但自然语言理解能力会相对有限。

### 业务上下文理解

用户输入会被解析成结构化业务条件，并覆盖默认 Demo 场景中的对应字段。

系统当前会识别：

- Budget：采购预算
- TrafficLevel：是否高客流
- PromotionFlag：是否促销或节假日需求
- ShelfLifePreference：是否偏好长保质期产品
- PreferredCategory：偏好品类
- ExcludedCategory：排除品类
- TimeRange：普通周期或节假日窗口

这意味着 Excel 场景提供基础客户、订单、库存和商品数据，用户输入决定最终推荐约束。

### 补货推荐评分

补货推荐主要面向客户历史买过、且当前有库存记录的产品。

每个产品会生成一个 0 到 100 的推荐分数，评分维度包括：

- 购买频率：20%
- 采购周期是否到点：20%
- 当前库存覆盖天数：20%
- 保质期匹配：15%
- 节假日相关性：15%
- 是否收藏或常用：10%

在基础评分之外，系统还会根据用户上下文做调整：

- 高客流：加分
- 促销活动：加分
- 偏好品类：加分
- 排除品类：减分
- 长保质期偏好：Frozen / Dry 加分，Fresh 减分

最终系统会按推荐分数排序，优先展示高分、高紧急度的产品。

### 推荐数量公式

推荐数量不是固定值，而是根据目标库存覆盖天数、日均需求、当前库存和历史采购量共同计算。

不同产品类型有不同的基础目标覆盖天数：

- Fresh：7 天
- Chilled：10 天
- Frozen：21 天
- Dry：30 天

如果存在高客流、促销或节假日窗口，目标覆盖天数会相应增加。

核心计算逻辑：

```text
库存缺口数量 = max(目标覆盖天数 × 日均需求 - 当前库存, 0)

初步推荐数量 = max(历史平均采购量, 库存缺口数量)
```

如果用户偏好长保质期，系统会进一步限制短保质期商品：

- Fresh：不超过历史平均采购量
- Chilled：最多放大到历史平均采购量的 1.5 倍

如果用户提供预算，推荐数量还会受到预算限制：

```text
推荐数量 <= Budget / AvgCost
```

### 预算约束采购计划

最终 Procurement Plan 会从推荐候选中选择高优先级产品，并确保采购计划不超过用户预算。

计划采用分层预算分配，而不是简单按分数排序。

预算分配优先级：

- 第一层：Order Now，优先满足缺货风险和高优先级补货
- 第二层：Buy on Price Advantage，当前价格处于有利窗口的采购机会
- 第三层：Trial Buy，增长机会的小规模试采
- 第四层：Monitor Price，价格偏高或风险较低的观察项

同一层级内再按以下规则排序：

- 推荐分数更高的产品优先
- 在分数相近时，成本更低的产品优先
- 最后按产品名称稳定排序

预算约束逻辑：

```text
可负担数量 = Remaining Budget // Unit Cost

最终采购数量 = min(推荐数量, 可负担数量)
```

如果剩余预算无法购买某个产品，系统会跳过该产品。最终展示的 Total Investment 不会超过用户输入的 Budget。

无预算输入逻辑：

```text
如果用户未输入 Budget：
不使用测试场景 Budget
不执行预算裁剪
按补货优先级、增长机会、库存覆盖、价格信号和推荐分数生成采购建议
```

这种分层逻辑可以确保预算有限时，系统先处理断货风险，再考虑价格机会和增长试采。

### 价格走势推荐逻辑

当前 Demo 已加入 Excel 数据版的产品历史价格走势能力。系统会读取 Excel 中的 `PriceHistory` sheet，用产品过去约 90 天的价格变化判断当前是否是合适采购时机。

`PriceHistory` 数据字段包括：

- ProductId：产品 ID
- PriceDate：价格日期
- StoreName：价格来源门店或市场均值
- UnitPrice：单位价格
- PromoFlag：是否促销价格
- Source：数据来源

价格走势会计算以下核心指标：

- current_price：当前最新价格
- avg_30d_price：近 30 天平均价
- avg_90d_price：近 90 天平均价
- min_90d_price：近 90 天最低价
- max_90d_price：近 90 天最高价
- price_position：当前价格在 90 天价格区间中的位置

核心公式：

```text
price_position =
(current_price - min_90d_price) / (max_90d_price - min_90d_price)
```

系统会根据 `price_position` 生成价格信号：

- Buy Now：当前价格接近 90 天低点，适合采购
- Fair Price：当前价格接近近期均值，可以正常采购
- Wait：当前价格接近 90 天高点，建议谨慎采购

价格信号会影响补货推荐分数：

```text
Buy Now：推荐分数 +8
Fair Price：推荐分数不调整
Wait：推荐分数 -8
```

如果商品库存非常紧张，系统会保护补货优先级，不会因为价格偏高而过度降低推荐，避免为了等低价造成缺货。

价格走势也会影响采购数量和成本计算：

- 采购金额优先使用 `PriceHistory` 中的最新 UnitPrice，而不是静态 AvgCost。
- Buy Now 且商品不是 Fresh / Chilled 时，系统会适度提高采购数量。
- Buy Now 且商品是 Chilled 时，系统只做小幅提高。
- Fresh 商品即使处于 Buy Now，也不会因为低价盲目加量，避免损耗风险。
- Wait 且库存覆盖安全时，系统会适度减少采购数量，降低高价采购暴露。

这意味着系统不仅会判断“价格是否合适”，还会把价格信号转化成更合理的采购金额和采购数量。

在页面上，价格走势会体现在：

- Procurement Plan 表格中的 Price Signal 列
- Why Selected 中的价格原因

例如：

```text
Price Signal: Buy Now
Current price is near the 90-day low.
```

这让推荐逻辑不仅能回答“该不该买、买多少”，还能进一步回答“现在是不是值得买”。

### Growth Opportunity 试采逻辑

增长机会商品用于发现客户尚未采购、但在同类行业中表现较好的潜在产品。

系统会基于以下信号识别增长机会：

- Industry coverage rate：同行业客户覆盖率
- Popularity score：行业热度
- Profit margin：利润空间
- PreferredCategory：用户偏好品类
- Favorites：客户收藏或常用品信号

增长机会不直接建议大批量采购，而是生成低风险试采数量。

试采数量逻辑：

```text
试采数量 = 同类商品历史平均采购量 × 25%
```

同时根据产品类型设置上限：

- Fresh：最多 3 个单位，避免损耗
- Chilled：最多 4 个单位
- Frozen / Dry：最多 6 个单位

高分增长机会会以 `Trial Buy` 标签进入 Procurement Plan，并继续受到预算约束。

进入采购计划的条件：

```text
priority = Trial Buy
score >= 60
remaining budget 足够覆盖试采成本
```

如果有价格历史，试采商品同样会使用最新 UnitPrice 计算成本，并显示 Price Signal。

示例：

```text
Lemon Variant 5
Quantity: 3
Priority: Trial Buy
Price Signal: Fair Price
```

这让采购计划同时覆盖两类决策：

- Replenishment：降低缺货风险
- Trial Buy：捕捉增长机会

### Why Selected 业务化解释

页面中的 `Why Selected` 不直接展示原始算法描述，而是转化为采购经理更容易理解的业务语言。

例如系统会将底层信号转化为：

```text
Recommended action: Order Now.
Inventory covers only 2 days, creating stockout risk.
Current price is near the 90-day low, making this a favorable buying window.
```

对于试采商品，解释会强调风险控制：

```text
Recommended action: Trial Buy.
Small trial quantity limits risk while testing a growth opportunity.
Current price is close to the recent average, supporting a normal purchase decision.
```

这样客户看到的不是算法中间值，而是可执行的采购判断。

## 6. 核心业务价值

- 降低采购经理手动分析库存、历史订单和预算约束的时间成本。
- 将自然语言需求转化为可执行采购计划。
- 在推荐商品时同时考虑预算、库存覆盖、需求变化和风险。
- 结合产品历史价格走势，识别当前是否处于适合采购的价格窗口。
- 避免生成不可执行的超预算采购方案。
- 将 AI 输出从聊天回复升级为业务决策报告。

## 7. 客户演示重点

演示时建议强调以下三点：

- AI 理解业务约束：输入预算、客流、促销、保质期后，页面会显示结构化理解结果。
- AI 生成可执行计划：Procurement Plan 直接展示预算可行的采购表，而不是泛泛的文本建议。
- AI 遵守预算：输入较低预算时，Total Investment 仍不会超过 Budget。

## 8. 当前 Demo 边界

当前版本用于演示核心采购推荐体验，数据来自本地 Excel Demo 数据包。

暂未覆盖的生产级能力包括：

- 多用户登录和权限管理
- 实时 ERP / POS / 库存系统集成
- 采购审批流
- 供应商价格实时更新
- 自动下单

这些能力可作为后续产品化路线的一部分扩展。
