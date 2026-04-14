import asyncio
import inspect
import json
import re
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, List, Optional


def ensure_asyncio_run_signature(
    *,
    asyncio_module: Any = asyncio,
    inspect_signature_fn: Callable[..., Any] = inspect.signature,
) -> None:
    """Ensure ``asyncio.run`` accepts ``loop_factory`` when patched by pydevd."""
    current = asyncio_module.run
    try:
        params = inspect_signature_fn(current).parameters
    except (TypeError, ValueError):  # pragma: no cover - unable to introspect
        return
    if "loop_factory" in params:
        return
    if "pydevd" not in getattr(current, "__module__", ""):
        return

    original = current

    def _patched_run(main, *, debug=None, loop_factory=None):
        if loop_factory is None:
            return original(main, debug=debug)

        loop = loop_factory()
        try:
            try:
                asyncio_module.set_event_loop(loop)
            except RuntimeError:
                pass
            if debug is not None:
                loop.set_debug(debug)
            return loop.run_until_complete(main)
        finally:
            try:
                loop.close()
            finally:
                try:
                    asyncio_module.set_event_loop(None)
                except RuntimeError:
                    pass

    asyncio_module.run = _patched_run


def agi_version_missing_on_pypi(project_path: Path) -> bool:
    """Return True when a pinned ``agi*``/``agilab`` dependency is missing on PyPI."""
    try:
        pyproject = project_path / "pyproject.toml"
        if not pyproject.exists():
            return False
        text = pyproject.read_text(encoding="utf-8", errors="ignore")
        deps = re.findall(
            r"^(?:\s*)(ag(?:i[-_].+|ilab))\s*=\s*[\"']([^\"']+)[\"']",
            text,
            flags=re.MULTILINE,
        )
        if not deps:
            return False
        pairs = []
        for name, spec in deps:
            match = re.match(r"^(?:==\s*)?(\d+(?:\.\d+){1,2})$", spec.strip())
            if match:
                pairs.append((name.replace("_", "-"), match.group(1)))
        if not pairs:
            return False
        pkg, ver = pairs[0]
        try:
            with urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/json", timeout=5) as response:
                data = json.load(response)
            return ver not in data.get("releases", {})
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            return False
    except (OSError, UnicodeError, ValueError):
        return False


def format_exception_chain(exc: BaseException) -> str:
    """Return a compact representation of an exception chain."""
    messages: List[str] = []
    norms: List[str] = []
    visited = set()
    current: Optional[BaseException] = exc

    def _normalize(text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        lowered = text.lower()
        for token in ("error:", "exception:", "warning:", "runtimeerror:", "valueerror:", "typeerror:"):
            if lowered.startswith(token):
                return text[len(token):].strip()
        if ": " in text:
            head, tail = text.split(": ", 1)
            if head.endswith(("Error", "Exception", "Warning")):
                return tail.strip()
        return text

    while current and id(current) not in visited:
        visited.add(id(current))
        tb_exc = traceback.TracebackException.from_exception(current)
        text = "".join(tb_exc.format_exception_only()).strip()
        if not text:
            text = f"{current.__class__.__name__}: {current}"
        if text:
            norm = _normalize(text)
            if messages:
                last_norm = norms[-1]
                if not norm:
                    norm = text
                if norm == last_norm:
                    pass
                elif last_norm.endswith(norm):
                    messages[-1] = text
                    norms[-1] = norm
                elif norm.endswith(last_norm):
                    pass
                else:
                    messages.append(text)
                    norms.append(norm)
            else:
                messages.append(text)
                norms.append(norm if norm else text)

        if current.__cause__ is not None:
            current = current.__cause__
        elif current.__context__ is not None and not getattr(current, "__suppress_context__", False):
            current = current.__context__
        else:
            break

    if not messages:
        return str(exc).strip() or repr(exc)
    return " -> ".join(messages)
