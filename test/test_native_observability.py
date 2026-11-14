"""Real owned loopback collectors decode SDK spans and lifecycle lineage events."""

from contextlib import contextmanager
import builtins
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from agilab.agent_runtime.agent_run import AgentRunConfig
from agilab.agent_runtime.agent_trace import AgentTraceStore, load_trace_events
from agilab.evidence import observability as obs


@contextmanager
def _receiver(tmp_path, name, *, port=18431):
    captures = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data = self.rfile.read(int(self.headers["Content-Length"]))
            captures.append(
                {
                    "path": self.path,
                    "body": data,
                    "received_ns": time.time_ns(),
                    "content_encoding": self.headers.get("Content-Encoding", ""),
                }
            )
            self.send_response(self.server.response_status)
            if self.server.redirect_location:
                self.send_header("Location", self.server.redirect_location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.response_status = 200
    server.redirect_location = ""
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server, captures
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        assert not thread.is_alive()
        target = (
            Path(os.environ.get("AGILAB_OBSERVABILITY_QUALIFICATION_DIR", tmp_path))
            / name
        )
        target.mkdir(parents=True, exist_ok=True)
        for i, capture in enumerate(captures):
            suffix = ".pb" if capture["path"] == "/v1/traces" else ".json"
            (target / f"agilab-native-agent-capture-{i:03d}{suffix}").write_bytes(
                capture["body"]
            )
        (target / "agilab-native-observability-receiver-capture-index.json").write_text(
            json.dumps(
                [
                    {key: value for key, value in capture.items() if key != "body"}
                    for capture in captures
                ],
                indent=2,
            )
        )


def _spans(captures):
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )

    spans = []
    for capture in captures:
        if capture["path"] == "/v1/traces":
            body = capture["body"]
            if capture.get("content_encoding") == "gzip":
                import gzip

                body = gzip.decompress(body)
            elif capture.get("content_encoding") == "deflate":
                import zlib

                body = zlib.decompress(body)
            request = ExportTraceServiceRequest.FromString(body)
            spans.extend(
                span
                for resource in request.resource_spans
                for scope in resource.scope_spans
                for span in scope.spans
            )
    return spans


def _lineage(captures):
    return [json.loads(c["body"]) for c in captures if c["path"] == "/api/v1/lineage"]


def _schemas():
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource

    root = Path(__file__).parent / "fixtures" / "observability"
    specs = [
        json.loads((root / name).read_bytes())
        for name in (
            "openlineage-2-0-2.schema.json",
            "openlineage-parent-1-2-0.schema.json",
        )
    ]
    registry = Registry().with_resources(
        (spec["$id"], Resource.from_contents(spec)) for spec in specs
    )

    def validator(ref):
        return Draft202012Validator(
            {"$ref": ref}, registry=registry, format_checker=FormatChecker()
        )

    return (
        validator(obs.OPENLINEAGE_SCHEMA_URL + "#/$defs/RunEvent"),
        validator(specs[1]["$id"] + "#/$defs/ParentRunFacet"),
    )


def _config(tmp_path, run_id, *, fail=False, timeout=10):
    script = tmp_path / "observed-child.py"
    script.write_text(
        "from pathlib import Path\nimport sys\n"
        "from agilab.evidence.observability import child_span\n"
        "with child_span(otlp_endpoint=sys.argv[1], receipt_path=Path(sys.argv[2]), "
        "run_id=sys.argv[3]):\n"
        "    Path(sys.argv[4]).write_text('actual child artifact')\n"
        "    print('token=secret-example')\n"
        "    if sys.argv[5] == 'fail': raise RuntimeError('secret-example')\n"
    )
    return AgentRunConfig(
        agent="local-qualification",
        label="Observed agent command",
        command=(
            sys.executable,
            str(script),
            "http://127.0.0.1:18431/v1/traces",
            str(tmp_path / "child-delivery.ndjson"),
            run_id,
            str(tmp_path / "child-result.txt"),
            "fail" if fail else "pass",
        ),
        cwd=tmp_path,
        output_dir=tmp_path / "execution",
        run_id=run_id,
        timeout_seconds=timeout,
        permission_level="standard",
    )


@pytest.mark.parametrize("fail", [False, True])
def test_real_agent_child_spans_and_lineage(tmp_path, fail):
    pytest.importorskip("opentelemetry.sdk")
    run_id = "native-fail" if fail else "native-pass"
    with _receiver(tmp_path, run_id) as (_server, captures):
        observer = obs.AgentLifecycleObserver(
            run_id=run_id,
            job_name="local-agent",
            receipt_path=tmp_path / "delivery.ndjson",
            otlp_endpoint="http://127.0.0.1:18431/v1/traces",
            lineage_endpoint="http://127.0.0.1:18431/api/v1/lineage",
            parent_run_id="parent-run",
            followup_run_id="previous-run",
            artifact_paths={"child-result": tmp_path / "child-result.txt"},
        )
        result = obs.run_observed_agent_command(
            _config(tmp_path, run_id, fail=fail), observer
        )
        assert result["returncode"] == (1 if fail else 0)
        assert result["execution"]["status"] == ("fail" if fail else "pass")
        assert result["delivery"]["status"] == "pass"
        spans = _spans(captures)
        assert sorted(s.name for s in spans) == [
            "agilab.agent",
            "agilab.child",
            "agilab.command",
        ]
        by_name = {span.name: span for span in spans}
        parent, command, child = [
            by_name[n] for n in ("agilab.agent", "agilab.command", "agilab.child")
        ]
        assert len({span.trace_id for span in spans}) == 1
        assert len({span.span_id for span in spans}) == 3
        assert command.parent_span_id == parent.span_id
        assert child.parent_span_id == command.span_id
        assert (
            parent.start_time_unix_nano
            <= command.start_time_unix_nano
            <= child.start_time_unix_nano
        )
        assert (
            child.end_time_unix_nano
            <= command.end_time_unix_nano
            <= parent.end_time_unix_nano
        )
        assert all(
            span.start_time_unix_nano < span.end_time_unix_nano for span in spans
        )
        assert all(span.status.code == (2 if fail else 1) for span in spans)
        assert all("secret-example" not in str(span) for span in spans)
        events = _lineage(captures)
        assert [e["eventType"] for e in events] == [
            "START",
            "RUNNING",
            "RUNNING",
            "FAIL" if fail else "COMPLETE",
        ]
        validator, parent_validator = _schemas()
        for event in events:
            validator.validate(event)
            parent_validator.validate(event["run"]["facets"]["parent"])
            assert event["run"]["runId"] == obs.lineage_run_id(run_id)
            facet = event["run"]["facets"]["agilabEvidence"]
            assert facet["observationMode"] == "live"
            assert facet["followupRunId"] == obs.lineage_run_id("previous-run")
        final_hash = events[-1]["outputs"][0]["facets"]["agilabEvidence"]
        assert (
            final_hash["observedSha256"]
            == hashlib.sha256(b"actual child artifact").hexdigest()
        )
        assert (
            final_hash["recordedSha256"] == ""
            and final_hash["hashVerification"] == "not_recorded"
        )
        trace = load_trace_events(tmp_path / "execution")
        by_sequence = {e.sequence: e for e in trace}
        for event in events:
            facet = event["run"]["facets"]["agilabEvidence"]
            recorded = by_sequence[facet["sequence"]]
            assert event["eventTime"] == recorded.created_at
            assert facet["executionStatus"] == recorded.status
        receipts = [
            json.loads(line)
            for line in (tmp_path / "delivery.ndjson").read_text().splitlines()
        ]
        assert all(r["status"] == "pass" for r in receipts)
        assert {r["transport"] for r in receipts} == {"otlp", "openlineage"}


