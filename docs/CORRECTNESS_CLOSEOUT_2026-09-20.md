# 正确性修复收尾记录

范围：2026-09-08 审查后中断的正确性修复及其关联 Debug/Trace 工作区改动。
基线 HEAD：`2e09c35b3dbde5a46eb9d9e1187f2f71bd76e081`。本记录对应未提交工作区，不是发布或线上验收报告。

## 改动分组

| 分组 | 内容 | 主要验证入口 |
| --- | --- | --- |
| 意图与约束 | 否定商品成为 PRODUCT/EXCLUDE；V2 候选和 V1 降级保留排除条件；预算支持千分位及基础中文表达，无效/冲突声明要求澄清 | `test_intent_correctness.py`、`test_intent_parser.py`、`test_v2_preparation.py` |
| 数据缓存 | 规范化文件路径、mtime_ns、size 参与缓存键；覆盖不同文件、更新和删除 | `test_excel_loader.py` |
| 独立校验 | 从 Product 读取 SalesUnit/AvgCost，修复路径使用可信主数据；拒绝无效数量和主数据 | `test_validator_regression.py`、`test_hard_validator.py` |
| 未知库存 | 缺失、负数或非有限库存不按零库存补货；跳过对应候选并在 UI 披露 | `test_inventory_regression.py`、`test_intent_correctness.py` |
| 调用指标与日志 | 每次调用重置 metrics，失败记录本次耗时和状态；普通错误日志脱敏及长度限制 | `test_provider_metrics_regression.py` |
| Debug/Trace | 环境开关、会话隔离、输入输出快照、SKU 检索和导出；刷新不重跑采购流程 | `test_runtime_trace.py`、`test_debug_trace_ui.py`、`test_app_state.py` |
| 开发文档 | AGENTS 规则精简与模型委派策略、README 启动/配置/验证说明 | 本地链接、编码及 diff 检查 |

这些改动部分共享 app、preparation、optimizer、provider 等文件。后续提交应审查相关 diff 与依赖，不能仅按文件名机械拆分；新增未跟踪模块和测试也必须纳入版本。

## 本轮补充

- 复现并修复预算声明部分解析：`no budget limit, budget 100` 不再返回无限预算；`budget 100 and budget unclear` 等不再静默取第一个有效值。
- 同一金额重复声明和金额后的 NZD/dollars 单位仍可正常解析。
- 补上成本元数据一致性校验：即使没有预算违规，伪造单价、行费用、总额或剩余预算也会触发 `COST_METADATA_MISMATCH`，本地修复后重新校验。
- Trace 无法序列化的值改为固定脱敏占位，保留原业务返回值；校验前快照失败也不阻止函数执行。异常本身无法转为字符串时保留原异常。
- 新增 `private_key` 字段、内联键值及 PEM 私钥文本脱敏。

## 最终验证

- 在仓库根目录设置 `AI_ENABLED=false`，运行 `.venv/Scripts/python.exe -m unittest discover -s tests`：**228 tests，38.376 秒，OK**。
- 67 个 Python 文件 AST 解析通过；文档本地链接、UTF-8/NUL 检查及 `git diff --check` 通过。
- Trace/UI/请求状态专项 27 项通过；校验器/缓存/provider 专项 42 项通过；最终全量包含上述测试及预算补充回归。
- 本地完整日志：[closeout-tests-2026-09-20.log](../outputs/closeout-tests-2026-09-20.log)。代码、测试、数据及 requirements 的 69 文件 SHA-256 快照：[closeout-manifest-2026-09-20.json](../outputs/closeout-manifest-2026-09-20.json)。`outputs/` 被 Git 忽略，这两个文件仅在当前工作区存在；克隆仓库后需重新生成验证证据。
- 本轮代码审查与离线收尾完成，改动仍未提交。后续版本提交应包括新增模块和测试；提交后记录 commit 并另行进行真实模型验收。

## 验证边界与后续

- 本次不调用真实模型、不部署、不提交或推送。离线测试包含模拟 provider 和 Streamlit AppTest，不等于真实 API、人工浏览器或线上验收。
- 旧 V2 验收报告对应旧版本，不能覆盖本轮代码与 Prompt/Schema 改动；真实模型六场景及浏览器验收仍是后续步骤。
- 缓存采用文件状态键，不是内容哈希；内容被替换但路径、大小、mtime_ns 全部不变时，不保证失效。
- 自然语言本地解析仍是有限规则集，不保证任意否定、比较、替代或预算表达都能理解。
- V1 降级仍不是完整 V2 校验链；保留未验证标识。显式 Demo 日期、依赖锁定、CI 和独立业务评估不属于本轮修复范围。
- 原有视频素材与部署配置未在本轮修改。
