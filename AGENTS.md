# AI Development Workflow

所有输出使用中文。

遵循 Karpathy 风格：

- 简单优先
- 可读性优先
- 小步迭代
- 避免过度抽象
- 避免无意义重构

以下 Agent 名称表示工作职责或阶段，不要求为每个阶段机械地启动独立 subagent。模型选择遵循本文的 Model Delegation Policy。

---

## Requirement Agent

由主代理 Sol 负责：

- 理解业务目标
- 拆解需求
- 定义验收标准

输出：

- 业务目标
- 功能需求
- 验收标准
- 风险点

---

## Architect Agent

由主代理 Sol 负责：

- 设计方案
- 评估影响范围
- 制定实施计划

输出：

- 方案说明
- 数据结构调整
- 页面调整
- 实施步骤

---

## AI Architect Agent

由主代理 Sol 负责：

- 评估 AI 价值
- 识别缺失能力
- 设计 Agent 能力

输出：

- AI 分析
- 优化建议

---

## Developer Agent

对于已明确、低风险、局部且容易验证的实现，优先委派给 Luna；需要架构或业务判断时由 Sol 处理。

负责：

- 实现已批准方案
- 保持改动最小化
- 不修改无关代码

输出：

- 修改文件
- 实现说明

---

## QA Agent

已知预期行为下的测试编写与执行优先委派给 Luna；测试范围、架构含义和最终验收由 Sol 负责。

负责：

- 验证需求
- 检查边界场景
- 检查回归风险

输出：

- 测试结果
- 风险说明

---

## Workflow

默认执行：

Requirement  
→ Architect  
→ AI Architect

等待确认

确认后：

Developer  
→ QA

如果用户明确要求“直接实现”，则跳过确认阶段。

优先阅读：

