#!/usr/bin/env python3
"""Plan or delete an explicit, backed-up list of first-party PyPI releases."""

from __future__ import annotations

import argparse
import base64
import binascii
import configparser
import hmac
import hashlib
from html.parser import HTMLParser
import json
import os
import re
import struct
import sys
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote, urljoin, urlparse

from packaging.version import InvalidVersion, Version
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

try:
    from pypi_release_version_policy import public_package_entries, selected_public_versions
except ModuleNotFoundError:  # pragma: no cover - used when imported as tools.*
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pypi_release_version_policy import public_package_entries, selected_public_versions


PYPI_JSON_URLS = {
    "pypi": "https://pypi.org/pypi/{package}/json",
    "testpypi": "https://test.pypi.org/pypi/{package}/json",
}
PYPI_RELEASE_JSON_URLS = {
    "pypi": "https://pypi.org/pypi/{package}/{version}/json",
    "testpypi": "https://test.pypi.org/pypi/{package}/{version}/json",
}
PYPI_HOSTS = {
    "pypi": "https://pypi.org/",
    "testpypi": "https://test.pypi.org/",
}
SCHEMA_VERSION = "agilab.pypi_release_retention.v1"
PYPI_PROJECT_NAME_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$"
)
EXACT_RELEASE_PRESENT = "present"
EXACT_RELEASE_ABSENT = "absent"
EXACT_RELEASE_ERROR = "error"


@dataclass(frozen=True)
class HtmlForm:
    action: str | None
    inputs: dict[str, str]


class FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: list[HtmlForm] = []
        self._action: str | None = None
        self._inputs: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value for key, value in attrs}
        if tag == "form":
            self._action = values.get("action")
            self._inputs = {}
            return
        if tag == "input" and self._inputs is not None:
            name = values.get("name")
            if name:
                self._inputs[name] = values.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._inputs is not None:
            self.forms.append(HtmlForm(action=self._action, inputs=dict(self._inputs)))
            self._action = None
            self._inputs = None


@dataclass(frozen=True)
class ReleasePlan:
    package: str
    protect_version: str
    published_versions: list[str]
    delete_versions: list[str]
    retained_versions: list[str]
    missing_protected_version: bool
    retention_skipped_reason: str | None = None


def normalize_version(version: str) -> str:
    try:
        return str(Version(version.strip().lstrip("v")))
    except InvalidVersion as exc:
        raise SystemExit(f"ERROR: invalid version {version!r}") from exc


def exact_release_regex(version: str) -> str:
    normalize_version(version)
    return f"^{re.escape(version)}$"


def split_packages(values: Sequence[str] | None) -> list[str]:
    packages: list[str] = []
    for value in values or ():
        packages.extend(token for token in re.split(r"[\s,]+", value.strip()) if token)
    return list(dict.fromkeys(packages))


def read_packages_file(path: Path | str) -> list[str]:
    source = str(path)
    if source == "-":
        text = sys.stdin.read()
    else:
        text = Path(path).read_text(encoding="utf-8")
    packages: list[str] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if re.search(r"[\s,]", line):
            raise SystemExit(
                f"ERROR: {source}:{line_number} must contain exactly one package name. "
                "Use one non-wrapped package per line."
            )
        packages.append(line)
    return packages


def validate_package_names(packages: Sequence[str]) -> None:
    invalid = [
        package
        for package in packages
        if not PYPI_PROJECT_NAME_RE.fullmatch(package)
    ]
    if invalid:
        raise SystemExit(
            "ERROR: invalid PyPI package name(s): "
            + ", ".join(invalid)
            + ". If this came from a long --packages value, it was likely "
            "line-wrapped inside a package name. Use repeated --package or "
            "--packages-file with one package per line."
        )


def resolve_package_selection(
    *,
    package_values: Sequence[str],
    packages_values: Sequence[str],
    packages_files: Sequence[Path | str],
) -> list[str]:
    packages = split_packages([*package_values, *packages_values])
    for path in packages_files:
        packages.extend(read_packages_file(path))
    packages = list(dict.fromkeys(packages))
    validate_package_names(packages)
    return packages


def release_plan_package_names(repo_root: Path) -> list[str]:
    return list(selected_public_versions(repo_root.resolve()).keys())


def filter_packages_with_visible_protect_version(
    *,
    packages: Sequence[str],
    repo: str,
    protect_version: str,
) -> tuple[list[str], list[str]]:
    selected: list[str] = []
    skipped: list[str] = []
    for package in packages:
        plan = build_plan(package, repo, protect_version)
        if plan.missing_protected_version:
            skipped.append(package)
        else:
            selected.append(package)
    return selected, skipped


def split_package_versions(values: Sequence[str] | None) -> dict[str, str]:
    package_versions: dict[str, str] = {}
    for value in values or ():
        for token in re.split(r"[\s,]+", value.strip()):
            if not token:
                continue
            if "=" not in token:
                raise SystemExit(
                    "ERROR: --protect-package-version values must use package=version"
                )
            package, version = (part.strip() for part in token.split("=", 1))
            if not package or not version:
                raise SystemExit(
                    "ERROR: --protect-package-version values must use package=version"
                )
            normalized = normalize_version(version)
            previous = package_versions.get(package)
            if previous is not None and Version(previous) != Version(normalized):
                raise SystemExit(
                    f"ERROR: conflicting protected versions for {package}: "
                    f"{previous} and {normalized}"
                )
            package_versions[package] = normalized
    return package_versions


