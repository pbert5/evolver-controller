from __future__ import annotations

import argparse
import json
from pathlib import Path

from compiler import compile_definition, load_definition, DefinitionError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Compile a schema-defined eVOLVER experiment definition")
    parser.add_argument("definition", type=Path)
    parser.add_argument("--json", action="store_true", help="emit canonical JSON")
    args = parser.parse_args(argv)
    try:
        bundle = compile_definition(load_definition(args.definition.read_text(encoding="utf-8")))
    except (OSError, DefinitionError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(bundle, sort_keys=True, indent=None if args.json else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
