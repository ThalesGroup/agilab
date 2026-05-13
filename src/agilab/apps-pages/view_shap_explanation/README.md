# SHAP Explanation View

`view_shap_explanation` displays local feature-attribution evidence exported by
SHAPKit, `shap`, or another compatible explainer.

The page intentionally does not depend on a specific explainer library. Producer
workflows should export stable artifacts such as:

- `shap_values.csv`: one row per feature with `feature` and `shap_value`
- `feature_values.csv`: optional feature values with `feature` and `feature_value`
- `explanation_summary.json`: optional metadata such as `prediction`,
  `base_value`, `model_name`, and `instance_id`

This keeps AGILAB analysis lightweight while allowing training or workflow stages
to use heavier explainability libraries.
