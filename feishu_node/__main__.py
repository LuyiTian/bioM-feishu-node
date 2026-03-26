"""
CLI entry point for feishu-node.

Usage:
    python -m feishu_node --server ws://central:9200 --name laptop
    python -m feishu_node --server ws://central:9200 --name laptop --allow-dir ~/projects
    python -m feishu_node --server ws://central:9200 --name laptop --no-shell --no-ui
"""

import argparse
import logging
import os
import sys

from .node_client import run_node


def main():
    parser = argparse.ArgumentParser(
        prog="feishu-node",
        description="Remote node client for a Feishu coding agent gateway.",
    )
    parser.add_argument("--server", required=True, help="Central server WebSocket URL (e.g., ws://server:9200)")
    parser.add_argument("--name", required=True, help="Unique name for this node (e.g., laptop, gpu-box)")
    parser.add_argument(
        "--gateway-token",
        default=os.getenv("NODE_WS_GATEWAY_TOKEN", ""),
        help="Optional gateway token for WS handshake (Authorization: Bearer ...).",
    )
    parser.add_argument(
        "--allow-dir",
        action="append",
        default=[],
        dest="allow_dirs",
        help="Directories the agent can access (repeatable). Also manageable via web UI.",
    )
    parser.add_argument("--no-shell", action="store_true", help="Disable shell command execution")
    parser.add_argument("--port", type=int, default=9201, help="Port for the local web UI (default: 9201)")
    parser.add_argument("--no-ui", action="store_true", help="Disable the local web UI")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
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
