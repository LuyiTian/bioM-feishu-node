import inspect

from feishu_node.__main__ import _resolve_gateway_token_env, build_parser
from feishu_node.node_client import run_node


def test_resolve_gateway_token_env_prefers_biom(monkeypatch):
    monkeypatch.setenv("BIOM_GATEWAY_TOKEN", "biom-token")
    monkeypatch.setenv("NODE_WS_GATEWAY_TOKEN", "legacy-token")
    assert _resolve_gateway_token_env() == "biom-token"


def test_resolve_gateway_token_env_fallback_legacy(monkeypatch):
    monkeypatch.delenv("BIOM_GATEWAY_TOKEN", raising=False)
    monkeypatch.setenv("NODE_WS_GATEWAY_TOKEN", "legacy-token")
    assert _resolve_gateway_token_env() == "legacy-token"


def test_resolve_gateway_token_env_empty(monkeypatch):
    monkeypatch.delenv("BIOM_GATEWAY_TOKEN", raising=False)
    monkeypatch.delenv("NODE_WS_GATEWAY_TOKEN", raising=False)
    assert _resolve_gateway_token_env() == ""


def test_cli_ui_disabled_by_default():
    parser = build_parser()
    args = parser.parse_args(["--server", "wss://example.com", "--name", "node-a"])
    assert args.no_ui is True


def test_cli_ui_flag_enables_local_ui():
    parser = build_parser()
    args = parser.parse_args(["--server", "wss://example.com", "--name", "node-a", "--ui"])
    assert args.no_ui is False


def test_cli_no_ui_flag_still_accepted_for_backward_compat():
    parser = build_parser()
    args = parser.parse_args(["--server", "wss://example.com", "--name", "node-a", "--no-ui"])
    assert args.no_ui is True


def test_cli_last_flag_wins_for_ui_toggle():
    parser = build_parser()
    args1 = parser.parse_args(["--server", "wss://example.com", "--name", "node-a", "--ui", "--no-ui"])
    args2 = parser.parse_args(["--server", "wss://example.com", "--name", "node-a", "--no-ui", "--ui"])
    assert args1.no_ui is True
    assert args2.no_ui is False


def test_cli_help_exposes_ui_flag_only(capsys):
    parser = build_parser()
    try:
        parser.parse_args(["--help"])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert "--ui" in out
    assert "--no-ui" not in out


def test_run_node_default_ui_is_disabled():
    assert inspect.signature(run_node).parameters["no_ui"].default is True
