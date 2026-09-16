from argparse import Namespace
from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.run_configured_workbench import environment, main, prepare_state


class ConfiguredLauncherTests(unittest.TestCase):
    def test_environment_is_local_and_has_no_openai_key_or_implicit_azure_profile(self):
        args = Namespace(state_dir=Path("state"), backend_port=8766, real_model=False, azure_config_dir=None)
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "private-test-value", "OPENAI_LOG": "debug",
            "AZURE_CONFIG_DIR": "unselected-profile", "FOUNDRY_HOSTING_ENVIRONMENT": "production",
        }):
            value = environment(args, "x" * 43)
        self.assertNotIn("OPENAI_API_KEY", value)
        self.assertNotIn("OPENAI_LOG", value)
        self.assertNotIn("AZURE_CONFIG_DIR", value)
        self.assertEqual(value["AGENTSERVER_TASKS_BACKEND"], "local")
        self.assertEqual(value["FOUNDRY_HOSTING_ENVIRONMENT"], "")
        self.assertEqual(value["INFORMATION_EXTRACTION_CONFIGURED_BACKEND_URL"], "http://127.0.0.1:8766")
        self.assertEqual(value["INFORMATION_EXTRACTION_CONFIGURED_TOKEN"], "x" * 43)
        args.real_model, args.azure_config_dir = True, Path("explicit-profile")
        self.assertEqual(environment(args, "x" * 43)["AZURE_CONFIG_DIR"], "explicit-profile")

    def test_real_mode_requires_explicit_configuration_before_state_creation(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "not-created"
            with self.assertRaises(SystemExit), patch("sys.stderr"):
                main(["--real-model", "--state-dir", str(target)])
            self.assertFalse(target.exists())

    def test_prepare_only_default_and_direct_script_entrypoint(self):
        with TemporaryDirectory() as directory:
            with patch("scripts.run_configured_workbench.launch") as launch:
                self.assertEqual(main(["--state-dir", directory]), 0)
            self.assertFalse(launch.call_args.args[0].real_model)
        script = Path(__file__).resolve().parents[1] / "scripts" / "run_configured_workbench.py"
        result = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--real-model", result.stdout)
        self.assertNotIn("private-test-value", result.stdout)

    def test_state_marker_preserves_owned_state_and_rejects_foreign_native_state(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            foreign = root / "old-workbench"
            foreign.mkdir()
            (foreign / "native-state").mkdir()
            with self.assertRaises(RuntimeError):
                prepare_state(foreign)
            self.assertFalse((foreign / ".configured-workbench-v1").exists())
            owned = root / "new-workbench"
            prepare_state(owned)
            retained = owned / "retained.sqlite3"
            retained.write_bytes(b"retained")
            prepare_state(owned)
            self.assertEqual(retained.read_bytes(), b"retained")
