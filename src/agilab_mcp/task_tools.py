"""Opt-in selected-action tools. Approval authority stays outside MCP."""

from agilab.agent_runtime.tasks import TaskStore, summary


BOUNDARY = {
    "mode": "registered-experiments",
    "execution_tools_enabled": True,
    "arbitrary_shell_enabled": False,
    "approval_tools_enabled": False,
    "authority": "Local operator registers experiments and approves the exact plan and attempt via CLI/API",
    "scope": "Trusted Python executes with operator permissions; no sandbox or restriction on code side effects",
    "recovery": "Status is read-only; reconcile, resume and fresh approved retries are local operator actions",
}


class TaskTools:
    def __init__(self, store: TaskStore):
        self.store = store
        self.tools = {
            "list_task_actions": self.list_actions,
            "submit_agent_task": self.submit,
            "read_agent_task": self.status,
            "start_agent_task": self.start,
            "cancel_agent_task": self.cancel,
        }

    def list_actions(self, *, offset: int = 0, limit: int = 20):
        return self.store.actions(offset=offset, limit=limit)

    def submit(self, action_id: str, idempotency_key: str):
        return summary(self.store.submit(action_id, idempotency_key))

    def status(self, task_id: str):
        return summary(self.store.status(task_id))

    def start(self, task_id: str, attempt: int):
        return summary(self.store.start(task_id, attempt=attempt))

    def cancel(self, task_id: str, attempt: int):
        return summary(self.store.cancel(task_id, attempt=attempt))


def descriptors():
    identifier = {"type": "string", "minLength": 1, "maxLength": 80}
    definitions = [
        (
            "list_task_actions",
            "List operator-registered experiment ids and plan digests.",
            {
                "offset": {"type": "integer", "minimum": 0, "maximum": 100000},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            [],
            True,
        ),
        (
            "submit_agent_task",
            "Persist a selected task awaiting local approval; reuse the same request key after transport failure.",
            {"action_id": identifier, "idempotency_key": identifier},
            ["action_id", "idempotency_key"],
            False,
        ),
        (
            "read_agent_task",
            "Read compact durable task state without execution or reconciliation.",
            {"task_id": identifier},
            ["task_id"],
            True,
        ),
        (
            "start_agent_task",
            "Start an already locally approved attempt in an owned background worker; poll read_agent_task.",
            {
                "task_id": identifier,
                "attempt": {"type": "integer", "minimum": 1, "maximum": 32},
            },
            ["task_id", "attempt"],
            False,
        ),
        (
            "cancel_agent_task",
            "Persist sticky cancellation for this attempt; the owned worker cooperatively stops its command.",
            {
                "task_id": identifier,
                "attempt": {"type": "integer", "minimum": 1, "maximum": 32},
            },
            ["task_id", "attempt"],
            False,
        ),
    ]
    task_schema = {
        "type": "object",
        "required": ["schema", "task_id", "status", "attempt", "revision"],
        "properties": {
            "schema": {"type": "string"},
            "task_id": identifier,
            "status": {
                "type": "string",
                "enum": [
                    "awaiting_approval",
                    "queued",
                    "running",
                    "interrupted",
                    "completed",
                    "failed",
                    "cancelled",
                    "denied",
                ],
            },
            "attempt": {"type": "integer", "minimum": 1},
            "revision": {"type": "integer", "minimum": 0},
        },
    }
    result = []
    for name, description, properties, required, read_only in definitions:
        result.append(
            {
                "name": name,
                "description": description,
                "inputSchema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
                "outputSchema": {
                    "type": "object",
                    "required": ["schema", "actions", "next_offset"],
                    "properties": {
                        "schema": {"type": "string"},
                        "actions": {"type": "array", "maxItems": 100},
                        "next_offset": {"type": ["integer", "null"]},
                    },
                }
                if name == "list_task_actions"
                else task_schema,
                "annotations": {
                    "readOnlyHint": read_only,
                    "destructiveHint": not read_only,
                    "idempotentHint": True,
                    "openWorldHint": name == "start_agent_task",
                },
            }
        )
    return result
