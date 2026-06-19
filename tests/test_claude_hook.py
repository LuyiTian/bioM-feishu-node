"""Tests for unattended Claude Code hook installation (feishu_node.claude_hook).

When a node runs with --monitor-claude it should self-install the Stop hook so
deployment is hands-off: write ~/.claude/hooks/cc-event-hook.py, merge a Stop
hook into ~/.claude/settings.json (idempotently, never clobbering existing
config), and create the event spool dir. Hook fixes then ship via normal node
auto-upgrade — no manual re-copy.
"""

from __future__ import annotations

import json

from feishu_node import claude_hook


def _settings(home):
    return json.loads((home / ".claude" / "settings.json").read_text())


def test_fresh_install_creates_hook_settings_and_spool(tmp_path):
    res = claude_hook.install_claude_hook(home=tmp_path)

    hook = tmp_path / ".claude" / "hooks" / "cc-event-hook.py"
    assert hook.exists()
    assert hook.read_text() == claude_hook.hook_source()
    assert (tmp_path / ".feishu-node" / "claude-events").is_dir()

    data = _settings(tmp_path)
    cmds = [
        h.get("command")
        for entry in data["hooks"]["Stop"]
        for h in entry.get("hooks", [])
    ]
    assert claude_hook.STOP_HOOK_COMMAND in cmds
    assert res["hook_written"] and res["settings_updated"]


def test_idempotent_no_duplicate_stop_hook(tmp_path):
    claude_hook.install_claude_hook(home=tmp_path)
    res2 = claude_hook.install_claude_hook(home=tmp_path)

    data = _settings(tmp_path)
    matching = [
        h
        for entry in data["hooks"]["Stop"]
        for h in entry.get("hooks", [])
        if h.get("command") == claude_hook.STOP_HOOK_COMMAND
    ]
    assert len(matching) == 1
    assert not res2["settings_updated"]  # nothing changed second time


def test_preserves_existing_unrelated_settings_and_hooks(tmp_path):
    cdir = tmp_path / ".claude"
    cdir.mkdir(parents=True)
    (cdir / "settings.json").write_text(
        json.dumps(
            {
                "model": "claude-opus-4-8",
                "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}]},
            }
        )
    )

    claude_hook.install_claude_hook(home=tmp_path)

    data = _settings(tmp_path)
    assert data["model"] == "claude-opus-4-8"  # untouched
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "echo hi"  # preserved
    stop_cmds = [h.get("command") for e in data["hooks"]["Stop"] for h in e.get("hooks", [])]
    assert claude_hook.STOP_HOOK_COMMAND in stop_cmds  # added


def test_corrupt_settings_not_clobbered(tmp_path):
    cdir = tmp_path / ".claude"
    cdir.mkdir(parents=True)
    (cdir / "settings.json").write_text("{ this is not valid json ")

    res = claude_hook.install_claude_hook(home=tmp_path)

    # The unparseable file is left intact (we never destroy user config)...
    assert (cdir / "settings.json").read_text() == "{ this is not valid json "
    assert res["settings_skipped"] is True
    # ...but the hook script + spool are still installed (best-effort).
    assert (cdir / "hooks" / "cc-event-hook.py").exists()


def test_updates_hook_when_content_differs(tmp_path):
    hooks = tmp_path / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "cc-event-hook.py").write_text("# stale old hook\n")

    res = claude_hook.install_claude_hook(home=tmp_path)

    assert (hooks / "cc-event-hook.py").read_text() == claude_hook.hook_source()
    assert res["hook_written"] is True


def test_hook_source_matches_package_module(tmp_path):
    # hook_source() must be the exact source of the shipped cc_event_hook module,
    # so an installed hook is byte-identical to what the package was tested with.
    import importlib.resources as ir

    pkg = ir.files("feishu_node").joinpath("cc_event_hook.py").read_text()
    assert claude_hook.hook_source() == pkg


def test_never_raises(tmp_path):
    # Even pointed at a path it can partially handle, it returns a dict, never raises.
    res = claude_hook.install_claude_hook(home=tmp_path / "deep" / "nested" / "home")
    assert isinstance(res, dict)
