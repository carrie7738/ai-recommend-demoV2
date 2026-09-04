# V2 韧性覆盖审计

审计日期：2026-09-04

本轮只对本地确定性路径和 DeepSeek adapter 接口做回归。所有新增测试都注入 fake client，
不会访问真实 API；Gemini 调用和 A/B 比较按当前任务范围暂停。

## 新增证据

`tests/test_v2_resilience.py` 共 9 个测试，覆盖以下此前缺少的边界：

| 区域 | 本地证据 |
| --- | --- |
| Model provider 缺少 key | provider 标记不可用，调用在 client 创建前失败 |
| timeout | 转换为 `ModelProviderError`，adapter 请求次数保持 1 |
| HTTP 429 | 转换为 `ModelProviderError`，adapter 请求次数保持 1 |
| 空内容 | 在 JSON 解析前拒绝，并保留未解析状态 |
| 非法 JSON | 返回明确错误，`json_parse_success=False` |
| schema-capable Intent | 即使 provider 声称支持 JSON Schema，也由本地完整 Intent schema 校验并回退 |
| Intent transport 失败 | 回退到规则解析，同时保留可信门店身份和 `StructuredIntent.store_id` |
| 非法 `AvailableStock` | candidate pool 按无可用库存 fail-closed，并记录 `NO_AVAILABLE_STOCK` |
| 非法 Product `AvgCost` | local optimizer 拒绝继续计算并抛出 `LocalOptimizerError` |

## 已有覆盖，未重复添加

- 空 eligible candidates 不调用 AI，并返回合法零采购 V2 成功结果：`tests/test_ai_decision.py`。
- 预算、当前库存、供应库存、SalesUnit、尾库存和确定性修复：`tests/test_local_optimizer.py`、
  `tests/test_hard_validator.py`、`tests/test_v2_optimizer_scenarios.py`。
- 一次 constrained retry 的上限，以及 retry 后重新优化/校验：`tests/test_hard_validator.py`。
- 原始 V2 失败原因保留在 fallback status 和 UI：`tests/test_app_state.py`、`tests/test_v2_ui.py`、
  `tests/test_v2_ui_runtime.py`。
- 缺失或小数 SalesUnit fail-closed：`tests/test_v2_candidate_pool.py`。

## 当前 gap 和未验证范围

1. 本轮没有真实 DeepSeek 异常注入；timeout、429、空内容和非法 JSON 的证据来自 fake
   OpenAI-compatible client。没有声称真实网络、代理网关或供应商响应格式已通过。
2. adapter 自身不做应用层重试；本轮只证明一次调用不会在 adapter 内循环。OpenAI SDK
   默认 transport retry、连接超时配置和 429 backoff 未在本地 fake client 中验证。
3. 合法 JSON 但根节点为数组或其他非 object 时，provider 会拒绝，但目前没有专门回归
   记录该分支的 metrics 语义；schema 校验失败主要在 IntentParser 本地路径验证。
4. Streamlit 主函数的完整状态迁移（pipeline 抛错、保存 `v2_error`、同一轮执行 V1
   fallback）没有在本轮新增测试；现有 helper、runtime rendering 和 pipeline gate 测试
   已验证错误文本/展示及失败时不生成最终 V2 计划。
5. Gemini 实际 API、跨 provider A/B、配额恢复和 profile-bearing 请求均未验证，符合当前
   “仅 DeepSeek，不做 A/B 或 Gemini API”范围。

## 执行结果

使用仓库虚拟环境执行：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_v2_resilience
```

结果：9 tests，全部通过。

相关回归组合执行（不触发真实 API）：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_v2_resilience tests.test_model_providers tests.test_intent_parser tests.test_app_state tests.test_v2_candidate_pool tests.test_local_optimizer tests.test_v2_ui tests.test_v2_ui_runtime
```

结果：74 tests，全部通过。测试日志中的 fallback、timeout、429 和 Streamlit
`ScriptRunContext` 提示均为预期日志，不是失败。
