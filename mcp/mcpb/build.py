"""Build both bundle flavours.

    python mcp/mcpb/build.py [--version 0.1.0] [--out .]

  attest-<v>.mcpb            packed by `mcpb pack` — Claude Desktop, the MCPB spec's tool shape (name + description)
  attest-<v>-smithery.mcpb   the same tree, but each tool carries its `inputSchema`

Smithery's validator requires a full tool object; the MCPB CLI rejects the extra key. Rather than pick one, the
Smithery flavour is zipped directly after `sync_tools.py` has regenerated the metadata from the running server.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version")
    ap.add_argument("--out", default=".")
    a = ap.parse_args()

    subprocess.run([sys.executable, str(HERE / "sync_tools.py")], check=True)
    manifest_path = HERE / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    version = a.version or manifest["version"]
    if manifest["version"] != version:
        manifest["version"] = version
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    standard = out / f"attest-{version}.mcpb"
    subprocess.run(["npx", "-y", "@anthropic-ai/mcpb", "validate", str(manifest_path)], check=True)
    subprocess.run(["npx", "-y", "@anthropic-ai/mcpb", "pack", str(HERE), str(standard)], check=True)

    from attest.mcp.server import TOOLS
    smithery = out / f"attest-{version}-smithery.mcpb"
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "bundle"
        shutil.copytree(HERE, tree, ignore=shutil.ignore_patterns("sync_tools.py", "build.py", "__pycache__"))
        doc = json.loads((tree / "manifest.json").read_text())
        doc["tools"] = [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
                        for t in TOOLS]
        (tree / "manifest.json").write_text(json.dumps(doc, indent=2) + "\n")
        smithery.unlink(missing_ok=True)
        with zipfile.ZipFile(smithery, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(tree.rglob("*")):
                if f.is_file() and not f.name.startswith("."):
                    z.write(f, f.relative_to(tree))

    for f in (standard, smithery):
        print(f"{f.name}  {f.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
