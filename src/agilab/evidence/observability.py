"""Explicit local agent lifecycle instrumentation; no default exporter or service.

Observers consume redacted, already durable AgentTraceStore events. Delivery
receipts describe transport, never scientific validity or remote retention.
"""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from datetime import datetime
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import socket
import threading
import time
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5
import warnings

from agilab.agent_runtime.agent_trace import AgentTraceEvent, observe_trace_events

DELIVERY_SCHEMA = "agilab.observability_delivery.v1"
OBSERVATION_SCHEMA = "agilab.local_agent_observation.v1"
OPENLINEAGE_SCHEMA_URL = "https://openlineage.io/spec/2-0-2/OpenLineage.json"
PRODUCER = "https://github.com/ThalesGroup/agilab"
_PARENT_SCHEMA = (
    "https://openlineage.io/spec/facets/1-2-0/ParentRunFacet.json#/$defs/ParentRunFacet"
)


def _endpoint(value: str) -> tuple[str, int, str]:
    diagnostic = (
        "Observability requires an explicit HTTP loopback IP and port, "
        "without credentials or query."
    )
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port is None
            or not 1 <= parsed.port <= 65535
        ):
            raise ValueError(diagnostic)
        return parsed.hostname, parsed.port, parsed.path or "/"
    except ValueError:
        raise ValueError(diagnostic) from None


def _timeout(value: float) -> float:
    if not math.isfinite(value) or not 0 < value <= 30:
        raise ValueError(
            "Observability timeout must be greater than zero and at most 30 seconds."
        )
    return value


def lineage_run_id(run_id: str) -> str:
    """Deterministic UUID identity for the same AGILAB run, including followups."""
    return str(uuid5(NAMESPACE_URL, "agilab:agent:" + run_id))


def _time_ns(event: AgentTraceEvent) -> int:
    return int(
        datetime.fromisoformat(event.created_at.replace("Z", "+00:00")).timestamp()
        * 1_000_000_000
    )


class DeliveryReceipts:
    """Separate append-only, fsynced transport results for one observer process."""

    def __init__(self, path: Path, run_id: str):
        self.path = Path(path).expanduser()
        self.run_id = run_id
        self.lock = threading.RLock()
        self.passed = 0
        self.failed = 0
        self.observation_failures = 0
        self.diagnostics: deque[dict[str, Any]] = deque(maxlen=100)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Detect an unusable receipt destination before launching a command.
        with self.path.open("a", encoding="utf-8"):
            pass

    def append(
        self,
        *,
        transport: str,
        passed: bool,
        sequence: int = 0,
        event: str = "",
        execution_status: str = "",
        historical: bool = False,
        error_code: str = "",
    ) -> None:
        payload = {
            "schema": DELIVERY_SCHEMA,
            "run_id": self.run_id,
            "transport": transport,
            "sequence": sequence,
            "event": event,
            "status": "pass" if passed else "fail",
            "execution_status": execution_status,
            "historical": historical,
            "error_code": error_code,
        }
        with self.lock:
            try:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, sort_keys=True) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception as exc:
                self.record_failure(
                    "receipt_storage_error", type(exc).__name__, sequence
                )
                raise
            if passed:
                self.passed += 1
            else:
                self.failed += 1
        if not passed:
            try:
                warnings.warn(
                    f"Observability delivery failed ({transport}, {error_code}); "
                    "execution status is unchanged. Inspect the delivery receipts.",
                    RuntimeWarning,
                    stacklevel=2,
                )
            except RuntimeWarning:
                pass

    def record_failure(
        self, code: str, error_type: str = "", sequence: int = 0
    ) -> None:
        """Sticky process-local status; independent of receipt storage health."""
        with self.lock:
            self.observation_failures += 1
            self.diagnostics.append(
                {
                    "code": code,
                    "error_type": "".join(c for c in error_type if c.isalnum())[:80],
                    "sequence": sequence,
                }
            )

    def report(self) -> dict[str, Any]:
        with self.lock:
            return {
                "schema": DELIVERY_SCHEMA,
                "status": "fail"
                if self.failed or self.observation_failures
                else "pass",
                "delivered": self.passed,
                "failed": self.failed + self.observation_failures,
                "observation_failures": self.observation_failures,
                "diagnostics": list(self.diagnostics),
                "receipt_path": str(self.path),
                "scope": "local transport response; not collector retention or execution verification",
            }


