import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from src.config import Config
from src.infrastructure.sessions.export_service import (
    SessionArtifacts,
    export_account_session,
)
from src.logging_utils import (
    configure_logging,
    log_print,
    logger,
    operator_logging_context,
)
from src.path_utils import build_timestamped_run_dir

MAX_ACCOUNT_HITS_PER_RUN = 2
INTER_ACCOUNT_COOLDOWN_SECONDS = 5


def build_output_dir(
    *,
    now_provider: Callable[[], datetime] | None = None,
) -> Path:
    timestamp = (now_provider or (lambda: datetime.now().astimezone()))()
    run_dir = build_timestamped_run_dir(Path("reports") / "sessions", timestamp)
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def export_configured_sessions(
    config: Config,
    *,
    output_dir: Path | None = None,
    exporter: Callable[[Config, Path], SessionArtifacts] = export_account_session,
    sleep_func: Callable[[float], None] = time.sleep,
    log=logger,
    log_print_func=log_print,
    max_account_hits: int = MAX_ACCOUNT_HITS_PER_RUN,
    cooldown_seconds: int = INTER_ACCOUNT_COOLDOWN_SECONDS,
) -> tuple[list[SessionArtifacts], list[str], Path]:
    account_configs = config.account_configs()
    if not account_configs:
        raise ValueError(
            "No account configuration found. Set EMAIL/PIN/NIK or EMAIL_1/PIN_1/NIK_1."
        )

    selected_account_configs = account_configs[:max_account_hits]
    if len(account_configs) > max_account_hits:
        log_print_func(
            (
                f"Configured {len(account_configs)} accounts, "
                f"but this run is limited to the first {max_account_hits} "
                f"account hits to avoid bursting the app."
            ),
            level="WARNING",
            event="user_sessions.limit_applied",
            configured_accounts=len(account_configs),
            selected_accounts=len(selected_account_configs),
            max_account_hits=max_account_hits,
        )

    run_context = getattr(config, "run_context", None)
    context_run_dir = getattr(run_context, "run_dir", None)
    resolved_output_dir = output_dir or (
        Path(context_run_dir) / "artifacts" / "sessions"
        if context_run_dir is not None
        else build_output_dir()
    )
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    log_print_func(
        f"Session artifacts directory: {resolved_output_dir.resolve()}",
        event="user_sessions.output_dir",
        output_dir=str(resolved_output_dir.resolve()),
    )

    artifacts: list[SessionArtifacts] = []
    failed_operators: list[str] = []

    for index, account_config in enumerate(selected_account_configs):
        operator = getattr(account_config, "operator_id", "") or (
            f"operator_{index + 1:02d}"
        )

        with operator_logging_context(operator):
            try:
                artifact = exporter(account_config, resolved_output_dir)
                if artifact.operator != operator:
                    artifact = SessionArtifacts(
                        operator=operator,
                        artifact_dir=artifact.artifact_dir,
                        profile_dir=artifact.profile_dir,
                        cookie_count=artifact.cookie_count,
                        xhr_count=artifact.xhr_count,
                    )
                artifacts.append(artifact)
            except Exception:  # noqa: BLE001 - isolate independent account exports.
                failed_operators.append(operator)
                log.bind(
                    event="user_session.failed",
                    operator_id=operator,
                    output_dir=str(resolved_output_dir.resolve()),
                ).exception("Failed to capture user session")

        is_last_account = index == len(selected_account_configs) - 1
        if not is_last_account:
            log_print_func(
                (
                    f"Cooling down for {cooldown_seconds} seconds "
                    f"before the next account to avoid bursting the app."
                ),
                event="user_sessions.cooldown",
                cooldown_seconds=cooldown_seconds,
            )
            sleep_func(cooldown_seconds)

    for artifact in artifacts:
        log_print_func(
            (
                f"[{artifact.operator}] cookies={artifact.cookie_count} "
                f"xhr={artifact.xhr_count} "
                f"artifact_dir={artifact.artifact_dir.resolve()} "
                f"profile_dir={artifact.profile_dir.resolve()}"
            ),
            event="user_sessions.summary.row",
            operator_id=artifact.operator,
            cookie_count=artifact.cookie_count,
            xhr_count=artifact.xhr_count,
            artifact_dir=str(artifact.artifact_dir.resolve()),
            profile_dir=str(artifact.profile_dir.resolve()),
        )

    return artifacts, failed_operators, resolved_output_dir


def run_user_session_export(
    *,
    config_factory: Callable[[], Config] = Config,
    configure_logging_func=configure_logging,
    exporter: Callable[[Config, Path], SessionArtifacts] = export_account_session,
    sleep_func: Callable[[float], None] = time.sleep,
    log=logger,
    log_print_func=log_print,
) -> int:
    config = config_factory()
    run_context = getattr(config, "run_context", None)
    try:
        if run_context is None:
            raise TypeError
        logging_meta = configure_logging_func(
            app_name="user_sessions",
            run_context=run_context,
        )
    except TypeError:
        # Backward-compatible injection seam for simple test/third-party factories.
        logging_meta = configure_logging_func(app_name="user_sessions")
    log.bind(
        event="user_sessions.start",
        run_id=logging_meta["run_id"],
        json_log_path=logging_meta["json_log_path"],
    ).info("User session export started")

    try:
        artifacts, failed_operators, output_dir = export_configured_sessions(
            config,
            exporter=exporter,
            sleep_func=sleep_func,
            log=log,
            log_print_func=log_print_func,
        )

        log.bind(
            event="user_sessions.finished",
            success_count=len(artifacts),
            failure_count=len(failed_operators),
            failed_operators=failed_operators,
            output_dir=str(output_dir.resolve()),
        ).info("User session export finished")

        return 1 if failed_operators else 0
    finally:
        complete = getattr(log, "complete", None)
        if callable(complete):
            complete()
