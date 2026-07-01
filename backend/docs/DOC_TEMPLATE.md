---
covers: [<source paths this doc describes, e.g. backend/payments/refunds/>]
status: active
last_verified: <YYYY-MM-DD or commit hash>
---

# <Feature Name>

## Purpose
The problem this solves and why it exists, in product terms, not implementation terms. Should make sense to someone who has never seen this codebase.

## Behavior Specification
The functional contract, precise enough that someone with no access to this codebase could implement an equivalent feature from this section alone.
- **Inputs:** what comes in, with types/constraints
- **Process:** the logic, as a numbered sequence of steps/rules, not narrative prose
- **Outputs:** what comes out, in every case (success and failure)
- **Validation rules:** what's rejected, and why
- **Error handling:** what happens when something goes wrong, and what the caller sees

1. ...
2. ...
3. ...

## Data & Interface Contract
The shape of what flows through this feature. Skip whichever part doesn't apply.
- **Data model:** fields, types, relationships
- **API / function signatures:** request/response shapes, or function inputs and outputs

## Example
A concrete walkthrough: one sample input and the resulting output or state change. This single example is often worth more to an AI rebuilding this than the entire spec above — always include at least one.

## Dependencies & Integration Points
External services, other internal modules, or environment assumptions a new implementation would need to account for or stub out. Write "None" if there aren't any.

## Edge Cases & Known Gotchas
Behavior that looks wrong but is intentional, or things that have caused bugs before.

## Key Files
Paths only. This is the map a reader (human or agent) uses to jump straight to the real implementation instead of trusting this doc blindly.
- `path/to/entry_point` — where this starts
- `path/to/core_logic` — main logic
- `path/to/tests` — tests covering this behavior

## Why (Design Rationale)
The decisions and trade-offs behind this approach. Rarely needs updates even when implementation details change — useful context if this is ever rebuilt under different constraints.

## Open Issues
Known bugs or limitations not yet fixed. Remove an item the moment it's resolved.