def resolve_protect_versions(
    *,
    packages: Sequence[str],
    protect_version: str | None = None,
    protect_package_versions: Sequence[str] | None = None,
    protect_versions_from_projects: bool = False,
    repo_root: Path = Path.cwd(),
) -> dict[str, str]:
    sources = [
        bool(protect_version),
        bool(protect_package_versions),
        protect_versions_from_projects,
    ]
    if sum(1 for source in sources if source) != 1:
        raise SystemExit(
            "ERROR: provide exactly one of --protect-version, "
            "--protect-package-version, or --protect-versions-from-projects"
        )

    if protect_version:
        return {
            package: normalize_version(protect_version)
            for package in packages
        }
    if protect_package_versions:
        package_versions = split_package_versions(protect_package_versions)
    else:
        package_versions = {
            package: normalize_version(version)
            for package, version in selected_public_versions(
                repo_root.resolve(),
                package_names=packages,
            ).items()
        }

    missing = [package for package in packages if package not in package_versions]
    extra = [package for package in package_versions if package not in packages]
    if missing:
        raise SystemExit(
            "ERROR: missing protected versions for: " + ", ".join(missing)
        )
    if extra:
        raise SystemExit(
            "ERROR: protected versions were provided for unselected packages: "
            + ", ".join(extra)
        )
    return {
        package: package_versions[package]
        for package in packages
    }


