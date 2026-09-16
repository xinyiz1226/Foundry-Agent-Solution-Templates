from contextlib import redirect_stdout
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.import_abcd import main, normalize_file
from information_extraction.abcd import MAX_INPUT_BYTES
from information_extraction.contracts import InvalidInput
from tests.test_abcd import FIXTURE


class ABCDImportScriptTests(unittest.TestCase):
    def test_plain_and_gzip_files_export_same_documents_without_labels(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            compressed = root / "sample.json.gz"
            compressed.write_bytes(gzip.compress(FIXTURE.read_bytes(), mtime=0))
            results = []
            for name, source in (("plain", FIXTURE), ("gzip", compressed)):
                output = root / f"{name}.json"
                with patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
                    result = normalize_file(source, output, split="train")
                document = json.loads(output.read_bytes())
                self.assertEqual(result["documents"], 2)
                self.assertEqual(result["dialogue_blocks"], 7)
                self.assertEqual(result["excluded_action_turns"], 1)
                self.assertFalse(result["extraction_performed"])
                self.assertEqual(result["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
                self.assertEqual(document["source_file_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
                self.assertFalse(document["training_labels_imported"])
                self.assertNotIn("HIDDEN_", output.read_text())
                self.assertNotIn("hidden_resolution", output.read_text())
                results.append(document["documents"])
            self.assertEqual(*results)
            self.assertFalse(list(root.glob("*.tmp")))

    def test_existing_output_and_input_are_never_overwritten(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "existing.json"
            path.write_bytes(FIXTURE.read_bytes())
            original = path.read_bytes()
            for source in (FIXTURE, path):
                with self.assertRaises(FileExistsError):
                    normalize_file(source, path, split="train")
                self.assertEqual(path.read_bytes(), original)
            self.assertEqual(sorted(item.name for item in path.parent.iterdir()), ["existing.json"])

    def test_publish_race_preserves_other_writer_and_removes_temporary_file(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"

            def other_writer(*_):
                output.write_bytes(b"other-writer")
                raise FileExistsError

            with patch("scripts.import_abcd.os.link", side_effect=other_writer):
                with self.assertRaises(FileExistsError):
                    normalize_file(FIXTURE, output, split="train")
            self.assertEqual(output.read_bytes(), b"other-writer")
            self.assertEqual(list(output.parent.iterdir()), [output])

    def test_invalid_input_and_compressed_size_limit_publish_nothing(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for payload in (b"private-input", b" " * (MAX_INPUT_BYTES + 1)):
                source = root / "input.json.gz"
                source.write_bytes(gzip.compress(payload))
                output = root / "not-created" / "output.json"
                with self.assertRaises(InvalidInput):
                    normalize_file(source, output, split="train")
                self.assertFalse(output.parent.exists())

    def test_cli_errors_are_explicit_and_do_not_echo_private_data(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.json.gz"
            invalid_deflate = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03\x07" + b"\x00" * 8
            for payload in (b"private-corrupt-gzip", invalid_deflate, gzip.compress(b"[]")[:-5]):
                source.write_bytes(payload)
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    code = main(["--input", str(source), "--output", str(root / "out.json"), "--split", "train"])
                self.assertEqual(code, 1)
                self.assertEqual(json.loads(stdout.getvalue()), {"error": "abcd_file_read_or_publish_failed"})
                self.assertNotIn("private-corrupt-gzip", stdout.getvalue())
                self.assertFalse((root / "out.json").exists())

    def test_cli_success_and_existing_output_have_machine_readable_results(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "out.json"
            arguments = ["--input", str(FIXTURE), "--output", str(output), "--split", "train"]
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(arguments)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["documents"], 2)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(arguments)
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(stdout.getvalue()), {"error": "abcd_output_exists"})

    def test_non_regular_link_and_network_paths_are_rejected_before_read(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(InvalidInput, "regular_input_file_required"):
                normalize_file(root, root / "out.json", split="train")
            for method in ("is_symlink", "is_junction"):
                with self.subTest(method=method), patch(f"pathlib.Path.{method}", return_value=True):
                    with self.assertRaisesRegex(InvalidInput, "link_path_not_supported"):
                        normalize_file(FIXTURE, root / "out.json", split="train")
            if os.name == "nt":
                with self.assertRaisesRegex(InvalidInput, "network_path_not_supported"):
                    normalize_file(Path(r"\\server\share\input.json"), root / "out.json", split="train")
            self.assertFalse((root / "out.json").exists())
