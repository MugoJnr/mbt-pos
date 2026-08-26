"""Keep release tests isolated from any globally installed MBT POS build."""
from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
root_text = str(ROOT)

# Windows may expose the installed application's `_internal` directory through
# process search paths. Always test the checked-out release candidate.
sys.path[:] = [
    path
    for path in sys.path
    if path != root_text
    and not (
        "MugoByte" in path
        and "MBT POS" in path
        and "_internal" in path
    )
]
sys.path.insert(0, root_text)

for package in ("backend", "desktop", "licensing", "printing", "diagnostics"):
    module = sys.modules.get(package)
    module_file = str(getattr(module, "__file__", "") or "")
    if module is not None and module_file and not module_file.startswith(root_text):
        del sys.modules[package]


def pytest_sessionfinish(session, exitstatus):
    """Bypass the known PyQt5 Windows interpreter-finalizer access violation.

    The native fault happens only after pytest has completed and reported every
    test, when Windows tears down Qt objects during Python module destruction.
    Runtime native faults still fail immediately.  Registering this at session
    finish preserves pytest's real exit status while avoiding that unsafe final
    C++ destruction pass (the same strategy used by the desktop QA runners).
    """
    if os.name != "nt" or "PyQt5" not in sys.modules:
        return

    def _clean_exit():
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        finally:
            os._exit(int(exitstatus))

    atexit.register(_clean_exit)
