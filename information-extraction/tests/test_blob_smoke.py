from contextlib import redirect_stdout
import io
import json
import unittest
from tests.test_blob_store import AZURE_AVAILABLE, Backend, FakeContainerClient


@unittest.skipUnless(AZURE_AVAILABLE, "optional Azure dependencies not installed")
class BlobSmokeTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()

    def invoke(self, action, *args):
        from scripts.blob_smoke import main
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(
                [action, "--prefix", "offline-smoke", *args],
                container_client=FakeContainerClient(self.backend),
            )
        return code, json.loads(output.getvalue())

    def test_independent_invocations_restore_fail_resume_and_historical_replay(self):
        code, created = self.invoke("create")
        self.assertEqual((code, created["revision"], created["model_calls"]), (0, 0, 0))
        code, first = self.invoke("advance", "--expected-revision", "0")
        self.assertEqual((code, first["revision"], first["model_calls"]), (0, 1, 1))
        code, inspected = self.invoke("inspect")
        self.assertNotEqual(code, 0, "partial inspection must not report full validation success")
        self.assertEqual((inspected["revision"], inspected["model_calls"]), (1, 0))
        code, failed = self.invoke("advance", "--expected-revision", "1", "--inject-failure")
        self.assertNotEqual(code, 0)
        self.assertEqual((failed["revision"], failed["status"]), (2, "failed"))
        code, completed = self.invoke("resume", "--expected-revision", "2")
        self.assertEqual((code, completed["revision"], completed["model_calls"]), (0, 3, 1))
        self.assertEqual(completed["candidates"][0], first["candidates"][0])
        code, inspected = self.invoke("inspect")
        self.assertEqual((code, inspected["snapshot_sha256"]), (0, completed["snapshot_sha256"]))
        code, replay = self.invoke("resume", "--expected-revision", "2")
        self.assertEqual((code, replay["model_calls"], replay["snapshot_sha256"]),
                         (0, 0, completed["snapshot_sha256"]))
        code, replay = self.invoke("create")
        self.assertEqual((code, replay["model_calls"], replay["snapshot_sha256"]),
                         (0, 0, created["snapshot_sha256"]))

    def test_run_finishes_and_repeats_with_no_additional_model_calls(self):
        code, result = self.invoke("run")
        self.assertEqual((code, result["revision"], result["model_calls"]), (0, 3, 3))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["attempt_count"], 3)
        self.assertEqual([item["value"] for item in result["candidates"]], [120, 18])
        code, replay = self.invoke("run")
        self.assertEqual((code, replay["snapshot_sha256"], replay["model_calls"]),
                         (0, result["snapshot_sha256"], 0))

    def test_safe_errors_do_not_echo_resource_values_or_storage_details(self):
        from scripts.blob_smoke import main
        from azure.core.exceptions import ServiceResponseError
        for argv in (
            ["not-an-action-private"],
            ["create", "--prefix", "unsafe/private"],
            ["create", "--prefix", "safe", "--account-url", "https://example.invalid/?sig=private",
             "--container", "fixture"],
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(argv)
            self.assertNotEqual(code, 0)
            self.assertNotIn("private", output.getvalue())
        self.backend.before_write = lambda name, data: (_ for _ in ()).throw(
            ServiceResponseError("private-storage-details")
        )
        code, result = self.invoke("create")
        self.assertNotEqual(code, 0)
        self.assertEqual(result, {"error": "storage_request_failed"})
