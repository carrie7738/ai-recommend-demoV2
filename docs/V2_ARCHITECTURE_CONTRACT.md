# V2 Procurement Recommendation Architecture Contract

This document is the repository-level contract for the V2 demo pipeline. It separates confirmed
business behavior from evaluation parameters so future model or UI changes do not silently move
deterministic rules into the LLM.

## Runtime flow

```text
User Request
→ Structured Intent
→ Candidate Pool
→ Safe Decision Features
→ AI Procurement Strategy / Candidate Decisions
→ Local Optimizer
→ Hard Validator
→ Decision Trace / Why Selected
→ V2 UI
```

V2 is the primary runtime. V1 may run only as an explicit, logged fallback after the original V2
failure is captured. A valid empty candidate pool produces a V2 no-purchase result and is not a V1
fallback condition.

## Responsibility boundary

### Model

- Interpret user language into the structured intent contract.
- Choose qualitative procurement strategy, candidate retention, priority, and intensity.
- Use only the safe signals supplied by the workflow.
- Never calculate or emit executable quantities, prices, costs, inventory, supplier availability,
  or budget gaps.

### Deterministic workflow

- Resolve trusted store identity and product references.
- Apply sellability and explicit hard constraints.
- Build replenishment, system-discovery, and user-requested discovery candidates.
- Convert private data into safe categorical features and allowed decision signals.
- Keep provider transport capability separate from local schema and semantic validation.

### Local optimizer

```text
Demand Baseline
→ Current Inventory Gap
→ AI Intensity
→ Sales Unit
→ Available Stock
→ Budget
→ Final Qty
```

- User-requested discovery may use verified Store Event, Peer Event, or Recent Store baselines.
- Other discovery candidates use the configured trial-sales-unit evaluation parameter.
- AI output cannot bypass Sales Unit, tail-stock, Available Stock, or Budget constraints.

### Hard validator

- Re-read trusted Product and SupplyAvailability data as of the effective decision date.
- Recompute plan cost from Product master data rather than trusting optimizer totals.
- Repair executable quantity violations locally before considering a model retry.
- Retry the model only when a recommended HIGH candidate cannot be allocated and a candidate-value
  trade-off is required.
- Retry feedback contains candidate identifiers and the required trade-off only; it never contains
  prices, quantities, budget differences, or other price-derived data.

## Confirmed V2 demo semantics

- `SalesUnit` is the purchase step, not MOQ. When remaining supplier stock is below one complete
  Sales Unit, the remaining stock may be purchased once.
- `AvailableStock` is supplier/warehouse stock and is separate from store `CurrentStock`.
- Sellability is product-level for the demo.
- Complex store eligibility is not implemented without confirmed source data.
- Recommendation type is based on store purchase history; an occasion does not turn an unpurchased
  user-requested product into replenishment.
- System discovery initially requires peer purchase count / total SKU purchase count at or above the
  configured 30% evaluation threshold.
- User-requested discovery requires eligibility but no minimum peer evidence.
- `prefer` and `focus on` are soft preferences. Only explicit `must`, `only`, or equivalent wording
  creates a hard constraint.
- Explicit product exclusions use `{"type":"PRODUCT","operator":"EXCLUDE","values":["SKU or exact product name"]}`.
  Negated catalog mentions must not become USER_REQUESTED candidates. Product exclusions and
  category/shelf-life hard constraints also filter the rules fallback before allocation.
- Missing, invalid, negative, or non-finite store inventory is unknown, not zero. The optimizer
  skips that candidate with `INVENTORY_UNAVAILABLE`; the UI must disclose this omission. A verified
  zero stock remains a valid replenishment input.
- The validator and local repair read SalesUnit from Product, never from optimizer metadata.
- Supplied cost metadata (unit/line/total cost and remaining budget) must match trusted
  recomputation, even when no budget limit is set. Mismatches trigger local repair and revalidation.
- A stated budget that the local parser cannot safely interpret requires clarification; it must
  not silently become an unlimited budget. Local parsing supports numeric NZD amounts including
  thousands separators and basic Chinese budget/category expressions, not arbitrary language.
  Every stated budget marker must be parsed; conflicting limited/unlimited declarations or a
  partially unparsed second declaration require clarification. Repeated equal amounts are valid.
- Event baseline order is Store Event → Peer Event → Recent Store.
- Why Selected uses verified supporting evidence. Low, unknown, or neutral facts remain audit context
  and are not presented as positive selection reasons.

## Evaluation parameters, not confirmed production rules

The following remain configurable evaluation inputs:

- purchase-frequency window and thresholds;
- stockout coverage formula and risk thresholds;
- demand-history and coverage periods;
- AI intensity coefficients;
- discovery trial sales units;
- discovery peer threshold;
- shelf-life day thresholds (not currently defined; V2 uses existing categorical product semantics).

Changes to these values require evaluation evidence and must not be described as confirmed production
business rules.

## Evaluation contract

Regression and A/B runs must bind each presentation scenario to an explicit `V2TestScenarios` row and
record `ScenarioId`, `CustomerId`, `AsOfDate`, and `DecisionPath`. A scenario passes only when both hard
constraints and its intended behavioral effect pass. A successful V1 fallback never converts an
original V2 failure into a V2 pass.

The September 8 correctness changes extend the intent contract and prompt. Earlier live acceptance
is historical evidence only; rerun live acceptance before claiming the updated contract is verified
against a real provider.
