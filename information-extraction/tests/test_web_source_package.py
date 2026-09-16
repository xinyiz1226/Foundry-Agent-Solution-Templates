import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts.package_source import PackageError, WEB_ALLOWED_FILES, build_package, check_package


try:
    for package in ("setuptools", "streamlit", "httpx", "PyJWT", "azure-identity", "cryptography"):
        importlib.metadata.version(package)
    CLOUD_AVAILABLE = True
except importlib.metadata.PackageNotFoundError:
    CLOUD_AVAILABLE = False


class WebSourcePackageTests(unittest.TestCase):
    def setUp(self):
        Path(".test-data").mkdir(exist_ok=True)
        self.directory = Path(self.enterContext(TemporaryDirectory(dir=".test-data"))).resolve()
        self.project = Path(__file__).resolve().parents[1]
        self.artifact = self.directory / "web.zip"

    def copy_source(self):
        source = self.directory / "source"
        for relative in WEB_ALLOWED_FILES:
            relative = Path("requirements-web.txt") if relative == Path("requirements.txt") else relative
            destination = source / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.project / relative, destination)
        return source

    def test_web_is_deterministic_and_maps_only_its_own_requirements(self):
        source = self.copy_source()
        for name in (
            "requirements.txt", "main.py", "workbench.py", ".env", "private.txt",
            ".local-data/private.json", ".test-data/private.json", ".venv/secret",
            "docs/private.md", "tests/test_private.py", "scripts/run_workbench.py",
            "src/information_extraction/hosted_app.py", "src/information_extraction/native_batch.py",
            "src/information_extraction/blob_store.py", "src/information_extraction/foundry_model.py",
        ):
            private = source / name
            private.parent.mkdir(parents=True, exist_ok=True)
            private.write_text("must-not-ship", encoding="utf-8")
        first = build_package(source, self.artifact, target="web")
        second_path = self.directory / "again.zip"
        second = build_package(source, second_path, target="web")
        self.assertEqual(self.artifact.read_bytes(), second_path.read_bytes())
        self.assertEqual(first["sha256"], hashlib.sha256(self.artifact.read_bytes()).hexdigest())
        self.assertEqual(first["sha256"], second["sha256"])
        with ZipFile(self.artifact) as archive:
            self.assertEqual(set(archive.namelist()), {
                "cloud_workbench.py", "requirements.txt", "pyproject.toml",
                "src/information_extraction/__init__.py",
                "src/information_extraction/batch.py",
                "src/information_extraction/codec.py",
                "src/information_extraction/contracts.py",
                "src/information_extraction/execution.py",
                "src/information_extraction/sample.py",
                "src/information_extraction/sqlite_store.py",
                "src/information_extraction/cloud_workbench_client.py",
                "src/information_extraction/workbench_auth.py",
                "src/information_extraction/workbench_client.py",
                "src/information_extraction/workbench_cloud.py",
                "src/information_extraction/workbench_ui.py",
                "src/information_extraction/legacy_financial.py",
                "src/information_extraction/outputs.py",
                "src/information_extraction/schema.py",
            })
            self.assertEqual(archive.namelist(), sorted(archive.namelist()))
            self.assertEqual(archive.read("requirements.txt"), (source / "requirements-web.txt").read_bytes())
            self.assertEqual(archive.read("requirements.txt").decode().splitlines(), [".[cloud-workbench]"])
            for member in archive.infolist():
                self.assertEqual(member.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertNotIn(b"must-not-ship", archive.read(member))

    def test_missing_or_wrong_web_manifest_does_not_fall_back_to_hosted(self):
        source = self.copy_source()
        manifest = source / "requirements-web.txt"
        (source / "requirements.txt").write_text(".[hosted]\n", encoding="utf-8")
        manifest.unlink()
        with self.assertRaisesRegex(PackageError, "^source_file_missing$"):
            build_package(source, self.artifact, target="web")
        manifest.write_text(".[hosted]\n", encoding="utf-8")
        with self.assertRaisesRegex(PackageError, "^web_requirements_mismatch$"):
            build_package(source, self.artifact, target="web")
        self.assertFalse(self.artifact.exists())

    def test_web_entry_and_mapped_manifest_use_shared_source_safety_checks(self):
        source = self.copy_source()
        entry = source / "cloud_workbench.py"
        entry.unlink()
        with self.assertRaisesRegex(PackageError, "^source_file_missing$"):
            build_package(source, self.artifact, target="web")
        shutil.copyfile(self.project / "cloud_workbench.py", entry)
        manifest = source / "requirements-web.txt"
        manifest.write_bytes(b"x" * (1024 * 1024 + 1))
        with self.assertRaisesRegex(PackageError, "^source_size_limit_exceeded$"):
            build_package(source, self.artifact, target="web")
        manifest.unlink()
        try:
            manifest.symlink_to(self.project / "requirements-web.txt")
        except OSError:
            self.skipTest("creating symlinks is not permitted on this host")
        with self.assertRaisesRegex(PackageError, "^links_not_allowed$"):
            build_package(source, self.artifact, target="web")
        self.assertFalse(self.artifact.exists())

    def test_target_selection_is_explicit_and_rejects_cross_target_archives(self):
        with self.assertRaisesRegex(PackageError, "^unknown_package_target$"):
            build_package(self.project, self.artifact, target="everything")
        with self.assertRaisesRegex(PackageError, "^unknown_package_target$"):
            check_package(self.artifact, target="everything")
        build_package(self.project, self.artifact, target="web")
        with self.assertRaisesRegex(PackageError, "^archive_allowlist_mismatch$"):
            check_package(self.artifact)
        build_package(self.project, self.artifact)
        with self.assertRaisesRegex(PackageError, "^archive_allowlist_mismatch$"):
            check_package(self.artifact, target="web")

    def test_check_rejects_hosted_local_and_private_extras_before_building(self):
        for name in (
            "main.py", "workbench.py", ".env", "../private.txt",
            "src/information_extraction/hosted_app.py",
            "src/information_extraction/native_batch.py",
            "src/information_extraction/blob_store.py",
            "src/information_extraction/foundry_model.py",
        ):
            with self.subTest(name=name):
                build_package(self.project, self.artifact, target="web")
                with ZipFile(self.artifact, "a") as archive:
                    archive.writestr(name, "must-not-import")
                with self.assertRaisesRegex(PackageError, "^archive_allowlist_mismatch$"):
                    check_package(self.artifact, target="web")
        self.assertEqual(list(self.directory.glob("package-check-*")), [])

    def test_check_rejects_wrong_requirements_even_with_exact_allowlist(self):
        build_package(self.project, self.artifact, target="web")
        changed = self.directory / "changed.zip"
        with ZipFile(self.artifact) as original, ZipFile(changed, "w") as archive:
            for entry in original.infolist():
                archive.writestr(
                    entry, b".[hosted]\n" if entry.filename == "requirements.txt" else original.read(entry),
                )
        with self.assertRaisesRegex(PackageError, "^web_requirements_mismatch$"):
            check_package(changed, target="web")

    def test_cli_selects_web_and_reports_archive(self):
        completed = subprocess.run(
            [sys.executable, str(self.project / "scripts" / "package_source.py"),
             "--target", "web", "--output", str(self.artifact)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(len(result["files"]), 18)
        self.assertEqual(result["sha256"], hashlib.sha256(self.artifact.read_bytes()).hexdigest())

    @unittest.skipUnless(CLOUD_AVAILABLE, "optional cloud-workbench dependencies unavailable")
    def test_real_wheel_page_blocks_missing_login_without_network_or_services(self):
        build_package(self.project, self.artifact, target="web")
        poison = self.directory / "poison" / "information_extraction"
        poison.mkdir(parents=True)
        (poison / "__init__.py").write_text('raise RuntimeError("ambient_source")\n', encoding="utf-8")
        with patch.dict(os.environ, {
            "PYTHONPATH": str(poison.parent),
            "INFORMATION_EXTRACTION_WEB_TENANT_ID": "00000000-0000-0000-0000-000000000001",
            "INFORMATION_EXTRACTION_WEB_CLIENT_ID": "00000000-0000-0000-0000-000000000002",
            "INFORMATION_EXTRACTION_WEB_OPERATOR_ID": "00000000-0000-0000-0000-000000000003",
            "INFORMATION_EXTRACTION_PROJECT_ENDPOINT": "https://must-not-call.services.ai.azure.com/api/projects/test",
            "INFORMATION_EXTRACTION_AGENT_NAME": "must-not-call",
        }):
            result = check_package(self.artifact, target="web")
        self.assertEqual(result, {
            "wheel_built": True, "entrypoint_imported": True, "isolated": True,
            "network_calls": 0, "target": "web", "login_configuration_blocked": True,
            "service_calls": 0, "streamlit_version": importlib.metadata.version("streamlit"),
        })
        self.assertEqual(list(self.directory.glob("package-check-*")), [])

    @unittest.skipUnless(CLOUD_AVAILABLE, "optional cloud-workbench dependencies unavailable")
    def test_check_cannot_use_ambient_source_to_hide_an_empty_wheel(self):
        source = self.copy_source()
        metadata = source / "pyproject.toml"
        metadata.write_text(
            metadata.read_text(encoding="utf-8").replace(
                'include = ["information_extraction*"]', 'include = ["not_shipped*"]',
            ), encoding="utf-8",
        )
        build_package(source, self.artifact, target="web")
        with self.assertRaises(PackageError):
            check_package(self.artifact, target="web")
        self.assertEqual(list(self.directory.glob("package-check-*")), [])

    @unittest.skipUnless(CLOUD_AVAILABLE, "optional cloud-workbench dependencies unavailable")
    def test_check_imports_lazy_cloud_transport_too(self):
        source = self.copy_source()
        transport = source / "src" / "information_extraction" / "cloud_workbench_client.py"
        transport.write_text(
            transport.read_text(encoding="utf-8") + "\nfrom .missing_transport import Client\n",
            encoding="utf-8",
        )
        build_package(source, self.artifact, target="web")
        with self.assertRaisesRegex(PackageError, "^package_check_missing_dependency:information_extraction.missing_transport$"):
            check_package(self.artifact, target="web")