MAX_RESPONSE_BYTES = 64 * 1024


def _post_loopback(
    endpoint: str,
    body: bytes,
    content_type: str,
    timeout: float,
    *,
    content_encoding: str = "",
) -> tuple[int, bytes]:
    """Bound the entire HTTP exchange and response, including dripping headers."""
    host, port, path = _endpoint(endpoint)
    _timeout(timeout)
    headers = {"Content-Type": content_type}
    if content_encoding:
        if content_encoding not in {"gzip", "deflate"}:
            raise ValueError("Unsupported collector payload compression.")
        headers["Content-Encoding"] = content_encoding
    deadline = time.monotonic() + timeout
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    expired = threading.Event()
    response = None
    sock = None

    def interrupt() -> None:
        expired.set()
        # shutdown interrupts a socket.makefile read too; close alone does not.
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    timer = threading.Timer(timeout, interrupt)
    timer.daemon = True
    timer.start()
    try:
        connection.connect()  # Literal loopback IP: no DNS or ambient proxies.
        sock = connection.sock
        if expired.is_set() or time.monotonic() >= deadline:
            raise TimeoutError("Collector delivery deadline exceeded.")
        connection.sock.settimeout(max(0.001, deadline - time.monotonic()))
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise ValueError("Collector redirects are not accepted.")
        length = response.getheader("Content-Length")
        if length is not None and not 0 <= int(length) <= MAX_RESPONSE_BYTES:
            raise ValueError("Collector response exceeds the byte limit.")
        payload = response.read(MAX_RESPONSE_BYTES + 1)
        if expired.is_set() or time.monotonic() >= deadline:
            raise TimeoutError("Collector delivery deadline exceeded.")
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError("Collector response exceeds the byte limit.")
        # A collector's error text is not a diagnostic/log payload.
        return response.status, payload if 200 <= response.status < 300 else b""
    finally:
        try:
            if response is not None:
                response.close()
        finally:
            try:
                connection.close()
            finally:
                timer.cancel()
                timer.join()


def _tracer(endpoint: str, timeout: float, receipts: DeliveryReceipts):
    _endpoint(endpoint)
    _timeout(timeout)
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            SimpleSpanProcessor,
            SpanExporter,
            SpanExportResult,
        )
        from requests import Response, Session
    except ImportError as exc:
        raise RuntimeError(
            "Native OpenTelemetry export requires the optional agilab[observability] extra."
        ) from exc

    # Ignore ambient proxy, .netrc, exporter credentials and endpoint configuration.
    class LoopbackSession(Session):
        def request(self, method, url, **kwargs):
            if method.upper() != "POST" or url != endpoint:
                raise ValueError(
                    "Collector request differs from the configured endpoint."
                )
            status, payload = _post_loopback(
                endpoint,
                kwargs.get("data") or b"",
                "application/x-protobuf",
                min(timeout, kwargs.get("timeout", timeout)),
                content_encoding=next(
                    (
                        value
                        for key, value in (kwargs.get("headers") or {}).items()
                        if key.lower() == "content-encoding"
                    ),
                    "",
                ),
            )
            # The SDK's response interface receives only an already closed,
            # bounded exchange, never a live stream or an unbounded .content read.
            response = Response()
            response.status_code = status
            response.reason = http.client.responses.get(status, "Collector response")
            response._content = payload
            response._content_consumed = True
            response.close()
            return response

    session = LoopbackSession()
    session.trust_env = False
    exporter = OTLPSpanExporter(
        endpoint=endpoint,
        timeout=timeout,
        session=session,
        headers={"Content-Type": "application/x-protobuf"},
    )

    class RecordedExporter(SpanExporter):
        def export(self, spans):
            try:
                result = exporter.export(spans)
                passed = result == SpanExportResult.SUCCESS
            except Exception:
                result, passed = SpanExportResult.FAILURE, False
            for span in spans:
                attributes = span.attributes or {}
                receipts.append(
                    transport="otlp",
                    passed=passed,
                    event=span.name,
                    sequence=int(attributes.get("agilab.sequence.end", 0)),
                    execution_status=str(attributes.get("agilab.execution.status", "")),
                    historical=bool(attributes.get("agilab.historical", False)),
                    error_code="" if passed else "export_failed",
                )
            return result

        def shutdown(self):
            try:
                exporter.shutdown()
            finally:
                session.close()

    provider = TracerProvider(
        resource=Resource(
            {"service.name": "agilab.native-agent", "agilab.run_id": receipts.run_id}
        ),
        shutdown_on_exit=False,
    )
    provider.add_span_processor(SimpleSpanProcessor(RecordedExporter()))
    return provider, provider.get_tracer("agilab.native-agent")


