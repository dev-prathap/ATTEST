"""MCP registry listing files stay valid, and the `attestlayer` launcher dispatches."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def schema():
    return json.loads((ROOT / "mcp" / "server.schema.json").read_text())


@pytest.mark.parametrize("name", ["server.json", "server-proxy.json"])
def test_server_json_matches_schema_and_package(schema, name):
    jsonschema = pytest.importorskip("jsonschema")
    doc = json.loads((ROOT / "mcp" / name).read_text())
    jsonschema.Draft202012Validator(schema).validate(doc)
    pkg = doc["packages"][0]
    assert pkg["registryType"] == "pypi" and pkg["identifier"] == "attestlayer" and pkg["runtimeHint"] == "uvx"
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert f'version = "{doc["version"]}"' in pyproject and pkg["version"] == doc["version"]
    assert f"mcp-name: {doc['name']}" in (ROOT / "README.md").read_text()  # PyPI ownership marker
    assert doc["name"].startswith("io.github.dev-prathap/")


def test_mcpb_manifest_and_glama():
    m = json.loads((ROOT / "mcp" / "mcpb" / "manifest.json").read_text())
    assert m["server"]["mcp_config"]["command"] == "uvx" and m["server"]["mcp_config"]["args"] == ["attestlayer"]
    assert (ROOT / "mcp" / "mcpb" / m["server"]["entry_point"]).exists()
    assert {t["name"] for t in m["tools"]} == {"attest_decide", "attest_confirm", "attest_confirm_status", "attest_record", "attest_verify", "attest_ledger"}
    for key in m["server"]["mcp_config"]["env"].values():
        assert key.startswith("${user_config.") and key[len("${user_config."):-1] in m["user_config"]
    assert json.loads((ROOT / "glama.json").read_text())["maintainers"] == ["dev-prathap"]


def test_launcher_dispatch(tmp_path):
    env = {**os.environ, "ATTEST_LEDGER": str(tmp_path / "l.sqlite"), "ATTEST_AUTO_APPROVE": "1"}
    out = subprocess.run([sys.executable, "-m", "attest.mcp.launcher", "--help"], capture_output=True, text=True, env=env)
    assert "uvx attestlayer" in out.stdout
    msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    out = subprocess.run([sys.executable, "-m", "attest.mcp.launcher"], input=msg, capture_output=True, text=True, env=env, timeout=60)
    assert len(json.loads(out.stdout.splitlines()[0])["result"]["tools"]) == 6
    out = subprocess.run([sys.executable, "-m", "attest.mcp.launcher", "gateway", "--help"], capture_output=True, text=True, env=env)
    assert "outbound" in out.stdout
    out = subprocess.run([sys.executable, "-m", "attest.mcp.launcher", "bogus"], capture_output=True, text=True, env=env)
    assert out.returncode == 2 and "unknown command" in out.stderr
