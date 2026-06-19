"""Unattended installation of the Claude Code Stop hook.

A node started with ``--monitor-claude`` calls :func:`install_claude_hook` on
startup so the whole pipeline is hands-off — no human copies scripts or edits
``~/.claude/settings.json``. Because the hook source is shipped *inside* the
package (``feishu_node/cc_event_hook.py``), hook fixes ride the normal node
auto-upgrade: a new release re-installs the updated hook on next start.

Everything here is best-effort and idempotent: it never raises (a failure to
install must not take the node down), never duplicates the Stop hook, and never
overwrites or destroys unrelated user config.
"""

from __future__ import annotations

import importlib.resources as _ir
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# The command Claude Code runs on every Stop event. Installed into the user's
# ~/.claude/settings.json. Kept as a "~"-relative path so it is portable across
# users/homes (Claude Code expands ~).
STOP_HOOK_COMMAND = "python3 ~/.claude/hooks/cc-event-hook.py"
_HOOK_TIMEOUT_S = 5


def hook_source() -> str:
    """Return the canonical hook script text shipped with this package."""
    return _ir.files("feishu_node").joinpath("cc_event_hook.py").read_text(encoding="utf-8")


def _stop_hook_present(settings: dict) -> bool:
    for entry in settings.get("hooks", {}).get("Stop", []) or []:
        if not isinstance(entry, dict):
            continue
        for h in entry.get("hooks", []) or []:
            if isinstance(h, dict) and (h.get("command") or "").strip() == STOP_HOOK_COMMAND:
                return True
    return False


def install_claude_hook(home: Optional[os.PathLike] = None) -> dict:
    """Idempotently install the Stop hook, settings entry, and spool dir.

    Returns a summary dict; never raises. Keys: ``hook_written``,
    ``settings_updated``, ``spool_created``, ``settings_skipped``.
    """
    result = {"hook_written": False, "settings_updated": False, "spool_created": False, "settings_skipped": False}
    home = Path(home) if home is not None else Path.home()

    # 1. Event spool dir (mirrors what the monitor would create anyway).
    try:
        spool = home / ".feishu-node" / "claude-events"
        if not spool.exists():
            spool.mkdir(parents=True, exist_ok=True)
            result["spool_created"] = True
    except OSError as e:
        logger.warning("claude_hook: could not create spool dir: %s", e)

    # 2. Hook script — write only if missing or stale (so upgrades refresh it).
    try:
        hooks_dir = home / ".claude" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook_path = hooks_dir / "cc-event-hook.py"
        src = hook_source()
        current = hook_path.read_text(encoding="utf-8") if hook_path.exists() else None
        if current != src:
            hook_path.write_text(src, encoding="utf-8")
            hook_path.chmod(0o755)
            result["hook_written"] = True
    except OSError as e:
        logger.warning("claude_hook: could not write hook script: %s", e)

    # 3. settings.json Stop hook — idempotent merge, never clobber on parse error.
    try:
        settings_path = home / ".claude" / "settings.json"
        settings: dict = {}
        if settings_path.exists():
            raw = settings_path.read_text(encoding="utf-8")
            try:
                settings = json.loads(raw) if raw.strip() else {}
            except ValueError:
                logger.warning("claude_hook: %s is not valid JSON; leaving it untouched", settings_path)
                result["settings_skipped"] = True
                return result
        if not isinstance(settings, dict):
            logger.warning("claude_hook: %s is not a JSON object; leaving it untouched", settings_path)
            result["settings_skipped"] = True
            return result

        if not _stop_hook_present(settings):
            hooks = settings.setdefault("hooks", {})
            stop = hooks.setdefault("Stop", [])
            if not isinstance(stop, list):
                logger.warning("claude_hook: settings.hooks.Stop is not a list; leaving settings untouched")
                result["settings_skipped"] = True
                return result
            stop.append(
                {"matcher": "", "hooks": [{"type": "command", "command": STOP_HOOK_COMMAND, "timeout": _HOOK_TIMEOUT_S}]}
            )
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            if settings_path.exists():
                shutil.copy2(settings_path, settings_path.with_name("settings.json.feishu-bak"))
            tmp = settings_path.with_name("settings.json.tmp")
            tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, settings_path)  # atomic
            result["settings_updated"] = True
    except OSError as e:
        logger.warning("claude_hook: could not update settings.json: %s", e)

    return result


def main() -> int:
    """CLI entry point (``feishu-node-install-hook``) for manual installation."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    res = install_claude_hook()
    print(f"Claude Code hook install: {res}")
    print(f"  hook  : {Path.home() / '.claude' / 'hooks' / 'cc-event-hook.py'}")
    print(f"  spool : {Path.home() / '.feishu-node' / 'claude-events'}")
    print("  Stop hook registered in ~/.claude/settings.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
