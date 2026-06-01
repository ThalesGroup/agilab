#!/usr/bin/env python3
"""Enforce PyPI release retention after a successful trusted publish."""

from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import hashlib
from html.parser import HTMLParser
import json
import os
import re
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urljoin, urlparse

from packaging.version import InvalidVersion, Version

try:
    from pypi_release_version_policy import selected_public_versions
except ModuleNotFoundError:  # pragma: no cover - used when imported as tools.*
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pypi_release_version_policy import selected_public_versions


PYPI_JSON_URLS = {
    "pypi": "https://pypi.org/pypi/{package}/json",
    "testpypi": "https://test.pypi.org/pypi/{package}/json",
}
PYPI_HOSTS = {
    "pypi": "https://pypi.org/",
    "testpypi": "https://test.pypi.org/",
}
SCHEMA_VERSION = "agilab.pypi_release_retention.v1"


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
    missing_protected_version: bool


def normalize_version(version: str) -> str:
    try:
        return str(Version(version.strip().lstrip("v")))
    except InvalidVersion as exc:
        raise SystemExit(f"ERROR: invalid version {version!r}") from exc


def exact_release_regex(version: str) -> str:
    return f"^{re.escape(normalize_version(version))}$"


def split_packages(values: Sequence[str] | None) -> list[str]:
    packages: list[str] = []
    for value in values or ():
        packages.extend(token for token in re.split(r"[\s,]+", value.strip()) if token)
    return list(dict.fromkeys(packages))


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
            if previous is not None and previous != normalized:
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
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise RuntimeError(f"{url}: HTTP {exc.code}") from exc
    releases = data.get("releases") or {}
    if not isinstance(releases, dict):
        raise RuntimeError(f"{url}: expected JSON object with a releases mapping")
    return sorted(releases, key=lambda value: Version(value))


def build_plan(package: str, repo: str, protect_version: str) -> ReleasePlan:
    protected = Version(normalize_version(protect_version))
    releases = fetch_releases(package, repo)
    delete_versions = [
        version
        for version in releases
        if Version(normalize_version(version)) != protected
    ]
    missing_protected = all(
        Version(normalize_version(version)) != protected for version in releases
    )
    return ReleasePlan(
        package=package,
        protect_version=str(protected),
        published_versions=releases,
        delete_versions=delete_versions,
        missing_protected_version=missing_protected,
    )


def wait_for_protected_releases(
    *,
    packages: Sequence[str],
    repo: str,
    protect_version: str,
    attempts: int,
    retry_delay: float,
) -> list[ReleasePlan]:
    latest: list[ReleasePlan] = []
    for attempt in range(1, max(1, attempts) + 1):
        latest = [build_plan(package, repo, protect_version) for package in packages]
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
) -> list[ReleasePlan]:
    latest: list[ReleasePlan] = []
    for attempt in range(1, max(1, attempts) + 1):
        latest = [
            build_plan(package, repo, protect_version)
            for package, protect_version in package_versions.items()
        ]
        if all(not plan.missing_protected_version for plan in latest):
            return latest
        if attempt < attempts:
            time.sleep(max(0.0, retry_delay))
    return latest


