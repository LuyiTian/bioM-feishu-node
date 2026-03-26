"""
Embedded local web UI for the remote node.

Serves a single-page HTML app on localhost that lets the user
add/remove allowed directories dynamically, and shows node status.

Pure asyncio — no aiohttp, no frameworks, no CDN.
"""

import asyncio
import json
import logging
import os
import platform
import string
import urllib.parse

logger = logging.getLogger("feishu-node.ui")


def _list_roots() -> list[str]:
    """List filesystem roots. On Windows returns drive letters, on Unix returns ['/']."""
    if platform.system() == "Windows":
        import ctypes

        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        drives = []
        for i, letter in enumerate(string.ascii_uppercase):
            if bitmask & (1 << i):
                drives.append(f"{letter}:\\")
        return drives
    return ["/"]


def _browse_directory(path: str) -> dict:
    """List subdirectories of a path. Returns {current, parent, dirs, error?}."""
    if not path:
        home = os.path.expanduser("~")
        path = home

    path = os.path.realpath(os.path.expanduser(path))

    if not os.path.isdir(path):
        return {"error": f"Not a directory: {path}"}

    parent = os.path.dirname(path)
    if parent == path:
        parent = None  # Already at root

    dirs = []
    try:
        for entry in sorted(os.scandir(path), key=lambda e: e.name.lower()):
            if entry.is_dir(follow_symlinks=False):
                # Skip hidden dirs and system dirs
                name = entry.name
                if name.startswith(".") or name.startswith("$"):
                    continue
                dirs.append(name)
    except PermissionError:
        return {"current": path, "parent": parent, "dirs": [], "error": "Permission denied"}
    except OSError as e:
        return {"current": path, "parent": parent, "dirs": [], "error": str(e)}

    return {"current": path, "parent": parent, "dirs": dirs}


