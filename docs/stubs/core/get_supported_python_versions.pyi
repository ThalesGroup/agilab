import toml
import sys
from packaging.specifiers import SpecifierSet
from packaging.version import Version
import json
from typing import Any

CANDIDATE_VERSIONS = [f"3.{i}" for i in range(6, 14)]

def extract_requires_python(*args: Any, **kwargs: Any) -> Any: ...

def main(*args: Any, **kwargs: Any) -> Any: ...
