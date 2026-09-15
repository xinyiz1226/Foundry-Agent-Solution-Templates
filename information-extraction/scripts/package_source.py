"""Deterministic, explicitly allowlisted source ZIP; never deploys or authenticates."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
from zipfile import ZIP_STORED, BadZipFile, ZipFile, ZipInfo


ALLOWED_FILES = (
    Path("main.py"),
    Path("requirements.txt"),
    Path("pyproject.toml"),
    *(Path("src") / "information_extraction" / name for name in (
        "__init__.py", "batch.py", "blob_store.py", "codec.py", "contracts.py",
        "execution.py", "hosted_app.py", "hosted_lifecycle.py", "native_batch.py", "sample.py", "sqlite_store.py",
    )),
)
MAX_SOURCE_FILE_BYTES = 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 4 * 1024 * 1024


BUILD_AND_IMPORT = r"""
import contextlib
import importlib.metadata
import importlib.util
import io
from pathlib import Path
import socket
import sys
import json
from zipfile import ZipFile

network_attempts = 0

def deny_network(*args, **kwargs):
    global network_attempts
    network_attempts += 1
    raise RuntimeError("package_check_network_forbidden")

socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.socket.bind = deny_network
socket.getaddrinfo = deny_network

try:
    import setuptools.build_meta
    root = Path.cwd()
    wheels = root.parent / "wheels"
    installed = root.parent / "installed"
    wheels.mkdir()
    installed.mkdir()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        wheel_name = setuptools.build_meta.build_wheel(str(wheels))
    with ZipFile(wheels / wheel_name) as wheel:
        wheel.extractall(installed)
    sys.path.insert(0, str(installed))
    spec = importlib.util.spec_from_file_location("packaged_main", root / "main.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("entrypoint_loader_missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(module.main):
        raise RuntimeError("entrypoint_missing")
    for name, loaded in tuple(sys.modules.items()):
        if name == "information_extraction" or name.startswith("information_extraction."):
            if not Path(loaded.__file__).resolve().is_relative_to(installed.resolve()):
                raise RuntimeError("ambient_source_imported")
    if network_attempts:
        raise RuntimeError("package_check_network_attempted")
    result = {
        "wheel_built": True,
        "entrypoint_imported": True,
        "isolated": bool(sys.flags.isolated),
        "network_calls": 0,
        "core_version": importlib.metadata.version("azure-ai-agentserver-core"),
        "invocations_version": importlib.metadata.version("azure-ai-agentserver-invocations"),
    }
except ModuleNotFoundError as error:
    print(json.dumps({"error": "package_check_missing_dependency", "dependency": error.name}))
    sys.exit(1)
except Exception:
    print(json.dumps({"error": "package_check_failed"}))
    sys.exit(1)
print(json.dumps(result, sort_keys=True))
"""


class PackageError(ValueError):
    pass


def _no_links(path: Path) -> None:
    if path.drive.startswith("\\\\"):
        raise PackageError("network_paths_not_supported")
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise PackageError("links_not_allowed")


def build_package(project_root: Path, output: Path) -> dict:
    project_root, output = project_root.absolute(), output.absolute()
    _no_links(project_root)
    _no_links(output)
    project_root, output = project_root.resolve(strict=True), output.resolve()
    if output.suffix.lower() != ".zip":
        raise PackageError("zip_output_required")
    if output.is_relative_to(project_root) and output.relative_to(project_root).parts[0] not in (
        ".local-data", ".test-data",
    ):
        raise PackageError("artifact_path_must_be_outside_source")
    files = []
    total = 0
    for relative in sorted((Path(name) for name in ALLOWED_FILES), key=lambda path: path.as_posix()):
        source = project_root / relative
        _no_links(source)
        if not source.is_file():
            raise PackageError("source_file_missing")
        if not source.resolve(strict=True).is_relative_to(project_root):
            raise PackageError("source_outside_project")
        with source.open("rb") as stream:
            content = stream.read(MAX_SOURCE_FILE_BYTES + 1)
        total += len(content)
        if len(content) > MAX_SOURCE_FILE_BYTES or total > MAX_TOTAL_SOURCE_BYTES:
            raise PackageError("source_size_limit_exceeded")
        files.append((relative.as_posix(), content))
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        for name, content in files:
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_STORED
            archive.writestr(info, content)
    payload = buffer.getvalue()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=output.parent, prefix="source-package-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {
        "output": str(output),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "files": [
            {"path": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            for name, content in files
        ],
    }


def check_package(artifact: Path) -> dict:
    """Build in isolation and import the wheel's entrypoint with preinstalled SDKs."""
    artifact = artifact.absolute()
    _no_links(artifact)
    if artifact.stat().st_size > MAX_TOTAL_SOURCE_BYTES + 65536:
        raise PackageError("archive_size_limit_exceeded")
    expected = {Path(name).as_posix() for name in ALLOWED_FILES}
    with TemporaryDirectory(prefix="package-check-", dir=artifact.parent) as temporary:
        source = Path(temporary).resolve() / "source"
        source.mkdir()
        try:
            with ZipFile(artifact) as archive:
                entries = archive.infolist()
                if len(entries) != len(expected) or set(archive.namelist()) != expected:
                    raise PackageError("archive_allowlist_mismatch")
                if any(
                    entry.file_size > MAX_SOURCE_FILE_BYTES
                    or entry.compress_type != ZIP_STORED
                    or (entry.external_attr >> 16) != 0o100644
                    for entry in entries
                ) or sum(entry.file_size for entry in entries) > MAX_TOTAL_SOURCE_BYTES:
                    raise PackageError("archive_member_invalid")
                archive.extractall(source)
        except BadZipFile:
            raise PackageError("invalid_source_archive") from None
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        environment.update(PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_CONFIG_FILE=os.devnull)
        try:
            checked = subprocess.run(
                [sys.executable, "-I", "-c", BUILD_AND_IMPORT],
                cwd=source, env=environment, capture_output=True, text=True, timeout=60, check=False,
            )
        except subprocess.TimeoutExpired:
            raise PackageError("package_check_timeout") from None
        try:
            result = json.loads(checked.stdout)
        except (ValueError, TypeError):
            raise PackageError("package_check_failed") from None
        if checked.returncode != 0:
            if result.get("error") == "package_check_missing_dependency":
                raise PackageError(f"package_check_missing_dependency:{result.get('dependency')}")
            raise PackageError("package_check_failed")
        return result


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / ".local-data" / "synthetic-agent.zip")
    parser.add_argument("--check", action="store_true", help="Build/import the artifact offline with installed SDKs")
    args = parser.parse_args()
    try:
        result = build_package(root, args.output)
        if args.check:
            result["check"] = check_package(args.output)
    except PackageError as error:
        print(json.dumps({"error": str(error)}))
        return 1
    except OSError:
        print(json.dumps({"error": "package_io_failed"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
