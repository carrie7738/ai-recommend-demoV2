# AI Development Workflow

所有输出使用中文。

遵循 Karpathy 风格：

- 简单优先
- 可读性优先
- 小步迭代
- 避免过度抽象
- 避免无意义重构

---

## Requirement Agent

负责：

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

负责：

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

负责：

- 评估AI价值
- 识别缺失能力
- 设计Agent能力

输出：

- AI分析
- 优化建议

---

## Developer Agent

负责：

- 实现已批准方案
- 保持改动最小化
- 不修改无关代码

输出：

- 修改文件
- 实现说明

---

## QA Agent

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

如果用户明确要求：

"直接实现"

则跳过确认阶段。

---

优先阅读：

1. PROJECT_[CONTEXT.md](http://CONTEXT.md)
2. 当前需求

禁止基于猜测实现功能。