def test_tool_lifecycle_uses_persisted_tool_identity(tmp_path):
    pytest.importorskip("opentelemetry.sdk")
    with _receiver(tmp_path, "tool-lifecycle") as (_server, captures):
        observer = obs.AgentLifecycleObserver(
            run_id="tools",
            job_name="tool-job",
            receipt_path=tmp_path / "receipt.ndjson",
            otlp_endpoint="http://127.0.0.1:18431/v1/traces",
            lineage_endpoint="http://127.0.0.1:18431/api/v1/lineage",
        )
        store = AgentTraceStore(
            tmp_path / "trace", run_id="tools", observers=(observer,)
        )
        store.append("session_start")
        store.append("command_start")
        store.append("tool_start", metadata={"tool_call_id": "actual-tool"})
        outcome = subprocess.run(
            [sys.executable, "-c", "print('actual tool')"],
            text=True,
            capture_output=True,
            timeout=5,
            check=True,
        )
        store.append(
            "tool_done",
            status="pass",
            metadata={"tool_call_id": "actual-tool", "returncode": outcome.returncode},
        )
        store.append("command_done", status="pass")
        store.append("session_end", status="pass")
        assert observer.close()["status"] == "pass"
        spans = {span.name: span for span in _spans(captures)}
        assert spans["agilab.tool"].parent_span_id == spans["agilab.command"].span_id
        assert [e["eventType"] for e in _lineage(captures)] == [
            "START",
            "RUNNING",
            "RUNNING",
            "RUNNING",
            "RUNNING",
            "COMPLETE",
        ]


def test_delivery_failure_visible_execution_unchanged_and_next_run_recovers(tmp_path):
    with _receiver(tmp_path, "delivery-recovery") as (server, captures):
        server.response_status = 503
        failed = obs.AgentLifecycleObserver(
            run_id="delivery-failure",
            job_name="job",
            receipt_path=tmp_path / "failed.ndjson",
            lineage_endpoint="http://127.0.0.1:18431/api/v1/lineage",
            timeout=0.2,
        )
        store = AgentTraceStore(
            tmp_path / "failed-trace", run_id="delivery-failure", observers=(failed,)
        )
        with pytest.warns(RuntimeWarning, match="execution status is unchanged"):
            store.append("session_start")
            store.append("session_end", status="pass")
        assert failed.close()["status"] == "fail"
        assert load_trace_events(tmp_path / "failed-trace")[-1].status == "pass"
        server.response_status = 200
        recovered = obs.AgentLifecycleObserver(
            run_id="delivery-recovered",
            job_name="job",
            receipt_path=tmp_path / "recovered.ndjson",
            lineage_endpoint="http://127.0.0.1:18431/api/v1/lineage",
        )
        store = AgentTraceStore(
            tmp_path / "recovered-trace",
            run_id="delivery-recovered",
            observers=(recovered,),
        )
        store.append("session_start")
        store.append("session_end", status="pass")
        assert recovered.close()["status"] == "pass"
        assert [e["eventType"] for e in _lineage(captures)] == ["START", "COMPLETE"] * 2


def test_historical_replay_is_labeled_and_not_live(tmp_path):
    trace = AgentTraceStore(tmp_path / "trace", run_id="history")
    trace.append("session_start")
    trace.append("session_end", status="fail")
    with _receiver(tmp_path, "historical") as (_server, captures):
        observer = obs.AgentLifecycleObserver(
            run_id="history",
            job_name="job",
            receipt_path=tmp_path / "receipt.ndjson",
            lineage_endpoint="http://127.0.0.1:18431/api/v1/lineage",
        )
        assert (
            obs.replay_historical_trace(tmp_path / "trace", observer)["status"]
            == "pass"
        )
        assert [e["eventType"] for e in _lineage(captures)] == ["START", "FAIL"]
        assert all(
            e["run"]["facets"]["agilabEvidence"]["observationMode"] == "historical"
            for e in _lineage(captures)
        )


