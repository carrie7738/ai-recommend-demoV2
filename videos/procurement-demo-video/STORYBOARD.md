# Procurement Scenario Demo Storyboard

**Format:** 1920×1080 landscape
**Audio:** None; deliberately silent for later voiceover
**Style basis:** DESIGN.md and captured Streamlit screenshots

## Asset Audit

| Asset | Type | Assignments | Role |
| --- | --- | --- | --- |
| `assets/scenarios/*-input.png` | Product screenshot | Input beats 1–6 | Shows the natural-language request before analysis. |
| `assets/scenarios/*-plan.png` | Product screenshot | Report beats 1–6 | Shows the budget summary and recommended products table. |

## Beat Pattern

Each scenario uses the same calm editorial movement: the request screen fades and eases forward, then crossfades into the procurement report. The report drifts forward by 3% during a six-second silent hold. A small navy scenario pill enters from the upper left; it never obscures product data.

### Scenarios 1–6

1. **High traffic and budget optimization** — request input followed by an optimized NZD 1000 report.
2. **Christmas promotion readiness** — seasonal promotion request followed by the decision report.
3. **Low budget stockout prevention** — NZD 300 stockout-prevention request followed by the constrained plan.
4. **Long shelf-life preference** — shelf-life request followed by the constrained report.
5. **Fruit category focus** — fruit demand request followed by the category-focused report.
6. **No budget constraint** — open replenishment request followed by the priority-ranked report.

## Production Architecture

```text
procurement-demo-video/
├── index.html
├── DESIGN.md
├── SCRIPT.md
├── STORYBOARD.md
└── assets/scenarios/
```