class AgentLifecycleObserver:
    """One explicitly configured controller/run; callbacks execute outside trace locks."""

    def __init__(
        self,
        *,
        run_id: str,
        job_name: str,
        receipt_path: Path,
        otlp_endpoint: str | None = None,
        lineage_endpoint: str | None = None,
        timeout: float = 2,
        namespace: str = "agilab.local-agent",
        parent_run_id: str = "",
        followup_run_id: str = "",
        artifact_paths: Mapping[str, Path] | None = None,
        recorded_hashes: Mapping[str, str] | None = None,
        parent_carrier: Mapping[str, str] | None = None,
    ):
        if not run_id or not job_name or not namespace:
            raise ValueError("Observation requires a run ID, job name and namespace.")
        if not otlp_endpoint and not lineage_endpoint:
            raise ValueError(
                "Observation requires at least one explicit collector endpoint."
            )
        self.timeout = _timeout(timeout)
        for endpoint in (otlp_endpoint, lineage_endpoint):
            if endpoint:
                _endpoint(endpoint)
        self.run_id, self.job_name, self.namespace = run_id, job_name, namespace
        self.parent_run_id, self.followup_run_id = parent_run_id, followup_run_id
        self.artifact_paths = dict(artifact_paths or {})
        self.recorded_hashes = dict(recorded_hashes or {})
        self.parent_carrier = dict(parent_carrier or {})
        self.lineage_endpoint = lineage_endpoint
        self.lock = threading.RLock()
        self.root_span = self.command_span = None
        self.tool_spans: dict[str, Any] = {}
        self.started = self.ended = self.closed = False
        self.receipts = DeliveryReceipts(receipt_path, run_id)
        self.provider = self.tracer = None
        if otlp_endpoint:
            self.provider, self.tracer = _tracer(otlp_endpoint, timeout, self.receipts)

    def __call__(self, event: AgentTraceEvent) -> None:
        self.observe(event)

    def observation_failed(self, *, sequence: int, error_type: str) -> None:
        self.receipts.record_failure("observer_callback_error", error_type, sequence)

    def observe(self, event: AgentTraceEvent, *, historical: bool = False) -> None:
        try:
            self._observe(event, historical=historical)
        except Exception as exc:
            self.observation_failed(
                sequence=event.sequence, error_type=type(exc).__name__
            )
            raise

    def _observe(self, event: AgentTraceEvent, *, historical: bool = False) -> None:
        with self.lock:
            if self.closed or event.run_id != self.run_id:
                raise ValueError(
                    "Observer is closed or trace run identity does not match."
                )
            if event.event == "session_start":
                if self.started:
                    raise ValueError(
                        "A lifecycle observer accepts one session start per run."
                    )
                self.started = True
            elif not self.started:
                raise ValueError(
                    "A lifecycle observer requires session_start before later events."
                )
            if self.tracer:
                self._span_event(event, historical=historical)
            transition = {
                "session_start": "START",
                "command_start": "RUNNING",
                "tool_start": "RUNNING",
                "tool_done": "RUNNING",
                "command_done": "RUNNING",
                "error": "RUNNING",
                "session_end": "COMPLETE" if event.status == "pass" else "FAIL",
            }.get(event.event)
            if self.lineage_endpoint and transition:
                self._lineage(event, transition, historical=historical)
            if event.event == "session_end":
                self.ended = True

    def _span_event(self, event: AgentTraceEvent, *, historical: bool) -> None:
        from opentelemetry import trace
        from opentelemetry.context import Context
        from opentelemetry.trace import Status, StatusCode
        from opentelemetry.trace.propagation.tracecontext import (
            TraceContextTextMapPropagator,
        )

        timestamp = _time_ns(event)
        attributes = {
            "agilab.run_id": self.run_id,
            "agilab.historical": historical,
            "agilab.sequence.start": event.sequence,
        }
        if event.event == "session_start":
            parent = TraceContextTextMapPropagator().extract(
                self.parent_carrier, context=Context()
            )
            self.root_span = self.tracer.start_span(
                "agilab.agent",
                context=parent,
                start_time=timestamp,
                attributes=attributes,
            )
        elif event.event == "command_start":
            self.command_span = self.tracer.start_span(
                "agilab.command",
                context=trace.set_span_in_context(self.root_span, Context()),
                start_time=timestamp,
                attributes=attributes,
            )
        elif event.event == "tool_start":
            key = str(event.metadata.get("tool_call_id", event.sequence))
            if key in self.tool_spans:
                raise ValueError("Duplicate active tool call identity.")
            self.tool_spans[key] = self.tracer.start_span(
                "agilab.tool",
                context=trace.set_span_in_context(
                    self.command_span or self.root_span, Context()
                ),
                start_time=timestamp,
                attributes=attributes,
            )
        elif event.event == "tool_done":
            key = str(event.metadata.get("tool_call_id", ""))
            span = self.tool_spans.pop(key, None)
            if span is None:
                raise ValueError("Tool completion requires its active tool_call_id.")
            self._end_span(span, event)
        elif event.event == "command_done" and self.command_span:
            self._end_span(self.command_span, event)
            self.command_span = None
        elif event.event == "error":
            for span in (self.root_span, self.command_span):
                if span:
                    span.set_status(Status(StatusCode.ERROR))
        elif event.event == "session_end":
            for span in self.tool_spans.values():
                self._end_span(span, event, incomplete=True)
            self.tool_spans.clear()
            if self.command_span:
                self._end_span(self.command_span, event, incomplete=True)
                self.command_span = None
            if self.root_span:
                self._end_span(self.root_span, event)
                self.root_span = None
        active = self.command_span or self.root_span
        if active:
            active.add_event(
                event.event,
                timestamp=timestamp,
                attributes={
                    "agilab.sequence": event.sequence,
                    "agilab.status": event.status,
                },
            )

    @staticmethod
    def _end_span(span, event: AgentTraceEvent, *, incomplete: bool = False) -> None:
        from opentelemetry.trace import Status, StatusCode

        span.set_attribute("agilab.sequence.end", event.sequence)
        span.set_attribute("agilab.execution.status", event.status)
        passed = event.status == "pass" and not incomplete
        span.set_status(Status(StatusCode.OK if passed else StatusCode.ERROR))
        span.end(end_time=_time_ns(event))

    def child_environment(self, environment: Mapping[str, str]) -> dict[str, str]:
        """Inject W3C context into the environment of the actual owned subprocess."""
        if not self.command_span and not self.root_span:
            raise ValueError("Child context requires an active instrumented span.")
        from opentelemetry import trace
        from opentelemetry.context import Context
        from opentelemetry.trace.propagation.tracecontext import (
            TraceContextTextMapPropagator,
        )

        carrier: dict[str, str] = {}
        TraceContextTextMapPropagator().inject(
            carrier,
            context=trace.set_span_in_context(
                self.command_span or self.root_span, Context()
            ),
        )
        result = dict(environment)
        result.pop("TRACEPARENT", None)
        result.pop("TRACESTATE", None)
        result.update({key.upper(): value for key, value in carrier.items()})
        return result

    def _lineage(
        self, event: AgentTraceEvent, transition: str, *, historical: bool
    ) -> None:
        facet = {
            "_producer": PRODUCER,
            "_schemaURL": OPENLINEAGE_SCHEMA_URL + "#/$defs/RunFacet",
            "sourceRunId": self.run_id,
            "sequence": event.sequence,
            "sourceEvent": event.event,
            "executionStatus": event.status,
            "observationMode": "historical" if historical else "live",
        }
        if self.followup_run_id:
            facet["followupRunId"] = lineage_run_id(self.followup_run_id)
        facets = {"agilabEvidence": facet}
        if self.parent_run_id:
            facets["parent"] = {
                "_producer": PRODUCER,
                "_schemaURL": _PARENT_SCHEMA,
                "run": {"runId": lineage_run_id(self.parent_run_id)},
                "job": {"namespace": self.namespace, "name": self.job_name},
            }
        outputs = []
        if event.event == "session_end":
            for name, path in sorted(self.artifact_paths.items()):
                exists = Path(path).is_file()
                digest = ""
                if exists:
                    with Path(path).open("rb") as handle:
                        digest = hashlib.file_digest(handle, "sha256").hexdigest()
                outputs.append(
                    {
                        "namespace": "agilab.local-artifact",
                        "name": name,
                        "facets": {
                            "agilabEvidence": {
                                "_producer": PRODUCER,
                                "_schemaURL": OPENLINEAGE_SCHEMA_URL
                                + "#/$defs/DatasetFacet",
                                "exists": exists,
                                "observedSha256": digest,
                                "recordedSha256": self.recorded_hashes.get(name, ""),
                                "hashVerification": (
                                    "not_recorded"
                                    if not self.recorded_hashes.get(name)
                                    else "match"
                                    if digest
                                    and digest == self.recorded_hashes[name].lower()
                                    else "mismatch"
                                    if digest
                                    else "unavailable"
                                ),
                            }
                        },
                    }
                )
        payload = {
            "schemaURL": OPENLINEAGE_SCHEMA_URL + "#/$defs/RunEvent",
            "producer": PRODUCER,
            "eventType": transition,
            "eventTime": event.created_at,
            "run": {"runId": lineage_run_id(self.run_id), "facets": facets},
            "job": {"namespace": self.namespace, "name": self.job_name},
            "inputs": [],
            "outputs": outputs,
        }
        body = json.dumps(payload).encode()
        passed, error = False, ""
        try:
            status, _body = _post_loopback(
                self.lineage_endpoint,
                body,
                "application/json",
                self.timeout,
            )
            passed = 200 <= status < 300
            error = "" if passed else f"http_{status}"
        except (OSError, ValueError, http.client.HTTPException):
            error = "transport_error"
        self.receipts.append(
            transport="openlineage",
            passed=passed,
            sequence=event.sequence,
            event=transition,
            execution_status=event.status,
            historical=historical,
            error_code=error,
        )

    def close(self) -> dict[str, Any]:
        with self.lock:
            if not self.closed:
                if self.started and not self.ended:
                    try:
                        self.receipts.append(
                            transport="lifecycle",
                            passed=False,
                            error_code="missing_session_end",
                        )
                    except Exception:
                        pass  # The sticky in-memory storage failure already records it.
                    # Export unfinished spans as explicitly incomplete, never successful.
                    for span in [
                        *self.tool_spans.values(),
                        self.command_span,
                        self.root_span,
                    ]:
                        if span:
                            from opentelemetry.trace import Status, StatusCode

                            span.set_attribute("agilab.execution.status", "incomplete")
                            span.set_status(Status(StatusCode.ERROR))
                            span.end()
                    self.tool_spans.clear()
                    self.command_span = self.root_span = None
                if self.provider:
                    try:
                        self.provider.shutdown()
                    except Exception as exc:
                        self.receipts.record_failure(
                            "shutdown_error", type(exc).__name__
                        )
                self.closed = True
            return self.receipts.report()