# ── HTML page (embedded) ────────────────────────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Feishu Node</title>
<style>
  :root {
    --bg: #f7f8fa; --surface: #fff; --border: #e2e5e9;
    --text: #1a1d21; --text2: #616670; --accent: #3370ff;
    --accent-hover: #2860e0; --danger: #e34d59; --danger-hover: #c43e4a;
    --ok: #2ba471; --radius: 8px;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.5;
  }
  .container { max-width: 640px; margin: 0 auto; padding: 32px 20px; }
  h1 { font-size: 20px; font-weight: 600; }
  .header { display: flex; align-items: center; gap: 12px; margin-bottom: 24px; }
  .dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
  .dot.on { background: var(--ok); } .dot.off { background: var(--danger); }
  .meta { color: var(--text2); font-size: 13px; margin-top: 2px; }

  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 12px 16px; margin-bottom: 8px;
    display: flex; align-items: center; justify-content: space-between;
  }
  .card .path { font-size: 14px; word-break: break-all; }
  .btn {
    border: none; border-radius: var(--radius); padding: 6px 14px;
    font-size: 13px; font-weight: 500; cursor: pointer; transition: background .15s;
    white-space: nowrap;
  }
  .btn-primary { background: var(--accent); color: #fff; }
  .btn-primary:hover { background: var(--accent-hover); }
  .btn-secondary { background: #eef1f6; color: var(--text); }
  .btn-secondary:hover { background: #e2e5e9; }
  .btn-danger { background: none; color: var(--danger); padding: 4px 10px; }
  .btn-danger:hover { background: #fde8ea; }
  .btn-ok { background: var(--ok); color: #fff; }
  .btn-ok:hover { background: #249963; }

  .add-row { display: flex; gap: 8px; margin-bottom: 24px; }
  .add-row input {
    flex: 1; padding: 8px 12px; border: 1px solid var(--border);
    border-radius: var(--radius); font-size: 14px; outline: none;
  }
  .add-row input:focus { border-color: var(--accent); }

  .section-title { font-size: 14px; font-weight: 600; margin-bottom: 8px; color: var(--text2); }
  .empty { color: var(--text2); font-size: 14px; padding: 16px 0; text-align: center; }

  .toast {
    position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
    padding: 10px 20px; border-radius: var(--radius); font-size: 14px;
    color: #fff; opacity: 0; transition: opacity .3s; pointer-events: none; z-index: 100;
  }
  .toast.show { opacity: 1; }
  .toast.ok { background: var(--ok); } .toast.err { background: var(--danger); }

  .caps { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
  .cap-tag {
    font-size: 12px; padding: 2px 8px; border-radius: 4px;
    background: #eef1f6; color: var(--text2);
  }

  /* ── Folder browser ── */
  .browser-overlay {
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,.3);
    z-index: 50; justify-content: center; align-items: center;
  }
  .browser-overlay.open { display: flex; }
  .browser {
    background: var(--surface); border-radius: 12px; width: 560px; max-height: 80vh;
    display: flex; flex-direction: column; box-shadow: 0 8px 32px rgba(0,0,0,.15);
  }
  .browser-header {
    padding: 16px 20px; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
  }
  .browser-header h2 { font-size: 16px; font-weight: 600; }
  .browser-path {
    padding: 10px 20px; border-bottom: 1px solid var(--border);
    font-size: 13px; color: var(--text2); word-break: break-all;
    display: flex; align-items: center; gap: 8px;
  }
  .browser-path code {
    flex: 1; background: var(--bg); padding: 4px 8px; border-radius: 4px;
    font-family: Consolas, "Courier New", monospace; font-size: 13px; color: var(--text);
  }
  .browser-list {
    flex: 1; overflow-y: auto; padding: 8px 12px; min-height: 200px; max-height: 50vh;
  }
  .browser-item {
    padding: 8px 12px; border-radius: 6px; cursor: pointer; font-size: 14px;
    display: flex; align-items: center; gap: 8px;
  }
  .browser-item:hover { background: #f0f3f7; }
  .browser-item .icon { font-size: 16px; width: 20px; text-align: center; flex-shrink: 0; }
  .browser-roots { display: flex; gap: 6px; flex-wrap: wrap; padding: 12px 20px; border-bottom: 1px solid var(--border); }
  .root-btn {
    padding: 4px 12px; border-radius: 6px; border: 1px solid var(--border);
    background: var(--surface); cursor: pointer; font-size: 13px; font-family: Consolas, monospace;
  }
  .root-btn:hover { background: #f0f3f7; }
  .browser-footer {
    padding: 12px 20px; border-top: 1px solid var(--border);
    display: flex; justify-content: flex-end; gap: 8px;
  }
  .browser-empty { color: var(--text2); text-align: center; padding: 32px 0; font-size: 14px; }
  .browser-error { color: var(--danger); text-align: center; padding: 12px 0; font-size: 13px; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div>
      <h1 id="title">Feishu Node</h1>
      <div class="meta" id="server-info">Connecting...</div>
      <div class="caps" id="caps"></div>
    </div>
    <span class="dot off" id="dot"></span>
  </div>

  <div class="section-title">Allowed Directories</div>
  <div class="add-row">
    <input id="dir-input" type="text" placeholder="Enter path or click Browse">
    <button class="btn btn-secondary" onclick="openBrowser()">Browse</button>
    <button class="btn btn-primary" onclick="addDir()">Add</button>
  </div>
  <div id="dir-list"></div>
</div>

<div class="browser-overlay" id="browser-overlay" onclick="if(event.target===this)closeBrowser()">
  <div class="browser">
    <div class="browser-header">
      <h2>Select Folder</h2>
      <button class="btn btn-secondary" onclick="closeBrowser()" style="padding:4px 10px">X</button>
    </div>
    <div class="browser-roots" id="browser-roots"></div>
    <div class="browser-path">
      <button class="btn btn-secondary" onclick="browseUp()" style="padding:4px 10px" title="Parent folder">^</button>
      <code id="browser-current"></code>
    </div>
    <div class="browser-list" id="browser-list"></div>
    <div class="browser-footer">
      <button class="btn btn-secondary" onclick="closeBrowser()">Cancel</button>
      <button class="btn btn-ok" onclick="selectCurrent()">Select this folder</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let STATUS = {};
let BROWSE = { current: '', parent: null, dirs: [], roots: [] };

function toast(msg, ok) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show ' + (ok ? 'ok' : 'err');
  setTimeout(() => t.className = 'toast', 2500);
}

async function fetchStatus() {
  try {
    const r = await fetch('/api/status');
    if (!r.ok) { document.getElementById('server-info').textContent = 'HTTP ' + r.status; return; }
    STATUS = await r.json();
    render();
  } catch(e) {
    document.getElementById('server-info').textContent = 'Error: ' + e.message;
    console.error(e);
  }
}

function render() {
  document.getElementById('title').textContent = STATUS.name || 'Feishu Node';
  document.getElementById('server-info').textContent = STATUS.server || '';
  const dot = document.getElementById('dot');
  dot.className = 'dot ' + (STATUS.connected ? 'on' : 'off');
  dot.title = STATUS.connected ? 'Connected' : 'Disconnected';

  const caps = document.getElementById('caps');
  caps.innerHTML = (STATUS.capabilities || []).map(c => '<span class="cap-tag">' + c + '</span>').join('');

  const list = document.getElementById('dir-list');
  const dirs = STATUS.dirs || [];
  if (!dirs.length) {
    list.innerHTML = '<div class="empty">No directories configured. Click Browse or enter a path above.</div>';
    return;
  }
  list.innerHTML = dirs.map(d =>
    '<div class="card"><span class="path">' + escHtml(d) + '</span>' +
    '<button class="btn btn-danger" onclick="removeDir(\'' + escJs(d) + '\')">Remove</button></div>'
  ).join('');
}

function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function escJs(s) { return s.replace(/\\/g, '\\\\').replace(/'/g, "\\'"); }

async function addDir(path) {
  if (!path) {
    const inp = document.getElementById('dir-input');
    path = inp.value.trim();
  }
  if (!path) { toast('Enter a path first', false); return; }
  try {
    const r = await fetch('/api/dirs', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path}) });
    const data = await r.json();
    if (data.error) { toast(data.error, false); return; }
    STATUS = data; render();
    document.getElementById('dir-input').value = '';
    toast('Directory added', true);
  } catch(e) { toast('Request failed', false); }
}

async function removeDir(path) {
  try {
    const r = await fetch('/api/dirs', { method: 'DELETE', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path}) });
    const data = await r.json();
    if (data.error) { toast(data.error, false); return; }
    STATUS = data; render();
    toast('Directory removed', true);
  } catch(e) { toast('Request failed', false); }
}

/* ── Folder browser ── */

async function openBrowser() {
  // Fetch roots first
  try {
    const r = await fetch('/api/browse?roots=1');
    const data = await r.json();
    BROWSE.roots = data.roots || ['/'];
  } catch(e) { BROWSE.roots = ['/']; }

  const rootsEl = document.getElementById('browser-roots');
  rootsEl.innerHTML = BROWSE.roots.map(r =>
    '<button class="root-btn" onclick="browseTo(\'' + escJs(r) + '\')">' + escHtml(r) + '</button>'
  ).join('');

  document.getElementById('browser-overlay').classList.add('open');
  // Browse to home directory initially
  browseTo('');
}

function closeBrowser() {
  document.getElementById('browser-overlay').classList.remove('open');
}

async function browseTo(path) {
  try {
    const r = await fetch('/api/browse?path=' + encodeURIComponent(path));
    const data = await r.json();
    BROWSE.current = data.current || path;
    BROWSE.parent = data.parent || null;
    BROWSE.dirs = data.dirs || [];
    renderBrowser(data.error);
  } catch(e) {
    console.error(e);
    toast('Browse failed', false);
  }
}

function browseUp() {
  if (BROWSE.parent) browseTo(BROWSE.parent);
}

function renderBrowser(error) {
  document.getElementById('browser-current').textContent = BROWSE.current;
  const list = document.getElementById('browser-list');
  let html = '';
  if (error) {
    html += '<div class="browser-error">' + escHtml(error) + '</div>';
  }
  if (!BROWSE.dirs.length && !error) {
    html = '<div class="browser-empty">No subdirectories</div>';
  }
  html += BROWSE.dirs.map(d =>
    '<div class="browser-item" ondblclick="browseTo(\'' + escJs(BROWSE.current + (BROWSE.current.endsWith('/') || BROWSE.current.endsWith('\\') ? '' : (BROWSE.current.includes('\\') ? '\\' : '/')) + d) + '\')">' +
    '<span class="icon">&#128193;</span><span>' + escHtml(d) + '</span></div>'
  ).join('');
  list.innerHTML = html;
  list.scrollTop = 0;
}

function selectCurrent() {
  if (!BROWSE.current) return;
  closeBrowser();
  addDir(BROWSE.current);
}

fetchStatus();
setInterval(fetchStatus, 5000);
document.getElementById('dir-input').addEventListener('keydown', e => { if (e.key === 'Enter') addDir(); });
</script>
</body>
</html>"""


# ── HTTP server (pure asyncio) ──────────────────────────────────────

async def _read_http_request(reader: asyncio.StreamReader) -> tuple[str, str, str, dict, bytes]:
    """Parse a minimal HTTP request. Returns (method, path, query_string, headers, body)."""
    request_line = await asyncio.wait_for(reader.readline(), timeout=10)
    if not request_line:
        raise ConnectionError("Empty request")
    parts = request_line.decode("utf-8", errors="replace").strip().split(" ")
    method = parts[0] if parts else "GET"
    raw_path = parts[1] if len(parts) > 1 else "/"

    # Split path and query string
    if "?" in raw_path:
        path, query_string = raw_path.split("?", 1)
    else:
        path, query_string = raw_path, ""

    headers: dict[str, str] = {}
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=10)
        decoded = line.decode("utf-8", errors="replace").strip()
        if not decoded:
            break
        if ":" in decoded:
            k, v = decoded.split(":", 1)
            headers[k.strip().lower()] = v.strip()

    body = b""
    content_length = int(headers.get("content-length", 0))
    if content_length > 0:
        body = await asyncio.wait_for(reader.readexactly(content_length), timeout=10)

    return method, path, query_string, headers, body


def _http_response(status: int, body: str, content_type: str = "application/json") -> bytes:
    status_text = {200: "OK", 400: "Bad Request", 404: "Not Found", 500: "Internal Server Error"}.get(status, "OK")
    body_bytes = body.encode("utf-8")
    header = (
        f"HTTP/1.1 {status} {status_text}\r\n"
        f"Content-Type: {content_type}; charset=utf-8\r\n"
        f"Content-Length: {len(body_bytes)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    )
    return header.encode("utf-8") + body_bytes


class WebUI:
    """Minimal HTTP server for the node management UI."""

    def __init__(self, node_client, host: str = "127.0.0.1", port: int = 9201):
        self._client = node_client
        self.host = host
        self.port = port

    async def start(self):
        try:
            server = await asyncio.start_server(self._handle_connection, self.host, self.port)
        except OSError as e:
            logger.warning(f"Web UI failed to bind to port {self.port}: {e}")
            print(f"\n  Warning: Web UI port {self.port} is in use. Try --port <other> or kill the old process.")
            print(f"  Node continues running without web UI.\n")
            return
        logger.info(f"Web UI available at http://{self.host}:{self.port}")
        async with server:
            await server.serve_forever()

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            method, path, qs, headers, body = await _read_http_request(reader)
            response = self._route(method, path, qs, body)
            writer.write(response)
            await writer.drain()
        except Exception as e:
            logger.debug(f"HTTP handler error: {e}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def _route(self, method: str, path: str, qs: str, body: bytes) -> bytes:
        if path == "/" and method == "GET":
            return _http_response(200, HTML_PAGE, content_type="text/html")

        if path == "/api/status" and method == "GET":
            return _http_response(200, json.dumps(self._client.get_status()))

        if path == "/api/browse" and method == "GET":
            return self._handle_browse(qs)

        if path == "/api/dirs" and method == "POST":
            return self._handle_add_dir(body)

        if path == "/api/dirs" and method == "DELETE":
            return self._handle_remove_dir(body)

        return _http_response(404, json.dumps({"error": "Not found"}))

    def _handle_browse(self, qs: str) -> bytes:
        params = urllib.parse.parse_qs(qs)
        if "roots" in params:
            return _http_response(200, json.dumps({"roots": _list_roots()}))
        path = params.get("path", [""])[0]
        result = _browse_directory(path)
        return _http_response(200, json.dumps(result, ensure_ascii=False))

    def _handle_add_dir(self, body: bytes) -> bytes:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return _http_response(400, json.dumps({"error": "Invalid JSON"}))
        path = data.get("path", "").strip()
        if not path:
            return _http_response(400, json.dumps({"error": "Path is required"}))
        err = self._client.add_directory(path)
        if err:
            return _http_response(400, json.dumps({"error": err}))
        return _http_response(200, json.dumps(self._client.get_status()))

    def _handle_remove_dir(self, body: bytes) -> bytes:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return _http_response(400, json.dumps({"error": "Invalid JSON"}))
        path = data.get("path", "").strip()
        if not path:
            return _http_response(400, json.dumps({"error": "Path is required"}))
        err = self._client.remove_directory(path)
        if err:
            return _http_response(400, json.dumps({"error": err}))
        return _http_response(200, json.dumps(self._client.get_status()))
