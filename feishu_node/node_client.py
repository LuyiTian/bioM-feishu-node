"""
WebSocket client for the remote node.

Connects OUT to the central server, handles pairing, authentication,
auto-reconnect, and dispatches tool calls to the Tools layer.
"""

import asyncio
import hashlib
import json
import logging
import os
import platform
import random
import signal
import string
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import websockets
    from websockets.asyncio.client import connect as ws_connect
except ImportError:
    print("Missing dependency. Install with: pip install websockets")
    sys.exit(1)

from .tools import Sandbox, Tools
from .web_ui import WebUI

logger = logging.getLogger("feishu-node")

CONFIG_DIR = Path.home() / ".feishu-node"
CONFIG_FILE = CONFIG_DIR / "config.json"
CONFIG_VERSION = 1


def _generate_pairing_code() -> str:
    """6-char alphanumeric pairing code (uppercase, no ambiguous chars)."""
    chars = string.ascii_uppercase.replace("O", "").replace("I", "") + string.digits.replace("0", "").replace("1", "")
    return "".join(random.choices(chars, k=6))


def _default_config() -> dict:
    return {"version": CONFIG_VERSION, "profiles": {}}


def _normalize_server_url(server_url: str) -> str:
    return str(server_url or "").strip().rstrip("/")


def _profile_key(server_url: str, node_name: str) -> str:
    return f"{_normalize_server_url(server_url)}::{str(node_name or '').strip()}"


def _normalize_dirs(values: list[str] | None) -> list[str]:
    values = values or []
    seen = set()
    dirs: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            continue
        resolved = os.path.realpath(os.path.expanduser(text))
        if resolved in seen:
            continue
        seen.add(resolved)
        dirs.append(resolved)
    return dirs


def _migrate_legacy_config(raw: dict) -> dict:
    if not isinstance(raw, dict):
        return _default_config()

    # New format: {"version": 1, "profiles": {...}}
    profiles = raw.get("profiles")
    if isinstance(profiles, dict):
        cleaned_profiles: dict[str, dict] = {}
        for key, entry in profiles.items():
            if not isinstance(entry, dict):
                continue
            server_url = _normalize_server_url(entry.get("server_url", ""))
            node_name = str(entry.get("node_name") or "").strip()
            if not server_url or not node_name:
                if "::" in str(key):
                    guessed_server, guessed_node = str(key).split("::", 1)
                    server_url = server_url or _normalize_server_url(guessed_server)
                    node_name = node_name or guessed_node.strip()
            if not server_url or not node_name:
                continue
            cleaned_profiles[_profile_key(server_url, node_name)] = {
                "server_url": server_url,
                "node_name": node_name,
                "token": str(entry.get("token") or ""),
                "allowed_dirs": _normalize_dirs(entry.get("allowed_dirs") if isinstance(entry.get("allowed_dirs"), list) else []),
            }
        return {"version": CONFIG_VERSION, "profiles": cleaned_profiles}

    # Legacy format: { "<server_url>": {node_name, token, allowed_dirs} }
    migrated = _default_config()
    for maybe_server_url, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        server_url = _normalize_server_url(maybe_server_url)
        node_name = str(entry.get("node_name") or "").strip()
        if not server_url or not node_name:
            continue
        key = _profile_key(server_url, node_name)
        migrated["profiles"][key] = {
            "server_url": server_url,
            "node_name": node_name,
            "token": str(entry.get("token") or ""),
            "allowed_dirs": _normalize_dirs(entry.get("allowed_dirs") if isinstance(entry.get("allowed_dirs"), list) else []),
        }
    return migrated


def _load_config() -> dict:
    if not CONFIG_FILE.exists():
        return _default_config()
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        backup = CONFIG_FILE.with_suffix(f".broken-{int(time.time())}.json")
        try:
            CONFIG_FILE.replace(backup)
            logger.warning("Invalid config file moved to %s: %s", backup, e)
        except Exception:
            logger.warning("Invalid config file at %s (kept in place): %s", CONFIG_FILE, e)
        return _default_config()

    migrated = _migrate_legacy_config(raw)
    if migrated != raw:
        _save_config(migrated)
    return migrated


