# Promotion forecast lab

A real Chronos-2 Small forecast app built through Tokki and imported as a
three-stage AGILAB workflow. All demand and promotion data are synthetic.
Changing a future promotion schedule produces a scenario forecast, not a
measured causal effect.

## Run locally

Install [uv](https://docs.astral.sh/uv/), extract this bundle, and run from its
root. Python 3.13 is the recorded notebook-build environment. The supplied requirements
list packages the generated app for reuse; Python 3.14 and Transformers 5 were
also checked with real inference. Generated Python and notebook files are unchanged.

```sh
uv run --python 3.13 --with-requirements requirements.txt python -c 'from huggingface_hub import snapshot_download; snapshot_download("autogluon/chronos-2-small", revision="ddec01313e50b6bc58ebaa92ede81bc24a3d9f9a", allow_patterns=["config.json", "model.safetensors"])'
uv run --python 3.13 --with-requirements requirements.txt streamlit run app.py
```

The public, ungated checkpoint is about 112 MB. It is downloaded once to the
Hugging Face cache, not included in this bundle. The app itself performs local
CPU inference and fails clearly when the checkpoint is missing. Alternatively,
set CHRONOS_MODEL_PATH to a complete local snapshot. No AI provider subscription
or API key is required to run the generated app.

In the hosted AGILAB demo, the demo wrapper prepares the same pinned checkpoint
before running the original generated app. First preparation needs network
access; subsequent runs reuse the cache.

The solution.ipynb notebook demonstrates the same analysis and writes a fresh
results.json. lab_stages.toml preserves the imported workflow stages. The
bundle's existing result.json is the separate public build and verification
receipt; it is not the notebook's analysis output.

## Source and licenses

Adapted from Amazon Science's official [Chronos-2 quickstart notebook](https://github.com/amazon-science/chronos-forecasting/blob/10afa9ebe016e514f9d7dc1aa873f66af57e116b/notebooks/chronos-2-quickstart.ipynb),
commit 10afa9ebe016e514f9d7dc1aa873f66af57e116b. The original notebook is retained
under source/. The adaptation uses the notebook's covariate forecasting API,
with newly generated synthetic sales instead of its external retail datasets.
LICENSE and NOTICE preserve the upstream Apache-2.0 attribution; modifications
include the synthetic fixture, reusable core, interactive app, and workflow.

Model: [autogluon/chronos-2-small](https://huggingface.co/autogluon/chronos-2-small/tree/ddec01313e50b6bc58ebaa92ede81bc24a3d9f9a),
revision ddec01313e50b6bc58ebaa92ede81bc24a3d9f9a, Apache-2.0 (MODEL_LICENSE).
The original notebook and checkpoint have independent source revisions.

## What the receipt proves

The recorded Tokki agent build completed in 361 seconds. Its objective checks
executed the generated notebook in a fresh directory, checked a fresh analysis
artifact, started the app, and exercised Run analysis. Three additional seeded
model checks measure error against a seasonal baseline, check finite ordered
quantiles, verify that held-out targets cannot change predictions, and confirm
that changing the known promotion schedule changes forecasts.

Those checks are bounded examples, not general scientific validation. The
nominal 80% prediction interval is poorly calibrated on this synthetic fixture;
the app displays measured coverage and error without promising production
accuracy. Hashes detect changes relative to the receipt; they are not a digital
signature. Hosted file hashes are checked again before app execution.
