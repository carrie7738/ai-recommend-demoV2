# UI 调整交付记录

2026-09-04；实施范围为子目录 V2 的当前工作树。

## 页面变化

- 固定顺序：Business Request → AI Understanding → Purchase Plan → Potential Opportunities。
- 初始大输入框；已提交请求后使用紧凑输入。增加理解和生成的加载提示。
- Understanding 只读，直接读取结构化字段，不显示标记为 missing 的字段，不补默认置信度。
- Purchase Plan 汇总预算、金额、余额和商品数；保留数量、单位、单价、priority 和行金额。
- 无预算显示 Not specified；服务未返回余额时显示 —。
- Why Selected 绑定最终入单商品，按商品折叠展示现有理由。没有理由时明确显示不可用。
- 技术状态和策略收进 Technical details；规则降级仍在主流程提示。
- V2 校验失败或缺失时隐藏计划。V1 fallback 明确缺少校验结果，不再通过旧 UI 推导库存理由或声明 Within Budget。
- V1 使用已有 growth 数据，按商品 ID 排除已入单商品；不纳入计划统计。
- 复用浅背景和现有样式，减少卡片，表格增加横向滚动，窄屏汇总采用两列。

## 复用的数据

本项目通过 Python 服务调用传递数据，没有新增 HTTP API。
复用 StructuredIntent、Uncertainty.FieldSources、AIAnalysisStatus、final_purchase_plan、
optimizer_result、validation_result、why_selected 及 V1 的 procurement_plan/growth。
未修改推荐引擎、Prompt、模型路由、Validator 或 Repair。

## 明确缺口

- V2 没有明确的未入单机会集合：显示不可用提示，不从 DISCOVERY 或 unallocated_candidates 推断机会。
- V1 没有等价的校验契约；priority 原始值也不保证统一成 High/Medium/Low，因此原样展示。
- Evidence 尚无统一类型与来源契约：本次展示已有理由，没有补造分组或证据。
- 字段来源不完整，不能为所有字段标记默认值来源。

## 验证范围

- unittest 全套 167 项通过；最后的样式与输入状态微调后，13 项 UI 测试再次通过。
- 六条 Demo 输入完成离线页面渲染、顺序和预算检查；采购结果使用显式测试 fixture，不代表真实模型六场景验收。
- 已验证失败校验隐藏计划、合法空计划、缺失金额不转为零、缺失意图字段不补值、fallback 不宣称验证通过。
- 现有六场景工作簿映射、候选契约及 optimizer 场景测试通过。
- Python 编译检查和 git diff --check 通过。项目没有独立的 lint/typecheck/build 配置。
- 浏览器检查使用 AI_ENABLED=false，仅运行本地数据与规则 fallback，没有调用外部模型。
- 浏览器初始页、无预算 fallback 及 390px 窄屏检查通过：页面 scrollWidth=390；表格容器宽 348、内容宽 620，overflow-x=auto，没有撑宽整页。

## 修改文件

- app.py
- services/ui.py
- tests/test_ui_refactor.py
- tests/test_v2_ui.py（更新计划标题断言）
- 本交付记录

仓库原有未提交的后端及文档修改未纳入本次 UI 修改。
