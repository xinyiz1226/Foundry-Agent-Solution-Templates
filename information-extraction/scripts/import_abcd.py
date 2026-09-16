"""Normalize a local ABCD-format subset; no download, inference or ledger mutation."""

import argparse
from dataclasses import asdict
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import zlib

from information_extraction.abcd import MAX_INPUT_BYTES, PARSER_VERSION, SPLITS, import_abcd
from information_extraction.contracts import InvalidInput


def _local_path(path: Path) -> Path:
    absolute = path.absolute()
    if absolute.drive.startswith("\\\\"):
        raise InvalidInput("abcd_network_path_not_supported")
    for part in (absolute, *absolute.parents):
        if part.is_symlink() or part.is_junction():
            raise InvalidInput("abcd_link_path_not_supported")
    return absolute


def normalize_file(source: Path, output: Path, *, split: str) -> dict:
    source, output = _local_path(source), _local_path(output)
    if not source.is_file():
        raise InvalidInput("abcd_regular_input_file_required")
    if output.suffix.lower() != ".json":
        raise InvalidInput("abcd_json_output_required")
    if output.exists():
        raise FileExistsError
    with source.open("rb") as stream:
        encoded = stream.read(MAX_INPUT_BYTES + 1)
    if len(encoded) > MAX_INPUT_BYTES:
        raise InvalidInput("abcd_input_too_large")
    if source.suffix.lower() == ".gz":
        with gzip.GzipFile(fileobj=io.BytesIO(encoded)) as stream:
            payload = stream.read(MAX_INPUT_BYTES + 1)
    else:
        payload = encoded
    sources = import_abcd(payload, split=split)
    document = {
        "format": "information-extraction.abcd-source.v1",
        "parser_version": PARSER_VERSION,
        "source_kind": "abcd-format-original-dialogue",
        "source_file_sha256": hashlib.sha256(encoded).hexdigest(),
        "split": split,
        "documents": [asdict(item) for item in sources],
        "extraction_performed": False,
        "training_labels_imported": False,
    }
    content = (json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=output.parent, prefix="abcd-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        # Publish atomically without replacing an existing source or output.
        os.link(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {
        "output": str(output),
        "documents": len(sources),
        "dialogue_blocks": sum(len(source.turns) for source in sources),
        "excluded_action_turns": sum(source.excluded_action_turns for source in sources),
        "sha256": hashlib.sha256(content).hexdigest(),
        "extraction_performed": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--split", required=True, choices=SPLITS)
    args = parser.parse_args(argv)
    try:
        result = normalize_file(args.input, args.output, split=args.split)
    except InvalidInput as error:
        print(json.dumps({"error": str(error)}))
        return 1
    except FileExistsError:
        print(json.dumps({"error": "abcd_output_exists"}))
        return 1
    except (OSError, EOFError, zlib.error):
        print(json.dumps({"error": "abcd_file_read_or_publish_failed"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
