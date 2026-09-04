# V2 UI 验收记录 — 2026-09-04

## 真实浏览器（部分完成）

本机 Streamlit，DeepSeek `deepseek-v4-flash`；请求：
`For Cafe Store 001, high traffic is expected next week. Budget is NZD 1000.`
门店解析为 C001，不能与六场景 harness 的 C051 混用。

- 初始页面只有请求输入，不预先展示客户采购数据。
- 已在浏览器可访问性树及截图检查请求区、AI Understanding、模型状态和商品解释卡片；布局可读。
- 页面实际展示 Structured Intent、Procurement Strategy、AI Product Decisions、Final Purchase Plan；
  商品卡包含 priority/intensity 和理由；表格包含数量、单位、单价、金额和 priority；预算汇总包含总额与余额。
- 本次实际结果为 12 行 discovery、总额 NZD 242、余额 NZD 758，Validator 通过。
- 但 Intent 因 `store_context` schema 冲突降级，页面显示 `Rules Fallback`、`Intent: fallback`。
  `Fallback: No` 指 V1 pipeline fallback，不能理解为 Intent 没有降级。本次不算全链路真实模型通过。
- 已修正提示词明确 `store_context` 必须为空对象，由本地补入可信门店资料。
  自动审批拒绝了重新生成（门店资料向 DeepSeek 外发），修正后的真实 UI 验收仍待明确授权。

## 离线 Streamlit 运行时

`tests/test_v2_ui_runtime.py` 使用真实 AppTest 渲染，不调用 API：

- 合法空方案：Validated、零金额、No executable purchase quantities。
- Validator 失败：隐藏采购表，显示具体 violation。
- V1 fallback：保留 V2 FAILED 与经过 HTML 转义的原始原因。

三项通过。此证据不替代修正后真实 API 的浏览器验收，也不代表用户已完成人工验收。