def test_optional_capability_fails_before_execution_and_no_ambient_export(
    tmp_path, monkeypatch
):
    original = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name.startswith("opentelemetry"):
            raise ModuleNotFoundError(name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    with pytest.raises(RuntimeError, match=r"agilab\[observability\]"):
        obs.AgentLifecycleObserver(
            run_id="missing",
            job_name="job",
            receipt_path=tmp_path / "receipt.ndjson",
            otlp_endpoint="http://127.0.0.1:18431/v1/traces",
        )
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:18432")
    ordinary = AgentTraceStore(tmp_path / "ordinary", run_id="ordinary")
    ordinary.append("session_start")
    assert ordinary.observers == ()


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.com",
        "http://127.0.0.1:18431/?token=secret-example",
        "http://user:password@127.0.0.1:18431",
        "http://localhost:18431",
    ],
)
def test_endpoints_and_timeouts_are_explicit_local_and_bounded(tmp_path, endpoint):
    with pytest.raises(ValueError, match="loopback"):
        obs.AgentLifecycleObserver(
            run_id="test",
            job_name="job",
            receipt_path=tmp_path / "receipt",
            lineage_endpoint=endpoint,
        )
    for timeout in (0, -1, 31, float("inf"), float("nan")):
        with pytest.raises(ValueError, match="timeout"):
            obs.AgentLifecycleObserver(
                run_id="test",
                job_name="job",
                receipt_path=tmp_path / "receipt",
                timeout=timeout,
                lineage_endpoint="http://127.0.0.1:18431",
            )


def test_close_incomplete_lifecycle_is_visible_and_does_not_deadlock(tmp_path):
    with _receiver(tmp_path, "incomplete") as (server, _captures):
        server.response_status = 503
        observer = obs.AgentLifecycleObserver(
            run_id="incomplete",
            job_name="job",
            receipt_path=tmp_path / "receipts.ndjson",
            lineage_endpoint="http://127.0.0.1:18431/api/v1/lineage",
            timeout=0.05,
        )
        store = AgentTraceStore(
            tmp_path / "trace", run_id="incomplete", observers=(observer,)
        )
        with pytest.warns(RuntimeWarning):
            store.append("session_start")
            assert observer.close()["status"] == "fail"
        assert observer.close()["status"] == "fail"


@pytest.mark.parametrize(
    "returncode,delivery_failure", [(0, False), (3, False), (0, True)]
)
def test_real_cli_help_dispatch_and_separate_exit_status(
    tmp_path, returncode, delivery_failure
):
    from agilab.evidence import evidence_contract

    with pytest.raises(SystemExit) as exc:
        evidence_contract.main(["observe-agent", "--help"])
    assert exc.value.code == 0
    with _receiver(tmp_path, f"cli-{returncode}-{int(delivery_failure)}") as (
        server,
        captures,
    ):
        if delivery_failure:
            server.response_status = 503
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "agilab.evidence.evidence_contract",
                "observe-agent",
                "--run-id",
                "cli-run",
                "--job-name",
                "cli-job",
                "--output-dir",
                str(tmp_path / "execution"),
                "--receipt",
                str(tmp_path / "receipts.ndjson"),
                "--lineage-endpoint",
                "http://127.0.0.1:18431/api/v1/lineage",
                "--permission-level",
                "standard",
                "--json",
                "--cwd",
                str(tmp_path),
                "--",
                sys.executable,
                "-c",
                f"import sys; sys.exit({returncode})",
            ],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == (returncode or int(delivery_failure)), result.stderr
        payload = json.loads(result.stdout)
        assert payload["execution"]["status"] == ("pass" if returncode == 0 else "fail")
        assert payload["delivery"]["status"] == ("fail" if delivery_failure else "pass")
        assert _lineage(captures)[-1]["eventType"] == (
            "COMPLETE" if returncode == 0 else "FAIL"
        )


def test_otlp_redirect_failure_is_recorded_without_forwarding_and_recovers(tmp_path):
    pytest.importorskip("opentelemetry.sdk")
    with _receiver(tmp_path, "otlp-redirect-target", port=18432) as (
        _target,
        forwarded,
    ):
        with _receiver(tmp_path, "otlp-redirect-source") as (server, captures):
            server.response_status = 307
            server.redirect_location = "http://127.0.0.1:18432/v1/traces"
            observer = obs.AgentLifecycleObserver(
                run_id="redirected",
                job_name="job",
                receipt_path=tmp_path / "failed.ndjson",
                otlp_endpoint="http://127.0.0.1:18431/v1/traces",
                timeout=0.2,
            )
            trace = AgentTraceStore(
                tmp_path / "trace", run_id="redirected", observers=(observer,)
            )
            trace.append("session_start")
            with pytest.warns(RuntimeWarning, match="delivery failed"):
                trace.append("session_end", status="pass")
            assert observer.close()["status"] == "fail"
            assert load_trace_events(tmp_path / "trace")[-1].status == "pass"
            assert forwarded == []
            server.response_status, server.redirect_location = 200, ""
            recovery = obs.AgentLifecycleObserver(
                run_id="redirect-recovery",
                job_name="job",
                receipt_path=tmp_path / "recovered.ndjson",
                otlp_endpoint="http://127.0.0.1:18431/v1/traces",
            )
            trace = AgentTraceStore(
                tmp_path / "recovered",
                run_id="redirect-recovery",
                observers=(recovery,),
            )
            trace.append("session_start")
            trace.append("session_end", status="pass")
            assert recovery.close()["status"] == "pass"
            assert len(_spans(captures)) == 2


