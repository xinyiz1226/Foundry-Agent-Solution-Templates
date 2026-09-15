import hashlib
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts.package_source import ALLOWED_FILES, PackageError, build_package
from tests.test_hosted_app import INVOCATIONS_AVAILABLE


class SourcePackageTests(unittest.TestCase):
    def setUp(self):
        Path(".test-data").mkdir(exist_ok=True)
        self.directory = Path(self.enterContext(TemporaryDirectory(dir=".test-data")))
        self.project = Path(__file__).resolve().parents[1]

    def test_source_zip_is_deterministic_and_contains_only_the_explicit_allowlist(self):
        first = self.directory / "first.zip"
        second = self.directory / "second.zip"
        result = build_package(self.project, first)
        repeated = build_package(self.project, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(result["sha256"], hashlib.sha256(first.read_bytes()).hexdigest())
        self.assertEqual(result["sha256"], repeated["sha256"])
        with ZipFile(first) as archive:
            self.assertEqual(set(archive.namelist()), {
                "main.py", "requirements.txt", "pyproject.toml",
                "src/information_extraction/__init__.py",
                "src/information_extraction/batch.py",
                "src/information_extraction/blob_store.py",
                "src/information_extraction/codec.py",
                "src/information_extraction/contracts.py",
                "src/information_extraction/execution.py",
                "src/information_extraction/hosted_app.py",
                "src/information_extraction/hosted_lifecycle.py",
                "src/information_extraction/native_batch.py",
                "src/information_extraction/sample.py",
                "src/information_extraction/sqlite_store.py",
            })
            self.assertEqual(archive.namelist(), sorted(archive.namelist()))
            self.assertEqual(archive.read("requirements.txt").decode("utf-8").splitlines(), [".[hosted]"])
            for member in archive.infolist():
                self.assertEqual(member.date_time, (1980, 1, 1, 0, 0, 0))

    def test_unlisted_private_files_are_not_packaged_and_missing_sources_fail_closed(self):
        source = self.directory / "source"
        source.mkdir()
        for name in ALLOWED_FILES:
            relative = Path(name)
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.project / relative, target)
        (source / ".env").write_text("secret=must-not-ship", encoding="utf-8")
        (source / "customer-document.txt").write_text("private document", encoding="utf-8")
        result = build_package(source, self.directory / "only-allowed.zip")
        self.assertNotIn("secret", str(result))
        with ZipFile(self.directory / "only-allowed.zip") as archive:
            self.assertNotIn(".env", archive.namelist())
            self.assertNotIn("customer-document.txt", archive.namelist())
        (source / "main.py").unlink()
        with self.assertRaisesRegex(PackageError, "^source_file_missing$"):
            build_package(source, self.directory / "missing.zip")
        self.assertFalse((self.directory / "missing.zip").exists())

    @unittest.skipUnless(INVOCATIONS_AVAILABLE, "optional Invocations SDK not installed")
    def test_packaged_wheel_and_entrypoint_import_without_ambient_pythonpath_or_network(self):
        from scripts.package_source import check_package

        artifact = self.directory / "agent.zip"
        build_package(self.project, artifact)
        poison = self.directory / "poison" / "information_extraction"
        poison.mkdir(parents=True)
        (poison / "__init__.py").write_text(
            'raise RuntimeError("ambient_workspace_imported")\n', encoding="utf-8",
        )
        with patch.dict(os.environ, {"PYTHONPATH": str(poison.parent)}):
            result = check_package(artifact)
        self.assertEqual(result, {
            "wheel_built": True,
            "entrypoint_imported": True,
            "isolated": True,
            "network_calls": 0,
            "core_version": "2.1.0",
            "invocations_version": "1.1.0",
        })
        self.assertEqual(list(self.directory.glob("package-check-*")), [])

    def test_package_refuses_source_links_and_oversized_files(self):
        source = self.directory / "source"
        source.mkdir()
        for relative in ALLOWED_FILES:
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.project / relative, target)
        entrypoint = source / "main.py"
        entrypoint.write_bytes(b"x" * (1024 * 1024 + 1))
        with self.assertRaisesRegex(PackageError, "^source_size_limit_exceeded$"):
            build_package(source, self.directory / "oversized.zip")
        entrypoint.unlink()
        outside = self.directory / "outside.py"
        outside.write_text("private = True\n", encoding="utf-8")
        try:
            entrypoint.symlink_to(outside.resolve())
        except OSError:
            self.skipTest("creating symlinks is not permitted on this host")
        with self.assertRaisesRegex(PackageError, "^links_not_allowed$"):
            build_package(source, self.directory / "linked.zip")
        self.assertFalse((self.directory / "linked.zip").exists())
        self.assertEqual(outside.read_text(encoding="utf-8"), "private = True\n")

    def test_package_refuses_artifact_inside_tracked_source(self):
        with self.assertRaisesRegex(PackageError, "^artifact_path_must_be_outside_source$"):
            build_package(self.project, self.project / "src" / "must-not-create.zip")
        self.assertFalse((self.project / "src" / "must-not-create.zip").exists())

    def test_package_check_rejects_unlisted_archive_content_before_building(self):
        from scripts.package_source import check_package
        artifact = self.directory / "extra.zip"
        build_package(self.project, artifact)
        with ZipFile(artifact, "a") as archive:
            archive.writestr("credentials.txt", "must-not-import")
        with self.assertRaisesRegex(PackageError, "^archive_allowlist_mismatch$"):
            check_package(artifact)
        self.assertEqual(list(self.directory.glob("package-check-*")), [])