def require_credentials(username: str | None, password: str | None) -> tuple[str, str]:
    user = (username or os.environ.get("PYPI_RELEASE_PRUNE_USERNAME") or "").strip()
    secret = (password or os.environ.get("PYPI_RELEASE_PRUNE_PASSWORD") or "").strip()
    if not user or not secret:
        raise SystemExit(
            "ERROR: PyPI release pruning needs PYPI_RELEASE_PRUNE_USERNAME and "
            "PYPI_RELEASE_PRUNE_PASSWORD secrets because Trusted Publishing/OIDC "
            "only covers upload, not release deletion."
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
    target = Version(normalize_version(version))
    return all(
        Version(normalize_version(candidate)) != target
        for candidate in fetch_releases(package, repo)
    )


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
) -> None:
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

        login_path = "/account/login/"
        login_url = f"{base_url}{login_path}"
        response = session.get(login_url)
        response.raise_for_status()
        login_form = _find_form(response.text, target_path=login_path)
        login_data = dict(login_form.inputs)
        login_data.update({"username": username, "password": password})
        response = session.post(
            urljoin(base_url, login_form.action or login_path),
            data=login_data,
            headers={"referer": login_url},
        )
        response.raise_for_status()
        if response.url.rstrip("/") == login_url.rstrip("/"):
            raise RuntimeError(f"login failed for PyPI user {username!r}")

        two_factor_prefix = f"{base_url}/account/two-factor/"
        if response.url.startswith(two_factor_prefix):
            auth_code = _fresh_totp_code(auth_code, secret=totp_secret)
            if auth_code is None:
                raise RuntimeError(
                    "PyPI requested 2FA but no non-interactive code was available"
                )
            two_factor_path = urlparse(response.url).path
            two_factor_form = _find_form(response.text, target_path=two_factor_path)
            two_factor_data = dict(two_factor_form.inputs)
            two_factor_data.update({"method": "totp", "totp_value": auth_code})
            response = session.post(
                urljoin(base_url, two_factor_form.action or two_factor_path),
                data=two_factor_data,
                headers={"referer": response.url},
            )
            response.raise_for_status()
            if response.url.startswith(two_factor_prefix):
                raise RuntimeError("PyPI rejected the generated TOTP code")

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
            if confirm_login_url_provider is not None:
                confirm_url = confirm_login_url_provider()
                if confirm_url:
                    _consume_confirm_login_url(session, confirm_url)
                    _cleanup_confirm_login_url_provider(confirm_login_url_provider)
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
    direct_web_only: bool = False,
    verbose: bool = False,
) -> None:
    if direct_web_only:
        print(
            "[pypi-retention] using direct PyPI web deletion",
            file=sys.stderr,
        )
        try:
            delete_release_via_pypi_web(
                package=package,
                version=version,
                repo=repo,
                username=username,
                password=password,
                auth_code=auth_code,
                totp_secret=totp_secret,
                confirm_login_url_provider=confirm_login_url_provider,
            )
        except Exception as exc:
            raise SystemExit(
                "ERROR: direct PyPI web deletion failed for "
                f"{package} {version}: {exc}"
            ) from exc
        return

    cmd = [
        "pypi-cleanup",
        "--version-regex",
        exact_release_regex(version),
        "--do-it",
        "-y",
        "--host",
        PYPI_HOSTS[repo],
        "--package",
        package,
        "--username",
        username,
    ]
    if verbose:
        cmd.append("-v")
    env = os.environ.copy()
    env.update(
        {
            "PYPI_USERNAME": username,
            "PYPI_PASSWORD": password,
            "PYPI_CLEANUP_PASSWORD": password,
        }
    )
    completed = subprocess.run(
        cmd,
        check=False,
        text=True,
        env=env,
        input=f"{auth_code}\n" if auth_code else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = _redact_auth_code(completed.stdout or "", auth_code)
    if output:
        print(output, end="" if output.endswith("\n") else "\n", file=sys.stderr)
    if completed.returncode == 0:
        return
    if auth_code is None and ("Authentication code:" in output or "EOFError" in output):
        raise SystemExit(
            "ERROR: PyPI release pruning reached a 2FA prompt. Add repository secret "
            "PYPI_RELEASE_PRUNE_TOTP_SECRET for non-interactive TOTP generation, or "
            "PYPI_RELEASE_PRUNE_OTP for a one-time manual rerun."
        )
    if "No CSFR found" in output or "No CSRF found" in output:
        print(
            "[pypi-retention] pypi-cleanup could not parse the delete form; "
            "using direct PyPI web fallback",
            file=sys.stderr,
        )
        try:
            delete_release_via_pypi_web(
                package=package,
                version=version,
                repo=repo,
                username=username,
                password=password,
                auth_code=auth_code,
                totp_secret=totp_secret,
                confirm_login_url_provider=confirm_login_url_provider,
            )
        except Exception as exc:
            raise SystemExit(
                "ERROR: direct PyPI web deletion fallback failed for "
                f"{package} {version}: {exc}"
            ) from exc
        return
    raise SystemExit(f"ERROR: pypi-cleanup failed for {package} {version} with exit code {completed.returncode}")



def verify_retention(
    *,
    packages: Sequence[str],
    repo: str,
    protect_version: str,
    attempts: int,
    retry_delay: float,
) -> list[ReleasePlan]:
    latest: list[ReleasePlan] = []
    for attempt in range(1, max(1, attempts) + 1):
        latest = [build_plan(package, repo, protect_version) for package in packages]
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
) -> list[ReleasePlan]:
    latest: list[ReleasePlan] = []
    for attempt in range(1, max(1, attempts) + 1):
        latest = [
            build_plan(package, repo, protect_version)
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
                "missing_protected_version": plan.missing_protected_version,
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


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Delete old PyPI releases for selected projects while keeping the "
            "current release version."
        )
    )
    parser.add_argument("--repo", choices=tuple(PYPI_JSON_URLS), default="pypi")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--package", action="append", default=[])
    parser.add_argument(
        "--packages",
        action="append",
        default=[],
        help="Comma- or space-separated package names.",
    )
    parser.add_argument(
        "--protect-version",
        help="Single version to protect for every selected package. Kept for legacy aligned releases.",
    )
    parser.add_argument(
        "--protect-package-version",
        action="append",
        default=[],
        help="Per-package protected version as package=version. Can be repeated or comma-separated.",
    )
    parser.add_argument(
        "--protect-versions-from-projects",
        action="store_true",
        help="Read protected versions from each selected release-plan project pyproject.toml.",
    )
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--otp-code")
    parser.add_argument("--totp-secret")
    parser.add_argument("--confirm-delete", action="store_true")
    parser.add_argument(
        "--allow-delete-failure-warning",
        action="store_true",
        help=(
            "Return success after recording stale releases when PyPI web deletion "
            "needs interactive cleanup. Missing protected releases still fail."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--direct-web-only",
        action="store_true",
        help=(
            "Use the in-process PyPI web deletion flow directly instead of "
            "trying pypi-cleanup first. This keeps unrecognized-login "
            "confirmation tied to the deletion session."
        ),
    )
    parser.add_argument("--verify-attempts", type=int, default=6)
    parser.add_argument("--retry-delay", type=float, default=10.0)
    parser.add_argument(
        "--github-confirm-login-repository",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="GitHub repository whose Actions variable carries a temporary PyPI confirmation URL.",
    )
    parser.add_argument(
        "--github-confirm-login-variable",
        help="GitHub Actions variable name containing the temporary PyPI confirmation URL.",
    )
    parser.add_argument(
        "--github-confirm-login-timeout",
        type=float,
        default=0.0,
        help="Seconds to wait for the temporary PyPI confirmation URL variable.",
    )
    parser.add_argument(
        "--github-confirm-login-poll-delay",
        type=float,
        default=5.0,
    )
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument(
        "--github-step-summary",
        nargs="?",
        const=os.environ.get("GITHUB_STEP_SUMMARY"),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    packages = split_packages([*args.package, *args.packages])
    if not packages:
        raise SystemExit("ERROR: at least one --package or --packages value is required")
    protect_versions = resolve_protect_versions(
        packages=packages,
        protect_version=args.protect_version,
        protect_package_versions=args.protect_package_version,
        protect_versions_from_projects=args.protect_versions_from_projects,
        repo_root=args.repo_root,
    )

    plans = wait_for_package_protected_releases(
        package_versions=protect_versions,
        repo=args.repo,
        attempts=args.verify_attempts,
        retry_delay=args.retry_delay,
    )
    missing = [
        f"{plan.package}={plan.protect_version}"
        for plan in plans
        if plan.missing_protected_version
    ]
    if missing:
        raise SystemExit(
            "ERROR: protected package versions are not visible on "
            f"{args.repo}: {', '.join(missing)}"
        )

    pending_deletes = [
        (plan.package, version)
        for plan in plans
        for version in plan.delete_versions
    ]
    if pending_deletes and not args.dry_run:
        if not args.confirm_delete:
            raise SystemExit("ERROR: destructive PyPI retention requires --confirm-delete")
        username, password = require_credentials(args.username, args.password)
        confirm_provider = None
        if args.github_confirm_login_variable and args.github_confirm_login_timeout > 0:
            if not args.github_confirm_login_repository or not args.github_token:
                raise SystemExit(
                    "ERROR: GitHub confirmation polling needs GITHUB_REPOSITORY "
                    "and GITHUB_TOKEN."
                )

            def confirm_provider() -> str | None:
                print(
                    "Waiting for PyPI login confirmation URL in GitHub Actions "
                    f"variable {args.github_confirm_login_variable!r}...",
                    file=sys.stderr,
                )
                return _wait_for_github_confirm_login_url(
                    repository=args.github_confirm_login_repository,
                    variable=args.github_confirm_login_variable,
                    token=args.github_token,
                    timeout=args.github_confirm_login_timeout,
                    poll_delay=args.github_confirm_login_poll_delay,
                )

            def cleanup_confirm_provider() -> None:
                _cleanup_github_confirm_login_variable(
                    repository=args.github_confirm_login_repository,
                    variable=args.github_confirm_login_variable,
                    token=args.github_token,
                )

            confirm_provider.cleanup = cleanup_confirm_provider  # type: ignore[attr-defined]

        delete_blocked = False
        rotating_totp_secret = _rotating_totp_secret(args.otp_code, args.totp_secret)
        previous_auth_code: str | None = None
        for package, version in pending_deletes:
            print(f"[pypi-retention] deleting {package} {version}", file=sys.stderr)
            if rotating_totp_secret:
                auth_code = _fresh_totp_code(
                    previous_auth_code,
                    secret=rotating_totp_secret,
                )
            else:
                auth_code = resolve_auth_code(args.otp_code, args.totp_secret)
            try:
                delete_release(
                    package=package,
                    version=version,
                    repo=args.repo,
                    username=username,
                    password=password,
                    auth_code=auth_code,
                    totp_secret=rotating_totp_secret,
                    confirm_login_url_provider=confirm_provider,
                    direct_web_only=args.direct_web_only,
                    verbose=args.verbose,
                )
                if rotating_totp_secret:
                    previous_auth_code = generate_totp(rotating_totp_secret)
                else:
                    previous_auth_code = auth_code
            except SystemExit as exc:
                if not args.allow_delete_failure_warning:
                    raise
                delete_blocked = True
                message = str(exc).replace("\n", " ")
                print(
                    "::warning title=PyPI release retention::"
                    f"Old PyPI releases remain for {package}: {message}",
                    file=sys.stderr,
                )
                break
        plans = verify_package_retention(
            package_versions=protect_versions,
            repo=args.repo,
            attempts=args.verify_attempts,
            retry_delay=args.retry_delay,
        )
    else:
        delete_blocked = False

    summary = render_summary(plans, dry_run=args.dry_run)
    if args.github_step_summary:
        append_step_summary(Path(args.github_step_summary), summary)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        for package in summary["packages"]:
            deleted = ", ".join(package["delete_versions"]) or "(none)"
            print(
                f"{package['package']}: keep={package['protect_version']} "
                f"published={len(package['published_versions'])} old={deleted}"
            )
    return 0 if summary["success"] or args.dry_run or delete_blocked else 1


if __name__ == "__main__":
    raise SystemExit(main())