def test_native_capture_timeout_reaps_only_its_child_and_keeps_failed_execution(
    tmp_path,
):
    pid_path = tmp_path / "owned-child.pid"
    config = AgentRunConfig(
        agent="local-qualification",
        label="Timeout qualification",
        run_id="timeout",
        command=(
            sys.executable,
            "-c",
            "import os,time,pathlib; pathlib.Path("
            + repr(str(pid_path))
            + ").write_text(str(os.getpid())); time.sleep(30)",
        ),
        cwd=tmp_path,
        output_dir=tmp_path / "execution",
        timeout_seconds=0.5,
        permission_level="standard",
    )
    with _receiver(tmp_path, "native-timeout") as (_server, captures):
        observer = obs.AgentLifecycleObserver(
            run_id="timeout",
            job_name="job",
            receipt_path=tmp_path / "receipt.ndjson",
            lineage_endpoint="http://127.0.0.1:18431/api/v1/lineage",
        )
        result = obs.run_observed_agent_command(config, observer)
        assert result["returncode"] == 124
        assert result["execution"]["status"] == "timeout"
        assert result["delivery"]["status"] == "pass"
        assert _lineage(captures)[-1]["eventType"] == "FAIL"
        pid = int(pid_path.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


# OBS regressions use finite owned collectors and native child execution.
@contextmanager
def _dripping_receiver(mode, *, port=18431):
    stopped = threading.Event()
    handlers = []
    payload = b"x" * (16 * 1024)
    stats = {"requests": 0, "sent_bytes": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            handlers.append(threading.current_thread())
            self.rfile.read(int(self.headers["Content-Length"]))
            stats["requests"] += 1
            try:
                if mode == "headers":
                    for byte in b"HTTP/1.1 200 OK\r\nX-Slow: " + b"x" * 30:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        if stopped.wait(0.02):
                            return
                    self.wfile.write(b"\r\nContent-Length: 0\r\n\r\n")
                else:
                    self.send_response(302 if mode == "redirect" else 200)
                    if mode == "redirect":
                        self.send_header("Location", "http://127.0.0.1:18432/forbidden")
                    self.send_header(
                        "Content-Length",
                        "30" if mode == "drip" else str(4 * 1024 * 1024),
                    )
                    self.end_headers()
                    chunk = b"x" if mode == "drip" else payload
                    for _ in range(30 if mode == "drip" else 256):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        stats["sent_bytes"] += len(chunk)
                        if stopped.wait(0.05 if mode == "drip" else 0.005):
                            return
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02))
    thread.start()
    try:
        yield stats
    finally:
        stopped.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        for handler in handlers:
            handler.join(timeout=2)
        assert not thread.is_alive()
        assert not any(handler.is_alive() for handler in handlers)


def _minimal_observed_config(tmp_path, run_id, command=None, *, timeout=5):
    return AgentRunConfig(
        command=command or (sys.executable, "-c", "print('execution completed')"),
        agent="obs-regression",
        label="Observation blocker regression",
        cwd=tmp_path,
        output_dir=tmp_path / run_id,
        run_id=run_id,
        permission_level="standard",
        timeout_seconds=timeout,
    )


@pytest.mark.parametrize("mode", ["body", "redirect", "headers", "drip"])
def test_obs_regression_elapsed_budget_and_bounded_response(
    tmp_path, mode, record_property
):
    import tracemalloc

    observer = obs.AgentLifecycleObserver(
        run_id=mode,
        job_name="deadline",
        receipt_path=tmp_path / f"{mode}-receipts.ndjson",
        otlp_endpoint="http://127.0.0.1:18431/v1/traces",
        timeout=0.2,
    )
    with _dripping_receiver(mode) as stats:
        tracemalloc.start()
        started = time.monotonic()
        try:
            with pytest.warns(RuntimeWarning):
                result = obs.run_observed_agent_command(
                    _minimal_observed_config(tmp_path, mode), observer
                )
            elapsed = time.monotonic() - started
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert result["execution"]["status"] == "pass"
        assert result["delivery"]["status"] == "fail"
        assert stats["requests"] > 0
        record_property("elapsed_seconds", elapsed)
        record_property("peak_traced_bytes", peak)
        record_property("collector_sent_bytes", stats["sent_bytes"])
        assert elapsed < 0.9, (mode, elapsed, peak)
        assert peak < 2 * 1024 * 1024, (mode, elapsed, peak)
        assert observer.close()["status"] == "fail"
    with _receiver(tmp_path, f"{mode}-recovery"):
        fresh = obs.AgentLifecycleObserver(
            run_id=f"{mode}-recovery",
            job_name="deadline",
            receipt_path=tmp_path / f"{mode}-recovery.ndjson",
            otlp_endpoint="http://127.0.0.1:18431/v1/traces",
            timeout=0.2,
        )
        assert (
            obs.run_observed_agent_command(
                _minimal_observed_config(tmp_path, f"{mode}-recovery"), fresh
            )["delivery"]["status"]
            == "pass"
        )


@pytest.mark.parametrize("failure", ["callback", "encoding", "fsync"])
def test_obs_regression_start_failure_is_sticky_after_end(
    tmp_path, monkeypatch, failure
):
    with _receiver(tmp_path, f"sticky-{failure}") as (_server, captures):
        observer = obs.AgentLifecycleObserver(
            run_id=f"sticky-{failure}",
            job_name="sticky",
            receipt_path=tmp_path / "sticky-receipts.ndjson",
            lineage_endpoint="http://127.0.0.1:18431/api/v1/lineage",
        )
        secret = "password=OBS_PRIVATE_DIAGNOSTIC"
        if failure == "fsync":
            original = obs.os.fsync
            inode = observer.receipts.path.stat().st_ino
            failed = False

            def fsync(fd):
                nonlocal failed
                if not failed and os.fstat(fd).st_ino == inode:
                    failed = True
                    raise OSError(secret)
                return original(fd)

            monkeypatch.setattr(obs.os, "fsync", fsync)
        elif failure == "encoding":
            original_dumps = obs.json.dumps
            failed = False

            def encode_once(value, *args, **kwargs):
                nonlocal failed
                if (
                    isinstance(value, dict)
                    and value.get("eventType") == "START"
                    and not failed
                ):
                    failed = True
                    raise ValueError(secret)
                return original_dumps(value, *args, **kwargs)

            monkeypatch.setattr(obs.json, "dumps", encode_once)
        else:
            name = "observe"
            original = getattr(observer, name)
            failed = False

            def once(*args, **kwargs):
                nonlocal failed
                if not failed:
                    failed = True
                    if failure == "callback":
                        original(*args, **kwargs)
                    raise ValueError(secret)
                return original(*args, **kwargs)

            monkeypatch.setattr(observer, name, once)
        with pytest.warns(RuntimeWarning):
            result = obs.run_observed_agent_command(
                _minimal_observed_config(tmp_path, observer.run_id), observer
            )
        assert result["execution"]["status"] == "pass"
        assert _lineage(captures)[-1]["eventType"] == "COMPLETE"
        assert result["delivery"]["status"] == "fail"
        assert result["delivery"]["failed"] >= 1
        assert result["delivery"]["diagnostics"]
        assert "OBS_PRIVATE_DIAGNOSTIC" not in json.dumps(result)
        assert observer.close() == result["delivery"]
    with _receiver(tmp_path, f"sticky-recovery-{failure}"):
        fresh = obs.AgentLifecycleObserver(
            run_id="sticky-recovery",
            job_name="sticky",
            receipt_path=tmp_path / "recovered-receipts.ndjson",
            lineage_endpoint="http://127.0.0.1:18431/api/v1/lineage",
        )
        assert (
            obs.run_observed_agent_command(
                _minimal_observed_config(tmp_path, "sticky-recovery"), fresh
            )["delivery"]["status"]
            == "pass"
        )