def _save_config(config: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = _migrate_legacy_config(config)
    tmp = CONFIG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONFIG_FILE)
    # Restrict permissions on config file (contains token)
    if platform.system() != "Windows":
        os.chmod(CONFIG_FILE, 0o600)


def _load_saved_dirs(server_url: str, node_name: str) -> list[str]:
    """Load saved allowed_dirs for a server+node from config."""
    config = _load_config()
    profile = config.get("profiles", {}).get(_profile_key(server_url, node_name), {})
    dirs = profile.get("allowed_dirs", [])
    return _normalize_dirs(dirs if isinstance(dirs, list) else [])


class NodeClient:
    """WebSocket client that connects to the central Feishu gateway."""

    def __init__(
        self,
        server_url: str,
        node_name: str,
        tools: Tools,
        allowed_dirs: list[str],
        gateway_token: str = "",
        capabilities: Optional[list[str]] = None,
    ):
        self.server_url = _normalize_server_url(server_url)
        self.node_name = str(node_name or "").strip()
        self.tools = tools
        self.allowed_dirs = allowed_dirs
        self.gateway_token = (gateway_token or "").strip()
        self.capabilities = capabilities or self._detect_capabilities()
        self.token: Optional[str] = None
        self._running = True
        self._paired = asyncio.Event()
        self._ws = None  # current WebSocket connection
        self._connected = False

        # Load saved token from previous session (server+node scoped)
        config = _load_config()
        saved = config.get("profiles", {}).get(_profile_key(self.server_url, self.node_name), {})
        if isinstance(saved, dict):
            token = str(saved.get("token") or "").strip()
            if token:
                self.token = token

    def _detect_capabilities(self) -> list[str]:
        caps = ["file_ops"]
        if self.tools.allow_shell:
            caps.append("run_command")
        return caps

    async def run(self):
        """Main loop: connect, authenticate, handle requests. Auto-reconnect on failure."""
        backoff = 1
        while self._running:
            try:
                await self._connect_and_serve()
                backoff = 1  # Reset on clean disconnect
            except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError) as e:
                if not self._running:
                    break
                logger.warning(f"Connection lost: {e}. Reconnecting in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            except Exception as e:
                if not self._running:
                    break
                logger.error(f"Unexpected error: {e}. Reconnecting in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _connect_and_serve(self):
        """Single connection lifecycle: connect → auth → serve requests."""
        ws_url = f"{self.server_url}/ws/node"
        logger.info(f"Connecting to {ws_url}...")

        additional_headers = None
        if self.gateway_token:
            additional_headers = {"Authorization": f"Bearer {self.gateway_token}"}

        async with ws_connect(ws_url, max_size=20 * 1024 * 1024, additional_headers=additional_headers) as ws:
            self._ws = ws
            # Phase 1: Register / authenticate
            await self._authenticate(ws)
            self._connected = True
            logger.info("Connected and authenticated.")
            print(f"\n  Node '{self.node_name}' is online and serving requests.")
            print(f"  Capabilities: {', '.join(self.capabilities)}")
            print(f"  Press Ctrl+C to disconnect.\n")

            try:
                # Phase 2: Serve tool call requests
                async for message in ws:
                    try:
                        request = json.loads(message)
                        # Handle server-initiated control messages (no "id" field)
                        if "method" in request and "id" not in request:
                            method = request["method"]
                            params = request.get("params", {})
                            if method == "update_dirs":
                                new_dirs = _normalize_dirs(params.get("dirs", []))
                                self.allowed_dirs = new_dirs
                                self.tools.sandbox.allowed_dirs = list(new_dirs)
                                self._save_dirs()  # no args — reads self.allowed_dirs
                                logger.info(f"Dirs updated by server: {len(new_dirs)} entries")
                            else:
                                logger.debug(f"Unknown control: {method}")
                            continue
                        response = await self._handle_request(request)
                        await ws.send(json.dumps(response))
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON from server: {message[:200]}")
                    except Exception as e:
                        logger.error(f"Error handling request: {e}")
                        # Try to send error response
                        try:
                            req_id = json.loads(message).get("id", "unknown")
                            await ws.send(json.dumps({"id": req_id, "error": {"code": -1, "message": str(e)}}))
                        except Exception:
                            pass
            finally:
                self._connected = False
                self._ws = None

    async def _authenticate(self, ws):
        """Authenticate with saved token, or initiate pairing flow."""
        if self.token:
            # Reconnect with saved token
            await ws.send(
                json.dumps(
                    {
                        "method": "register",
                        "params": {
                            "node_id": self.node_name,
                            "token": self.token,
                            "allowed_dirs": self.allowed_dirs,
                            "capabilities": self.capabilities,
                        },
                    }
                )
            )
            resp = json.loads(await ws.recv())
            if resp.get("result") == "ok":
                return
            else:
                logger.warning(f"Saved token rejected: {resp.get('error', {}).get('message', 'unknown')}. Re-pairing...")
                self.token = None

        # Pairing flow: generate code, wait for user to confirm in Feishu
        pairing_code = _generate_pairing_code()
        await ws.send(
            json.dumps(
                {
                    "method": "pair",
                    "params": {
                        "node_id": self.node_name,
                        "pairing_code": pairing_code,
                        "allowed_dirs": self.allowed_dirs,
                        "capabilities": self.capabilities,
                    },
                }
            )
        )

        print("\n" + "=" * 50)
        print(f"  Pairing code:  {pairing_code}")
        print(f"  Send this in Feishu:  /node pair {pairing_code}")
        print(f"  Code expires in 5 minutes.")
        print("=" * 50 + "\n")

        # Wait for server to confirm pairing
        resp = json.loads(await ws.recv())
        if resp.get("result") == "paired":
            self.token = resp["token"]
            # Save token for future reconnections (server+node scoped)
            config = _load_config()
            config.setdefault("profiles", {})
            config["profiles"][_profile_key(self.server_url, self.node_name)] = {
                "server_url": self.server_url,
                "node_name": self.node_name,
                "token": self.token,
                "allowed_dirs": _normalize_dirs(self.allowed_dirs),
            }
            _save_config(config)
            print(f"  Paired successfully! Token saved to {CONFIG_FILE}")
        else:
            raise ConnectionError(f"Pairing failed: {resp.get('error', {}).get('message', 'unknown')}")

    async def _handle_request(self, request: dict) -> dict:
        """Handle a JSON-RPC request from the server."""
        req_id = request.get("id", "unknown")
        method = request.get("method", "")

        if method == "ping":
            return {"id": req_id, "result": "pong"}

        if method == "call_tool":
            params = request.get("params", {})
            tool_name = params.get("tool", "")
            tool_args = params.get("args", {})
            logger.info(f"Executing: {tool_name}({', '.join(f'{k}={repr(v)[:50]}' for k, v in tool_args.items())})")

            # Run tool in thread pool to avoid blocking the event loop
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self.tools.dispatch, tool_name, tool_args)
            return {"id": req_id, "result": result}

        return {"id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}

    # ── Dynamic directory management ────────────────────────────────

    def get_status(self) -> dict:
        """Return current node status for the web UI."""
        return {
            "name": self.node_name,
            "server": self.server_url,
            "connected": self._connected,
            "dirs": list(self.allowed_dirs),
            "capabilities": list(self.capabilities),
        }

    def add_directory(self, path: str) -> Optional[str]:
        """Add a directory. Returns error string or None on success."""
        resolved = os.path.realpath(os.path.expanduser(path))
        if not os.path.isdir(resolved):
            return f"Directory does not exist: {path}"
        if resolved in self.allowed_dirs:
            return f"Directory already added: {resolved}"
        self.allowed_dirs.append(resolved)
        self.tools.sandbox.add_dir(resolved)
        self._save_dirs()
        self._schedule_update_dirs()
        logger.info(f"Added directory: {resolved}")
        return None

    def remove_directory(self, path: str) -> Optional[str]:
        """Remove a directory. Returns error string or None on success."""
        resolved = os.path.realpath(os.path.expanduser(path))
        if resolved not in self.allowed_dirs:
            return f"Directory not in list: {path}"
        self.allowed_dirs = [d for d in self.allowed_dirs if d != resolved]
        self.tools.sandbox.remove_dir(resolved)
        self._save_dirs()
        self._schedule_update_dirs()
        logger.info(f"Removed directory: {resolved}")
        return None

    def _save_dirs(self):
        """Persist allowed_dirs to config."""
        config = _load_config()
        config.setdefault("profiles", {})
        profile_key = _profile_key(self.server_url, self.node_name)
        entry = config["profiles"].get(profile_key, {})
        entry["server_url"] = self.server_url
        entry["node_name"] = self.node_name
        entry["allowed_dirs"] = _normalize_dirs(self.allowed_dirs)
        if self.token:
            entry["token"] = self.token
        config["profiles"][profile_key] = entry
        _save_config(config)

    def _schedule_update_dirs(self):
        """Schedule sending update_dirs to server (fire-and-forget)."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._send_update_dirs())
        except RuntimeError:
            pass  # No running loop — skip

    async def _send_update_dirs(self):
        """Notify the server of updated allowed_dirs."""
        if self._ws and self._connected:
            try:
                await self._ws.send(
                    json.dumps({"method": "update_dirs", "params": {"allowed_dirs": self.allowed_dirs}})
                )
            except Exception as e:
                logger.warning(f"Failed to send update_dirs: {e}")

    def stop(self):
        self._running = False


def run_node(
    server_url: str,
    node_name: str,
    allowed_dirs: list[str],
    gateway_token: str = "",
    no_shell: bool = False,
    ui_port: int = 9201,
    no_ui: bool = True,
):
    """Entry point: create tools, client, and run the event loop."""
    # Merge CLI dirs with saved dirs from config
    server_url = _normalize_server_url(server_url)
    node_name = str(node_name or "").strip()
    saved_dirs = _load_saved_dirs(server_url, node_name)
    all_dirs_raw = list(allowed_dirs) + saved_dirs
    all_dirs = _normalize_dirs(all_dirs_raw)

    sandbox = Sandbox(all_dirs)
    tools = Tools(sandbox, allow_shell=not no_shell)
    client = NodeClient(
        server_url=server_url,
        node_name=node_name,
        tools=tools,
        allowed_dirs=all_dirs,
        gateway_token=gateway_token,
    )

    # Graceful shutdown on Ctrl+C
    loop = asyncio.new_event_loop()

    def shutdown(sig, frame):
        print("\nShutting down...")
        client.stop()
        loop.call_soon_threadsafe(loop.stop)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"feishu-node v0.1.0")
    print(f"  Name:     {node_name}")
    print(f"  Server:   {server_url}")
    print(f"  Dirs:     {', '.join(all_dirs) if all_dirs else '(none — add via --allow-dir)'}")
    print(f"  Shell:    {'enabled' if not no_shell else 'disabled'}")
    if no_ui:
        print("  Web UI:   disabled (use --ui to enable)")

    async def _run():
        tasks = [client.run()]
        if not no_ui:
            ui = WebUI(client, port=ui_port)
            tasks.append(ui.start())
            print(f"  Web UI:   http://127.0.0.1:{ui_port}")
        await asyncio.gather(*tasks)

    try:
        loop.run_until_complete(_run())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
