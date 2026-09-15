import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.adaptive_cli import main
from analysis.model_client import ReplayClient
from test_adaptive import BoundaryClient, response


class AdaptiveCliTests(unittest.TestCase):
    def setUp(self):
        self.output = ROOT / ".artifacts" / ("adaptive-cli-test-" + uuid4().hex)
        self.addCleanup(lambda: shutil.rmtree(self.output, ignore_errors=True))
        self.args = [
            "--csv", str(ROOT / "evaluation" / "worked_sales.csv"),
            "--config", str(ROOT / "evaluation" / "worked-example.json"),
            "--output", str(self.output),
        ]

    def test_offline_default_needs_no_credentials_or_network(self):
        with patch("socket.socket", side_effect=AssertionError("Network forbidden")), contextlib.redirect_stdout(io.StringIO()):
            status = main(self.args)
        self.assertEqual(status, 0)
        report = json.loads((self.output / "evaluation.json").read_text(encoding="utf-8"))
        self.assertEqual(report["execution_kind"], "replay_harness_only")
        self.assertEqual(report["adaptive"]["metrics"]["model_inference_requests"], 0)
        self.assertEqual(report["adaptive"]["metrics"]["scope"]["selected_territory_ids"], ["10"])

    def test_inference_requires_explicit_approval_and_injected_identity_and_client(self):
        for extra, kwargs in (
            ([], {"client": ReplayClient([{"name": "compare", "arguments": {"filters": {}}}]),
                  "model": "deepseek", "caller_identity": "test-caller"}),
            (["--approve-model-inference"], {}),
            (["--approve-model-inference"], {"client": object(), "model": "deepseek"}),
        ):
            with self.subTest(extra=extra, kwargs=kwargs), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(self.args + extra, **kwargs), 2)
        self.assertFalse(self.output.exists())

    def test_approved_inference_path_accepts_only_caller_supplied_configuration(self):
        client = BoundaryClient([
            response(),
            response("finish", '{"result_ids":["r1"],"evidence_ids":["q1","q2"],"stop_reason":"complete"}', "call_2"),
        ])
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(self.args + ["--approve-model-inference", "--question", "Compare profit"],
                        client=client, model="external-boundary-double", caller_identity="test-identity-not-a-token")
        self.assertEqual(code, 0)
        self.assertEqual(client.requests[0]["model"], "external-boundary-double")
        self.assertNotIn("test-identity-not-a-token", json.dumps(client.requests))
        report = json.loads((self.output / "evaluation.json").read_text(encoding="utf-8"))
        self.assertTrue(report["authorization"]["model_inference_explicitly_approved"])
        self.assertFalse(report["authorization"]["cloud_deployment_approved"])


if __name__ == "__main__":
    unittest.main()
