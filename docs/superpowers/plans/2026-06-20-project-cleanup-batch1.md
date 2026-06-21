# 项目清理 Batch 1：零风险纯内部修复 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复代码质量缺陷和内部逻辑不一致，不改 UI 渲染输出、不改推荐算法结果。

**Architecture:** 6 个独立任务，每个任务含 TDD 循环（写测试 → 验证失败 → 实现 → 验证通过 → 提交）。所有改动为行为保持型，靠现有 17 个测试 + 新增测试守住正确行为。

**Tech Stack:** Python 3.9.6, unittest, Streamlit, pandas, openpyxl, DeepSeek/OpenAI SDK

## Global Constraints

- **行为不变**：UI 渲染输出、推荐算法结果、页面文案与布局必须与当前完全一致。
- **Python 3.9 兼容**：使用 `from __future__ import annotations`，不使用 3.10+ 语法。
- **测试框架**：unittest（非 pytest），遵循 `tests/test_recommendation_engine.py` 既有风格。
- **测试运行命令**：`cd "/Users/carrie/Documents/ai/recommend demo" && PYTHONPYCACHEPREFIX=/tmp/python-cache .venv/bin/python -m unittest <module>`
- **禁止基于猜测**：所有改动基于已读代码。
- **Karpathy 风格**：简单优先、可读性优先、小步迭代、避免过度抽象。

**参考设计文档**：`docs/superpowers/specs/2026-06-20-project-cleanup-design.md` 批 1 节。

---

### Task 1: git init + .gitignore（前置）

**Files:**
- Create: `.gitignore`

**说明**：设计文档将 git init 归入路线图，但计划的提交工作流依赖 git。此任务最小化地从路线图拉入 git init + .gitignore，仅启用提交能力，不触碰 settings/dotenv 等其余配置项。

- [ ] **Step 1: 创建 .gitignore**

```
.venv/
.DS_Store
__pycache__/
*.pyc
.python-cache/
.env
```

- [ ] **Step 2: 初始化 git 仓库并首次提交**

```bash
cd "/Users/carrie/Documents/ai/recommend demo"
git init
git add -A
git commit -m "chore: initialize git repo with .gitignore"
```

- [ ] **Step 3: 验证 .venv 未被跟踪**

```bash
git status --short .venv/
```
Expected: 无输出（.venv/ 已被 ignore）

---

### Task 2: 修复 intent_parser fallback（import re + "no " 误匹配）

**Files:**
- Modify: `services/intent_parser.py:1-10`（import re 移顶部）
- Modify: `services/intent_parser.py:113-151`（fallback 排除品类逻辑）
- Test: `tests/test_intent_parser.py`（新建）

**Interfaces:**
- Consumes: `services/ai_client.py` 的 `AIClient`（已有，不改）
- Produces: `IntentParser._fallback_parse` 行为修正 — `"no "` 不再误匹配 `"next week no problem"` 等无排除意图的输入；`import re` 移到模块顶部。

**Bug 描述**：
- `services/intent_parser.py:119` — `import re` 在 `_fallback_parse` 函数内部，应移到模块顶部。
- `services/intent_parser.py:138` — `if "avoid" in lower or "no " in lower:` 中的 `"no "` 会命中 `"next week no problem"`、`"no issue"` 等无排除意图的文本，随后若文本中恰好含品类词（如 `"fresh fruit"`），会错误设置 `ExcludedCategory`。

- [ ] **Step 1: 创建测试文件，写失败测试**

Create `tests/test_intent_parser.py`:

