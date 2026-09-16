"""Fresh-process import contracts: pytest's warmed sys.modules cannot hide cycles."""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def run_python(code):
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("module", [
    "src.infrastructure.browser.playwright_session",
    "src.infrastructure.browser.page_objects.dashboard_page",
    "src.infrastructure.browser.page_objects.customer_update_page",
    "src.application.models.customer_workflow",
    "src.application.services.transaction_prechecks",
    "src.application.services.account_runner",
    "src.orchestration.transaction_processor",
    "src.orchestration.browser_session",
    "src.web.pages.dashboard",
    "src.web.reporter",
    "src.pipelines.solve_slider",
    "src.pipelines.slider",
])
def test_direct_module_import_in_fresh_process(module):
    run_python(f"import importlib; importlib.import_module({module!r})")


@pytest.mark.parametrize("first_module", [
    "src.application", "src.infrastructure.browser", "src.orchestration", "src.web.pages",
])
def test_public_exports_and_identity_after_different_import_orders(first_module):
    run_python(f"import importlib; importlib.import_module({first_module!r})\n" + textwrap.dedent('''
        import importlib
        import src.application as application

        expected = {
            "AccountRunContext": "src.application.dto.run_context",
            "RunContext": "src.application.dto.run_context",
            "AccountRunner": "src.application.services.account_runner",
            "PuzzleService": "src.application.services.puzzle_service",
            "PuzzleSolveOutcome": "src.application.services.puzzle_service",
            "SessionRecoveryService": "src.application.services.session_recovery",
            "TransactionPrechecksService": "src.application.services.transaction_prechecks",
            "build_output_dir": "src.application.use_cases.export_session",
            "export_configured_sessions": "src.application.use_cases.export_session",
            "run_user_session_export": "src.application.use_cases.export_session",
            "process_account": "src.application.use_cases.process_account",
            "process_accounts": "src.application.use_cases.process_account",
        }
        assert set(application.__all__) == set(expected)
        assert {"AccountRunner", "TransactionPrechecksService", "PuzzleService"} <= set(dir(application))
        exported = {}
        exec("from src.application import *", exported)
        for name, path in expected.items():
            canonical = getattr(importlib.import_module(path), name)
            assert exported[name] is canonical
            assert getattr(application, name) is canonical
        try:
            application.not_a_taskbot_export
        except AttributeError:
            pass
        else:
            raise AssertionError("Unknown export must raise AttributeError")

        from src.infrastructure.browser.playwright_session import BrowserSession, PlaywrightSession
        from src.orchestration.browser_session import BrowserSession as legacy_session
        from src.orchestration import BrowserSession as package_session, TransactionProcessor
        from src.orchestration.transaction_processor import TransactionProcessor as canonical_processor
        import src.infrastructure.browser as browser
        assert BrowserSession is PlaywrightSession is legacy_session is package_session is browser.BrowserSession
        assert browser.PlaywrightSession is PlaywrightSession
        assert TransactionProcessor is canonical_processor

        import src.web.pages as legacy_pages
        import src.infrastructure.browser.page_objects as pages
        for name, filename in {
            "BasePage": "base_page", "CekPenjualan": "cek_penjualan",
            "Dashboard": "dashboard", "Login": "login", "Penjualan": "penjualan",
        }.items():
            legacy = getattr(importlib.import_module("src.web.pages." + filename), name)
            assert legacy is getattr(pages, name) is getattr(legacy_pages, name) is getattr(browser, name)

        import src.web as web
        from src.web.reporter import TransactionReporter
        assert web.TransactionReporter is TransactionReporter
        import src.pipelines.solve_slider as legacy_slider
        import src.pipelines.slider as slider
        providers = {
            "BoundingBoxes": "types", "CoordinateMapping": "types",
            "SliderConfig": "types", "SliderElements": "types",
            "SliderSolver": "solver", "solve_slider_with_puzzle": "solver",
            "CoordinateMapper": "coordinates", "DiagramCreator": "artifacts",
            "MetadataWriter": "artifacts", "DragExecutor": "execution",
            "ElementResolver": "elements", "MaskProcessor": "mask",
            "MovementGenerator": "movement", "SuccessDetector": "success",
        }
        assert set(legacy_slider.__all__) == set(providers)
        for name, provider in providers.items():
            canonical = getattr(importlib.import_module("src.pipelines.slider." + provider), name)
            assert getattr(legacy_slider, name) is canonical
            if name in slider.__all__:
                assert getattr(slider, name) is canonical
    '''))


@pytest.mark.parametrize("path", [
    "tests/unit/test_playwright_session.py",
    "tests/unit/test_dashboard_nib.py",
    "tests/unit/test_customer_data_close_wrapper.py",
    "tests/unit/test_customer_workflow.py",
])
def test_isolated_pytest_collection(path):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", path, "--collect-only", "-q"],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_importing_application_model_does_not_eagerly_initialize_services():
    run_python('''
        import sys
        from src.application.models.customer_workflow import CustomerUpdateData
        assert "src.application.services" not in sys.modules
        assert "src.infrastructure.browser" not in sys.modules
        from src.application import AccountRunner
        from src.application.services.account_runner import AccountRunner as canonical
        assert AccountRunner is canonical
    ''')