@contextmanager
def child_span(
    *,
    otlp_endpoint: str,
    receipt_path: Path,
    run_id: str,
    name: str = "agilab.child",
    environment: Mapping[str, str] | None = None,
):
    """Explicit SDK instrumentation in the real child, using the injected W3C parent."""
    receipts = DeliveryReceipts(receipt_path, run_id)
    provider, tracer = _tracer(otlp_endpoint, 2, receipts)
    from opentelemetry.context import Context
    from opentelemetry.trace import Status, StatusCode
    from opentelemetry.trace.propagation.tracecontext import (
        TraceContextTextMapPropagator,
    )

    environment = os.environ if environment is None else environment
    carrier = {
        key.lower(): environment[key]
        for key in ("TRACEPARENT", "TRACESTATE")
        if key in environment
    }
    context = TraceContextTextMapPropagator().extract(carrier, context=Context())
    try:
        with tracer.start_as_current_span(
            name,
            context=context,
            record_exception=False,
            set_status_on_exception=False,
            attributes={"agilab.run_id": run_id},
        ) as span:
            try:
                yield span
            except BaseException:
                span.set_attribute("agilab.execution.status", "fail")
                span.set_status(Status(StatusCode.ERROR))
                raise
            else:
                span.set_attribute("agilab.execution.status", "pass")
                span.set_status(Status(StatusCode.OK))
    finally:
        provider.shutdown()


