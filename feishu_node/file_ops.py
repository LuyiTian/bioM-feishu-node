"""
Pure file operations — single implementation shared by local skills and remote nodes.

Every function:
- Takes an **absolute path** (already resolved/sandboxed by caller)
- Returns a **string** result
- Has **zero dependencies** beyond stdlib
- Handles cross-platform concerns (CRLF, path separators)
"""

import fnmatch
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path


# ── Filesystem ──────────────────────────────────────────────────


def list_directory(path: str, recursive: bool = False) -> str:
    """List files/directories. Returns tab-separated lines: kind\\tsize\\tname."""
    if not os.path.isdir(path):
        return f"Error: Not a directory: {path}"

    lines: list[str] = []
    if recursive:
        for root, dirs, files in os.walk(path):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "node_modules"))
            rel = os.path.relpath(root, path)
            for d in dirs:
                entry_path = d if rel == "." else os.path.join(rel, d)
                lines.append(f"dir\t0\t{entry_path}/")
            for name in sorted(files):
                fp = os.path.join(root, name)
                try:
                    size = os.path.getsize(fp)
                except OSError:
                    size = 0
                entry_path = name if rel == "." else os.path.join(rel, name)
                lines.append(f"file\t{size}\t{entry_path}")
                if len(lines) > 2000:
                    lines.append(f"... truncated ({len(lines)}+ entries)")
                    return "\n".join(lines)
    else:
        try:
            entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name))
        except PermissionError:
            return f"Error: Permission denied: {path}"
        for entry in entries:
            kind = "dir" if entry.is_dir() else "file"
            try:
                size = entry.stat().st_size if entry.is_file() else 0
            except OSError:
                size = 0
            lines.append(f"{kind}\t{size}\t{entry.name}")

    return "\n".join(lines) if lines else "(empty directory)"


def read_file(path: str, limit: int = 50000) -> str:
    """Read file content as text. Returns raw content (no line numbers)."""
    if not os.path.isfile(path):
        return f"Error: File not found: {path}"
    try:
        content = open(path, "r", errors="replace").read()
        if len(content) > limit:
            return content[:limit] + "\n\n... (truncated, file too large)"
        return content
    except Exception as e:
        return f"Error reading {path}: {e}"


def write_file(path: str, content: str) -> str:
    """Write content to file. Creates parent directories."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return f"Written {len(content)} bytes to {path}"


def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Edit file with string replacement. First occurrence only. Handles CRLF."""
    if not os.path.isfile(path):
        return f"Error: File not found: {path}"
    # Preserve original line endings
    content = open(path, "r", newline="", errors="replace").read()
    # LLM sends LF-only old_text, but file might have CRLF
    search = old_text
    replace = new_text
    if "\r\n" in content and "\r\n" not in old_text:
        search = old_text.replace("\n", "\r\n")
        replace = new_text.replace("\n", "\r\n")
    if search not in content:
        return f"Error: old_text not found in {path}"
    new_content = content.replace(search, replace, 1)
    with open(path, "w", newline="") as f:
        f.write(new_content)
    return f"Edited: {path}"


def apply_edit_blocks(path: str, edit_blocks: str) -> str:
    """Apply multiple SEARCH/REPLACE blocks to a file in one call.

    Each block has the format:
        <<<<<<< SEARCH
        (exact text to find)
        =======
        (replacement text)
        >>>>>>> REPLACE

    Multiple blocks are applied in order. All blocks must match or the
    entire operation is aborted (atomic).
    """
    if not os.path.isfile(path):
        return f"Error: File not found: {path}"

    # Parse edit blocks
    blocks = []
    parts = edit_blocks.split("<<<<<<< SEARCH")
    for part in parts[1:]:  # skip before first marker
        if "=======" not in part or ">>>>>>> REPLACE" not in part:
            return "Error: Malformed edit block. Expected <<<<<<< SEARCH ... ======= ... >>>>>>> REPLACE"
        search_section, rest = part.split("=======", 1)
        replace_section = rest.split(">>>>>>> REPLACE", 1)[0]
        # Strip the leading/trailing newline that comes from the marker lines
        search_text = search_section.strip("\n")
        replace_text = replace_section.strip("\n")
        blocks.append((search_text, replace_text))

    if not blocks:
        return "Error: No edit blocks found"

    content = open(path, "r", newline="", errors="replace").read()
    is_crlf = "\r\n" in content
    next_content = content

    # Validate and preview sequentially so later blocks see earlier edits.
    for i, (search_text, replace_text) in enumerate(blocks):
        search = search_text
        replace = replace_text
        if is_crlf and "\r\n" not in search_text:
            search = search_text.replace("\n", "\r\n")
            replace = replace_text.replace("\n", "\r\n")
        if search not in next_content:
            return f"Error: Block {i + 1} search text not found in {path}"
        next_content = next_content.replace(search, replace, 1)

    with open(path, "w", newline="") as f:
        f.write(next_content)
    return f"Applied {len(blocks)} edit(s) to {path}"


