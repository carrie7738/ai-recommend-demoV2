# 项目清理与结构重构设计

> 状态：待审阅
> 日期：2026-06-20
> 作者：brainstorming 流程产出
> 适用范围：AI Procurement Assistant Demo（`/Users/carrie/Documents/ai/recommend demo`）

## 1. 背景与目标

通读项目后发现多处不合理之处，跨结构、配置、安全、逻辑、代码质量、文档测试 6 大类。经与用户确认，本次重点解决其中 4 类：

- 逻辑不一致修复
- 代码质量小修
- 结构与架构重构
- 文档与测试整理

未纳入本次的 2 类（配置与依赖修复、安全与部署清理）作为后续路线图。

**核心约束**：重构必须保持现有 demo 行为与 UI 外观完全不变。所有改动为行为保持型（behavior-preserving），客户演示体验不受任何影响。

**推进策略**：方案 A —— 按风险递增分三批，每批可独立验证、独立提交，契合 `agent.md` 的"小步迭代、简单优先"原则。

## 2. 范围

### 纳入本次

- 批 1：零风险纯内部修复（代码质量 + 逻辑不一致中不改外观的项）
- 批 2：结构重构（行为保持，靠测试守）
- 批 3：文档整理 + 测试补齐

### 不纳入本次（路线图）

- 配置与依赖修复（settings 默认 model、dotenv 支持、.gitignore、git 初始化）
- 安全与部署清理（README 服务器 IP、systemd 占位 key）
- 风险等级 Medium/High 配色区分（本质需改 CSS，违反外观不变约束）

## 3. 约束与原则

- **行为不变**：UI 渲染输出、推荐算法结果、页面文案与布局必须与当前一致。
- **小步迭代**：每批独立闭环（改 + 测 + 验证），不跨批硬耦合。
- **避免过度抽象**：遵循 Karpathy 风格，拆分只为单一职责，不为拆而拆。
- **禁止基于猜测**：所有改动基于已读代码，不臆造功能。

## 4. 批 1 设计：零风险纯内部修复

### 4.1 代码质量小修

| 项 | 文件:行 | 改动 |
|---|---|---|
| `import re` 移顶部 | `services/intent_parser.py:119` | 从 `_fallback_parse` 内部移到模块顶部 |
| `"no "` 误匹配 | `services/intent_parser.py:138` | 改为精确匹配 `"avoid"`/`"exclude"`/`"no fresh"`/`"no dairy"` 等组合，避免命中 `"next week"`/`"no problem"` |
| 缩进异常 | `engines/replenishment_engine.py:95` | 修正多余空格 |
| 魔法数字 | `engines/replenishment_engine.py:92-101` | `60`/`40` 提为常量 `HIGH_SCORE_THRESHOLD`/`MEDIUM_SCORE_THRESHOLD` |
| `page_icon` 空值 | `app.py:51` | 改为合理默认或移除参数 |
| `customer_name` 硬编码 | `app.py:97`、`services/ui.py:893` | 默认值 `"Auckland Central Supermarket"` 合并为 `config/settings.py` 单一常量 |

### 4.2 逻辑不一致修复（内部统一，保外观）

**action 词汇表对应关系文档化**：
- 经分析，`_with_allocation_tier` 产出的 engine action（`Order Now`/`Buy on Price Advantage`/`Order This Week`/`Monitor Price`/`Trial Buy`）与 UI `_get_action_tag` 的显示文案（`Order Immediately`/`Order This Week`/`Monitor`）无法单值映射——同一 engine action `Order Now` 在 UI 当前会按 `coverage_days` 再分为 `Order Immediately`（≤3 天）与 `Order This Week`（>3 天）。
- 在"外观不变"硬约束下，强行统一会改变 replenishment 卡片显示，故**本次不强行统一**，仅在 `_get_action_tag` 与 `_with_allocation_tier` 处加注释说明两套词汇表的对应关系与历史原因。
- 真正的词汇表统一移入路线图（需配合 UI 文案重设计）。

