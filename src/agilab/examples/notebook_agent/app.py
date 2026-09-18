"""Source-checkout entry point for the packaged notebook demo."""
import runpy

runpy.run_module("agilab.agent_runtime.notebook_demo_ui", run_name="__main__")
