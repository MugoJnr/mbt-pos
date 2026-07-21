"""Write exported Lovable file content to the correct path."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "MANIFEST.json"


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: save_file.py <relative-path> <content-file-or-dash>", file=sys.stderr)
        sys.exit(1)
    rel = sys.argv[1].replace("\\", "/")
    src = sys.argv[2]
    content = sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")
    dest = ROOT / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8", newline="\n")
    manifest = {}
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest[rel] = len(content.encode("utf-8"))
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"saved {rel} ({manifest[rel]} bytes)")


if __name__ == "__main__":
    main()