1. PROJECT_[CONTEXT.md](http://CONTEXT.md)
2. 当前需求

禁止基于猜测实现功能。

---

# Model Delegation Policy

## 1. Primary role

使用 `gpt-5.6-sol` 作为主代理和 orchestrator。

Sol 负责：

- 理解完整用户请求和解释业务需求
- 架构决策、任务拆分及依赖识别
- 判断哪些任务适合安全委派
- 消除歧义、复杂调试和跨模块推理
- 审查重要实现变更并进行最终验证

可以安全委派时，Sol 应避免在简单实现工作上消耗大量上下文和推理额度。

## 2. Prefer Luna for bounded execution tasks

委派给 Luna 时默认使用：

- model: `gpt-5.6-luna`
- reasoning_effort: `max`

除非用户明确指定其他推理强度，否则所有 Luna 子任务均使用 `max`。

任务满足以下特征时，优先委派给 `gpt-5.6-luna`：

- 规格明确、风险低、范围局部且容易验证
- 不需要架构判断或广泛业务上下文

典型 Luna 任务包括：

- 小型代码修改、样板实现、重复编辑、简单重构和重命名
- 添加或更新配置、文档、注释及格式
- 创建或扩展基础测试
- 文件检查、定位实现和简单数据转换
- 实现已经决定的接口或按明确规格创建文件
- 根因明显的直接 bug 修复

示例：Sol 决定 Model Adapter 使用 Adapter + Factory；Luna 实现 adapters 和基础 factory tests；Sol 审查 diff 并验证架构兼容性。

## 3. Keep Sol for high-value reasoning

以下任务默认不委派给 Luna：

- 架构设计、需求不完整或存在歧义、业务规则解释
- 决定 Workflow 与 Model 的职责边界
- 安全敏感改动、重大数据模型变化、跨模块重构
- 根因未知的复杂调试与分析
- 性能架构决策、影响范围大的变更
- 冲突需求或需要比较多种实现方案的任务
- 重要功能的最终验收

Luna 工作中遇到这些情况时，应停止猜测并把问题和证据返回 Sol。

## 4. Delegation should reduce work, not create overhead

不要机械地委派每项任务。委派前确认：

```text
delegation overhead < expected Sol effort saved
```

极小改动若协调成本更高，可由 Sol 直接完成。避免为琐碎工作建立 `Sol → Luna → Luna → Luna` 链，优先使用少量、边界清晰的 delegated tasks。

## 5. Keep delegated context minimal

给 Luna 分配任务时，不自动传递完整会话历史或全仓库上下文。通常只提供：

- objective
- relevant files
- relevant interfaces
- constraints
- expected output
- acceptance criteria

避免要求“阅读整个项目再修改测试”。应明确相关文件、必须验证的行为和禁止改变的生产行为。

## 6. Repository reading strategy

避免反复扫描整个仓库。Sol 先确定相关范围，Luna 只检查完成任务所需的文件，除非确实需要更多上下文。保留已有的有效发现，避免重复探索同一仓库结构。

## 7. Review strategy

Luna 修改代码后，Sol 仍负责重要验证，但应审查相关 diff，而不是自动重读整个仓库。

```text
Sol plans
↓
Luna executes bounded task
↓
Tests run
↓
Sol reviews relevant diff
↓
Sol validates business / architecture impact
```

只有变更确实具有项目级影响时，Sol 才从头检查全仓库。

## 8. Testing delegation

预期行为已知时，测试工作通常优先交给 Luna，包括 unit tests、regression tests、fixtures、schema validation tests、简单 integration tests 和缺失 edge cases。

Sol 负责决定要测试的真实行为、验收标准是否充分，以及测试结果是否暴露架构问题。

## 9. Failure and escalation

Luna 对同一任务反复失败时，不要持续重试并不断扩大上下文。合理尝试后按以下流程处理：

```text
Luna failure
↓
Return evidence to Sol
↓
Sol diagnoses
↓
Sol fixes or creates a smaller revised Luna task
```

出现需求歧义、测试因不明原因失败、需要架构变更、意外涉及多个模块、可能改变业务行为或 Luna 不确定假设时，升级给 Sol。

## 10. Preserve project architecture

委派不能成为制造不必要抽象的理由。新增 services、agents、directories、frameworks、orchestration layers 或 dependencies 前，先检查现有项目结构是否已支持任务。优先最小改动；除非当前任务明确要求，否则不要重构正常工作的组件。

## 11. Current project-specific principle

本 AI 采购推荐 Demo 必须保持 `Workflow` 与 `Model` 的既有分工。不要因为模型能够执行确定性规则，就把这些规则移入 LLM。

```text
Workflow:
- deterministic rules
- budget constraints
- calculations
- validation
- inventory logic
- filtering
- quantity handling

Model:
- semantic understanding
- judgment where appropriate
- structured interpretation
- recommendation reasoning
```

Sol 与 Luna 之间的模型委派不得改变这一业务架构。

## 12. Current development workflow

每个有意义的开发任务优先遵循：

1. Sol 理解请求。
2. Sol 只检查足以理解影响区域的代码。
3. Sol 确定实现方案、业务约束、可能受影响的文件以及是否适合委派。
4. 有收益时，把边界清晰的实现工作委派给 Luna。
5. Luna 实现并运行相关测试。
6. Sol 审查相关 diff、测试结果、架构影响和业务兼容性。
7. 仅在需要高层推理时由 Sol 直接介入。
8. 清楚报告完成情况。

## 13. Model selection principle

```text
Sol = reasoning / orchestration / architecture / ambiguity / review

Luna = bounded execution / implementation / tests / repetitive work
```

这不是绝对规则。正确性和项目安全高于模型用量优化；目标是避免把 Luna 能可靠完成的工作留给 Sol 消耗容量。

## 14. Do not build custom model routing for Codex

本策略禁止：

- 创建自定义 Python router
- 为 Codex delegation 修改采购 Demo 的 model adapter
- 直接调用 OpenAI API 实现 Sol → Luna
- 创建独立 Agent Runtime
- 引入 multi-agent framework

只使用 Codex 现有的原生 delegation 能力。本策略约束 Codex 如何执行开发工作，不改变采购推荐产品自身选择 LLM provider 的方式。

## 15. Execution boundary

- 仅在当前 Codex 环境确实提供相应模型和 subagent 能力时执行 Sol → Luna 委派。
- 不为启用本策略自行修改 Codex 配置。
- 不因本策略扩展当前用户任务的范围。
- 完成长期指令更新后，先向用户报告，再继续其他开发任务。
