#!/usr/bin/env python3
"""
Claude Code Stop Hook → Feishu notification event spooler.

Installed as a Stop hook in ~/.claude/settings.json.
When Claude Code finishes responding, this script:
1. Reads the Stop event JSON from stdin
2. Resolves the current tmux pane via TTY matching
3. Writes a JSON event file to ~/.feishu-node/claude-events/

The feishu-node (with --monitor-claude) picks up the event file,
debounces for 30 seconds, then sends a notification to Feishu.

Anti-recursion: if stop_hook_active is true, exits immediately.

Usage in ~/.claude/settings.json:
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/cc-event-hook.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
"""
import json
import os
import subprocess
import sys
import time


def _controlling_tty():
    """Return this process's controlling terminal path (e.g. /dev/pts/15), or "".

    Claude Code pipes the Stop-event JSON to our stdin, so fd 0 is a pipe — not
    the pane's pty — and os.ttyname(0) raises ENOTTY. The controlling terminal
    survives that redirection, so read it from /proc/self/stat (Linux) where
    field `tty_nr` encodes the device. Fall back to os.ttyname on fd 0/1/2 in
    case one of them happens to be the tty (non-Linux, or unredirected).
    """
    try:
        data = open("/proc/self/stat").read()
        # comm (field 2) may contain spaces/parens — split after the last ')'.
        rest = data[data.rindex(")") + 2:].split()
        tty_nr = int(rest[4])  # state ppid pgrp session tty_nr
        if tty_nr:
            major = (tty_nr >> 8) & 0xFFF
            minor = (tty_nr & 0xFF) | ((tty_nr >> 12) & 0xFFF00)
            if major == 136:  # UNIX98 pseudo-terminal slaves -> /dev/pts/N
                return "/dev/pts/%d" % minor
    except (OSError, ValueError, IndexError):
        pass
    for fd in (0, 1, 2):
        try:
            return os.ttyname(fd)
        except OSError:
            continue
    return ""


def resolve_tmux_target():
    """Find the tmux pane for this process via TTY matching.
    Returns 'session:window.pane' or '' if not in tmux."""
    tty = _controlling_tty()
    if not tty:
        return ""

    try:
        result = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#{pane_tty} #{session_name}:#{window_index}.#{pane_index}"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        for line in result.stdout.strip().splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0] == tty:
                return parts[1]
    except Exception:
        pass
    return ""


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # Never block Claude Code

    # Anti-recursion: if stop_hook_active is true, exit immediately
    if event.get("stop_hook_active"):
        sys.exit(0)

    cwd = event.get("cwd", "")
    transcript_path = event.get("transcript_path", "")
    session_id = event.get("session_id", "")

    # Normalize paths
    if cwd:
        cwd = os.path.realpath(cwd)
    if transcript_path:
        transcript_path = os.path.realpath(transcript_path)

    # Resolve tmux target
    tmux_target = resolve_tmux_target()

    # Write event file to spool directory
    spool_dir = os.path.expanduser("~/.feishu-node/claude-events")
    os.makedirs(spool_dir, exist_ok=True)

    event_data = {
        "session_id": session_id,
        "cwd": cwd,
        "transcript_path": transcript_path,
        "tmux_target": tmux_target,
        "timestamp": time.time(),
    }

    event_file = os.path.join(spool_dir, f"{int(time.time() * 1000)}.json")
    try:
        with open(event_file, "w") as f:
            json.dump(event_data, f)
    except Exception:
        pass  # Never block Claude Code

    sys.exit(0)


if __name__ == "__main__":
    main()
