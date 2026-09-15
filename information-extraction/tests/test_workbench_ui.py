"""Exercise the page through Streamlit and its external HTTP boundary."""

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest
from unittest.mock import patch

from tests.test_workbench_client import ROUND


PAGE = Path(__file__).resolve().parents[1] / "workbench.py"


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "optional workbench dependencies unavailable")
class WorkbenchPageTests(unittest.TestCase):
    def setUp(self):
        self.commands = []
        self.projection = None
        self.pending = None
        self.status = 200
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.commands.append(request)
                if request["action"] == "current":
                    result = {
                        "synthetic_only": True, "job_id": "synthetic-job",
                        "app_instance_id": "backend-1", "current": owner.projection,
                        "pending_request": owner.pending,
                    }
                    status = owner.status
                else:
                    owner.projection = deepcopy(ROUND)
                    owner.pending = None
                    result = {
                        "synthetic_only": True,
                        "authorization": {"request_id": request["request_id"], "run_id": "run-1"},
                    }
                    status = 202
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.environment = patch.dict(os.environ, {
            "INFORMATION_EXTRACTION_BACKEND_URL": f"http://127.0.0.1:{self.server.server_port}",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.shutdown)

    def page(self):
        from streamlit.testing.v1 import AppTest

        page = AppTest.from_file(str(PAGE), default_timeout=10).run()
        self.assertEqual(len(page.exception), 0)
        return page

    def test_start_then_reopen_restores_candidates_without_another_start(self):
        page = self.page()
        self.assertEqual(self.commands, [{"action": "current"}])
        self.assertEqual(page.number_input(key="attempts").value, 1)
        page.button(key="start").click().run()
        self.assertEqual(len(page.exception), 0)
        self.assertEqual([c["action"] for c in self.commands].count("start"), 1)
        self.assertEqual(page.table[0].value["Value"].tolist(), [120])
        self.assertTrue(any("ExampleCo revenue" in item.value for item in page.code))

        reopened = self.page()
        self.assertEqual(reopened.table[0].value["Review"].tolist(), ["Pending"])
        self.assertIn("resume", [button.key for button in reopened.button])
        self.assertEqual([c["action"] for c in self.commands].count("start"), 1)
        reopened.button(key="refresh").click().run()
        self.assertEqual([c["action"] for c in self.commands].count("start"), 1)
        reopened.button(key="resume").click().run()
        self.assertEqual(len(reopened.exception), 0)
        self.assertEqual([c["action"] for c in self.commands].count("resume"), 1)

    def test_pending_intent_is_recovered_and_only_retried_by_explicit_click(self):
        self.pending = {
            "action": "start", "job_id": "synthetic-job", "request_id": "saved-request",
            "expected_revision": 0, "max_attempts": 1, "deadline": 900,
        }
        original = deepcopy(self.pending)
        page = self.page()
        self.assertNotIn("start", [button.key for button in page.button])
        self.assertNotIn("resume", [button.key for button in page.button])
        self.assertEqual(self.commands, [{"action": "current"}])
        page = self.page()
        page.button(key="retry").click().run()
        self.assertEqual(len(page.exception), 0)
        self.assertEqual([c for c in self.commands if c["action"] != "current"], [original])

    def test_unknown_claim_is_inspection_only(self):
        self.projection = deepcopy(ROUND)
        self.projection["state"] = "in_progress_or_interrupted"
        page = self.page()
        self.assertFalse({"start", "resume", "retry"} & {button.key for button in page.button})
        self.assertTrue(any("inspection only" in item.value.lower() for item in page.error))
        self.assertEqual(self.commands, [{"action": "current"}])

    def test_backend_error_does_not_enable_start(self):
        self.status = 503
        page = self.page()
        self.assertEqual(len(page.error), 1)
        self.assertFalse({"start", "resume", "retry"} & {button.key for button in page.button})
        self.assertEqual(self.commands, [{"action": "current"}])
