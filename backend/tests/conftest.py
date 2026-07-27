"""Pytest fixtures shared across the test-suite.

We force the fake (offline) LLM backend and point DATA_ROOT at a temp dir so
tests never touch AWS or the real ``data/works`` directory.
"""

import os

os.environ.setdefault("NOVEL_KG_USE_FAKE_LLM", "1")