**`render_risks_section` fallback 修复**（`services/ui.py:1142-1167`）：
- 当前用列表位置 `risks[len(out_of_stock):len(out_of_stock)+3]` 硬凑 overstock/near_expiry，会错放分类。
- 改为按字段真实分类：overstock = `coverage_days is not None and coverage_days > 30`；near_expiry = `risk_level == "Medium"`。注意 `risk_engine` 输出的 risks 字典不含 `BatchExpiryDate` 字段，故 near_expiry 只能按 `risk_level` 判定（与当前一致，仅去掉错误的列表位置 fallback）。
- Tab 名与每 tab 展示数量上限不变。

**`strength` 语义**（`engines/scoring_utils.py`）：
- 保留 `strength()` 返回值（保外观），但在 `_with_allocation_tier` 中不再把 `recommendation_strength` 当 action 判断依据，改用明确的 `priority`/`coverage_days`/`price_signal`。
- 加文档注释说明 "Monitor" 档实为低强度可观察档，避免后续误读。

**`suggest_session`**（`services/context_engine.py:47`）：
- 保留多 session 匹配能力不删，仅补注释说明 demo 当前单 session 场景，避免未来误删。

### 4.3 批 1 验收

- `python -m unittest tests.test_recommendation_engine` 全过。
- 手动跑 demo，对比修复前后页面，确认渲染输出无差异。
- `intent_parser` fallback 对 `"next week no problem"` 不再误判 `ExcludedCategory`。

## 5. 批 2 设计：结构重构（行为保持）

### 5.1 拆分 `services/ui.py`（1370 行 → package）

转为 `services/ui/` package，`__init__.py` 重导出所有公开函数，**保持 `app.py` 的 `from services.ui import ...` 完全不变**：

```
services/ui/
  __init__.py            # 重导出 render_*、inject_theme
  theme.py               # inject_theme + 全部 CSS
  components/
    __init__.py
    header.py            # render_header
    ai_request.py        # render_ai_request_section
    ai_understanding.py  # render_ai_understanding + _titleize_signal/_confidence_class
    replenishment.py     # render_replenishment_section + _get_action_tag
    growth.py            # render_growth_section
    risks.py             # render_risks_section + _render_risk_list
    procurement_plan.py  # render_procurement_plan_report + _procurement_reasons/_business_reason_from_raw
```

每文件约 100-250 行，单一职责。

### 5.2 清理 `models/` 死代码

`Customer`/`Product`/`Inventory` 三个 dataclass（`models/customer.py`、`models/product.py`、`models/inventory.py`）全项目从未被引用，代码都用 dict 传递。

**直接删除 `models/` 目录**（YAGNI）。不选"真正用起来"——那会改所有 engine 返回值，违反行为不变且超出批 2 范围。未来若要引入领域模型，按需重建。

### 5.3 解耦 `excel_loader.py` 对 streamlit 的依赖

- 移除 `import streamlit as st` 和所有 `@st.cache_data` 装饰器。
- `_self` 参数改回 `self`（`@st.cache_data` 的特殊约定不再需要）。
- 成为纯 pandas 加载器。
- 缓存职责上移到 `app.py`：把现有 `get_workbook()` 改用 `@st.cache_data(show_spinner=False)` 包装 `get_excel_loader().load_workbook()`。
- 收益：excel_loader 可在测试/CLI 中无 streamlit 运行。

### 5.4 `app.py` 去重（第 96-110 行）

当前 customer 信息查了两次（`customer_df` 与 `customer_row2` 几乎相同）。在 `ContextEngine` 加一个方法：

```python
def get_customer_info(
    self, workbook: dict[str, pd.DataFrame], customer_id: str
) -> dict[str, str]:
    """返回 {"store_name": ..., "industry": ...}，缺失时给默认值。"""
```

`app.py` 调用一次即可。职责合理（context 本就关联 customer）。

### 5.5 批 2 验收

- 现有测试全过。
- 批 2 重构前补的 `excel_loader`/`context_engine` 最小测试也过。
- 手动跑 demo 截图对比，渲染输出与批 1 后无差异。
- `python -c "from services.excel_loader import ExcelLoader"` 无 streamlit 也能 import。
- `grep -r "from models" --include=*.py`（项目源码，排除 .venv）无命中。

## 6. 批 3 设计：文档整理 + 测试补齐

### 6.1 修 `agent.md` 链接错误

第 119 行 `[PROJECT_CONTEXT.md](http://CONTEXT.md)` 把本地文件名误转为 URL。项目中无 `PROJECT_CONTEXT.md`，改为指向实际存在的 `README.md`，或改为纯文本"优先阅读：README.md 与当前需求"。

