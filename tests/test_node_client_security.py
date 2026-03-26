from __future__ import annotations

from pathlib import Path

import pytest

from feishu_node import node_client
from feishu_node.file_ops import run_script
from feishu_node.tools import Sandbox, Tools


def test_sandbox_without_allowed_dirs_is_explicit_error():
    sandbox = Sandbox([])
    with pytest.raises(PermissionError, match="No allowed directories configured"):
        sandbox.resolve("README.md")

    tools = Tools(sandbox)
    result = tools.dispatch("list_directory", {"path": "."})
    assert "No allowed directories configured" in result


def test_run_script_keeps_quoted_args(tmp_path: Path):
    script = tmp_path / "echo_args.py"
    script.write_text("import sys; print(sys.argv)", encoding="utf-8")

    output = run_script(
        str(script),
        args='--name "hello world"',
        cwd=str(tmp_path),
        timeout=10,
    )
    assert "exit_code=0" in output
    assert "hello world" in output


def test_load_config_handles_corrupt_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_dir = tmp_path / "cfg"
    config_file = config_dir / "config.json"
    config_dir.mkdir(parents=True)
    config_file.write_text("{", encoding="utf-8")

    monkeypatch.setattr(node_client, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(node_client, "CONFIG_FILE", config_file)

    loaded = node_client._load_config()
    assert loaded == {"version": node_client.CONFIG_VERSION, "profiles": {}}

    backups = list(config_dir.glob("config.broken-*.json"))
    assert backups, "Expected corrupt config to be moved to a backup file"


def test_saved_dirs_are_scoped_by_server_and_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_dir = tmp_path / "cfg"
    config_file = config_dir / "config.json"

    monkeypatch.setattr(node_client, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(node_client, "CONFIG_FILE", config_file)

    payload = {
        "version": node_client.CONFIG_VERSION,
        "profiles": {
            node_client._profile_key("wss://gateway.example", "node-a"): {
                "server_url": "wss://gateway.example",
                "node_name": "node-a",
                "token": "tok-a",
                "allowed_dirs": ["~/project-a"],
            },
            node_client._profile_key("wss://gateway.example", "node-b"): {
                "server_url": "wss://gateway.example",
                "node_name": "node-b",
                "token": "tok-b",
                "allowed_dirs": ["~/project-b"],
            },
        },
    }
    node_client._save_config(payload)

    dirs_a = node_client._load_saved_dirs("wss://gateway.example", "node-a")
    dirs_b = node_client._load_saved_dirs("wss://gateway.example", "node-b")

    assert len(dirs_a) == 1
    assert len(dirs_b) == 1
    assert dirs_a != dirs_b
