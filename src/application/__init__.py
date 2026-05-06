from src.application.dto import AccountRunContext, RunContext
from src.application.services import (
    AccountRunner,
    PuzzleService,
    PuzzleSolveOutcome,
    SessionRecoveryService,
    TransactionPrechecksService,
)

_USE_CASE_EXPORTS = {
    "build_output_dir",
    "export_configured_sessions",
    "process_account",
    "process_accounts",
    "run_user_session_export",
}

__all__ = [
    "AccountRunContext",
    "AccountRunner",
    "PuzzleService",
    "PuzzleSolveOutcome",
    "RunContext",
    "SessionRecoveryService",
    "TransactionPrechecksService",
    "build_output_dir",
    "export_configured_sessions",
    "process_account",
    "process_accounts",
    "run_user_session_export",
]


def __getattr__(name: str):
    if name in _USE_CASE_EXPORTS:
        from src.application import use_cases

        return getattr(use_cases, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
