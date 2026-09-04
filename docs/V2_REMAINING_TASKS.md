# V2 后续任务（2026-09-04）

用户已要求当前只使用 DeepSeek，暂时移除模型 A/B 测试。Gemini 实测和跨模型比较暂停；保留现有 adapter 和脚本，不增加路由。

基线：`aad1da2`（本地 stabilization checkpoint）。当前工作区的修复与验收证据必须单独记录，不能套用旧版本 API 结果。

| 任务 | 当前执行范围 |
| --- | --- |
| Task10.1 | 已完成：repair 日期与可信成本一致性修复，4 项回归；最终全量 162/162 通过 |
| Task11 | DeepSeek smoke：已通过真实 Intent/Decision 调用；详见 provider 测试文档 |
| Task12 | 待明确授权门店资料发往 DeepSeek 后运行六场景及同条件行为对照；不得用旧结果代替 |
| Task13 | 部分完成：真实 C001 UI 暴露 Intent fallback，提示已修正待真实复验；离线空方案/失败显示通过 |
| Task14 | 暂停：模型 A/B 测试，不调用 Gemini |
| Task15 | 参数/文档一致性审计完成；生产参数校准仍需业务证据，未调值 |
| Task16 | gap 审计完成，新增 9 项本地测试通过；真实网络及 SDK transport retry 未验证 |
| Task17 | 合同字段消费者与精简机会审计完成；保留正在使用的兼容字段，验收前不大重构 |

## 验收身份边界

六场景 harness 显式绑定 `C051 / V2 Target Cafe`，但视频请求字符串写 `Cafe Store 001`。
UI 通过 StoreResolver 解析该文本为 `C001`；当前 ConversationContext 仅包含 C001–C005，C051 不可从该 UI 入口选择。
因此 C051 脚本结果与 C001 浏览器结果必须分别标注，不能声称同一门店端到端一致。

不自动提交或推送。保留用户已有 AGENTS.md 修改；推送前仍需确认 checkpoint 的 CodexSandboxOffline 提交身份。

## 本轮本地验证

` .\.venv\Scripts\python.exe -m unittest discover -s tests -v `：162 项通过，34.243 秒。
Validator 新增回归先在旧实现暴露日期参数缺失、低/高伪造成本及元数据修正未生效的问题，
修复后目标测试 15/15 通过。上述结果不替代真实 API 或用户人工 UI 验收。

详细证据：`V2_MODEL_PROVIDER_TESTING.md`、`V2_UI_ACCEPTANCE.md`、
`V2_RESILIENCE_REVIEW.md`、`V2_CONTRACT_MAINTENANCE_REVIEW.md`。