@pytest.mark.parametrize("case", ["noisy", "timeout"])
def test_obs_regression_preserves_native_capture_evidence(tmp_path, case):
    from agilab.agent_runtime.agent_run import run_agent_command
    from agilab.agent_runtime.process_capture import MAX_LOG_BYTES

    if case == "noisy":
        script = "import sys; sys.stdout.write(('x'*1023+'\\n')*9216)"
        timeout = 10
    else:
        script = "import time; print('before timeout', flush=True); time.sleep(30)"
        timeout = 0.3
    command = (sys.executable, "-c", script)
    normal = run_agent_command(
        _minimal_observed_config(tmp_path, "ordinary", command, timeout=timeout)
    ).manifest
    with _receiver(tmp_path, f"capture-{case}"):
        observer = obs.AgentLifecycleObserver(
            run_id="observed",
            job_name="capture",
            receipt_path=tmp_path / "capture-receipts.ndjson",
            lineage_endpoint="http://127.0.0.1:18431/api/v1/lineage",
        )
        result = obs.run_observed_agent_command(
            _minimal_observed_config(tmp_path, "observed", command, timeout=timeout),
            observer,
        )
    observed = result["execution"]
    assert observed["status"] == normal["status"]
    assert observed["capture_outcome"] == normal["capture_outcome"]
    assert observed["output_capture"] == normal["output_capture"]
    for stream in ("stdout", "stderr"):
        assert (
            observed["artifacts"][stream]["sha256"]
            == normal["artifacts"][stream]["sha256"]
        )
    if case == "noisy":
        capture = observed["output_capture"]["stdout"]
        assert capture["observed_bytes"] > MAX_LOG_BYTES
        assert capture["stored_bytes"] == MAX_LOG_BYTES
        assert capture["truncated"] is True
    else:
        assert observed["capture_outcome"]["reason"] == "timeout"
        assert observed["capture_outcome"]["process_returncode"] != 0


def test_obs_regression_cli_retains_one_shot_observation_failure(
    tmp_path, monkeypatch, capsys
):
    from agilab.evidence import evidence_contract

    original_factory = obs.AgentLifecycleObserver

    def factory(**kwargs):
        observer = original_factory(**kwargs)
        append = observer.receipts.append
        failed = False

        def receipt(**values):
            nonlocal failed
            if values.get("event") == "START" and not failed:
                failed = True
                raise OSError("password=CLI_PRIVATE_FAILURE")
            return append(**values)

        monkeypatch.setattr(observer.receipts, "append", receipt)
        return observer

    monkeypatch.setattr(obs, "AgentLifecycleObserver", factory)
    with _receiver(tmp_path, "sticky-cli") as (_server, captures):
        with pytest.warns(RuntimeWarning):
            code = evidence_contract.main(
                [
                    "observe-agent",
                    "--run-id",
                    "sticky-cli",
                    "--job-name",
                    "sticky-cli",
                    "--output-dir",
                    str(tmp_path / "execution"),
                    "--receipt",
                    str(tmp_path / "delivery.ndjson"),
                    "--lineage-endpoint",
                    "http://127.0.0.1:18431/api/v1/lineage",
                    "--permission-level",
                    "standard",
                    "--cwd",
                    str(tmp_path),
                    "--json",
                    "--",
                    sys.executable,
                    "-c",
                    "print('real execution')",
                ]
            )
        payload = json.loads(capsys.readouterr().out)
        assert code == 1
        assert payload["returncode"] == 0
        assert payload["execution"]["status"] == "pass"
        assert payload["delivery"]["status"] == "fail"
        assert payload["delivery"]["diagnostics"]
        assert "CLI_PRIVATE_FAILURE" not in json.dumps(payload)
        assert _lineage(captures)[-1]["eventType"] == "COMPLETE"


