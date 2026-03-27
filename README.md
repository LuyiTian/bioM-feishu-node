# bioM Feishu Node

Public remote node client used with `feishu.biom.autos`.

This client runs on a user's machine and connects outbound to the gateway, exposing only explicitly allowed directories.

## Big Picture

1. User installs and runs `feishu-node` on their own machine.
2. `feishu-node` connects to gateway (for example `wss://feishu.biom.autos`).
3. User confirms pairing code in the target Feishu group: `/node pair <pairing-code>`.
4. User initializes remote root in the same group: `/project init remote <node>:<path>`.
5. Gateway routes tool calls from Feishu assistant to the paired node.
6. Node executes only inside allowed directories and returns results to gateway.

## Install (Current: GitHub Direct)

```bash
pip install "git+https://github.com/LuyiTian/bioM-feishu-node.git"
```

Upgrade to latest:

```bash
pip install --upgrade "git+https://github.com/LuyiTian/bioM-feishu-node.git"
```

Run from source:

```bash
python -m feishu_node --help
```

PyPI release is prepared but GitHub direct install is the current default channel.

## Quick Start

Set token once in your shell session (recommended):

```bash
read -s -p "Gateway token: " BIOM_GATEWAY_TOKEN; echo
export BIOM_GATEWAY_TOKEN
```

If your server does not require gateway auth, you can skip this.

Then run:

```bash
feishu-node \
  --server wss://feishu.biom.autos \
  --name <node-name> \
  --allow-dir <absolute-project-path>
```

After startup:
- terminal prints a pairing code
- in the target Feishu group: `/node pair <pairing-code>`
- in the same group: `/project init remote <node>:<path>`
- verify mapping: `/project info`
- node becomes online and reconnects automatically using local saved token
- local Web UI is disabled by default (enable with `--ui` if needed)

## Documentation

- [User Guide](docs/USER_GUIDE.md): end-user onboarding and `feishu.biom.autos` workflow
- [Release Guide](docs/RELEASE.md): optional PyPI publishing path

## Security Notes

- Never paste real gateway tokens in screenshots, tickets, or public chats.
- Prefer `BIOM_GATEWAY_TOKEN` env var instead of putting token directly in command history.
- Local token is stored at `~/.feishu-node/config.json` with restrictive permissions on Linux/macOS.
- The node only accesses directories that you explicitly allow.
- Use `--no-shell` if you want to disable remote command execution.

## CLI

```bash
feishu-node --server <ws/wss url> --name <node-name> [options]
```

Options:
- `--gateway-token <token>`: optional WS handshake bearer token
- env var: `BIOM_GATEWAY_TOKEN` (preferred), `NODE_WS_GATEWAY_TOKEN` (legacy)
- `--allow-dir <path>`: allow one directory (repeatable)
- `--no-shell`: disable shell command execution
- `--ui`: enable local web UI (`127.0.0.1`, disabled by default)
- `--port <int>`: local web UI port when `--ui` is enabled (default `9201`)
- `-v, --verbose`: debug logs

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pytest
```
