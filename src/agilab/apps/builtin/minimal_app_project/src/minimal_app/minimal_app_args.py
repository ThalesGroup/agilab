"""Compatibility wrapper for documentation tooling.

Older scripts referenced ``minimal_app.minimal_app_args``. The minimal_app project now exposes
its argument models in ``minimal_app.app_args``. This module re-exports the public
API to keep legacy imports working.
"""

from .app_args import *  # noqa: F401,F403