@pytest.mark.parametrize("blocked_sequence", [1, 3])
@pytest.mark.parametrize("handle_kind", ["same", "second", "alias"])
@pytest.mark.parametrize("hold_origin_lock", [False, True])
def test_obs_regression_real_spans_follow_barrier_order(
    tmp_path, blocked_sequence, handle_kind, hold_origin_lock, monkeypatch, request
):
    from agilab.agent_runtime import agent_trace as trace

    entered, release = threading.Event(), threading.Event()
    queued, exit_writer = threading.Event(), threading.Event()
    second_callback_started = threading.Event()
    origin_locks = []
    seen, failures = [], []
    with _receiver(tmp_path, f"ordered-spans-{blocked_sequence}-{handle_kind}") as (
        _server,
        captures,
    ):
        observer = obs.AgentLifecycleObserver(
            run_id="ordered-spans",
            job_name="ordered",
            receipt_path=tmp_path / "ordered-receipts.ndjson",
            otlp_endpoint="http://127.0.0.1:18431/v1/traces",
        )

        def callback(event):
            if event.sequence == blocked_sequence:
                entered.set()
                assert release.wait(3)
            if hold_origin_lock and event.sequence == blocked_sequence + 1:
                second_callback_started.set()
                with store.events_path.with_name(store.events_path.name + ".lock").open(
                    "a+b"
                ) as handle:
                    available = trace._try_lock_handle(handle)
                    origin_locks.append(available)
                    if available:
                        trace._unlock_handle(handle)
                with trace._event_file_lock(store.events_path):
                    assert load_trace_events(store.root)[-1].sequence == event.sequence
            seen.append(event.sequence)
            observer(event)

        store = AgentTraceStore(
            tmp_path / "trace", run_id=observer.run_id, observers=(callback,)
        )

        store.initialize()
        peer_root = store.root
        if handle_kind == "alias":
            peer_root = tmp_path / "trace-alias"
            peer_root.symlink_to(store.root, target_is_directory=True)
        peer = (
            store
            if handle_kind == "same"
            else AgentTraceStore(
                peer_root, run_id=observer.run_id, observers=(callback,)
            )
        )
        peer.initialize()
        original_queue = peer._queue_observer

        def queue(record):
            result = original_queue(record)
            if hold_origin_lock and record.sequence == blocked_sequence + 1:
                queued.set()
                assert exit_writer.wait(3)
            return result

        monkeypatch.setattr(peer, "_queue_observer", queue)

        def append(event, handle=store):
            try:
                handle.append(
                    event,
                    status="pass" if event.endswith("done") else "running",
                    metadata={"tool_call_id": "ordered-tool"},
                )
            except BaseException as exc:
                failures.append(exc)

        if blocked_sequence == 3:
            append("session_start")
            append("command_start")
            pair = ("tool_start", "tool_done")
        else:
            pair = ("session_start", "command_start")
        first = threading.Thread(target=append, args=(pair[0],))
        second = threading.Thread(target=append, args=(pair[1], peer))
        callback_started_before_origin_exit = False
        first.start()
        try:
            assert entered.wait(2)
            second.start()
            if hold_origin_lock:
                assert queued.wait(2)
                release.set()
                callback_started_before_origin_exit = second_callback_started.wait(0.1)
                exit_writer.set()
            second.join(timeout=2)
            assert not second.is_alive()
        finally:
            exit_writer.set()
            release.set()
            first.join(timeout=3)
            if second.ident is not None:
                second.join(timeout=3)
        assert not first.is_alive() and not second.is_alive()
        assert not failures
        assert not callback_started_before_origin_exit
        if hold_origin_lock:
            assert origin_locks == [True]
        append("command_done")
        terminal = peer.append("session_end", status="pass")
        store_closed = store.close_observers(timeout=0.2)
        peer_closed = peer.close_observers(timeout=0.2)
        delivery = observer.close()
        durable = [e.sequence for e in load_trace_events(store.root)]
        request.node.user_properties.extend(
            [
                ("durable_sequence", str(durable)),
                ("observed_sequence", str(seen)),
                ("execution_status", terminal.status),
                ("delivery_status", delivery["status"]),
                (
                    "callback_started_before_origin_exit",
                    callback_started_before_origin_exit,
                ),
                ("origin_file_lock_available", str(origin_locks)),
                ("threads_remaining", int(first.is_alive()) + int(second.is_alive())),
            ]
        )
        assert terminal.status == load_trace_events(store.root)[-1].status == "pass"
        assert seen == durable
        assert store_closed and peer_closed
        assert delivery["status"] == "pass"
        assert not store.observer_errors and not peer.observer_errors
        spans = {span.name: span for span in _spans(captures)}
        root, command = spans["agilab.agent"], spans["agilab.command"]
        assert command.parent_span_id == root.span_id
        assert command.trace_id == root.trace_id
        request.node.user_properties.extend(
            [
                ("root_span_id", root.span_id.hex()),
                ("command_parent_span_id", command.parent_span_id.hex()),
                ("root_trace_id", root.trace_id.hex()),
                ("command_trace_id", command.trace_id.hex()),
            ]
        )
        if blocked_sequence == 3:
            tool = spans["agilab.tool"]
            assert tool.parent_span_id == command.span_id
            assert tool.trace_id == root.trace_id
            attrs = {a.key: a.value.int_value for a in tool.attributes}
            assert attrs["agilab.sequence.start"] == 3
            assert attrs["agilab.sequence.end"] == 4
            request.node.user_properties.extend(
                [
                    ("command_span_id", command.span_id.hex()),
                    ("tool_parent_span_id", tool.parent_span_id.hex()),
                    ("tool_trace_id", tool.trace_id.hex()),
                ]
            )


def test_metadata_native_delivery_waits_for_budget_failure_notification(
    tmp_path, request
):
    from agilab.agent_runtime import agent_trace as trace

    entered, release = threading.Event(), threading.Event()
    failing, finish_failure = threading.Event(), threading.Event()
    driver_errors = []
    with _receiver(tmp_path, "completion-budget") as (_server, captures):
        observer = obs.AgentLifecycleObserver(
            run_id="completion-budget",
            job_name="completion",
            receipt_path=tmp_path / "completion-receipts.ndjson",
            otlp_endpoint="http://127.0.0.1:18431/v1/traces",
            lineage_endpoint="http://127.0.0.1:18431/api/v1/lineage",
        )

        class Callback:
            def __call__(self, event):
                if event.sequence == 1:
                    entered.set()
                    assert release.wait(5)
                observer(event)

            def observation_failed(self, *, sequence, error_type):
                failing.set()
                assert finish_failure.wait(5)
                observer.observation_failed(sequence=sequence, error_type=error_type)

        callback = Callback()
        store = AgentTraceStore(
            tmp_path / "trace", run_id=observer.run_id, observers=(callback,)
        )
        peer = AgentTraceStore(
            store.root, run_id=observer.run_id, observers=(callback,)
        )

        def append():
            try:
                store.append("session_start")
            except BaseException as exc:
                driver_errors.append(exc)

        worker = threading.Thread(target=append)
        worker.start()
        with pytest.warns(RuntimeWarning, match="ObserverDrainBudgetExceeded"):
            try:
                assert entered.wait(2)
                for _ in range(trace.MAX_OBSERVER_QUEUE):
                    peer.append("tool_output")
                release.set()
                assert failing.wait(2)
                completion = [
                    peer.flush_observers(0.02),
                    peer.close_observers(0.02),
                    store.close_observers(0.02),
                ]
                reopened = AgentTraceStore(
                    store.root, run_id=observer.run_id, observers=(callback,)
                )
                shared_dispatch = (
                    reopened._observer_dispatch is store._observer_dispatch
                )
                completion.append(reopened.flush_observers(0.02))
                report_while_sink_pending = observer.receipts.report()
            finally:
                finish_failure.set()
                release.set()
                worker.join(timeout=5)
        assert not worker.is_alive() and not driver_errors
        assert completion == [False] * 4 and shared_dispatch
        assert report_while_sink_pending["observation_failures"] == 0
        assert not store.observer_errors
        assert list(peer.observer_errors) == [
            {
                "sequence": trace.MAX_OBSERVER_QUEUE + 1,
                "error_type": "ObserverDrainBudgetExceeded",
            }
        ]
        reopened.append("command_start")
        reopened.append("command_done", status="pass")
        terminal = reopened.append("session_end", status="pass")
        assert reopened.close_observers(0.2)
        delivery = observer.close()
        assert delivery["status"] == "fail" and delivery["observation_failures"] == 1
        assert terminal.status == load_trace_events(store.root)[-1].status == "pass"
        assert [e.sequence for e in load_trace_events(store.root)] == list(
            range(1, trace.MAX_OBSERVER_QUEUE + 5)
        )
        assert _lineage(captures)[-1]["eventType"] == "COMPLETE"
        spans = {span.name: span for span in _spans(captures)}
        assert spans["agilab.command"].parent_span_id == spans["agilab.agent"].span_id
        request.node.user_properties.extend(
            [
                ("production_queue_limit", trace.MAX_OBSERVER_QUEUE),
                ("pending_completion_results", str(completion)),
                ("observation_failures", delivery["observation_failures"]),
                ("execution_status", terminal.status),
                ("threads_remaining", int(worker.is_alive())),
            ]
        )
    with _receiver(tmp_path, "completion-recovery"):
        recovered = obs.AgentLifecycleObserver(
            run_id="completion-recovery",
            job_name="completion",
            receipt_path=tmp_path / "recovery-receipts.ndjson",
            lineage_endpoint="http://127.0.0.1:18431/api/v1/lineage",
        )
        fresh = AgentTraceStore(
            tmp_path / "recovery", run_id=recovered.run_id, observers=(recovered,)
        )
        fresh.append("session_start")
        terminal = fresh.append("session_end", status="pass")
        assert fresh.close_observers(0.2)
        assert recovered.close()["status"] == "pass" and terminal.status == "pass"


