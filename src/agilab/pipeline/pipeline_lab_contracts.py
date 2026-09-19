"""Typed capabilities for the workflow page; no UI or runtime imports on load.

PipelineLabDeps preserves the existing constructor. Each field now names its
call contract so a local editor, lock, assistant or persistence task can inspect
its capability without loading the page renderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    from agi_env import AgiEnv


class LoadAllStages(Protocol):
    def __call__(
        self, module_path: Path, stages_file: Path, index_page: str
    ) -> Optional[List[Dict[str, Any]]]: ...


class SaveStage(Protocol):
    def __call__(
        self,
        module: Path,
        query: List[Any],
        current_stage: int,
        nstages: int,
        stages_file: Path,
        venv_map: Optional[Dict[int, str]] = ...,
        engine_map: Optional[Dict[int, str]] = ...,
        extra_fields: Optional[Dict[str, Any]] = ...,
    ) -> Tuple[int, Dict[str, Any]]: ...


class RemoveStage(Protocol):
    def __call__(
        self, module: Path, stage: str, stages_file: Path, index_page: str
    ) -> int: ...


class ForcePersistStage(Protocol):
    def __call__(
        self,
        module_path: Path,
        stages_file: Path,
        stage_idx: int,
        entry: Dict[str, Any],
    ) -> None: ...


class CapturePipelineSnapshot(Protocol):
    def __call__(
        self, index_page: str, stages: List[Dict[str, Any]]
    ) -> Dict[str, Any]: ...


class RestorePipelineSnapshot(Protocol):
    def __call__(
        self,
        module_path: Path,
        stages_file: Path,
        index_page: str,
        sequence_widget_key: str,
        snapshot: Dict[str, Any],
    ) -> Optional[str]: ...


class RunAllStages(Protocol):
    def __call__(
        self,
        lab_dir: Path,
        index_page_str: str,
        stages_file: Path,
        module_path: Path,
        env: AgiEnv,
        log_placeholder: Optional[Any] = ...,
        force_lock_clear: bool = ...,
        pipeline_profile: str = ...,
        pipeline_max_workers: int = ...,
        pipeline_stage_deps: Optional[Any] = ...,
    ) -> None: ...


class PrepareRunLogFile(Protocol):
    def __call__(
        self, index_page: str, env: AgiEnv, prefix: str
    ) -> Tuple[Optional[Path], Optional[str]]: ...


class GetRunPlaceholder(Protocol):
    def __call__(self, index_page: str) -> Optional[Any]: ...


class PushRunLog(Protocol):
    def __call__(
        self, index_page: str, message: str, placeholder: Optional[Any] = ...
    ) -> None: ...


class RerunFragmentOrApp(Protocol):
    def __call__(self) -> None: ...


class BumpHistoryRevision(Protocol):
    def __call__(self) -> None: ...


class AskGpt(Protocol):
    def __call__(
        self,
        question: str,
        df_file: Path,
        index_page: str,
        envars: Dict[str, str],
        *,
        generation_mode: str = ...,
        load_df_cached: Any = ...,
    ) -> List[Any]: ...


class ConfigureAssistantEngine(Protocol):
    def __call__(self, env: AgiEnv, *, container: Any | None = ...) -> str: ...


class MaybeAutofixGeneratedCode(Protocol):
    def __call__(
        self,
        *,
        original_request: str,
        df_path: Path,
        index_page: str,
        env: AgiEnv,
        merged_code: str,
        model_label: str,
        detail: str,
        load_df_cached: Any,
        push_run_log: PushRunLog,
        get_run_placeholder: GetRunPlaceholder,
    ) -> Tuple[str, str, str]: ...


class LoadDfCached(Protocol):
    def __call__(self, path: Path, *, with_index: bool = ...) -> Any: ...


class EnsureSafeServiceTemplate(Protocol):
    def __call__(
        self,
        env: AgiEnv,
        stages_file: Path,
        *,
        template_filename: str,
        marker: str,
        debug_log: Callable[[str, Any], None],
    ) -> Optional[Path]: ...


class InspectPipelineRunLock(Protocol):
    def __call__(self, env: AgiEnv) -> Optional[Dict[str, Any]]: ...


class RefreshPipelineRunLock(Protocol):
    def __call__(self, lock_handle: Optional[Dict[str, Any]]) -> None: ...


class AcquirePipelineRunLock(Protocol):
    def __call__(
        self,
        env: AgiEnv,
        index_page: str,
        placeholder: Optional[Any] = ...,
        *,
        force: bool = ...,
    ) -> Optional[Dict[str, Any]]: ...


class ReleasePipelineRunLock(Protocol):
    def __call__(
        self,
        lock_handle: Optional[Dict[str, Any]],
        index_page: str,
        placeholder: Optional[Any] = ...,
    ) -> None: ...


class LabelForStageRuntime(Protocol):
    def __call__(
        self, venv_root: str | Path | None, *, engine: str | None, code: str | None
    ) -> str: ...


class PythonForStage(Protocol):
    def __call__(
        self, venv_root: str | Path | None, *, engine: str | None, code: str | None
    ) -> Path: ...


class PythonForVenv(Protocol):
    def __call__(self, venv_root: str | Path | None) -> Path: ...


class StreamRunCommand(Protocol):
    def __call__(
        self,
        env: AgiEnv,
        index_page: str,
        cmd: str | Sequence[str],
        cwd: Path,
        *,
        placeholder: Optional[Any] = ...,
        extra_env: Optional[Dict[str, str]] = ...,
        timeout: Optional[int] = ...,
    ) -> str: ...


class RunLockedStage(Protocol):
    def __call__(
        self,
        env: AgiEnv,
        index_page_str: str,
        stages_file: Path,
        stage: int,
        entry: Dict[str, Any],
        selected_map: Dict[int, str],
        engine_map: Dict[int, str],
        *,
        normalize_runtime_path: Callable[[Any], str],
        prepare_run_log_file: PrepareRunLogFile,
        push_run_log: PushRunLog,
        refresh_pipeline_run_lock: RefreshPipelineRunLock,
        acquire_pipeline_run_lock: AcquirePipelineRunLock,
        release_pipeline_run_lock: ReleasePipelineRunLock,
        get_run_placeholder: GetRunPlaceholder,
        is_valid_runtime_root: Callable[[str | Path | None], bool],
        python_for_venv: PythonForVenv,
        stream_run_command: StreamRunCommand,
        stage_summary: Callable[[Optional[Dict[str, Any]], int], str],
    ) -> None: ...


class LoadPipelineConceptualDot(Protocol):
    def __call__(
        self, env: Optional[AgiEnv], lab_dir: Optional[Path]
    ) -> Tuple[Optional[Path], str]: ...


class RenderPipelineView(Protocol):
    def __call__(
        self, step_entries: List[Dict[str, Any]], *, title: str = ...
    ) -> None: ...


@dataclass(frozen=True)
class PipelineLabDeps:
    load_all_stages: LoadAllStages
    save_stage: SaveStage
    remove_stage: RemoveStage
    force_persist_stage: ForcePersistStage
    capture_pipeline_snapshot: CapturePipelineSnapshot
    restore_pipeline_snapshot: RestorePipelineSnapshot
    run_all_stages: RunAllStages
    prepare_run_log_file: PrepareRunLogFile
    get_run_placeholder: GetRunPlaceholder
    push_run_log: PushRunLog
    rerun_fragment_or_app: RerunFragmentOrApp
    bump_history_revision: BumpHistoryRevision
    ask_gpt: AskGpt
    configure_assistant_engine: ConfigureAssistantEngine
    maybe_autofix_generated_code: MaybeAutofixGeneratedCode
    load_df_cached: LoadDfCached
    ensure_safe_service_template: EnsureSafeServiceTemplate
    inspect_pipeline_run_lock: InspectPipelineRunLock
    refresh_pipeline_run_lock: RefreshPipelineRunLock
    acquire_pipeline_run_lock: AcquirePipelineRunLock
    release_pipeline_run_lock: ReleasePipelineRunLock
    label_for_stage_runtime: LabelForStageRuntime
    python_for_stage: PythonForStage
    python_for_venv: PythonForVenv
    stream_run_command: StreamRunCommand
    run_locked_stage: RunLockedStage
    load_pipeline_conceptual_dot: LoadPipelineConceptualDot
    render_pipeline_view: RenderPipelineView
    default_df: str
    safe_service_template_filename: str
    safe_service_template_marker: str
