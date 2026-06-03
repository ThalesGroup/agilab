"""Runtime package metadata consumed by ``agi-env``."""

from __future__ import annotations

RUNTIME_PACKAGE_SPEC = {
    "role": "node",
    "project_dir": "agi-node",
    "module_name": "agi_node",
    "order": 10,
    "cli_rel": "agi_dispatcher/cli.py",
    "worker_pre_install_rel": "agi_dispatcher/pre_install.py",
    "worker_post_install_rel": "agi_dispatcher/post_install.py",
    "worker_post_install_module": "agi_node.agi_dispatcher.post_install",
    "setup_app_module": "agi_node.agi_dispatcher.build",
    "hook_package": "agi_node.agi_dispatcher",
    "hook_source_rel": "src/agi_node/agi_dispatcher",
    "hook_cache_name": "agi_node_hooks",
}