@pytest.mark.skipif(
    os.name != "posix", reason="owned inherited descriptor qualification is POSIX"
)
def test_obs_regression_inherited_pipe_capture_and_owned_cleanup(tmp_path, monkeypatch):
    from agilab.agent_runtime.agent_run import run_agent_command

    real_popen = subprocess.Popen
    owned_roots, owned_holders = [], []

    def inherited_popen(command, **kwargs):
        if "inherited-root" not in " ".join(command):
            return real_popen(command, **kwargs)
        reader, writer = os.pipe()
        try:
            holder = real_popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                pass_fds=(writer,),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            owned_holders.append(holder)
            kwargs["stdout"] = writer
            root = real_popen(command, **kwargs)
            owned_roots.append(root)
        finally:
            os.close(writer)
        root.stdout = os.fdopen(reader, "rb")
        return root

    monkeypatch.setattr(subprocess, "Popen", inherited_popen)
    command = (sys.executable, "-c", "print('inherited-root', flush=True)")
    try:
        normal = run_agent_command(
            _minimal_observed_config(tmp_path, "ordinary-pipes", command)
        ).manifest
        with _receiver(tmp_path, "inherited-pipes"):
            observer = obs.AgentLifecycleObserver(
                run_id="observed-pipes",
                job_name="pipes",
                receipt_path=tmp_path / "pipe-receipts.ndjson",
                lineage_endpoint="http://127.0.0.1:18431/api/v1/lineage",
            )
            result = obs.run_observed_agent_command(
                _minimal_observed_config(tmp_path, "observed-pipes", command), observer
            )
        observed = result["execution"]
        assert (
            normal["capture_outcome"]
            == observed["capture_outcome"]
            == {
                "process_returncode": 0,
                "reason": "incomplete_output",
            }
        )
        assert normal["output_capture"] == observed["output_capture"]
        assert observed["output_capture"]["stdout"]["stream_complete"] is False
        assert observed["output_capture"]["stdout"]["truncated"] is True
        assert observed["returncode"] == 125
        for stream in ("stdout", "stderr"):
            assert (
                normal["artifacts"][stream]["sha256"]
                == observed["artifacts"][stream]["sha256"]
            )
        assert len(owned_roots) == len(owned_holders) == 2
    finally:
        for holder in owned_holders:
            if holder.poll() is None:
                holder.terminate()
            holder.wait(timeout=2)
        for root in owned_roots:
            root.wait(timeout=2)
        assert all(
            child.returncode is not None for child in owned_roots + owned_holders
        )


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
def test_obs_regression_retains_sdk_wire_compression(tmp_path, monkeypatch, encoding):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_COMPRESSION", encoding)
    with _receiver(tmp_path, f"compression-{encoding}") as (_server, captures):
        observer = obs.AgentLifecycleObserver(
            run_id="compression",
            job_name="compression",
            receipt_path=tmp_path / "compression-receipts.ndjson",
            otlp_endpoint="http://127.0.0.1:18431/v1/traces",
        )
        result = obs.run_observed_agent_command(
            _minimal_observed_config(tmp_path, "compression"), observer
        )
        assert result["execution"]["status"] == "pass"
        assert result["delivery"]["status"] == "pass"
        assert {c["content_encoding"] for c in captures} == {encoding}
        spans = {s.name: s for s in _spans(captures)}
        assert spans["agilab.command"].parent_span_id == spans["agilab.agent"].span_id


def test_obs_regression_response_close_and_deadline_threads_are_reaped(
    tmp_path, monkeypatch
):
    responses = []
    original = obs.http.client.HTTPResponse.close

    def close(response):
        responses.append(response)
        return original(response)

    monkeypatch.setattr(obs.http.client.HTTPResponse, "close", close)
    with _receiver(tmp_path, "response-close") as (_server, captures):
        observer = obs.AgentLifecycleObserver(
            run_id="response-close",
            job_name="close",
            receipt_path=tmp_path / "close-receipts.ndjson",
            otlp_endpoint="http://127.0.0.1:18431/v1/traces",
        )
        assert (
            obs.run_observed_agent_command(
                _minimal_observed_config(tmp_path, "response-close"), observer
            )["delivery"]["status"]
            == "pass"
        )
        assert len(responses) >= len(captures) > 0
        assert all(response.isclosed() for response in responses)
        assert not any(
            isinstance(thread, threading.Timer) for thread in threading.enumerate()
        )


