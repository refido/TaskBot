from src.application.dto import AccountRunContext, RunContext

# Importing an application model must not eagerly import services that depend
# on the page object currently importing that model.
_SERVICE_EXPORTS = {
    "AccountRunner",
    "PuzzleService",
    "PuzzleSolveOutcome",
    "SessionRecoveryService",
    "TransactionPrechecksService",
}

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
    if name in _SERVICE_EXPORTS:
        from src.application import services

        return getattr(services, name)
    if name in _USE_CASE_EXPORTS:
        from src.application import use_cases

        return getattr(use_cases, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(__all__))
