"""Source-deployment entrypoint for the synthetic-only hosted probe."""

import json
import sys

from information_extraction.contracts import ExecutionError
from information_extraction.hosted_app import create_app


def main() -> int:
    try:
        create_app().run()
    except ExecutionError as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    except Exception:
        print(json.dumps({"error": "synthetic_application_startup_failed"}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