```python
import unittest

from services.intent_parser import IntentParser


class OfflineAIClient:
    is_available = False


class IntentParserFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = IntentParser(ai_client=OfflineAIClient())

    def test_import_re_at_module_top(self) -> None:
        import services.intent_parser as mod
        self.assertTrue(hasattr(mod, "re"))

    def test_fallback_extracts_excluded_category_from_avoid(self) -> None:
        intent = self.parser.parse_intent("avoid fresh products please")
        self.assertEqual(intent["ExcludedCategory"], "Fresh")

    def test_fallback_extracts_excluded_category_from_no(self) -> None:
        intent = self.parser.parse_intent("no dairy in this order")
        self.assertEqual(intent["ExcludedCategory"], "Dairy")

    def test_fallback_does_not_misclassify_next_week_no_problem(self) -> None:
        intent = self.parser.parse_intent("I want fresh fruit, no problem next week")
        self.assertIsNone(intent["ExcludedCategory"])

    def test_fallback_does_not_misclassify_no_problem_with_category_word(self) -> None:
        intent = self.parser.parse_intent("need some frozen items, no problem at all")
        self.assertIsNone(intent["ExcludedCategory"])

    def test_fallback_preserves_existing_budget_traffic_shelf(self) -> None:
        intent = self.parser.parse_intent(
            "Budget NZD 100, high traffic next week, avoid short shelf-life products"
        )
        self.assertEqual(intent["Budget"], 100.0)
        self.assertEqual(intent["TrafficLevel"], "HIGH")
        self.assertEqual(intent["ShelfLifePreference"], "LONG")
        self.assertIsNone(intent["ExcludedCategory"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd "/Users/carrie/Documents/ai/recommend demo"
PYTHONPYCACHEPREFIX=/tmp/python-cache .venv/bin/python -m unittest tests.test_intent_parser
```
Expected: FAIL — `test_import_re_at_module_top` 失败（re 未在模块顶部导入）；`test_fallback_does_not_misclassify_next_week_no_problem` 失败（当前 `"no "` 误匹配 + `"fruit"` 命中 → ExcludedCategory 被错误设为 "Fruit"）。

- [ ] **Step 3: 将 `import re` 移到模块顶部**

在 `services/intent_parser.py` 顶部 import 区块添加 `import re`：

```python
from __future__ import annotations

import logging
import re
from typing import Any

from services.ai_client import AIClient, AIClientError
from services.procurement_understanding import ProcurementUnderstandingBuilder
```

- [ ] **Step 4: 修复 fallback 排除品类逻辑**

将 `services/intent_parser.py` 中 `_fallback_parse` 的排除品类段：

```python
        if "avoid" in lower or "no " in lower:
            for cat in ["fruit", "vegetable", "dairy", "frozen", "dry", "fresh"]:
                if cat in lower:
                    intent["ExcludedCategory"] = cat.capitalize()
                    break
```

替换为：

```python
        exclude_patterns = ["avoid ", "exclude ", "no "]
        for cat in ["fruit", "vegetable", "dairy", "frozen", "dry", "fresh"]:
            for pattern in exclude_patterns:
                if f"{pattern}{cat}" in lower:
                    intent["ExcludedCategory"] = cat.capitalize()
                    break
            if intent["ExcludedCategory"]:
                break
```

同时删除 `_fallback_parse` 内部的 `import re` 行（已移到顶部）：

```python
        if any(w in lower for w in ["budget", "nzd", "nz$", "$", "dollar"]):
            match = re.search(r'(\d+(?:\.\d+)?)', lower)
            if match:
                intent["Budget"] = float(match.group(1))
```

- [ ] **Step 5: 运行新测试验证通过**

```bash
PYTHONPYCACHEPREFIX=/tmp/python-cache .venv/bin/python -m unittest tests.test_intent_parser
```
Expected: PASS — 6 tests OK

- [ ] **Step 6: 运行全部已有测试确认无回归**

```bash
PYTHONPYCACHEPREFIX=/tmp/python-cache .venv/bin/python -m unittest tests.test_recommendation_engine
```
Expected: PASS — 17 tests OK

- [ ] **Step 7: 提交**

```bash
git add services/intent_parser.py tests/test_intent_parser.py
git commit -m "fix: intent_parser fallback 'no ' mis-matching and move import re to top"
```

---

### Task 3: 修复 replenishment_engine（缩进 + 提取魔法数字为常量）

**Files:**
- Modify: `engines/replenishment_engine.py:1-10`（添加常量）
- Modify: `engines/replenishment_engine.py:89-101`（修正缩进 + 使用常量）
- Test: `tests/test_recommendation_engine.py`（已有测试验证无回归）

**Interfaces:**
- Produces: 模块级常量 `HIGH_SCORE_THRESHOLD = 60`、`MEDIUM_SCORE_THRESHOLD = 40`，供 `generate_recommendations` 使用。行为不变，仅可读性提升。

