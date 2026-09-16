import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.prepare_workbench_acceptance import prepare


class PreparationTests(unittest.TestCase):
    def test_fresh_manifests_are_disjoint_and_do_not_touch_history(self):
        with TemporaryDirectory() as directory:
            parent = Path(directory)
            historical = parent / "historical-ledger"
            historical.write_bytes(b"preserve historical bytes")
            with (
                patch("socket.socket.connect", side_effect=AssertionError("network forbidden")),
                patch("subprocess.Popen", side_effect=AssertionError("process forbidden")),
            ):
                paths = [prepare(parent), prepare(parent)]
            manifests = [json.loads(path.read_text()) for path in paths]
            self.assertEqual(historical.read_bytes(), b"preserve historical bytes")
            bindings = [scenario["hosted_environment"] for manifest in manifests for scenario in manifest["scenarios"]]
            self.assertEqual(len({binding["EXTRACTION_JOB_ID"] for binding in bindings}), 4)
            self.assertEqual(len({binding["EXTRACTION_BLOB_PREFIX"] for binding in bindings}), 4)
            for manifest in manifests:
                self.assertFalse(manifest["azure_changes_performed"])
                self.assertFalse(manifest["cloud_execution_authorized"])
                self.assertTrue(manifest["synthetic_only"])
                self.assertEqual([s["round_attempt_allowances"] for s in manifest["scenarios"]], [[1, 1], [2]])
                self.assertEqual(manifest["future_cloud_window"]["max_total_committed_attempts"], 4)
                self.assertEqual(manifest["future_cloud_window"]["real_model_calls"], 0)
                for scenario in manifest["scenarios"]:
                    self.assertFalse(Path(scenario["local_state_dir"]).exists())
                    self.assertEqual(scenario["round_duration_seconds"], 120)
                    self.assertEqual(scenario["expected_final_revision"], 2)

    def test_collision_never_overwrites_existing_manifest(self):
        with TemporaryDirectory() as directory, patch("scripts.prepare_workbench_acceptance.uuid4") as identity:
            identity.return_value.hex = "a" * 32
            path = prepare(Path(directory))
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                prepare(Path(directory))
            self.assertEqual(path.read_bytes(), original)
