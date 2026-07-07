"""Typed Streamlit session-state key registry for AGILAB UI infrastructure."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionKey:
    """One registered Streamlit session-state key."""

    name: str
    owner: str
    description: str

    def __str__(self) -> str:
        return self.name


class SessionKeys:
    """Registered cross-page Streamlit session-state keys."""

    PAGE_ENV_REALIGNED = SessionKey(
        name="_agilab_page_env_realigned",
        owner="agilab.ui.page_bootstrap",
        description="Marks that a page repaired stale environment state for the active source root.",
    )
    PAGE_CONFIGURED = SessionKey(
        name="_agilab_page_configured",
        owner="agilab.ui.page_bootstrap",
        description="Marks that Streamlit page configuration has already been applied in this session.",
    )

    @classmethod
    def all(cls) -> tuple[SessionKey, ...]:
        return (
            cls.PAGE_ENV_REALIGNED,
            cls.PAGE_CONFIGURED,
        )
