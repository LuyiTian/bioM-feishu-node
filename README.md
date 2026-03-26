# bioM Feishu Node

Public remote node client for Feishu coding-agent gateways.

This client runs on a user's machine and connects outbound to your Feishu agent gateway, exposing only explicitly allowed directories.

## Install

```bash
pip install biom-feishu-node
```

If PyPI package is not published yet, install from GitHub:

```bash
pip install "git+https://github.com/LuyiTian/bioM-feishu-node.git"
```

Or run directly from source:

```bash
python -m feishu_node --help
```

## Quick Start

```bash
feishu-node \
  --server wss://<your-gateway-host> \
  --name <your-node-name> \
  --gateway-token <gateway-token> \
  --allow-dir ~/projects
```

After startup:
- the terminal shows a pairing code
- submit that code in the Feishu admin site
- once paired, the node reconnects automatically using a saved local token

## User Guide

See the step-by-step guide:
- [User Guide](docs/USER_GUIDE.md)

It includes:
- how to use the `feishu.biom` website
- pairing workflow
- directory permission setup
- security recommendations

## Security Notes

- Never paste real gateway tokens in screenshots, tickets, or public chats.
- The node stores token locally at `~/.feishu-node/config.json` with restrictive permissions on Linux/macOS.
- The node only accesses directories that you explicitly allow.
- Use `--no-shell` if you want to disable remote command execution.

## CLI

```bash
feishu-node --server <ws/wss url> --name <node-name> [options]
```

Options:
- `--gateway-token <token>`: optional WS handshake bearer token
- `--allow-dir <path>`: allow one directory (repeatable)
- `--no-shell`: disable shell command execution
- `--no-ui`: disable local web UI
- `--port <int>`: local web UI port (default `9201`)
- `-v, --verbose`: debug logs

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pytest
```