def search_content(path: str, pattern: str, glob_pattern: str = "*", max_results: int = 100) -> str:
    """Grep-like search: find regex pattern in files matching glob under path."""
    if not os.path.isdir(path):
        return f"Error: Not a directory: {path}"

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: Invalid regex: {e}"

    results: list[str] = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "node_modules")]
        for name in files:
            if not fnmatch.fnmatch(name, glob_pattern):
                continue
            fp = os.path.join(root, name)
            rel = os.path.relpath(fp, path)
            try:
                with open(fp, "r", errors="replace") as f:
                    for lineno, line in enumerate(f, 1):
                        if regex.search(line):
                            results.append(f"{rel}:{lineno}: {line.rstrip()}")
                            if len(results) >= max_results:
                                results.append(f"... truncated at {max_results} results")
                                return "\n".join(results)
            except (PermissionError, OSError):
                continue

    return "\n".join(results) if results else f"No matches for '{pattern}' in {path}"


def glob_files(path: str, pattern: str) -> str:
    """Find files matching a glob pattern under path."""
    matches = sorted(str(p.relative_to(path)) for p in Path(path).rglob(pattern))
    if len(matches) > 500:
        matches = matches[:500]
        matches.append("... truncated at 500 results")
    return "\n".join(matches) if matches else f"No files matching '{pattern}' in {path}"


def file_info(path: str) -> str:
    """Return JSON metadata about a file or directory."""
    if not os.path.exists(path):
        return f"Error: Path not found: {path}"
    stat = os.stat(path)
    return json.dumps(
        {
            "path": path,
            "type": "directory" if os.path.isdir(path) else "file",
            "size": stat.st_size,
            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
            "permissions": oct(stat.st_mode)[-3:],
        }
    )


def environment_info(dirs: list[str] | None = None, shell_enabled: bool = True) -> str:
    """Return JSON with system environment details."""
    info = {
        "os": platform.system(),
        "os_version": platform.version(),
        "arch": platform.machine(),
        "python": sys.version.split()[0],
        "hostname": platform.node(),
        "cwd": os.getcwd(),
        "shell_enabled": shell_enabled,
    }
    if dirs:
        info["allowed_dirs"] = dirs
        try:
            info["disk_free_gb"] = round(shutil.disk_usage(dirs[0]).free / (1024**3), 1)
        except OSError:
            pass
    return json.dumps(info)


# ── Command Execution ───────────────────────────────────────────


def run_command(command: str, cwd: str = ".", timeout: int = 120) -> str:
    """Execute a shell command. Cross-platform (bash on Linux/Mac, cmd on Windows)."""
    if not os.path.isdir(cwd):
        return f"Error: Working directory not found: {cwd}"

    if platform.system() == "Windows":
        shell_cmd = ["cmd", "/c", command]
    else:
        shell_candidates = [
            os.environ.get("SHELL", "").strip(),
            "/bin/bash",
            "/bin/sh",
        ]
        shell_path = next((s for s in shell_candidates if s and os.path.exists(s) and os.access(s, os.X_OK)), "")
        if not shell_path:
            return "Error: No shell executable found (tried SHELL, /bin/bash, /bin/sh)"
        shell_cmd = [shell_path, "-c", command]

    try:
        result = subprocess.run(
            shell_cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        return f"exit_code={result.returncode}\n{output[:50000]}"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


def run_script(path: str, args: str = "", cwd: str = ".", timeout: int = 60) -> str:
    """Run a Python script. Uses subprocess list args (no shell interpolation)."""
    if not os.path.isfile(path):
        return f"Error: Script not found: {path}"
    if not os.path.isdir(cwd):
        return f"Error: Working directory not found: {cwd}"

    cmd = [sys.executable, path]
    if args:
        try:
            cmd.extend(shlex.split(args, posix=(platform.system() != "Windows")))
        except ValueError as e:
            return f"Error: Invalid script args: {e}"

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        return f"exit_code={result.returncode}\n{output[:50000]}"
    except subprocess.TimeoutExpired:
        return f"Error: Script timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"
