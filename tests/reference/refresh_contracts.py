#!/usr/bin/env python3
"""Rewrite every generated contract from the closed runtime registry.

Offline and deterministic: it reads ``runtime/catalog.py`` and nothing else.
Run it from the bundle root after changing the registry, then run the tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parents[2]
if str(BUNDLE_ROOT) not in sys.path:
    sys.path.insert(0, str(BUNDLE_ROOT))

from tests.reference.build_contracts import (  # noqa: E402
    GENERATED_FILES,
    dump,
    manifest_with_external_effects,
)
from tests.reference.build_ui_pages import GENERATED_PAGES  # noqa: E402


def main() -> int:
    for relative, builder in GENERATED_FILES.items():
        path = BUNDLE_ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump(builder()), encoding="utf-8")
        print(f"wrote {relative}")
    for path, render in GENERATED_PAGES.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(), encoding="utf-8")
        print(f"wrote {path.relative_to(BUNDLE_ROOT)}")
    manifest = BUNDLE_ROOT / "extension.yaml"
    manifest.write_text(
        manifest_with_external_effects(manifest.read_text(encoding="utf-8")), encoding="utf-8"
    )
    print("wrote extension.yaml external_effects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
