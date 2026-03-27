"""
CLI entry point for feishu-node.

Usage:
    python -m feishu_node --server ws://central:9200 --name laptop
    python -m feishu_node --server ws://central:9200 --name laptop --allow-dir ~/projects
    python -m feishu_node --server ws://central:9200 --name laptop --no-shell
    python -m feishu_node --server ws://central:9200 --name laptop --ui
"""

import argparse
import logging
import os
import sys

from .node_client import run_node


def _resolve_gateway_token_env() -> str:
    # Canonical variable name for biom docs.
    # Keep NODE_WS_GATEWAY_TOKEN for backward compatibility.
    return os.getenv("BIOM_GATEWAY_TOKEN", "") or os.getenv("NODE_WS_GATEWAY_TOKEN", "")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feishu-node",
        description="Remote node client for a Feishu coding agent gateway.",
    )
    parser.add_argument("--server", required=True, help="Central server WebSocket URL (e.g., ws://server:9200)")
    parser.add_argument("--name", required=True, help="Unique name for this node (e.g., laptop, gpu-box)")
    parser.add_argument(
        "--gateway-token",
        default=_resolve_gateway_token_env(),
        help="Optional gateway token for WS handshake. Also reads BIOM_GATEWAY_TOKEN (or legacy NODE_WS_GATEWAY_TOKEN).",
    )
    parser.add_argument(
        "--allow-dir",
        action="append",
        default=[],
        dest="allow_dirs",
        help="Directories the agent can access (repeatable).",
    )
    parser.add_argument("--no-shell", action="store_true", help="Disable shell command execution")
    parser.add_argument("--port", type=int, default=9201, help="Port for local web UI when --ui is enabled (default: 9201)")
    parser.add_argument("--ui", dest="no_ui", action="store_false", help="Enable local web UI (disabled by default)")
    # Backward-compatible no-op; UI is already disabled by default.
    parser.add_argument("--no-ui", dest="no_ui", action="store_true", help=argparse.SUPPRESS)
    parser.set_defaults(no_ui=True)
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Validate CLI-provided directories exist
    for d in args.allow_dirs:
        expanded = os.path.expanduser(d)
        if not os.path.isdir(expanded):
            print(f"Error: Directory does not exist: {d}", file=sys.stderr)
            sys.exit(1)

    if args.no_ui and args.port != 9201:
        print("Warning: --port has no effect unless --ui is enabled.", file=sys.stderr)

    run_node(
        server_url=args.server,
        node_name=args.name,
        allowed_dirs=args.allow_dirs,
        gateway_token=args.gateway_token,
        no_shell=args.no_shell,
        ui_port=args.port,
        no_ui=args.no_ui,
    )


if __name__ == "__main__":
    main()