def run_observed_agent_command(
    config,
    observer: AgentLifecycleObserver,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Observe the native command route without replacing its capture or cleanup.

    Existing permissions, output ownership and result contracts remain authoritative.
    The explicit environment hook adds child context after command_start.
    """
    from agilab.agent_runtime.agent_run import run_agent_command

    if (
        not config.trace_enabled
        or config.print_only
        or config.run_id != observer.run_id
    ):
        raise ValueError(
            "Live observation requires a matching run ID, enabled trace and real execution."
        )

    def prepare_environment(environment: dict[str, str]) -> Mapping[str, str]:
        try:
            return observer.child_environment(environment)
        except Exception as exc:
            # Observation failure remains explicit and cannot cancel native execution.
            observer.receipts.record_failure("child_context_error", type(exc).__name__)
            result = dict(environment)
            result.pop("TRACEPARENT", None)
            result.pop("TRACESTATE", None)
            return result

    try:
        with observe_trace_events(observer):
            result = run_agent_command(
                config,
                prepare_environment=prepare_environment if observer.tracer else None,
                cancelled=cancelled,
            )
    finally:
        delivery = observer.close()
    return {
        "schema": OBSERVATION_SCHEMA,
        "execution": result.manifest,
        "returncode": result.returncode,
        "delivery": delivery,
    }


def replay_historical_trace(
    path: Path, observer: AgentLifecycleObserver
) -> dict[str, Any]:
    """Replay persisted events explicitly as historical, never live execution."""
    from agilab.agent_runtime.agent_trace import iter_trace_events

    try:
        for event in iter_trace_events(path):
            observer.observe(event, historical=True)
    finally:
        delivery = observer.close()
    return delivery