def fetch_releases(package: str, repo: str, *, timeout: int = 15) -> list[str]:
    url = PYPI_JSON_URLS[repo].format(package=package)
    request = urllib.request.Request(
        f"{url}?agilab_cache_bust={time.time_ns()}",
        headers={"Cache-Control": "no-cache, no-store", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise RuntimeError(f"{url}: HTTP {exc.code}") from exc
    releases = data.get("releases") or {}
    if not isinstance(releases, dict):
        raise RuntimeError(f"{url}: expected JSON object with a releases mapping")
    return sorted(releases, key=lambda value: Version(value))


def probe_exact_release_version(
    package: str,
    repo: str,
    version: str,
    *,
    timeout: int = 15,
) -> tuple[str, str | None]:
    """Return present, absent, or error from a cache-isolated release endpoint."""
    normalized = normalize_version(version)
    url = PYPI_RELEASE_JSON_URLS[repo].format(
        package=quote(package, safe=""),
        version=quote(normalized, safe=""),
    )
    request = urllib.request.Request(
        f"{url}?agilab_cache_bust={time.time_ns()}",
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
            "User-Agent": "agilab-pypi-retention/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return (EXACT_RELEASE_ABSENT, None) if exc.code == 404 else (EXACT_RELEASE_ERROR, None)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return EXACT_RELEASE_ERROR, None
    info = data.get("info") if isinstance(data, dict) else None
    observed = info.get("version") if isinstance(info, dict) else None
    if not isinstance(observed, str):
        return EXACT_RELEASE_ERROR, None
    try:
        observed_normalized = str(Version(observed))
    except InvalidVersion:
        return EXACT_RELEASE_ERROR, None
    if Version(observed_normalized) != Version(normalized):
        return EXACT_RELEASE_ERROR, None
    return EXACT_RELEASE_PRESENT, normalized


def fetch_exact_release_version(
    package: str,
    repo: str,
    version: str,
    *,
    timeout: int = 15,
) -> str | None:
    state, observed = probe_exact_release_version(
        package,
        repo,
        version,
        timeout=timeout,
    )
    return observed if state == EXACT_RELEASE_PRESENT else None


def build_plan(
    package: str,
    repo: str,
    protect_version: str,
    *,
    min_published_releases: int = 2,
) -> ReleasePlan:
    protected = Version(normalize_version(protect_version))
    releases = fetch_releases(package, repo)
    exact_release = fetch_exact_release_version(package, repo, str(protected))
    if exact_release is not None and all(
        Version(normalize_version(version)) != protected for version in releases
    ):
        releases = sorted([*releases, exact_release], key=lambda value: Version(value))
    old_versions = [
        version
        for version in releases
        if Version(normalize_version(version)) != protected
    ]
    missing_protected = exact_release is None
    if missing_protected:
        delete_versions = []
        retained_versions = old_versions
        retention_skipped_reason = "protected release is not confirmed by its exact PyPI endpoint"
    elif len(releases) < min_published_releases:
        delete_versions: list[str] = []
        retained_versions = old_versions
        retention_skipped_reason = (
            f"published release count {len(releases)} is below cleanup threshold "
            f"{min_published_releases}"
            if old_versions
            else None
        )
    else:
        delete_versions = old_versions
        retained_versions = []
        retention_skipped_reason = None
    return ReleasePlan(
        package=package,
        protect_version=str(protected),
        published_versions=releases,
        delete_versions=delete_versions,
        retained_versions=retained_versions,
        missing_protected_version=missing_protected,
        retention_skipped_reason=retention_skipped_reason,
    )


def reconcile_exact_deleted_releases(plan: ReleasePlan, *, repo: str) -> ReleasePlan:
    """Clear stale aggregate entries only after exact endpoints confirm deletion."""
    if not plan.delete_versions:
        return plan
    unresolved: list[str] = []
    confirmed_absent: set[str] = set()
    for version in plan.delete_versions:
        state, _observed = probe_exact_release_version(plan.package, repo, version)
        if state == EXACT_RELEASE_ABSENT:
            confirmed_absent.add(normalize_version(version))
        else:
            unresolved.append(version)
    if not confirmed_absent:
        return plan
    return replace(
        plan,
        published_versions=[
            version
            for version in plan.published_versions
            if normalize_version(version) not in confirmed_absent
        ],
        delete_versions=unresolved,
    )


def wait_for_protected_releases(
    *,
    packages: Sequence[str],
    repo: str,
    protect_version: str,
    attempts: int,
    retry_delay: float,
    min_published_releases: int = 2,
) -> list[ReleasePlan]:
    latest: list[ReleasePlan] = []
    for attempt in range(1, max(1, attempts) + 1):
        latest = [
            build_plan(
                package,
                repo,
                protect_version,
                min_published_releases=min_published_releases,
            )
            for package in packages
        ]
        if all(not plan.missing_protected_version for plan in latest):
            return latest
        if attempt < attempts:
            time.sleep(max(0.0, retry_delay))
    return latest


def wait_for_package_protected_releases(
    *,
    package_versions: dict[str, str],
    repo: str,
    attempts: int,
    retry_delay: float,
    min_published_releases: int = 2,
) -> list[ReleasePlan]:
    latest: list[ReleasePlan] = []
    for attempt in range(1, max(1, attempts) + 1):
        latest = [
            build_plan(
                package,
                repo,
                protect_version,
                min_published_releases=min_published_releases,
            )
            for package, protect_version in package_versions.items()
        ]
        if all(not plan.missing_protected_version for plan in latest):
            return latest
        if attempt < attempts:
            time.sleep(max(0.0, retry_delay))
    return latest


def read_cleanup_creds_from_pypirc(repo_name: str) -> tuple[str | None, str | None]:
    pypirc = Path.home() / ".pypirc"
    if not pypirc.exists():
        return None, None
    config = configparser.RawConfigParser()
    config.read(pypirc)
    section = f"{repo_name}_cleanup"
    if not config.has_section(section):
        return None, None
    username = (config.get(section, "username", fallback="") or "").strip() or None
    password = (config.get(section, "password", fallback="") or "").strip() or None
    return username, password


def require_credentials(
    username: str | None,
    password: str | None,
    *,
    repo_name: str = "pypi",
) -> tuple[str, str]:
    pypirc_user, pypirc_password = read_cleanup_creds_from_pypirc(repo_name)
    user = (
        username
        or os.environ.get("PYPI_RELEASE_PRUNE_USERNAME")
        or pypirc_user
        or ""
    ).strip()
    secret = (
        password
        or os.environ.get("PYPI_RELEASE_PRUNE_PASSWORD")
        or os.environ.get("PYPI_CLEANUP_PASSWORD")
        or os.environ.get("PYPI_PASSWORD")
        or pypirc_password
        or ""
    ).strip()
    if not user or not secret:
        raise SystemExit(
            "ERROR: PyPI release pruning needs cleanup web-login credentials via "
            "CLI, environment, or ~/.pypirc because Trusted Publishing/OIDC only "
            "covers upload, not release deletion."
        )
    if user == "__token__" or secret.startswith("pypi-"):
        raise SystemExit(
            "ERROR: PyPI release pruning uses the PyPI web cleanup flow; an API token "
            "or __token__ username is not accepted."
        )
    return user, secret


def generate_totp(secret: str, *, for_time: float | None = None, step: int = 30, digits: int = 6) -> str:
    normalized = re.sub(r"\s+", "", secret).upper()
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    try:
        key = base64.b32decode(normalized + padding, casefold=True)
    except (binascii.Error, ValueError) as exc:
        raise SystemExit("ERROR: PYPI_RELEASE_PRUNE_TOTP_SECRET is not valid base32") from exc
    counter = int((time.time() if for_time is None else for_time) // step)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**digits)).zfill(digits)


def resolve_auth_code(otp_code: str | None, totp_secret: str | None) -> str | None:
    explicit = (otp_code or os.environ.get("PYPI_RELEASE_PRUNE_OTP") or "").strip()
    if explicit:
        return explicit
    secret = (totp_secret or os.environ.get("PYPI_RELEASE_PRUNE_TOTP_SECRET") or "").strip()
    if secret:
        return generate_totp(secret)
    return None


def _rotating_totp_secret(otp_code: str | None, totp_secret: str | None) -> str | None:
    explicit = (otp_code or os.environ.get("PYPI_RELEASE_PRUNE_OTP") or "").strip()
    if explicit:
        return None
    secret = (totp_secret or os.environ.get("PYPI_RELEASE_PRUNE_TOTP_SECRET") or "").strip()
    return secret or None


def _redact_auth_code(output: str, auth_code: str | None) -> str:
    if auth_code:
        output = output.replace(auth_code, "***")
    return output


def _http_status_from_exception(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    return status_code if isinstance(status_code, int) else None


def _version_is_absent_from_public_index(*, package: str, version: str, repo: str) -> bool:
    state, _observed = probe_exact_release_version(package, repo, version)
    return state == EXACT_RELEASE_ABSENT


def _release_absent_after_not_found(
    *,
    package: str,
    version: str,
    repo: str,
    attempts: int = 4,
    retry_delay: float = 5.0,
) -> bool:
    for attempt in range(1, max(1, attempts) + 1):
        if _version_is_absent_from_public_index(
            package=package,
            version=version,
            repo=repo,
        ):
            return True
        if attempt < attempts:
            time.sleep(max(0.0, retry_delay))
    return False


def _raise_for_status_or_ignore_deleted_release(
    response: Any,
    *,
    package: str,
    version: str,
    repo: str,
    action: str,
) -> bool:
    try:
        response.raise_for_status()
    except Exception as exc:
        if _http_status_from_exception(exc) == 404 and _release_absent_after_not_found(
            package=package,
            version=version,
            repo=repo,
        ):
            print(
                "[pypi-retention] release already absent while "
                f"{action}; treating {package} {version} as deleted",
                file=sys.stderr,
            )
            return False
        raise
    return True


def _fresh_totp_code(previous: str | None, *, secret: str | None = None) -> str | None:
    secret = (secret or os.environ.get("PYPI_RELEASE_PRUNE_TOTP_SECRET") or "").strip()
    if not secret:
        return previous
    deadline = time.time() + 35
    code = generate_totp(secret)
    while previous and code == previous and time.time() < deadline:
        time.sleep(1)
        code = generate_totp(secret)
    return code


def _confirm_login_url_is_safe(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "pypi.org"
        and parsed.path == "/account/confirm-login/"
        and bool(parsed.query)
    )


def _consume_confirm_login_url(session: Any, url: str) -> None:
    if not _confirm_login_url_is_safe(url):
        raise RuntimeError("refusing to open a non-PyPI login confirmation URL")
    response = session.get(url)
    response.raise_for_status()


def _cleanup_confirm_login_url_provider(provider: Callable[[], str | None] | None) -> None:
    cleanup = getattr(provider, "cleanup", None)
    if callable(cleanup):
        cleanup()


def _fetch_github_actions_variable(
    *,
    repository: str,
    variable: str,
    token: str,
) -> str | None:
    api_url = f"https://api.github.com/repos/{repository}/actions/variables/{variable}"
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agilab-pypi-release-retention/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise RuntimeError(
            f"GitHub Actions variable lookup failed with HTTP {exc.code}"
        ) from exc
    value = str(payload.get("value") or "").strip()
    return value or None


def _delete_github_actions_variable(
    *,
    repository: str,
    variable: str,
    token: str,
) -> bool:
    api_url = f"https://api.github.com/repos/{repository}/actions/variables/{variable}"
    request = urllib.request.Request(
        api_url,
        method="DELETE",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agilab-pypi-release-retention/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise RuntimeError(
            f"GitHub Actions variable delete failed with HTTP {exc.code}"
        ) from exc
    return True


def _cleanup_github_confirm_login_variable(
    *,
    repository: str,
    variable: str,
    token: str,
) -> None:
    try:
        deleted = _delete_github_actions_variable(
            repository=repository,
            variable=variable,
            token=token,
        )
    except RuntimeError as exc:
        print(
            "::warning title=PyPI release retention::"
            f"Unable to clear temporary GitHub Actions variable {variable!r}: {exc}",
            file=sys.stderr,
        )
        return
    if deleted:
        print(
            f"[pypi-retention] cleared temporary GitHub Actions variable {variable!r}",
            file=sys.stderr,
        )


def _wait_for_github_confirm_login_url(
    *,
    repository: str,
    variable: str,
    token: str,
    timeout: float,
    poll_delay: float,
) -> str | None:
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() <= deadline:
        value = _fetch_github_actions_variable(
            repository=repository,
            variable=variable,
            token=token,
        )
        if value:
            return value
        time.sleep(max(1.0, poll_delay))
    return None


def _form_action_matches(action: str | None, target_path: str) -> bool:
    if not action:
        return True
    parsed = urlparse(action)
    action_path = parsed.path or target_path
    return action_path.rstrip("/") == target_path.rstrip("/")


def _find_form(
    html: str,
    *,
    target_path: str,
    required_input: str | None = None,
) -> HtmlForm:
    parser = FormParser()
    parser.feed(html)
    matching = [
        form
        for form in parser.forms
        if _form_action_matches(form.action, target_path)
        and "csrf_token" in form.inputs
    ]
    if required_input:
        with_input = [form for form in matching if required_input in form.inputs]
        if with_input:
            return with_input[0]
    if matching:
        return matching[0]
    raise RuntimeError(f"no csrf-bearing form found for {target_path}")


def _summarize_forms(html: str) -> str:
    parser = FormParser()
    parser.feed(html)
    if not parser.forms:
        return "forms=none"
    parts = []
    for form in parser.forms:
        inputs = ",".join(sorted(form.inputs)) or "none"
        parts.append(f"action={form.action or '(current)'} inputs={inputs}")
    return "forms=[" + "; ".join(parts) + "]"


def _find_reauth_form(html: str) -> HtmlForm | None:
    parser = FormParser()
    parser.feed(html)
    for form in parser.forms:
        if {"csrf_token", "password", "next_route", "next_route_matchdict"}.issubset(
            form.inputs
        ):
            return form
    return None


def _prepare_delete_form_data(form: HtmlForm, *, package: str, version: str) -> dict[str, str]:
    data = dict(form.inputs)
    data.setdefault("confirm_delete_version", version)
    for key in tuple(data):
        lowered = key.lower()
        if "version" in lowered and ("confirm" in lowered or "delete" in lowered):
            data[key] = version
        elif "project" in lowered and ("confirm" in lowered or "delete" in lowered):
            data[key] = package
    return data


def _submit_reauthentication_if_needed(
    session: Any,
    *,
    response: Any,
    base_url: str,
    username: str,
    password: str,
) -> Any:
    reauth_form = _find_reauth_form(response.text)
    if reauth_form is None:
        return response

    reauth_path = urlparse(reauth_form.action or "/account/reauthenticate/").path
    reauth_data = dict(reauth_form.inputs)
    reauth_data.setdefault("username", username)
    reauth_data.setdefault("next_route_query", "{}")
    reauth_data["password"] = password
    response = session.post(
        urljoin(base_url, reauth_form.action or reauth_path),
        data=reauth_data,
        headers={"referer": response.url},
    )
    response.raise_for_status()
    if _find_reauth_form(response.text) is not None:
        raise RuntimeError("PyPI rejected the re-authentication password")
    return response


def delete_release_via_pypi_web(
    *,
    package: str,
    version: str,
    repo: str,
    username: str,
    password: str,
    auth_code: str | None = None,
    totp_secret: str | None = None,
    confirm_login_url_provider: Callable[[], str | None] | None = None,
    session_factory: Callable[[], Any] | None = None,
    before_delete: Callable[[], None] | None = None,
) -> None:
    if not callable(before_delete):
        raise SystemExit("ERROR: deletion requires a guard immediately before the destructive POST")
    import requests

    base_url = PYPI_HOSTS[repo].rstrip("/")
    session_factory = session_factory or requests.Session
    with session_factory() as session:
        session.headers.update(
            {
                "User-Agent": (
                    "agilab-pypi-release-retention/1 "
                    f"(requests/{requests.__version__})"
                )
            }
        )

        def login_to_pypi(*, allow_confirmed_session: bool = False) -> Any:
            login_path = "/account/login/"
            login_url = f"{base_url}{login_path}"
            login_response = session.get(login_url)
            login_response.raise_for_status()
            try:
                login_form = _find_form(login_response.text, target_path=login_path)
            except RuntimeError:
                if allow_confirmed_session:
                    print(
                        "[pypi-retention] PyPI login form was absent after "
                        "confirmation; reusing the confirmed session",
                        file=sys.stderr,
                    )
                    return login_response
                raise
            login_data = dict(login_form.inputs)
            login_data.update({"username": username, "password": password})
            login_response = session.post(
                urljoin(base_url, login_form.action or login_path),
                data=login_data,
                headers={"referer": login_url},
            )
            login_response.raise_for_status()
            if login_response.url.rstrip("/") == login_url.rstrip("/"):
                raise RuntimeError(f"login failed for PyPI user {username!r}")

            two_factor_prefix = f"{base_url}/account/two-factor/"
            if not login_response.url.startswith(two_factor_prefix):
                return login_response

            fresh_auth_code = _fresh_totp_code(auth_code, secret=totp_secret)
            if fresh_auth_code is None:
                raise RuntimeError(
                    "PyPI requested 2FA but no non-interactive code was available"
                )
            two_factor_path = urlparse(login_response.url).path
            two_factor_form = _find_form(login_response.text, target_path=two_factor_path)
            two_factor_data = dict(two_factor_form.inputs)
            two_factor_data.update({"method": "totp", "totp_value": fresh_auth_code})
            login_response = session.post(
                urljoin(base_url, two_factor_form.action or two_factor_path),
                data=two_factor_data,
                headers={"referer": login_response.url},
            )
            login_response.raise_for_status()
            if login_response.url.startswith(two_factor_prefix):
                raise RuntimeError("PyPI rejected the generated TOTP code")
            return login_response

        login_to_pypi()

        def retry_login_after_confirmation() -> None:
            print(
                "[pypi-retention] PyPI login confirmation consumed; "
                "logging in again before opening the delete page",
                file=sys.stderr,
            )
            login_to_pypi(allow_confirmed_session=True)

        def consume_confirm_login_url() -> bool:
            if confirm_login_url_provider is None:
                return False
            confirm_url = confirm_login_url_provider()
            if not confirm_url:
                return False
            _consume_confirm_login_url(session, confirm_url)
            _cleanup_confirm_login_url_provider(confirm_login_url_provider)
            retry_login_after_confirmation()
            return True

        delete_path = f"/manage/project/{package}/release/{version}/"
        delete_url = f"{base_url}{delete_path}"

        def open_delete_page() -> Any:
            page_response = session.get(delete_url)
            if not _raise_for_status_or_ignore_deleted_release(
                page_response,
                package=package,
                version=version,
                repo=repo,
                action="opening the delete page",
            ):
                return None
            return _submit_reauthentication_if_needed(
                session,
                response=page_response,
                base_url=base_url,
                username=username,
                password=password,
            )

        response = open_delete_page()
        if response is None:
            return
        if urlparse(response.url).path.rstrip("/") == "/account/login":
            if consume_confirm_login_url():
                response = open_delete_page()
                if response is None:
                    return
            if urlparse(response.url).path.rstrip("/") == "/account/login":
                raise RuntimeError(
                    "PyPI redirected back to login while opening the release delete "
                    "page after password/TOTP authentication. PyPI likely requires "
                    "unrecognized-login email confirmation from the same runner IP; "
                    "use a self-hosted/static-IP runner for automatic deletion or "
                    "run the cleanup manually from a confirmed device."
                )
        try:
            delete_form = _find_form(
                response.text,
                target_path=delete_path,
                required_input="confirm_delete_version",
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"{exc}; url={response.url}; {_summarize_forms(response.text)}"
            ) from exc
        delete_data = _prepare_delete_form_data(
            delete_form,
            package=package,
            version=version,
        )
        before_delete()
        response = session.post(
            urljoin(base_url, delete_form.action or delete_path),
            data=delete_data,
            headers={"referer": delete_url},
        )
        _raise_for_status_or_ignore_deleted_release(
            response,
            package=package,
            version=version,
            repo=repo,
            action="submitting the delete form",
        )


def delete_release(
    *,
    package: str,
    version: str,
    repo: str,
    username: str,
    password: str,
    auth_code: str | None = None,
    totp_secret: str | None = None,
    confirm_login_url_provider: Callable[[], str | None] | None = None,
    before_delete: Callable[[], None] | None = None,
    direct_web_only: bool = False,
    verbose: bool = False,
) -> None:
    # An external subprocess cannot revalidate after its own authentication.
    # Always keep authentication and the guarded destructive POST in one process.
    if not callable(before_delete):
        raise SystemExit("ERROR: deletion requires a guard immediately before the destructive POST")
    try:
        delete_release_via_pypi_web(
            package=package, version=version, repo=repo,
            username=username, password=password, auth_code=auth_code,
            totp_secret=totp_secret,
            confirm_login_url_provider=confirm_login_url_provider,
            before_delete=before_delete,
        )
    except Exception as exc:
        raise SystemExit(f"ERROR: guarded PyPI web deletion failed for {package} {version}: {exc}") from exc



def verify_retention(
    *,
    packages: Sequence[str],
    repo: str,
    protect_version: str,
    attempts: int,
    retry_delay: float,
    min_published_releases: int = 2,
) -> list[ReleasePlan]:
    latest: list[ReleasePlan] = []
    for attempt in range(1, max(1, attempts) + 1):
        latest = [
            reconcile_exact_deleted_releases(
                build_plan(
                    package,
                    repo,
                    protect_version,
                    min_published_releases=min_published_releases,
                ),
                repo=repo,
            )
            for package in packages
        ]
        failures = [
            plan
            for plan in latest
            if plan.missing_protected_version or plan.delete_versions
        ]
        if not failures:
            return latest
        if attempt < attempts:
            time.sleep(max(0.0, retry_delay))
    return latest


def verify_package_retention(
    *,
    package_versions: dict[str, str],
    repo: str,
    attempts: int,
    retry_delay: float,
    min_published_releases: int = 2,
) -> list[ReleasePlan]:
    latest: list[ReleasePlan] = []
    for attempt in range(1, max(1, attempts) + 1):
        latest = [
            reconcile_exact_deleted_releases(
                build_plan(
                    package,
                    repo,
                    protect_version,
                    min_published_releases=min_published_releases,
                ),
                repo=repo,
            )
            for package, protect_version in package_versions.items()
        ]
        failures = [
            plan
            for plan in latest
            if plan.missing_protected_version or plan.delete_versions
        ]
        if not failures:
            return latest
        if attempt < attempts:
            time.sleep(max(0.0, retry_delay))
    return latest


def render_summary(plans: Sequence[ReleasePlan], *, dry_run: bool) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "success": all(
            not plan.missing_protected_version and not plan.delete_versions
            for plan in plans
        ),
        "dry_run": dry_run,
        "packages": [
            {
                "package": plan.package,
                "protect_version": plan.protect_version,
                "published_versions": plan.published_versions,
                "delete_versions": plan.delete_versions,
                "retained_versions": plan.retained_versions,
                "missing_protected_version": plan.missing_protected_version,
                "retention_skipped_reason": plan.retention_skipped_reason,
            }
            for plan in plans
        ],
    }


def append_step_summary(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "## PyPI release retention",
        "",
        f"- Status: `{'PASS' if summary['success'] else 'FAIL'}`",
        f"- Dry run: `{summary['dry_run']}`",
        "",
        "| Package | Keep | Published before cleanup | Deleted/remaining old versions |",
        "| --- | ---: | ---: | --- |",
    ]
    for package in summary["packages"]:
        if package.get("retention_skipped_reason"):
            retained = ", ".join(package["retained_versions"]) or "(none)"
            deleted = f"retained below threshold: {retained}"
        else:
            deleted = ", ".join(package["delete_versions"]) or "(none)"
        lines.append(
            "| `{package}` | `{protect}` | `{published}` | {deleted} |".format(
                package=package["package"],
                protect=package["protect_version"],
                published=len(package["published_versions"]),
                deleted=deleted,
            )
        )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")



@dataclass(frozen=True)
class ExplicitReleasePlan:
    package: str
    versions: tuple[str, ...]
    published_versions: tuple[str, ...]
    protected_versions: tuple[str, ...]


def parse_delete_releases(values: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """Accept only literal package==version selections, without implicit expansion."""
    selected: dict[str, list[str]] = {}
    seen: set[tuple[str, Version]] = set()
    for value in values:
        if value.count("==") != 1:
            raise SystemExit("ERROR: --delete-release must contain exactly package==version")
        package, version = value.split("==")
        if not PYPI_PROJECT_NAME_RE.fullmatch(package) or not version or version != version.strip():
            raise SystemExit("ERROR: --delete-release must contain exactly package==version")
        package = canonicalize_name(package)
        normalized = normalize_version(version)
        identity = (package, Version(normalized))
        if identity in seen:
            raise SystemExit(f"ERROR: duplicate deletion selection: {package}=={normalized}")
        seen.add(identity)
        selected.setdefault(package, []).append(normalized)
    if not selected:
        raise SystemExit("ERROR: an explicit --delete-release package==version is required; broad cleanup is disabled")
    return {package: tuple(versions) for package, versions in selected.items()}


def current_project_protections(repo_root: Path) -> dict[str, set[str]]:
    """Keep every current public package version and its exact first-party pins."""
    current = selected_public_versions(repo_root)
    protections = {
        canonicalize_name(package): {normalize_version(version)}
        for package, version in current.items()
    }
    for entry in public_package_entries(repo_root=repo_root):
        project = repo_root / entry["project"] / "pyproject.toml"
        data = tomllib.loads(project.read_text(encoding="utf-8"))
        metadata = data.get("project") or {}
        requirements = list(metadata.get("dependencies") or [])
        for group in (metadata.get("optional-dependencies") or {}).values():
            requirements.extend(group)
        for text in requirements:
            requirement = Requirement(text)
            name = canonicalize_name(requirement.name)
            if name in protections:
                for specifier in requirement.specifier:
                    if specifier.operator in {"==", "==="} and "*" not in specifier.version:
                        protections[name].add(normalize_version(specifier.version))
    return protections


def fresh_release_metadata(package: str, repo: str, version: str) -> dict[str, Any]:
    url = PYPI_RELEASE_JSON_URLS[repo].format(
        package=quote(package, safe=""), version=quote(version, safe="")
    )
    request = urllib.request.Request(
        f"{url}?agilab_cache_bust={time.time_ns()}",
        headers={"Cache-Control": "no-cache, no-store", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        metadata = json.loads(response.read().decode("utf-8"))
    info = metadata.get("info") or {}
    if (canonicalize_name(str(info.get("name", ""))) != package
            or Version(normalize_version(str(info.get("version", "")))) != Version(version)):
        raise SystemExit(f"ERROR: exact release metadata does not match {package}=={version}")
    return metadata


def build_explicit_plans(
    selected: dict[str, tuple[str, ...]], *, repo: str, repo_root: Path,
    extra_protections: Sequence[str] = (),
) -> list[ExplicitReleasePlan]:
    protections = {package: {Version(str(version)) for version in versions}
                   for package, versions in current_project_protections(repo_root).items()}
    unknown = set(selected) - set(protections)
    if unknown:
        raise SystemExit("ERROR: unknown first-party package(s): " + ", ".join(sorted(unknown)))
    extra = split_package_versions(extra_protections)
    for package, version in extra.items():
        name = canonicalize_name(package)
        if name not in protections:
            raise SystemExit(f"ERROR: unknown protected first-party package: {package}")
        protections[name].add(Version(version))
    plans: list[ExplicitReleasePlan] = []
    for package, versions in selected.items():
        published = fetch_releases(package, repo)
        indexed = {Version(version): version for version in published}
        if len(indexed) != len(published):
            raise SystemExit(f"ERROR: ambiguous equivalent published versions for {package}")
        if not indexed:
            raise SystemExit(f"ERROR: no published releases found for {package}")
        protections[package].add(max(indexed))
        selected_versions = {Version(version) for version in versions}
        unknown_versions = selected_versions - set(indexed)
        if unknown_versions:
            raise SystemExit(f"ERROR: unknown published version(s) for {package}: {', '.join(map(str, sorted(unknown_versions)))}")
        blocked = selected_versions & protections[package]
        if blocked:
            raise SystemExit(f"ERROR: refusing current, latest or pinned version(s) for {package}: {', '.join(map(str, sorted(blocked)))}")
        server_versions = tuple(indexed[Version(version)] for version in versions)
        for version in server_versions:
            fresh_release_metadata(package, repo, version)
        plans.append(ExplicitReleasePlan(
            package, server_versions, tuple(published),
            tuple(map(str, sorted(protections[package])))
        ))
    return plans


BACKUP_SCHEMA = "agilab.pypi_explicit_cleanup_backup.v1"
BACKUP_MANIFEST = "agilab_pypi_explicit_cleanup_backup_manifest.json"


def release_archive_entries(metadata: dict[str, Any], *, repo: str) -> list[dict[str, Any]]:
    entries = metadata.get("urls")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("ERROR: release has no downloadable files to back up")
    allowed_hosts = {"files.pythonhosted.org"} if repo == "pypi" else {
        "test-files.pythonhosted.org", "files.pythonhosted.org"
    }
    seen: set[str] = set()
    for entry in entries:
        filename = entry.get("filename", "")
        url = urlparse(entry.get("url", ""))
        digest = (entry.get("digests") or {}).get("sha256", "")
        if (not isinstance(filename, str) or not filename or Path(filename).name != filename
                or "/" in filename or "\\" in filename
                or filename in {".", ".."} or filename in seen
                or url.scheme != "https" or url.hostname not in allowed_hosts
                or url.username or url.password or url.port not in {None, 443}
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or not isinstance(entry.get("size"), int) or entry["size"] < 0):
            raise SystemExit("ERROR: invalid or duplicate PyPI archive metadata")
        seen.add(filename)
    return entries


def archive_path(root: Path, package: str, version: str, filename: str) -> Path:
    path = root / package / version / filename
    if (not path.resolve().is_relative_to(root.resolve())
            or any(parent.is_symlink() for parent in (path, *path.parents) if parent != root.parent)):
        raise SystemExit("ERROR: backup archive path must stay inside the backup directory without symlinks")
    return path


def prepare_release_backups(plans: Sequence[ExplicitReleasePlan], *, repo: str, directory: Path) -> None:
    """Create a new, complete archive; existing backups are never silently replaced."""
    if directory.exists():
        raise SystemExit("ERROR: --backup-dir already exists; use a new directory for a new backup")
    directory.mkdir(parents=True)
    releases = []
    for plan in plans:
        for version in plan.versions:
            metadata = fresh_release_metadata(plan.package, repo, version)
            entries = release_archive_entries(metadata, repo=repo)
            files = []
            for entry in entries:
                path = archive_path(directory, plan.package, version, entry["filename"])
                path.parent.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(entry["url"], timeout=60) as response:
                    payload = response.read()
                digest = hashlib.sha256(payload).hexdigest()
                if len(payload) != entry["size"] or digest != entry["digests"]["sha256"]:
                    raise SystemExit(f"ERROR: downloaded archive failed its size/hash check: {entry['filename']}")
                path.write_bytes(payload)
                files.append({"filename": entry["filename"], "sha256": digest, "size": len(payload)})
            releases.append({"package": plan.package, "version": version, "files": files})
    manifest = {"schema": BACKUP_SCHEMA, "repo": repo, "releases": releases}
    (directory / BACKUP_MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_release_backups(
    plans: Sequence[ExplicitReleasePlan], *, repo: str, directory: Path,
    current_target: tuple[str, str] | None = None,
) -> None:
    """Bind the saved bytes and complete file set to fresh official release metadata."""
    manifest_path = archive_path(directory, "", "", BACKUP_MANIFEST)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit("ERROR: readable backup manifest is required before deletion") from exc
    selected = {(plan.package, Version(version)) for plan in plans for version in plan.versions}
    releases = manifest.get("releases") or []
    identities = [(canonicalize_name(entry.get("package", "")),
                   Version(normalize_version(entry.get("version", "")))) for entry in releases]
    if (manifest.get("schema") != BACKUP_SCHEMA or manifest.get("repo") != repo
            or len(identities) != len(selected) or set(identities) != selected):
        raise SystemExit("ERROR: backup manifest must match the exact deletion selection and repository")
    target = ((current_target[0], Version(current_target[1]))
              if current_target else None)
    if target is not None and target not in selected:
        raise SystemExit("ERROR: backup verification target is outside the original exact selection")
    for release, identity in zip(releases, identities):
        if target is not None and identity != target:
            continue
        package, version = identity[0], release["version"]
        metadata = fresh_release_metadata(package, repo, version)
        expected = {
            entry["filename"]: (entry["digests"]["sha256"], entry["size"])
            for entry in release_archive_entries(metadata, repo=repo)
        }
        files = release.get("files") or []
        observed = {
            entry.get("filename"): (entry.get("sha256"), entry.get("size"))
            for entry in files
        }
        if observed != expected or len(files) != len(expected):
            raise SystemExit("ERROR: backup file set must match every official release archive")
        for filename, (digest, size) in expected.items():
            path = archive_path(directory, package, version, filename)
            if not path.is_file() or path.stat().st_size != size or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise SystemExit(f"ERROR: backup archive is missing or changed: {package}=={version}/{filename}")


def verify_explicit_cleanup(plans: Sequence[ExplicitReleasePlan], *, repo: str, attempts: int, retry_delay: float) -> bool:
    for attempt in range(max(1, attempts)):
        complete = True
        for plan in plans:
            for version in plan.versions:
                state, _ = probe_exact_release_version(plan.package, repo, version)
                complete = complete and state == EXACT_RELEASE_ABSENT
            published = {Version(version) for version in fetch_releases(plan.package, repo)}
            retained = {Version(version) for version in plan.published_versions} - {Version(version) for version in plan.versions}
            for version in retained - published:
                state, _ = probe_exact_release_version(plan.package, repo, str(version))
                if state != EXACT_RELEASE_PRESENT:
                    raise SystemExit(f"ERROR: unselected release is no longer confirmed: {plan.package}=={version}")
        if complete:
            return True
        if attempt + 1 < attempts:
            time.sleep(max(0.0, retry_delay))
    return False


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan exact first-party PyPI release deletions; deletion requires verified backups and explicit confirmation.")
    parser.add_argument("--repo", choices=tuple(PYPI_JSON_URLS), default="pypi")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--delete-release", action="append", default=[], metavar="PACKAGE==VERSION")
    parser.add_argument("--protect-package-version", action="append", default=[])
    parser.add_argument("--backup-dir", type=Path, help="Create a new backup during planning; verify an existing backup before confirmed deletion.")
    parser.add_argument("--confirm-delete", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Plan only (also the default without --confirm-delete).")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--otp-code")
    parser.add_argument("--totp-secret")
    parser.add_argument("--direct-web-only", action="store_true", help="Compatibility option: deletion always uses the guarded in-process web flow.")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verify-attempts", type=int, default=6)
    parser.add_argument("--retry-delay", type=float, default=10.0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    selected = parse_delete_releases(args.delete_release)
    if args.confirm_delete and args.dry_run:
        raise SystemExit("ERROR: --confirm-delete and --dry-run are mutually exclusive")
    plans = build_explicit_plans(selected, repo=args.repo, repo_root=args.repo_root, extra_protections=args.protect_package_version)
    dry_run = not args.confirm_delete
    if dry_run:
        if args.backup_dir:
            prepare_release_backups(plans, repo=args.repo, directory=args.backup_dir)
    else:
        if args.backup_dir is None:
            raise SystemExit("ERROR: deletion requires --backup-dir containing verified release archives")
        verify_release_backups(plans, repo=args.repo, directory=args.backup_dir)
        username, password = require_credentials(args.username, args.password, repo_name=args.repo)
        rotating_secret = _rotating_totp_secret(args.otp_code, args.totp_secret)
        previous_code = None
        for plan in plans:
            for version in plan.versions:
                def guard_selected_delete(package=plan.package, selected_version=version):
                    # This callback runs inside the authenticated web session immediately
                    # before its destructive POST, after all login/MFA/TOTP waits.
                    fresh = build_explicit_plans(
                        {package: (selected_version,)}, repo=args.repo,
                        repo_root=args.repo_root,
                        extra_protections=args.protect_package_version,
                    )
                    if fresh[0].versions != (selected_version,):
                        raise SystemExit("ERROR: published target spelling changed; prepare a new exact plan")
                    verify_release_backups(
                        plans, repo=args.repo, directory=args.backup_dir,
                        current_target=(package, selected_version),
                    )
                auth_code = (_fresh_totp_code(previous_code, secret=rotating_secret)
                             if rotating_secret else resolve_auth_code(args.otp_code, args.totp_secret))
                delete_release(package=plan.package, version=version, repo=args.repo,
                               username=username, password=password, auth_code=auth_code,
                               totp_secret=rotating_secret,
                               before_delete=guard_selected_delete,
                               direct_web_only=args.direct_web_only, verbose=args.verbose)
                previous_code = auth_code
        if not verify_explicit_cleanup(plans, repo=args.repo, attempts=args.verify_attempts, retry_delay=args.retry_delay):
            raise SystemExit("ERROR: selected release deletion is not confirmed by its exact endpoint")
    summary = {
        "schema": "agilab.pypi_explicit_cleanup.v1", "success": True, "dry_run": dry_run,
        "packages": [
            {"package": plan.package, "delete_versions": list(plan.versions),
             "published_versions": list(plan.published_versions),
             "protected_versions": list(plan.protected_versions),
             "retained_versions": [version for version in plan.published_versions if Version(version) not in {Version(target) for target in plan.versions}]}
            for plan in plans
        ],
    }
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        for plan in plans:
            print(f"{plan.package}: {'planned' if dry_run else 'deleted'}={','.join(plan.versions)} protected={','.join(plan.protected_versions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
