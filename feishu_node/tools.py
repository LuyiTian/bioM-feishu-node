"""
Filesystem and command tools for the remote node.

All tools operate within sandboxed directories (--allow-dir).
Path traversal outside allowed directories is blocked.

Tool implementations live in file_ops.py — this module adds sandboxing and dispatch.
"""

import base64
import json
import os
from typing import Optional

from . import file_ops


class Sandbox:
    """Restricts all file access to explicitly allowed directories."""

    def __init__(self, allowed_dirs: list[str]):
        self.allowed_dirs = [os.path.realpath(os.path.expanduser(d)) for d in allowed_dirs]

    def add_dir(self, path: str) -> None:
        resolved = os.path.realpath(os.path.expanduser(path))
        if resolved not in self.allowed_dirs:
            self.allowed_dirs.append(resolved)

    def remove_dir(self, path: str) -> None:
        resolved = os.path.realpath(os.path.expanduser(path))
        self.allowed_dirs = [d for d in self.allowed_dirs if d != resolved]

    def resolve(self, path: str) -> str:
        """Resolve path and verify it's under an allowed directory."""
        if not self.allowed_dirs:
            raise PermissionError(
                "No allowed directories configured. Add one via --allow-dir or the local web UI."
            )
        expanded = os.path.expanduser(path)
        if not os.path.isabs(expanded):
            # Relative paths resolve against the first allowed dir
            expanded = os.path.join(self.allowed_dirs[0], expanded)
        resolved = os.path.realpath(expanded)
        if not any(resolved == d or resolved.startswith(d + os.sep) for d in self.allowed_dirs):
            raise PermissionError(f"Path outside allowed directories: {path}")
        return resolved

    def resolve_cwd(self, cwd: str) -> str:
        """Resolve a working directory path."""
        resolved = self.resolve(cwd)
        if not os.path.isdir(resolved):
            raise NotADirectoryError(f"Not a directory: {cwd}")
        return resolved


class Tools:
    """Remote node tool implementations. Thin wrappers over file_ops with sandboxing."""

    def __init__(self, sandbox: Sandbox, allow_shell: bool = True):
        self.sandbox = sandbox
        self.allow_shell = allow_shell

    # ── Filesystem ──────────────────────────────────────────────────

    def list_directory(self, path: str = ".", recursive: bool = False) -> str:
        resolved = self.sandbox.resolve(path)
        return file_ops.list_directory(resolved, recursive=recursive)

    def read_file(self, path: str, offset: int = 0, limit: int = 50000) -> str:
        resolved = self.sandbox.resolve(path)
        return file_ops.read_file(resolved, limit=limit)

    def read_file_bytes(self, path: str, max_bytes: int = 5 * 1024 * 1024) -> str:
        """Read file as base64. For binary files and file transfer."""
        resolved = self.sandbox.resolve(path)
        if not os.path.isfile(resolved):
            return json.dumps({"error": f"File not found: {path}"})
        size = os.path.getsize(resolved)
        if size > max_bytes:
            return json.dumps({"error": f"File too large: {size} bytes (max {max_bytes})"})
        with open(resolved, "rb") as f:
            data = f.read()
        return json.dumps({"size": len(data), "encoding": "base64", "data": base64.b64encode(data).decode()})

    def write_file(self, path: str, content: str) -> str:
        resolved = self.sandbox.resolve(path)
        return file_ops.write_file(resolved, content)

    def edit_file(self, path: str, old_text: str, new_text: str) -> str:
        resolved = self.sandbox.resolve(path)
        return file_ops.edit_file(resolved, old_text, new_text)

    def apply_edit_blocks(self, path: str, edit_blocks: str) -> str:
        resolved = self.sandbox.resolve(path)
        return file_ops.apply_edit_blocks(resolved, edit_blocks)

    def search_content(self, path: str, pattern: str, glob: str = "*", max_results: int = 100) -> str:
        resolved = self.sandbox.resolve(path)
        return file_ops.search_content(resolved, pattern, glob_pattern=glob, max_results=max_results)

    def glob_files(self, path: str, pattern: str) -> str:
        resolved = self.sandbox.resolve(path)
        return file_ops.glob_files(resolved, pattern)

    def file_info(self, path: str) -> str:
        resolved = self.sandbox.resolve(path)
        return file_ops.file_info(resolved)

    def environment_info(self) -> str:
        return file_ops.environment_info(dirs=self.sandbox.allowed_dirs, shell_enabled=self.allow_shell)

    # ── Command Execution ───────────────────────────────────────────

    def run_command(self, command: str, cwd: str = ".", timeout: int = 120) -> str:
        if not self.allow_shell:
            return "Error: Shell access is disabled on this node (--no-shell)"
        resolved_cwd = self.sandbox.resolve_cwd(cwd)
        return file_ops.run_command(command, resolved_cwd, timeout)

    def run_script(self, path: str, args: str = "", cwd: str = ".", timeout: int = 60) -> str:
        if not self.allow_shell:
            return "Error: Shell access is disabled on this node (--no-shell)"
        resolved = self.sandbox.resolve(path)
        resolved_cwd = self.sandbox.resolve_cwd(cwd)
        return file_ops.run_script(resolved, args, resolved_cwd, timeout)

    # ── File Transfer ───────────────────────────────────────────────

    def receive_file(self, path: str, content_b64: str) -> str:
        """Write a base64-encoded file to disk. Used for transferring files from central server."""
        resolved = self.sandbox.resolve(path)
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        data = base64.b64decode(content_b64)
        with open(resolved, "wb") as f:
            f.write(data)
        return f"Received {len(data)} bytes -> {path}"

    # ── Dispatch ────────────────────────────────────────────────────

    def dispatch(self, tool: str, args: dict) -> str:
        """Route a tool call to the appropriate method."""
        method = getattr(self, tool, None)
        if method is None:
            return f"Error: Unknown tool: {tool}"
        try:
            return method(**args)
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error executing {tool}: {type(e).__name__}: {e}"
