"""Compatibility wrapper for documentation tooling.

Older scripts referenced ``mycode.mycode_args``. The mycode project now exposes
its argument models in ``mycode.app_args``. This module re-exports the public
API to keep legacy imports working.
"""

from .app_args import *  # noqa: F401,F403

