import importlib


def test_main_entrypoint_import_smoke():
    module = importlib.import_module("main")

    assert callable(module.main)
    assert callable(module.run_account)


def test_user_sessions_entrypoint_import_smoke():
    module = importlib.import_module("user_sessions")

    assert callable(module.main)
    assert callable(module.run_user_session_export)
