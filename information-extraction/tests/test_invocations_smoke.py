import json
from pathlib import Path
import subprocess
import sys
import unittest

from tests.test_hosted_app import INVOCATIONS_AVAILABLE


@unittest.skipUnless(INVOCATIONS_AVAILABLE, "optional Invocations SDK not installed")
class InvocationsSmokeTests(unittest.TestCase):
    def test_bounded_public_invocations_smoke_and_temporary_state_cleanup(self):
        before = set(Path(".test-data").glob("invocations-smoke-*"))
        result = subprocess.run(
            [sys.executable, str(Path("scripts") / "invocations_smoke.py")],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "lifecycle": "InvocationAgentServerHost",
            "transport": "in_process_asgi",
            "provider": "native-local-file",
            "first_round": "limited",
            "final_round": "completed",
            "revision": 2,
            "synthetic_model_calls": 2,
            "real_model_calls": 0,
            "cloud_recovery_verified": False,
        })
        self.assertEqual(set(Path(".test-data").glob("invocations-smoke-*")), before)