@pytest.mark.parametrize("failure", ["before_start", "child_context"])
def test_obs_regression_context_failure_never_stops_actual_execution(
    tmp_path, monkeypatch, failure
):
    with _receiver(tmp_path, f"context-failure-{failure}"):
        observer = obs.AgentLifecycleObserver(
            run_id="context-failure",
            job_name="context",
            receipt_path=tmp_path / "context-receipts.ndjson",
            otlp_endpoint="http://127.0.0.1:18431/v1/traces",
        )
        original = observer.observe
        failed = False

        def lose_start(event, **kwargs):
            nonlocal failed
            if not failed:
                failed = True
                raise ValueError("password=CONTEXT_PRIVATE_FAILURE")
            return original(event, **kwargs)

        def lose_context(_environment):
            raise ValueError("password=CONTEXT_PRIVATE_FAILURE")

        monkeypatch.setattr(
            observer,
            "observe" if failure == "before_start" else "child_environment",
            lose_start if failure == "before_start" else lose_context,
        )
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = obs.run_observed_agent_command(
                _minimal_observed_config(tmp_path, "context-failure"), observer
            )
        assert result["execution"]["status"] == "pass"
        assert result["returncode"] == 0
        assert result["delivery"]["status"] == "fail"
        assert result["delivery"]["diagnostics"]
        assert "CONTEXT_PRIVATE_FAILURE" not in json.dumps(result)
        output = Path(result["execution"]["artifacts"]["stdout"]["path"]).read_text()
        assert output == "execution completed\n"


def test_metadata_timeout_native_receipt_waits_for_owned_notification(
    tmp_path, request
):
    entered, release = threading.Event(), threading.Event()
    sink_entered, sink_release = threading.Event(), threading.Event()
    returned = threading.Event()
    callback_finished = threading.Event()
    errors, sink_threads, result = [], [], []
    with _receiver(tmp_path, "timeout-notification") as (_server, captures):
        observer = obs.AgentLifecycleObserver(
            run_id="timeout-notification",
            job_name="timeout-notification",
            receipt_path=tmp_path / "timeout-notification-receipts.ndjson",
            otlp_endpoint="http://127.0.0.1:18431/v1/traces",
            lineage_endpoint="http://127.0.0.1:18431/api/v1/lineage",
        )

        class Callback:
            def __call__(self, event):
                if event.sequence == 1:
                    entered.set()
                    if not release.wait(5):
                        errors.append("callback was not released")
                observer(event)
                callback_finished.set()

            def observation_failed(self, *, sequence, error_type):
                sink_threads.append(threading.current_thread())
                sink_entered.set()
                if not sink_release.wait(5):
                    errors.append("notification was not released")
                observer.observation_failed(sequence=sequence, error_type=error_type)

        callback = Callback()
        store = AgentTraceStore(
            tmp_path / "trace", run_id=observer.run_id, observers=(callback,)
        )
        peer = AgentTraceStore(
            store.root, run_id=observer.run_id, observers=(callback,)
        )
        reopened = None

        def append():
            try:
                store.append("session_start", status="pass")
            except BaseException as exc:
                errors.append(repr(exc))

        def flush():
            try:
                result.append(store.flush_observers(0.01))
            except BaseException as exc:
                errors.append(repr(exc))
            finally:
                returned.set()

        worker = threading.Thread(target=append)
        flusher = threading.Thread(target=flush)
        worker.start()
        try:
            assert entered.wait(2)
            flusher.start()
            assert sink_entered.wait(2)
            bounded_return = returned.wait(0.12)
            release.set()
            assert callback_finished.wait(3)
            completion = [
                peer.flush_observers(0),
                peer.close_observers(0),
                store.close_observers(0),
            ]
            reopened = AgentTraceStore(
                store.root, run_id=observer.run_id, observers=(callback,)
            )
            same_dispatch = reopened._observer_dispatch is store._observer_dispatch
            completion.append(reopened.flush_observers(0))
            pending_failures = observer.receipts.report()["observation_failures"]
        finally:
            release.set()
            sink_release.set()
            for thread in dict.fromkeys([worker, flusher, *sink_threads]):
                if thread.ident is not None:
                    thread.join(timeout=3)
            store.close_observers(0.2)
            peer.close_observers(0.2)
        assert bounded_return and result == [False]
        assert not errors and all(
            not thread.is_alive() for thread in [worker, flusher, *sink_threads]
        )
        assert sink_threads and sink_threads[0] is not flusher
        assert completion == [False] * 4 and same_dispatch
        assert pending_failures == 0
        assert not store.flush_observers(0) and not peer.observer_errors
        assert reopened.flush_observers(0.2)
        reopened.append("command_start")
        reopened.append("command_done", status="pass")
        terminal = reopened.append("session_end", status="pass")
        assert reopened.close_observers(0.2)
        delivery = observer.close()
        assert delivery["status"] == "fail" and delivery["observation_failures"] == 1
        assert terminal.status == load_trace_events(store.root)[-1].status == "pass"
        assert _lineage(captures)[-1]["eventType"] == "COMPLETE"
        spans = {span.name: span for span in _spans(captures)}
        assert spans["agilab.command"].parent_span_id == spans["agilab.agent"].span_id
        request.node.user_properties.extend(
            [
                ("bounded_timeout_return", bounded_return),
                ("pending_completion_results", str(completion)),
                ("same_dispatch_while_notification_pending", same_dispatch),
                ("pending_receipt_failures", pending_failures),
                ("final_observation_failures", delivery["observation_failures"]),
                ("execution_status", terminal.status),
            ]
        )
        recovered = obs.AgentLifecycleObserver(
            run_id="timeout-notification-recovery",
            job_name="timeout-notification",
            receipt_path=tmp_path / "timeout-recovery-receipts.ndjson",
            lineage_endpoint="http://127.0.0.1:18431/api/v1/lineage",
        )
        fresh = AgentTraceStore(
            tmp_path / "recovery", run_id=recovered.run_id, observers=(recovered,)
        )
        fresh.append("session_start")
        assert fresh.append("session_end", status="pass").status == "pass"
        assert fresh.close_observers(0.2)
        assert recovered.close()["status"] == "pass"
