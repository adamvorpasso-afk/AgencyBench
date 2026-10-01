#!/usr/bin/env python3
"""Agent Monitor: a live view of what your Claude Code agents are doing.

Claude Code POSTs every hook event here (type "http" hooks); this server keeps
recent events in memory and streams them to the dashboard over Server-Sent Events.

  python3 server.py --install     # add the hooks to ~/.claude/settings.json (backs it up first)
  python3 server.py               # start the monitor, then open http://127.0.0.1:4820
  python3 server.py --uninstall   # remove the hooks again

Standard library only. Listens on 127.0.0.1, so nothing leaves your machine.
"""
import argparse
import json
import queue
import shutil
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK_PATH = "/hook"
EVENTS = [
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure",
    "PermissionRequest", "Notification", "SubagentStart", "SubagentStop", "Stop", "StopFailure",
    "TaskCreated", "TaskCompleted",
]
TOOL_EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest"}
# Claude Code must ask you before any of these run, in every permission mode (ask rules
# still prompt in auto mode). Covers deleting things and sending email.
APPROVAL_RULES = [
    # email
    "mcp__*Gmail*__send*", "mcp__*Gmail*__reply*", "mcp__*Gmail*__forward*",
    "mcp__*__*send_email*", "mcp__*__*send_mail*",
    "mcp__*Zapier*__execute_zapier_write_action",
    "Bash(sendmail *)", "Bash(mail *)", "Bash(mutt *)",
    # deleting, in any connected service
    "mcp__*__*delete*", "mcp__*__*trash*", "mcp__*__*remove*", "mcp__*__*destroy*", "mcp__*__*purge*",
    "Artifact(action:delete)", "ArtifactData(action:delete)",
    # deleting files, branches and repos
    "Bash(rm *)", "Bash(rmdir *)", "Bash(unlink *)", "Bash(shred *)", "Bash(find * -delete*)",
    "Bash(git rm *)", "Bash(git clean *)", "Bash(git branch -d *)", "Bash(git branch -D *)",
    "Bash(git branch --delete *)", "Bash(git push --delete *)", "Bash(git push * --delete *)",
    "Bash(git push -d *)", "Bash(git push * -d *)", "Bash(gh repo delete *)",
]
MAX_TEXT = 1500  # long tool output is cut so the page stays fast

history = deque(maxlen=3000)
clients = set()
lock = threading.Lock()


def trim(v):
    if isinstance(v, str):
        return v if len(v) <= MAX_TEXT else v[:MAX_TEXT] + f"… [{len(v) - MAX_TEXT} more chars]"
    if isinstance(v, dict):
        return {k: trim(x) for k, x in v.items()}
    if isinstance(v, list):
        return [trim(x) for x in v[:50]]
    return v


def publish(event):
    event = trim(event)
    event["ts"] = time.time()
    data = json.dumps(event)
    with lock:
        history.append(data)
        for q in list(clients):
            q.put(data)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != HOOK_PATH:
            return self._send(404)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            publish(json.loads(self.rfile.read(n) or b"{}"))
        except Exception as e:  # never block Claude Code because of a bad payload
            print("bad event:", e, file=sys.stderr)
        self._send(200, b"{}")  # empty JSON: no decision, Claude Code carries on

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/stream":
            return self._stream()
        self._send(404)

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        q = queue.Queue()
        with lock:
            backlog = list(history)
            clients.add(q)
        try:
            for data in backlog:
                self.wfile.write(f"data: {data}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    data = q.get(timeout=15)
                    self.wfile.write(f"data: {data}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with lock:
                clients.discard(q)


def settings_path(project):
    return Path(".claude/settings.local.json") if project else Path.home() / ".claude/settings.json"


def is_ours(group, url):
    return any(h.get("type") == "http" and h.get("url") == url for h in group.get("hooks", []))


def install(port, project, remove=False):
    path = settings_path(project)
    url = f"http://127.0.0.1:{port}{HOOK_PATH}"
    settings = json.loads(path.read_text()) if path.exists() else {}
    if path.exists():
        backup = path.with_name(path.name + ".bak")
        shutil.copy(path, backup)
        print(f"Backed up {path} -> {backup}")
    hooks = settings.setdefault("hooks", {})
    for name in EVENTS:
        groups = [g for g in hooks.get(name, []) if not is_ours(g, url)]
        if not remove:
            group = {"hooks": [{"type": "http", "url": url, "timeout": 2}]}
            if name in TOOL_EVENTS:
                group = {"matcher": "*", **group}
            groups.append(group)
        if groups:
            hooks[name] = groups
        else:
            hooks.pop(name, None)
    if not hooks:
        settings.pop("hooks")
    perms = settings.setdefault("permissions", {})
    ask = [r for r in perms.get("ask", []) if r not in APPROVAL_RULES]
    if not remove:
        ask += APPROVAL_RULES
    if ask:
        perms["ask"] = ask
    else:
        perms.pop("ask", None)
    if not perms:
        settings.pop("permissions")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"{'Removed' if remove else 'Installed'} Agent Monitor hooks and approval rules in {path}")
    if not remove:
        print("Restart any running Claude Code sessions so they pick up the hooks.")


def main():
    ap = argparse.ArgumentParser(description="Live monitor for Claude Code agents")
    ap.add_argument("--port", type=int, default=4820)
    ap.add_argument("--install", action="store_true", help="add hooks to Claude Code settings")
    ap.add_argument("--uninstall", action="store_true", help="remove the hooks")
    ap.add_argument("--project", action="store_true",
                    help="use ./.claude/settings.local.json instead of your user settings")
    a = ap.parse_args()
    if a.install or a.uninstall:
        return install(a.port, a.project, remove=a.uninstall)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    srv.daemon_threads = True
    print(f"Agent Monitor running: open http://127.0.0.1:{a.port}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
