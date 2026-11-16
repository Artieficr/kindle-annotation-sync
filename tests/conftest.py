"""Run with calibre's Python: calibre-debug -c "import pytest; pytest.main(['tests'])".
Makes calibre_plugins.kindle_annotation_sync resolve to plugin/ as it does inside calibre."""

import sys
import types
from pathlib import Path

pkg = types.ModuleType("calibre_plugins.kindle_annotation_sync")
pkg.__path__ = [str(Path(__file__).parent.parent / "plugin")]
sys.modules.setdefault("calibre_plugins", types.ModuleType("calibre_plugins")).__path__ = []
sys.modules["calibre_plugins.kindle_annotation_sync"] = pkg
