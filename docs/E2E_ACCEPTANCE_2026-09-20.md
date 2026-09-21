# 2026-09-20 端到端验收记录

## 结论

基线提交 `3022c13` 的真实 DeepSeek 主链路通过。本轮完成结构化 Smoke、六场景回归和浏览器交互验收：

- Smoke：PASS；Intent 与 Decision 均为真实响应、JSON 可解析、Schema 通过，无 retry 或 fallback。
- 六场景：6/6 为 `Intent=live`、`V2=SUCCESS`、`Validator=PASS`，无合同违规、repair 或 V1 fallback。
- 浏览器：首次和再次提交、独立运行 Trace、Trace 筛选与下载、未知门店提示、错误后旧结果清理均通过。
- 2026-09-21 数据对齐后，UI 的 C001 请求已产生可执行采购单；C051 六场景身份保持不变。

验收日期为 2026-09-20，运行环境为 Windows、Python 3.12.14、Streamlit 1.62.0。真实模型请求使用用户授权的演示数据。

## 2026-09-21 C001 数据对齐复验

为统一 UI 演示门店，在 `Inventory` 中为 C001 补充 P201-P215 共 15 条 V2 库存记录。库存数量、快照日期、有效期和状态与现有 C051 V2 样本一致；C051 的场景、订单历史及六场景审计身份未改动。

浏览器请求 `For Cafe Store 001, high traffic is expected next week. Budget is NZD 1000.` 的真实模型结果：

- Provider `deepseek`，Model `deepseek-v4-flash`，Intent `live`，Decision `MODEL`，V2 `SUCCESS`，无 fallback。
- Business Data Date 为 2026-06-02，来源 `SupplyAvailability.LastUpdated.latest_not_future`。
- 采购 5 个 SKU：P204×2、P208×4、P210×6、P211×4、P215×5；总额 NZD 104，余额 NZD 896。
- Debug Trace 运行 ID `cd360e0f-849d-4cf6-bfc0-69ba89ba27fe`，捕获 48 个事件；Validator `PASS`、违规数 0，final `success`。

新增数据对齐测试覆盖 C001 的 V2 库存唯一性和高客流请求的非空采购结果。全量离线测试 232/232 通过，耗时 109.822 秒。

## 真实模型 Smoke

命令：

```powershell
.\.venv\Scripts\python.exe scripts/model_smoke_test.py --provider deepseek --model deepseek-v4-flash
```

| 阶段 | API | JSON | 延迟 | Token | 实际响应模型 |
| --- | --- | --- | ---: | --- | --- |
| Intent | 成功 | 成功 | 5711.5 ms | 3779 in / 597 out | `deepseek-flash` |
| Decision | 成功 | 成功、Schema 通过 | 1172.0 ms | 1005 in / 182 out | `deepseek-flash` |

配置请求模型为 `deepseek-v4-flash`，供应商响应指标报告为 `deepseek-flash`。两次调用均正常结束且未截断；该名称差异需要在后续模型锁定或供应商审计中继续核对。

机器可读证据：`outputs/e2e-smoke-2026-09-20.json`（Git 忽略）。

## 六场景回归

命令：

```powershell
.\.venv\Scripts\python.exe scripts/v2_scenario_regression.py --provider deepseek --model deepseek-v4-flash --summary
```

| 场景 | 门店 | 日期 | 采购行 | 总额 NZD | 余额 NZD | 结果 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| 01 high traffic | C051 | 2026-06-02 | 6 | 506 | 494 | PASS |
| 02 holiday promo | C051 | 2026-12-10 | 2 | 980 | 20 | PASS |
| 03 low budget | C051 | 2026-06-02 | 4 | 296 | 4 | PASS |
| 04 long shelf | C051 | 2026-06-02 | 6 | 506 | 494 | PASS |
| 05 fruit focus | C051 | 2026-06-02 | 6 | 506 | 294 | PASS |
| 06 no budget | C051 | 2026-06-02 | 6 | 506 | 不适用 | PASS |

C051 来自 `V2TestScenarios` 的可信场景绑定，不是 UI 门店解析器支持范围。脚本中用户可见文本与测试身份的绑定已显式固定，不能用 UI 解析结果替换。

机器可读证据：`outputs/e2e-scenarios-2026-09-20.json`（Git 忽略）。

## 浏览器验收（2026-09-20 数据修复前）

本机以 `AI_ENABLED=true`、`AI_PROVIDER=deepseek`、`DEEPSEEK_MODEL=deepseek-v4-flash`、`PROCUREMENT_DEBUG=true` 启动 Streamlit，并在 `http://127.0.0.1:8502/` 操作。

1. 空请求显示补充采购需求的提示，没有触发模型。
2. 请求 `For Cafe Store 001, high traffic is expected next week. Budget is NZD 1000.`：
   - 解析到 C001；Intent=live，Decision=MODEL，Validator=PASS，最终状态 success。
   - 运行 ID `9f51ab6f-537e-4919-8255-3bd89d718394`，预算 NZD 1000，采购行数 0。
   - SKU `P201` Trace 筛选仅改变展示，没有产生新运行。
   - “下载脱敏 Trace JSON”触发浏览器 download 事件。
3. 再次提交同一门店、预算 NZD 300：
   - 新运行 ID `0d18aac9-0bfb-48f6-b4f0-d70305250198`，证明两次运行相互隔离。
   - 页面显示预算 NZD 300、Intent=live、Decision=MODEL、Validator=PASS、最终状态 success。
   - 仍为合法空采购单；页面明确列出缺少或无效库存的 P201-P215。
4. 请求 C051 和 C999 均在门店解析阶段被拒绝，显示未知门店提示；上一轮采购计划和 Trace 已清空，没有残留结果或额外模型调用。

本节记录数据修复前的历史行为。实现仍将未知库存与零库存分开处理；2026-09-21 已为 C001 补齐可执行库存，当前结果见上方复验记录。

验收时发现 Debug Trace 表格仍使用 Streamlit 已弃用的 `use_container_width=True`。本轮已等价替换为 `width="stretch"`；受影响的 UI 测试通过。

验收后进一步明确了日期语义：页面始终标记 `DEMO MODE`，页头显示实际计算使用的 `Business Data Date` 及来源；`Run ... local` 单独表示本地运行时间。C001 本轮业务日期为 2026-06-02，来源为供应快照，不再把 2026-09-20 的运行时间显示成 Analysis Time。

上述修改完成后，全量 230 项离线测试通过，耗时 108.358 秒，退出码为 0；日志位于 `outputs/demo-date-tests.log`（Git 忽略）。

## 已知边界

- 本次证明的是单次真实调用与六场景结果，不构成随机稳定性或并发压力测试。
- C051 场景数据覆盖采购执行，但没有 `ConversationContext`，因此不能直接通过 UI 门店解析器进入；它继续作为脚本化审计身份。
- C001 已覆盖 UI 解析和 P201-P215 的 V2 库存，但没有迁移 C051 的专用历史订单；当前 C001 的 V2 候选主要来自同业信号。
- GitHub Actions 的 Windows、Ubuntu 远端运行仍需在推送后确认；当前本地证据为 232 项离线测试全部通过。
