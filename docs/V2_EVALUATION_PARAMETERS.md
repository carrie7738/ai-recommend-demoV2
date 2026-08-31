# V2 Evaluation Parameters

This document records the current V2 demo parameters and their confirmation status. Values marked
`INITIAL_EVAL_VALUE` are configurable evaluation inputs, not confirmed production business rules.

## Feature parameters

The following values are stored in the `V2FeaturePolicy` worksheet and loaded by
`V2FeaturePolicy.from_workbook`.

| Parameter | Current value | Decision path | Status |
| --- | ---: | --- | --- |
| Purchase frequency window | 90 days | High/Low Purchase Frequency | INITIAL_EVAL_VALUE |
| High purchase frequency threshold | 8 orders | High Purchase Frequency | INITIAL_EVAL_VALUE |
| Low purchase frequency threshold | 1 order | Low Purchase Frequency | INITIAL_EVAL_VALUE |
| High stockout-risk coverage | 3 days or less | High Stock Risk | INITIAL_EVAL_VALUE |
| Low stockout-risk coverage | 14 days or more | Low Stock Risk | INITIAL_EVAL_VALUE |
| Discovery history lookback | 12 months | System Discovery | CONFIRMED_V2 |
| Discovery peer ratio | 30% | System Discovery | INITIAL_EVAL_VALUE |
| Recent-store baseline lookback | 90 days | Event baseline fallback | INITIAL_EVAL_VALUE |
| Event baseline fallback | Store Event → Peer Event → Recent Store | Holiday/Event Baseline | CONFIRMED_V2 |

The 30% peer ratio is the initial admission signal: peer purchase count for the SKU divided by total
SKU purchase count. It does not apply to User Requested Discovery, where the explicit request is
sufficient evidence.

## Optimizer parameters

The following defaults are declared by `OptimizerPolicy`. They are included in every optimizer
result under `evaluation_parameters` so evaluation reports can identify the values used.

| Parameter | Current value | Decision path | Status |
| --- | ---: | --- | --- |
| Demand history | 90 days | Demand Baseline | INITIAL_EVAL_VALUE |
| Target coverage | 14 days | Inventory Gap | INITIAL_EVAL_VALUE |
| HIGH intensity factor | 1.25 | AI Intensity | INITIAL_EVAL_VALUE |
| MEDIUM intensity factor | 1.00 | AI Intensity | INITIAL_EVAL_VALUE |
| LOW intensity factor | 0.75 | AI Intensity | INITIAL_EVAL_VALUE |
| Discovery trial quantity | 1 Sales Unit | System/User Discovery | INITIAL_EVAL_VALUE |

These parameters do not override confirmed hard constraints. Final quantity must still respect Sales
Unit, the tail-stock exception, Available Stock, and Budget.

## Confirmed hard constraints and preferences

- Sales Unit is a purchase step, not MOQ. Tail stock below one Sales Unit may be purchased once in
  full.
- Available Stock is supplier/warehouse supply and is separate from store Current Stock.
- Product saleability is evaluated at product level for V2 Demo.
- User Requested Discovery does not require peer evidence.
- Long Shelf-life and Category wording are soft preferences unless the user explicitly states a hard
  constraint such as `only`, `must`, or an exclusion.
- Budget Retry exposes constraint feedback and affected candidates only; it must not expose price,
  budget difference, or price-derived data to the model.

## Business confirmation required

Before production use, evaluate and confirm the feature thresholds, demand/coverage windows,
intensity factors, and discovery trial quantity. Changing these values for evaluation must not require
changes to AI prompts or hard-validator logic.
