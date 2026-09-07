# Learning & Assessment: compatibility package

`agi-app-tescia-diagnostic` has moved to **`agi-app-learning-assessment`**.
Installing this compatibility package installs a compatible release of the new
package. New installations should use:

```bash
pip install agi-app-learning-assessment
```

The canonical AGILAB project is `learning_assessment_project`, displayed as
**Learning & Assessment**. The original TeSciA diagnostic collection is retained.
The old `tescia_diagnostic` and `tescia_diagnostic_project` discovery aliases
resolve to the canonical project. The old Python provider import remains usable.
Existing workspace data and settings are not moved or overwritten.

This distribution contains the compatibility provider and legacy discovery
entries. The new package owns the app payload; all entries resolve to it.
