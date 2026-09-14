"""A tiny stdio MCP server for proxy tests: initialize, tools/list, tools/call (create/get/update/delete issue)."""
import json
import sys

DB = {}
TOOLS = [
    {"name": "create_issue", "description": "create", "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}},
    {"name": "get_issue", "description": "get", "inputSchema": {"type": "object", "properties": {"issue_id": {"type": "string"}}, "required": ["issue_id"]}},
    {"name": "update_issue", "description": "update", "inputSchema": {"type": "object", "properties": {"issue_id": {"type": "string"}, "title": {"type": "string"}}, "required": ["issue_id"]}},
    {"name": "delete_issue", "description": "delete", "inputSchema": {"type": "object", "properties": {"issue_id": {"type": "string"}}, "required": ["issue_id"]}},
    {"name": "list_issues", "description": "list", "inputSchema": {"type": "object", "properties": {}}},
]


def text(obj, err=False):
    return {"content": [{"type": "text", "text": json.dumps(obj)}], "isError": err}


def call(name, a):
    if name == "create_issue":
        iid = f"I-{len(DB) + 1}"
        DB[iid] = {"id": iid, "title": a["title"]}
        return text(DB[iid])
    if name == "get_issue":
        return text(DB[a["issue_id"]]) if a["issue_id"] in DB else text({"error": "not found"}, True)
    if name == "update_issue":
        if a["issue_id"] not in DB:
            return text({"error": "not found"}, True)
        if a.get("title") == "LOSE-IT":  # simulate a vendor that says OK but does not persist
            return text({"ok": True})
        DB[a["issue_id"]]["title"] = a.get("title", DB[a["issue_id"]]["title"])
        return text({"ok": True, "id": a["issue_id"]})
    if name == "delete_issue":
        DB.pop(a["issue_id"], None)
        return text({"ok": True})
    if name == "list_issues":
        return text(list(DB.values()))
    return text({"error": f"unknown tool {name}"}, True)


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        out = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "0"}}
    elif method == "tools/list":
        out = {"tools": TOOLS}
    elif method == "tools/call":
        out = call(params.get("name"), params.get("arguments") or {})
    elif mid is None:
        continue  # notification
    else:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "unknown"}}) + "\n")
        sys.stdout.flush()
        continue
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": out}) + "\n")
    sys.stdout.flush()