**Bug 描述**：
- `engines/replenishment_engine.py:95` — 行前多一个空格（缩进异常）。
- `engines/replenishment_engine.py:92-101` — score 阈值 `60`/`40` 为魔法数字。

- [ ] **Step 1: 写失败测试（验证常量存在且值正确）**

在 `tests/test_recommendation_engine.py` 的 `RecommendationEngineTests` 类中添加：

```python
    def test_replenishment_engine_exposes_score_thresholds(self) -> None:
        from engines.replenishment_engine import HIGH_SCORE_THRESHOLD, MEDIUM_SCORE_THRESHOLD
        self.assertEqual(HIGH_SCORE_THRESHOLD, 60)
        self.assertEqual(MEDIUM_SCORE_THRESHOLD, 40)
```

- [ ] **Step 2: 运行测试验证失败**

```bash
PYTHONPYCACHEPREFIX=/tmp/python-cache .venv/bin/python -m unittest tests.test_recommendation_engine.RecommendationEngineTests.test_replenishment_engine_exposes_score_thresholds
```
Expected: FAIL — `ImportError: cannot import name 'HIGH_SCORE_THRESHOLD'`

- [ ] **Step 3: 添加常量并修正缩进**

在 `engines/replenishment_engine.py` 的 `ReplenishmentWeights` 之前添加：

```python
HIGH_SCORE_THRESHOLD = 60
MEDIUM_SCORE_THRESHOLD = 40


@dataclass(frozen=True)
class ReplenishmentWeights:
    ...
```

将 `generate_recommendations` 末尾的过滤逻辑：

```python
        recommendations.sort(key=lambda item: (-item["score"], -item["quantity"], item["product"]))

        # Filter by score threshold: try 60 first, fallback to 40 if no results
        high_score = [r for r in recommendations if r["score"] >= 60]
        if high_score:
            return high_score[:limit]
        
        # Fallback: show medium-score products (40-60) when no high-score items
        medium_score = [r for r in recommendations if r["score"] >= 40]
        if medium_score:
            return medium_score[:limit]
        
        return recommendations[:limit]
```

替换为（注意修正第 95 行缩进 + 使用常量）：

```python
        recommendations.sort(key=lambda item: (-item["score"], -item["quantity"], item["product"]))

        high_score = [r for r in recommendations if r["score"] >= HIGH_SCORE_THRESHOLD]
        if high_score:
            return high_score[:limit]

        medium_score = [r for r in recommendations if r["score"] >= MEDIUM_SCORE_THRESHOLD]
        if medium_score:
            return medium_score[:limit]

        return recommendations[:limit]
```

- [ ] **Step 4: 运行测试验证通过**

```bash
PYTHONPYCACHEPREFIX=/tmp/python-cache .venv/bin/python -m unittest tests.test_recommendation_engine.RecommendationEngineTests.test_replenishment_engine_exposes_score_thresholds
```
Expected: PASS

- [ ] **Step 5: 运行全部已有测试确认无回归**

```bash
PYTHONPYCACHEPREFIX=/tmp/python-cache .venv/bin/python -m unittest tests.test_recommendation_engine
```
Expected: PASS — 18 tests OK（原 17 + 新 1）

- [ ] **Step 6: 提交**

```bash
git add engines/replenishment_engine.py tests/test_recommendation_engine.py
git commit -m "refactor: extract score thresholds to constants and fix indentation in replenishment_engine"
```

---

### Task 4: 统一 customer_name 默认值 + 修复 page_icon

**Files:**
- Modify: `config/settings.py:24`（Settings 添加 `default_customer_name` 字段）
- Modify: `app.py:51`（page_icon 修复）
- Modify: `app.py:97`（使用 settings 中的默认值）
- Modify: `services/ui.py:893`（使用 settings 中的默认值）
- Test: `tests/test_recommendation_engine.py`（新增 import 验证测试）

**Interfaces:**
- Produces: `Settings.default_customer_name` 字段，默认值 `"Auckland Central Supermarket"`，消除 `app.py` 与 `ui.py` 两处硬编码。

**Bug 描述**：
- `app.py:51` — `page_icon=""` 空字符串，无实际图标。
- `app.py:97` — `customer_name = "Auckland Central Supermarket"` 硬编码。
- `services/ui.py:893` — `def render_header(customer_name: str = "Auckland Central Supermarket", ...)` 同一硬编码。

