"""Keep release tests isolated from any globally installed MBT POS build."""
from __future__ import annotations

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
