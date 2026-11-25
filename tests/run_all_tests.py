#!/usr/bin/env python
"""
Comprehensive Test Runner for Startup Idea Validator AI
Runs all unit and integration test suites:
- Database CRUD & constraint tests
- AI Agent tests (all 8 agents)
- Orchestration pipeline tests
- ReportLab PDF generation tests
- Flask routes tests (all 13 pages, auth, API endpoints, exports)
"""

import unittest
import sys
import os

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.test_db import DatabaseTestCase
from tests.test_agents import AgentsTestCase
from tests.test_orchestrator import OrchestratorTestCase
from tests.test_pdf import PDFReportTestCase
from tests.test_routes import RoutesTestCase
import tests.test_core as _core
import tests.test_pipeline as _pipeline
import tests.test_app as _app
import tests.test_improvements as _improve
import tests.test_any_idea as _anyidea
import tests.test_sizing_fix as _sizing
import tests.test_token_limits as _tokens

def suite():
    loader = unittest.TestLoader()
    test_suite = unittest.TestSuite()
    test_suite.addTest(loader.loadTestsFromTestCase(DatabaseTestCase))
    test_suite.addTest(loader.loadTestsFromTestCase(AgentsTestCase))
    test_suite.addTest(loader.loadTestsFromTestCase(OrchestratorTestCase))
    test_suite.addTest(loader.loadTestsFromTestCase(PDFReportTestCase))
    test_suite.addTest(loader.loadTestsFromTestCase(RoutesTestCase))
    for mod in (_core, _pipeline, _app, _improve, _anyidea, _sizing, _tokens):
        test_suite.addTests(loader.loadTestsFromModule(mod))
    return test_suite

if __name__ == "__main__":
    print("\n========================================================")
    print("  RUNNING ALL TESTS: STARTUP IDEA VALIDATOR AI")
    print("========================================================\n")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite())

    print("\n========================================================")
    if result.wasSuccessful():
        print(f"  SUCCESS! All {result.testsRun} tests passed without errors.")
        print("========================================================\n")
        sys.exit(0)
    else:
        print(f"  FAILURE: {len(result.failures)} failures, {len(result.errors)} errors out of {result.testsRun} tests.")
        print("========================================================\n")
        sys.exit(1)