- [ ] **Step 1: 写失败测试**

在 `tests/test_recommendation_engine.py` 添加：

```python
    def test_settings_provides_default_customer_name(self) -> None:
        from config.settings import Settings
        settings = Settings()
        self.assertEqual(settings.default_customer_name, "Auckland Central Supermarket")
```

- [ ] **Step 2: 运行测试验证失败**

```bash
PYTHONPYCACHEPREFIX=/tmp/python-cache .venv/bin/python -m unittest tests.test_recommendation_engine.RecommendationEngineTests.test_settings_provides_default_customer_name
```
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'default_customer_name'`

- [ ] **Step 3: 在 Settings 中添加 default_customer_name**

在 `config/settings.py` 的 `Settings` dataclass 中添加字段：

```python
@dataclass(frozen=True)
class Settings:
    app_title: str = "AI Smart Procurement Assistant"
    log_level: str = "INFO"
    excel_file: str = str(BASE_DIR / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx")
    default_customer_name: str = "Auckland Central Supermarket"
    ai: AISettings = field(default_factory=lambda: AISettings(
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
    ))
```

在 `get_settings()` 中也添加（从环境变量读取，回退默认值）：

```python
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_title=os.getenv("APP_TITLE", "AI Smart Procurement Assistant"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        excel_file=os.getenv(
            "EXCEL_FILE",
            str(BASE_DIR / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx"),
        ),
        default_customer_name=os.getenv("DEFAULT_CUSTOMER_NAME", "Auckland Central Supermarket"),
        ai=AISettings(
            enabled=os.getenv("AI_ENABLED", "true").lower() == "true",
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            temperature=float(os.getenv("AI_TEMPERATURE", "0.3")),
            max_tokens=int(os.getenv("AI_MAX_TOKENS", "1024")),
        ),
    )
```

- [ ] **Step 4: 修改 app.py 使用 settings 默认值**

在 `app.py` 顶部 import 中已有 `get_settings`。修改 `main()` 中 customer_name 部分：

```python
        customer_name = settings.default_customer_name
        customer_df = workbook.get("Customer")
```

- [ ] **Step 5: 修改 ui.py 使用 settings 默认值**

在 `services/ui.py` 顶部添加 import：

```python
from config.settings import get_settings
```

修改 `render_header` 签名（保留参数名，默认值改为从 settings 读取）：

```python
def render_header(
    customer_name: str | None = None,
    industry: str = "Retail - Grocery",
) -> None:
    if customer_name is None:
        customer_name = get_settings().default_customer_name
    from datetime import datetime
    now = datetime.now()
```

- [ ] **Step 6: 修复 page_icon**

在 `app.py` 的 `st.set_page_config` 中，将 `page_icon=""` 改为移除该参数（使用 Streamlit 默认图标）或设为 `"🛒"`：

```python
    st.set_page_config(
        page_title="AI Smart Procurement Assistant",
        page_icon="🛒",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
```

- [ ] **Step 7: 运行测试验证通过**

```bash
PYTHONPYCACHEPREFIX=/tmp/python-cache .venv/bin/python -m unittest tests.test_recommendation_engine
```
Expected: PASS — 19 tests OK

- [ ] **Step 8: 提交**

```bash
git add config/settings.py app.py services/ui.py tests/test_recommendation_engine.py
git commit -m "refactor: unify customer_name default into Settings and fix page_icon"
```

---

### Task 5: 提取并修复风险分类逻辑

**Files:**
- Modify: `services/ui.py:1142-1167`（提取纯函数 + 修复 fallback）
- Test: `tests/test_recommendation_engine.py`（新增分类测试）

**Interfaces:**
- Produces: `services/ui.classify_risks(risks) -> dict[str, list[dict]]` 纯函数，返回 `{"out_of_stock": [...], "overstock": [...], "near_expiry": [...]}`。`render_risks_section` 调用此函数。

**Bug 描述**：
- `services/ui.py:1149-1152` — 当没有 overstock 或 near_expiry 时，用列表位置 `risks[len(out_of_stock):len(out_of_stock)+3]` 和 `risks[-3:]` 硬凑，会把缺货项或低风险项错误放入 overstock/near_expiry tab。

- [ ] **Step 1: 写失败测试**

在 `tests/test_recommendation_engine.py` 添加：

```python
    def test_classify_risks_categorizes_correctly(self) -> None:
        from services.ui import classify_risks
        risks = [
            {"product": "A", "risk_level": "Critical", "coverage_days": 1},
            {"product": "B", "risk_level": "Low", "coverage_days": 45},
            {"product": "C", "risk_level": "Medium", "coverage_days": 10},
        ]
        result = classify_risks(risks)
        self.assertEqual([r["product"] for r in result["out_of_stock"]], ["A"])
        self.assertEqual([r["product"] for r in result["overstock"]], ["B"])
        self.assertEqual([r["product"] for r in result["near_expiry"]], ["C"])

    def test_classify_risks_no_fallback_misplacement(self) -> None:
        from services.ui import classify_risks
        risks = [
            {"product": "A", "risk_level": "Critical", "coverage_days": 1},
            {"product": "B", "risk_level": "Low", "coverage_days": 5},
        ]
        result = classify_risks(risks)
        self.assertEqual(result["overstock"], [])
        self.assertEqual(result["near_expiry"], [])
```

- [ ] **Step 2: 运行测试验证失败**

```bash
PYTHONPYCACHEPREFIX=/tmp/python-cache .venv/bin/python -m unittest tests.test_recommendation_engine.RecommendationEngineTests.test_classify_risks_categorizes_correctly tests.test_recommendation_engine.RecommendationEngineTests.test_classify_risks_no_fallback_misplacement
```
Expected: FAIL — `ImportError: cannot import name 'classify_risks' from 'services.ui'`

- [ ] **Step 3: 提取 classify_risks 纯函数并修复 fallback**

在 `services/ui.py` 中，`render_risks_section` 之前添加纯函数：

```python
def classify_risks(risks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Classify risks into out_of_stock, overstock, and near_expiry categories.

    No position-based fallback: if a category has no items, it stays empty.
    """
    out_of_stock = [r for r in risks if r.get("risk_level") in ("Critical", "High")]
    overstock = [
        r for r in risks
        if r.get("coverage_days") is not None and r.get("coverage_days", 0) > 30
    ]
    near_expiry = [r for r in risks if r.get("risk_level") == "Medium"]
    return {
        "out_of_stock": out_of_stock,
        "overstock": overstock,
        "near_expiry": near_expiry,
    }
```

然后将 `render_risks_section` 中的分类 + fallback 段：

```python
    out_of_stock = [r for r in risks if r.get("risk_level") in ("Critical", "High")]
    overstock = [r for r in risks if r.get("coverage_days") is not None and r.get("coverage_days", 0) > 30]
    near_expiry = [r for r in risks if r.get("risk_level") == "Medium"]

    if not overstock:
        overstock = risks[len(out_of_stock):len(out_of_stock)+3]
    if not near_expiry:
        near_expiry = risks[-3:]
```

替换为：

```python
    classified = classify_risks(risks)
    out_of_stock = classified["out_of_stock"]
    overstock = classified["overstock"]
    near_expiry = classified["near_expiry"]
```

- [ ] **Step 4: 运行测试验证通过**

```bash
PYTHONPYCACHEPREFIX=/tmp/python-cache .venv/bin/python -m unittest tests.test_recommendation_engine.RecommendationEngineTests.test_classify_risks_categorizes_correctly tests.test_recommendation_engine.RecommendationEngineTests.test_classify_risks_no_fallback_misplacement
```
Expected: PASS — 2 tests OK

- [ ] **Step 5: 运行全部已有测试确认无回归**

```bash
PYTHONPYCACHEPREFIX=/tmp/python-cache .venv/bin/python -m unittest tests.test_recommendation_engine
```
Expected: PASS — 21 tests OK（19 + 新 2）

- [ ] **Step 6: 提交**

```bash
git add services/ui.py tests/test_recommendation_engine.py
git commit -m "fix: extract classify_risks and remove position-based fallback that misplaces items"
```

---

### Task 6: 重构 _with_allocation_tier 使用 score 而非 strength 字符串 + 添加文档注释

**Files:**
- Modify: `engines/recommendation_engine.py:201-230`（用 score 替换 strength 判断）
- Modify: `engines/scoring_utils.py`（添加注释说明 "Monitor" 档语义）
- Modify: `services/ui.py:1059-1064`（添加注释说明两套 action 词汇表关系）
- Modify: `services/context_engine.py:47`（添加注释说明 suggest_session 用途）
- Test: `tests/test_recommendation_engine.py`（新增 score 阈值测试）

**Interfaces:**
- Produces: `_with_allocation_tier` 使用 `candidate.get("score", 0) >= 75` 替代 `strength in {"Very High", "High"}`，行为完全等价（strength 由 score 派生：Very High ≥90, High ≥75 → 两者并集 = score ≥75）。

**Bug 描述**：
- `engines/recommendation_engine.py:215` — `strength in {"Very High", "High"}` 用显示字符串做控制流判断，语义易误读。
- `engines/scoring_utils.py` — `strength()` 返回 `"Monitor"` 作为 recommendation_strength，但 "Monitor" 是动作不是强度等级。
- `services/ui.py:1059` 与 `engines/recommendation_engine.py:209` — 两套 action 词汇表无文档说明关系。
- `services/context_engine.py:47` — `suggest_session` 复杂但 demo 单 session，无注释说明保留原因。

- [ ] **Step 1: 写失败测试（验证 score 阈值等价性）**

在 `tests/test_recommendation_engine.py` 添加：

```python
    def test_allocation_tier_uses_score_for_order_now(self) -> None:
        candidate = {
            "product": "High Score Item",
            "product_id": "PX",
            "quantity": 1,
            "unit": "KG",
            "score": 80.0,
            "recommendation_strength": "High",
            "estimated_cost": 10.0,
            "coverage_days": 10.0,
            "priority": None,
            "price_trend": None,
        }
        result = RecommendationEngine._with_allocation_tier(candidate)
        self.assertEqual(result["allocation_tier"], 1)
        self.assertEqual(result["action"], "Order Now")

    def test_allocation_tier_score_below_75_not_order_now(self) -> None:
        candidate = {
            "product": "Medium Score Item",
            "product_id": "PY",
            "quantity": 1,
            "unit": "KG",
            "score": 65.0,
            "recommendation_strength": "Medium",
            "estimated_cost": 10.0,
            "coverage_days": 10.0,
            "priority": None,
            "price_trend": None,
        }
        result = RecommendationEngine._with_allocation_tier(candidate)
        self.assertNotEqual(result["action"], "Order Now")
```

- [ ] **Step 2: 运行测试验证当前状态**

```bash
PYTHONPYCACHEPREFIX=/tmp/python-cache .venv/bin/python -m unittest tests.test_recommendation_engine.RecommendationEngineTests.test_allocation_tier_uses_score_for_order_now tests.test_recommendation_engine.RecommendationEngineTests.test_allocation_tier_score_below_75_not_order_now
```
Expected: PASS（当前代码用 strength 字符串判断，但行为等价 — 这些测试验证等价性，作为重构安全网。先确认它们在当前代码下通过。）

- [ ] **Step 3: 重构 _with_allocation_tier**

将 `engines/recommendation_engine.py` 中 `_with_allocation_tier` 的：

```python
        if priority == "Trial Buy":
            tier = 3
            action = "Trial Buy"
        elif coverage_days is not None and coverage_days <= 3:
            tier = 1
            action = "Order Now"
        elif strength in {"Very High", "High"}:
            tier = 1
            action = "Order Now"
        elif price_signal == "Buy Now":
            tier = 2
            action = "Buy on Price Advantage"
        elif price_signal == "Wait":
            tier = 4
            action = "Monitor Price"
        else:
            tier = 2
            action = "Order This Week"
```

替换为：

```python
        if priority == "Trial Buy":
            tier = 3
            action = "Trial Buy"
        elif coverage_days is not None and coverage_days <= 3:
            tier = 1
            action = "Order Now"
        elif candidate.get("score", 0) >= 75:
            tier = 1
            action = "Order Now"
        elif price_signal == "Buy Now":
            tier = 2
            action = "Buy on Price Advantage"
        elif price_signal == "Wait":
            tier = 4
            action = "Monitor Price"
        else:
            tier = 2
            action = "Order This Week"
```

注意：`strength` 变量仍在函数中定义但不再用于分支判断。如果 `strength` 此后无其他引用，保留它（它来自 `candidate.get("recommendation_strength", "")`，不影响行为）。检查 — `strength` 在替换后仅定义未使用，可以删除该行以保持整洁：

```python
    @staticmethod
    def _with_allocation_tier(candidate: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(candidate)
        price_signal = (candidate.get("price_trend") or {}).get("price_signal")
        priority = candidate.get("priority") or candidate.get("recommendation_strength")
        coverage_days = candidate.get("coverage_days")
```

（删除 `strength = candidate.get("recommendation_strength", "")` 行）

- [ ] **Step 4: 添加文档注释**

在 `engines/scoring_utils.py` 添加注释：

```python
from __future__ import annotations


def strength(score: float) -> str:
    """Map a 0-100 score to a recommendation strength label.

    Note: "Monitor" is a low-strength "observe" tier, not an action command.
    It means the product is worth watching but not urgently recommended.
    """
    if score >= 90:
        return "Very High"
    if score >= 75:
        return "High"
    if score >= 60:
        return "Medium"
    if score >= 40:
        return "Monitor"
    return "Low"
```

在 `services/ui.py` 的 `_get_action_tag` 函数前添加注释：

```python
def _get_action_tag(strength: str, coverage_days: float | None) -> tuple[str, str]:
    """Map recommendation strength + coverage to a UI display label and CSS class.

    This produces a DIFFERENT vocabulary than engine `_with_allocation_tier`:
    - UI: "Order Immediately" / "Order This Week" / "Monitor"
    - Engine: "Order Now" / "Buy on Price Advantage" / "Trial Buy" / "Monitor Price" / "Order This Week"

    The two vocabularies coexist for historical reasons. Unifying them requires
    UI copy redesign and is tracked in the project roadmap.
    """
    if strength in ("Very High", "High"):
```

在 `services/context_engine.py` 的 `suggest_session` 方法前添加注释：

```python
    def suggest_session(
        self,
        workbook: dict[str, pd.DataFrame],
        user_input: str,
        parsed_intent: dict[str, Any] | None = None,
    ) -> str:
        """Pick the best-matching session from ConversationContext.

        Kept even though the current demo has a single session (S1):
        the matching logic supports multi-session workbooks for future demos
        and is covered by test_context_engine_reuses_parsed_intent_for_session_matching.
        """
```

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
PYTHONPYCACHEPREFIX=/tmp/python-cache .venv/bin/python -m unittest tests.test_recommendation_engine
```
Expected: PASS — 23 tests OK（21 + 新 2）

- [ ] **Step 6: 运行 intent_parser 测试确认无回归**

```bash
PYTHONPYCACHEPREFIX=/tmp/python-cache .venv/bin/python -m unittest tests.test_intent_parser
```
Expected: PASS — 6 tests OK

- [ ] **Step 7: 提交**

```bash
git add engines/recommendation_engine.py engines/scoring_utils.py services/ui.py services/context_engine.py tests/test_recommendation_engine.py
git commit -m "refactor: _with_allocation_tier uses score instead of strength string; document action vocabularies"
```

---

## Batch 1 完成验证

- [ ] **运行全部测试**

```bash
cd "/Users/carrie/Documents/ai/recommend demo"
PYTHONPYCACHEPREFIX=/tmp/python-cache .venv/bin/python -m unittest discover tests
```
Expected: ALL PASS（test_recommendation_engine 23 + test_intent_parser 6 = 29 tests）

- [ ] **手动验证 demo 渲染输出无差异**

```bash
cd "/Users/carrie/Documents/ai/recommend demo"
source .venv/bin/activate
streamlit run app.py --server.port 8501
```

在浏览器打开 `http://localhost:8501`，对比修复前后页面：
- AI Understanding 区域渲染正常
- Recommended Replenishment 卡片文案不变
- Growth Opportunities 卡片文案不变
- Inventory Risks 三个 tab 内容正常（overstock/near_expiry tab 不再错放缺货项）
- Procurement Plan 表格 priority 列文案不变

- [ ] **验证 git 提交历史**

```bash
git log --oneline
```
Expected: 7 个提交（1 init + 6 task commits）
