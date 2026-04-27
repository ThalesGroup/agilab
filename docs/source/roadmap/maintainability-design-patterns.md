# Maintainability design patterns

AGILAB should improve long-term maintainability through small, explicit design
patterns applied where they remove duplication or make behavior easier to test.
The goal is not a broad framework rewrite.

## Principles

- Prefer narrow patterns that keep existing app behavior stable.
- Keep Streamlit rendering thin and move user-triggered workflow logic into
  testable action functions.
- Treat shared core changes as higher-risk work; use page-local or app-local
  patterns first unless the shared abstraction is clearly justified.
- Add focused tests with each pattern so adoption is guarded by behavior, not by
  convention alone.
- Document the pattern only after one concrete adopter exists.

## Current pattern: action execution

The first maintenance slice introduces a command/result style action execution
primitive for Streamlit workflows:

- `ActionSpec` holds user-facing execution metadata such as the action name,
  spinner text, and default failure guidance.
- `ActionResult` carries a structured outcome: status, title, optional detail,
  optional next action, and machine-readable data for follow-up callbacks.
- `run_streamlit_action` centralizes spinner handling, exception-to-error
  conversion, result rendering, and success callbacks.

The first adopter is PROJECT clone creation. The page still controls layout and
navigation, but the clone operation itself is now a direct function with
success, duplicate-name, and missing-output tests.

## Adoption order

1. User-triggered Streamlit page actions where validation, execution, and UI
   feedback are currently interleaved.
2. Installer and doctor checks where command results need consistent operator
   guidance.
3. Evidence/report generators where typed outcomes can reduce ad hoc JSON
   shapes.

This order keeps the pattern practical: each step must remove visible
duplication, improve testability, or make operator feedback more consistent.

## Non-goals

- Do not add compatibility aliases for maintained apps that already live in the
  app repositories.
- Do not introduce silent runtime fallbacks between incompatible APIs.
- Do not move app-specific behavior into shared core without explicit approval
  and a regression plan.
- Do not add abstract factories, service locators, or plugin layers unless a
  repeated concrete use case already exists.
