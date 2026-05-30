#!/usr/bin/env python3
"""Register a PyPI pending GitHub trusted publisher for a new project."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import html
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

try:
    from pypi_release_retention import (
        PYPI_HOSTS,
        _find_form,
        _fresh_totp_code,
        _submit_reauthentication_if_needed,
        require_credentials,
        resolve_auth_code,
    )
    from pypi_trusted_publisher_contract import (
        DEFAULT_OWNER,
        DEFAULT_REPOSITORY,
        DEFAULT_WORKFLOW,
    )
except ModuleNotFoundError:  # pragma: no cover - used when imported as tools.*
    from tools.pypi_release_retention import (
        PYPI_HOSTS,
        _find_form,
        _fresh_totp_code,
        _submit_reauthentication_if_needed,
        require_credentials,
        resolve_auth_code,
    )
    from tools.pypi_trusted_publisher_contract import (
        DEFAULT_OWNER,
        DEFAULT_REPOSITORY,
        DEFAULT_WORKFLOW,
    )


LOGIN_PATH = "/account/login/"
PUBLISHING_PATH = "/manage/account/publishing/"
SCHEMA_VERSION = "agilab.pypi_pending_trusted_publisher.v1"

SUCCESS_FRAGMENT = "Registered a new pending publisher to create"
ALREADY_REGISTERED_FRAGMENT = "This trusted publisher has already been registered"
DIFFERENT_PROJECT_FRAGMENT = "for a different project name"
MAX_PENDING_FRAGMENT = "more than 3 pending trusted publishers"
PROJECT_EXISTS_FRAGMENT = "This project already exists"
GENERIC_FAILURE_FRAGMENT = "The trusted publisher could not be registered"


@dataclass(frozen=True)
class PendingGitHubPublisher:
    project_name: str
    owner: str
    repository: str
    workflow_filename: str
    environment: str


@dataclass(frozen=True)
class RegistrationResult:
    publisher: PendingGitHubPublisher
    registered: bool
    already_registered: bool
    project_exists: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class GitHubActionsVariable:
    value: str
    updated_at: float | None


def _normalize_html(text: str) -> str:
    plain = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    plain = re.sub(r"(?s)<[^>]+>", " ", plain)
    return re.sub(r"\s+", " ", html.unescape(plain)).strip()


def _authenticate_pypi_web(
    session: Any,
    *,
    base_url: str,
    username: str,
    password: str,
    auth_code: str | None,
) -> None:
    login_url = f"{base_url}{LOGIN_PATH}"
    response = session.get(login_url)
    response.raise_for_status()

    login_form = _find_form(response.text, target_path=LOGIN_PATH)
    login_data = dict(login_form.inputs)
    login_data.update({"username": username, "password": password})
    response = session.post(
        urljoin(base_url, login_form.action or LOGIN_PATH),
        data=login_data,
        headers={"referer": login_url},
    )
    response.raise_for_status()
    if response.url.rstrip("/") == login_url.rstrip("/"):
        raise RuntimeError(f"login failed for PyPI user {username!r}")

    two_factor_prefix = f"{base_url}/account/two-factor/"
    if not response.url.startswith(two_factor_prefix):
        return

    auth_code = _fresh_totp_code(auth_code)
    if auth_code is None:
        raise RuntimeError("PyPI requested 2FA but no non-interactive code was available")
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


def _publisher_form_data(
    form_inputs: dict[str, str],
    publisher: PendingGitHubPublisher,
) -> dict[str, str]:
    data = dict(form_inputs)
    data.update(
        {
            "project_name": publisher.project_name,
            "owner": publisher.owner,
            "repository": publisher.repository,
            "workflow_filename": publisher.workflow_filename,
            "environment": publisher.environment,
        }
    )
    return data


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


def _response_diagnostic(text: str) -> str:
    plain = _normalize_html(text)
    markers = [
        "trusted publisher could not",
        "registered a new pending publisher",
        "already been registered",
        "already exists",
        "project name",
        "owner",
        "repository",
        "workflow",
        "environment",
        "unknown",
        "invalid",
        "maximum",
        "pending trusted publisher",
        "no pending publishers",
        "add a new pending publisher",
    ]
    snippets: list[str] = []
    lowered = plain.lower()
    for marker in markers:
        index = lowered.find(marker)
        if index < 0:
            continue
        start = max(0, index - 160)
        end = min(len(plain), index + 420)
        snippet = plain[start:end].strip()
        if snippet and snippet not in snippets:
            snippets.append(snippet)
    if not snippets:
        snippets.append(plain[:800])
    return " || ".join(snippets)[:2400]


def _parse_github_timestamp(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _fetch_github_actions_variable_payload(
    *,
    repository: str,
    variable: str,
    token: str,
) -> GitHubActionsVariable | None:
    api_url = f"https://api.github.com/repos/{repository}/actions/variables/{variable}"
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agilab-pypi-pending-trusted-publisher/1",
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
    if not value:
        return None
    return GitHubActionsVariable(
        value=value,
        updated_at=_parse_github_timestamp(str(payload.get("updated_at") or "")),
    )


def _fetch_github_actions_variable(
    *,
    repository: str,
    variable: str,
    token: str,
) -> str | None:
    payload = _fetch_github_actions_variable_payload(
        repository=repository,
        variable=variable,
        token=token,
    )
    return payload.value if payload else None


def _github_variable_is_fresh(
    payload: GitHubActionsVariable,
    *,
    minimum_updated_at: float,
    allow_existing: bool,
) -> bool:
    if allow_existing:
        return True
    if payload.updated_at is None:
        return False
    return payload.updated_at >= minimum_updated_at


def _wait_for_github_confirm_login_url(
    *,
    repository: str,
    variable: str,
    token: str,
    timeout: float,
    poll_delay: float,
    allow_existing: bool = False,
) -> str | None:
    minimum_updated_at = time.time() - 10.0
    deadline = time.monotonic() + max(0.0, timeout)
    stale_reported = False
    while time.monotonic() <= deadline:
        payload = _fetch_github_actions_variable_payload(
            repository=repository,
            variable=variable,
            token=token,
        )
        if payload and _github_variable_is_fresh(
            payload,
            minimum_updated_at=minimum_updated_at,
            allow_existing=allow_existing,
        ):
            return payload.value
        if payload and not stale_reported:
            stale_reported = True
            print(
                "Ignoring stale PyPI login confirmation URL from GitHub Actions "
                f"variable {variable!r}; set a fresh URL from the current PyPI "
                "email for this runner attempt.",
                file=sys.stderr,
            )
        time.sleep(max(1.0, poll_delay))
    return None


def _open_publishing_settings(
    session: Any,
    *,
    base_url: str,
    username: str,
    password: str,
    confirm_login_url_provider: Callable[[], str | None] | None,
) -> Any:
    publishing_url = f"{base_url}{PUBLISHING_PATH}"
    response = session.get(publishing_url)
    response.raise_for_status()
    response = _submit_reauthentication_if_needed(
        session,
        response=response,
        base_url=base_url,
        username=username,
        password=password,
    )
    if urlparse(response.url).path.rstrip("/") != "/account/login":
        return response

    if confirm_login_url_provider is not None:
        confirm_url = confirm_login_url_provider()
        if confirm_url:
            _consume_confirm_login_url(session, confirm_url)
            response = session.get(publishing_url)
            response.raise_for_status()
            response = _submit_reauthentication_if_needed(
                session,
                response=response,
                base_url=base_url,
                username=username,
                password=password,
            )
            if urlparse(response.url).path.rstrip("/") != "/account/login":
                return response

    raise RuntimeError(
        "PyPI redirected back to login while opening account publishing "
        "settings after password/TOTP authentication. PyPI likely requires "
        "unrecognized-login email confirmation from the same runner IP that "
        "started the login attempt. "
        "Set repository variable PYPI_CONFIRM_LOGIN_URL from the confirmation "
        "email link, then rerun with the same project inputs. "
        "If this repeats on GitHub-hosted runners, switch this workflow to a "
        "self-hosted/static-IP runner and retry."
    )


def _interpret_registration_response(
    response_text: str,
    publisher: PendingGitHubPublisher,
) -> RegistrationResult:
    text = _normalize_html(response_text)
    if SUCCESS_FRAGMENT in text and publisher.project_name in text:
        return RegistrationResult(
            publisher=publisher,
            registered=True,
            already_registered=False,
        )
    if ALREADY_REGISTERED_FRAGMENT in text and DIFFERENT_PROJECT_FRAGMENT not in text:
        return RegistrationResult(
            publisher=publisher,
            registered=False,
            already_registered=True,
        )
    if (
        publisher.project_name in text
        and f"GitHub Repository: {publisher.owner}/{publisher.repository}" in text
        and f"Workflow: {publisher.workflow_filename}" in text
        and f"Environment name: {publisher.environment}" in text
    ):
        return RegistrationResult(
            publisher=publisher,
            registered=False,
            already_registered=True,
        )
    if MAX_PENDING_FRAGMENT in text:
        raise RuntimeError(
            "PyPI refused the pending publisher because the account already has "
            "three pending trusted publishers. Remove stale pending publishers in "
            "PyPI account publishing settings, then rerun this workflow."
        )
    if PROJECT_EXISTS_FRAGMENT in text:
        return RegistrationResult(
            publisher=publisher,
            registered=False,
            already_registered=False,
            project_exists=True,
        )
    if GENERIC_FAILURE_FRAGMENT in text or DIFFERENT_PROJECT_FRAGMENT in text:
        raise RuntimeError(
            "PyPI rejected the pending trusted publisher registration; check the "
            "project name, GitHub owner/repository, workflow filename, environment, "
            "and whether this publisher identity is already pending for another project."
        )
    raise RuntimeError(
        "PyPI did not confirm pending trusted publisher registration; "
        f"diagnostic: {_response_diagnostic(response_text)!r}"
    )


def register_pending_github_publisher(
    *,
    publisher: PendingGitHubPublisher,
    repo: str,
    username: str,
    password: str,
    auth_code: str | None = None,
    confirm_login_url_provider: Callable[[], str | None] | None = None,
    session_factory: Callable[[], Any] | None = None,
) -> RegistrationResult:
    import requests

    base_url = PYPI_HOSTS[repo].rstrip("/")
    session_factory = session_factory or requests.Session
    with session_factory() as session:
        session.headers.update(
            {
                "User-Agent": (
                    "agilab-pypi-pending-trusted-publisher/1 "
                    f"(requests/{requests.__version__})"
                )
            }
        )
        _authenticate_pypi_web(
            session,
            base_url=base_url,
            username=username,
            password=password,
            auth_code=auth_code,
        )

        response = _open_publishing_settings(
            session,
            base_url=base_url,
            username=username,
            password=password,
            confirm_login_url_provider=confirm_login_url_provider,
        )

        form = _find_form(
            response.text,
            target_path=PUBLISHING_PATH,
            required_input="project_name",
        )
        registration_data = _publisher_form_data(form.inputs, publisher)
        response = session.post(
            urljoin(base_url, form.action or PUBLISHING_PATH),
            data=registration_data,
            headers={"referer": f"{base_url}{PUBLISHING_PATH}"},
        )
        response.raise_for_status()
        return _interpret_registration_response(response.text, publisher)


def render_summary(result: RegistrationResult) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "success": True,
        "registered": result.registered,
        "already_registered": result.already_registered,
        "project_exists": result.project_exists,
        "dry_run": result.dry_run,
        "publisher": asdict(result.publisher),
    }


def append_step_summary(path: Path, summary: dict[str, Any]) -> None:
    publisher = summary["publisher"]
    status = "DRY RUN" if summary["dry_run"] else "PASS"
    if summary["project_exists"]:
        state = "project already exists"
    elif summary["already_registered"]:
        state = "already registered"
    else:
        state = "registered"
    if summary["dry_run"]:
        state = "not submitted"
    lines = [
        "## PyPI pending trusted publisher",
        "",
        f"- Status: `{status}`",
        f"- Result: `{state}`",
        f"- PyPI project: `{publisher['project_name']}`",
        f"- GitHub owner/repository: `{publisher['owner']}/{publisher['repository']}`",
        f"- Workflow: `{publisher['workflow_filename']}`",
        f"- Environment: `{publisher['environment']}`",
        "",
    ]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Register a PyPI pending GitHub trusted publisher for a project that "
            "does not exist yet."
        )
    )
    parser.add_argument("--repo", choices=tuple(PYPI_HOSTS), default="pypi")
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--workflow-filename", default=DEFAULT_WORKFLOW)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--otp-code")
    parser.add_argument("--totp-secret")
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
    parser.add_argument(
        "--allow-existing-github-confirm-login-url",
        action="store_true",
        help=(
            "Allow a pre-existing PYPI_CONFIRM_LOGIN_URL value. The default is "
            "to ignore values older than this workflow attempt so stale email "
            "links cannot be reused accidentally."
        ),
    )
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--github-step-summary",
        nargs="?",
        const=os.environ.get("GITHUB_STEP_SUMMARY"),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    publisher = PendingGitHubPublisher(
        project_name=args.project_name,
        owner=args.owner,
        repository=args.repository,
        workflow_filename=args.workflow_filename,
        environment=args.environment,
    )

    if args.dry_run:
        result = RegistrationResult(
            publisher=publisher,
            registered=False,
            already_registered=False,
            dry_run=True,
        )
    else:
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
                    allow_existing=args.allow_existing_github_confirm_login_url,
                )

        result = register_pending_github_publisher(
            publisher=publisher,
            repo=args.repo,
            username=username,
            password=password,
            auth_code=resolve_auth_code(args.otp_code, args.totp_secret),
            confirm_login_url_provider=confirm_provider,
        )

    summary = render_summary(result)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    elif result.dry_run:
        print(
            "Dry run: pending trusted publisher would be registered for "
            f"{publisher.project_name}."
        )
    elif result.already_registered:
        print(f"Pending trusted publisher already registered for {publisher.project_name}.")
    elif result.project_exists:
        print(
            f"PyPI project {publisher.project_name} already exists; "
            "pending publisher registration is no longer needed."
        )
    else:
        print(f"Registered pending trusted publisher for {publisher.project_name}.")

    if args.github_step_summary:
        append_step_summary(Path(args.github_step_summary), summary)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
