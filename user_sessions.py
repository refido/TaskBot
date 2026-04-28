from src.application.use_cases.export_session import (
    INTER_ACCOUNT_COOLDOWN_SECONDS,
    MAX_ACCOUNT_HITS_PER_RUN,
    build_output_dir,
    export_configured_sessions,
    run_user_session_export,
)
from src.infrastructure.sessions.export_service import (
    CHROMIUM_EPOCH,
    DEFAULT_NETWORK_WAIT_MS,
    SessionArtifacts,
    export_account_session,
)
from src.infrastructure.sessions.xhr_tracker import XHRTracker


def main() -> int:
    return run_user_session_export()


__all__ = [
    "CHROMIUM_EPOCH",
    "DEFAULT_NETWORK_WAIT_MS",
    "INTER_ACCOUNT_COOLDOWN_SECONDS",
    "MAX_ACCOUNT_HITS_PER_RUN",
    "SessionArtifacts",
    "XHRTracker",
    "build_output_dir",
    "export_account_session",
    "export_configured_sessions",
    "main",
    "run_user_session_export",
]


if __name__ == "__main__":
    raise SystemExit(main())