### 6.2 `docs/` 下两个 .docx 转 markdown

- `docs/AI_Smart_Procurement_PRD_V2_Full.docx` → `docs/AI_Smart_Procurement_PRD_V2_Full.md`
- `docs/Recommendation_Engine_Specification_V1.docx` → `docs/Recommendation_Engine_Specification_V1.md`

用 `python-docx`（或 pandoc 若可用）提取文本转 md，保留标题层级与表格。转换后删除原 .docx。若 docx 内有无法无损转换的复杂格式，保留核心文本并标注。

### 6.3 文档去重（最小化调整）

重新分工，不重写内容，只删重复段 + 加交叉链接：

| 文档 | 职责 | 调整 |
|---|---|---|
| `README.md` | 项目概览 + 快速开始 + 部署 | 推荐逻辑详述改为链接指向 `CUSTOMER_DEMO_GUIDE.md`，不再重复 |
| `CUSTOMER_DEMO_GUIDE.md` | 业务向功能与演示话术 | 保留现有推荐逻辑详述，作为单一真相源 |
| `docs/DEMO_LESSONS_AND_RECOMMENDATION_GUIDE.md` | 技术向经验沉淀 | 删除运行命令重复段，指向 README |
| `agent.md` | AI 开发工作流规范 | 删除运行命令重复，指向 README |

### 6.4 补 services/engines 层测试

当前仅 `tests/test_recommendation_engine.py`。新增：

- `tests/test_context_engine.py` — build_context、suggest_session、新 get_customer_info
- `tests/test_excel_loader.py` — 解耦后无 streamlit 即可测加载与错误分支
- `tests/test_procurement_understanding.py` — normalize_ai_response、build_from_base 边界
- `tests/test_intent_parser.py` — fallback 误匹配修复后的场景
- `tests/test_price_trend_engine.py` — 价格信号、数量调整
- `tests/test_growth_engine.py` — 增长机会评分、试采数量
- `tests/test_risk_engine.py` — 风险等级判定

**测试时序说明**：批 2 重构前会先补 `excel_loader`/`context_engine` 的最小测试作安全网（这部分测试编写实际发生在批 2 启动时），批 3 再补齐其余。批边界在此处有柔性交叉，属正常。

### 6.5 批 3 验收

- `agent.md` 无 `http://CONTEXT.md` 错误链接。
- `docs/` 下无 `.docx`，对应 `.md` 存在且可读。
- `grep -l "streamlit run app.py" *.md docs/*.md` 命中数减少（运行命令单一真相源化）。
- `python -m unittest discover tests` 全过，测试文件数 ≥ 7。

## 7. 风险与回滚

- **风险**：拆分 ui.py 时 import 路径或 CSS 字符串拼接出错，导致页面渲染异常。
  - 缓解：`__init__.py` 重导出保 app.py 不变；每拆一个组件即跑 demo 对比。
- **风险**：删除 `models/` 后有隐藏引用（如测试或动态导入）。
  - 缓解：删除前 `grep -r "from models\|import models"` 全项目扫描（已确认无源码引用）。
- **风险**：excel_loader 解耦后缓存行为变化影响 demo 性能。
  - 缓解：app.py 层 `@st.cache_data` 包装等价于原 `@st.cache_data` 装饰器，行为一致。
- **回滚**：每批独立提交（待项目纳入 git 后），任一批出问题可单独回滚。

## 8. 路线图（本次不做）

按用户确认，以下项作为后续独立工作：

1. **配置与依赖修复**：settings 默认 model 修正、python-dotenv 支持、`.gitignore`、git 初始化。
2. **安全与部署清理**：移除 README 服务器 IP/SSH 信息、systemd 模板占位 key、本地路径硬编码。
3. **风险等级配色**：Medium/High 配色区分（需改 CSS，属外观变更）。
4. **action 词汇表统一**：将 engine action 与 UI 显示文案真正统一（需配合 replenishment 卡片 UI 文案重设计，属外观变更）。

这些项可与本次清理解耦，独立设计推进。

## 9. 后续步骤

本设计经用户审阅通过后，进入 `writing-plans` skill，将三批拆为可执行的实施计划（每批含具体文件改动清单、测试用例、验证步骤），再按计划落地。
