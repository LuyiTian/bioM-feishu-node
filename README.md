# bioM Feishu Node

Public remote node client used with `feishu.biom.autos`.

This client runs on a user's machine and connects outbound to the gateway, exposing only explicitly allowed directories.

## Big Picture

1. User installs `feishu-node` on their own machine.
2. User runs `feishu-node-launcher`, which spawns and supervises `feishu-node`,
   restarts it on crash, and once per day auto-upgrades to the latest signed
   release tag.
3. `feishu-node` connects to gateway (for example `wss://feishu.biom.autos`).
4. User confirms pairing code in the target Feishu group: `/node pair <pairing-code>`.
5. User initializes remote root in the same group: `/project init remote <node>:<path>`.
6. Gateway routes tool calls from Feishu assistant to the paired node.
7. Node executes only inside allowed directories and returns results to gateway.

## Install

Distribution is direct from GitHub. **There is no PyPI package.** Pin to a release tag in production:

```bash
pip install "git+https://github.com/LuyiTian/bioM-feishu-node.git@v0.2.0"
```

Latest from `main` (development, not auto-upgrade-trusted):

```bash
pip install --upgrade --force-reinstall \
  "git+https://github.com/LuyiTian/bioM-feishu-node.git"
```

> **Already running an older node?** See [UPGRADE.md](UPGRADE.md) for a
> step-by-step cheat sheet (also designed to be runnable by an AI coding
> agent on the target host).

## Quick Start

Set token once in your shell session (recommended):

```bash
read -s -p "Gateway token: " BIOM_GATEWAY_TOKEN; echo
export BIOM_GATEWAY_TOKEN
```

If your server does not require gateway auth, skip this.

Then run under the launcher (recommended — gives you crash-restart and
auto-upgrade for free):

```bash
feishu-node-launcher -- \
  --server wss://feishu.biom.autos \
  --name <node-name> \
  --allow-dir <absolute-project-path>
```

After startup:
- terminal prints a pairing code (from the child `feishu-node` process)
- in the target Feishu group: `/node pair <pairing-code>`
- in the same group: `/project init remote <node>:<path>`
- verify mapping: `/project info`
- node becomes online and reconnects automatically using local saved token

Want it to survive logout? Use `tmux new -s feishu-node`, or register a
native auto-start service (see "Auto-upgrade & Service" below).

Don't want the launcher? You can still run `feishu-node` directly with the
same flags — you just lose auto-upgrade and crash-restart, and you'll
need to upgrade by hand each release.

## Auto-upgrade & Service

The launcher upgrades on two channels, both **tag-only** for safety:

- **Pull**: once every 24 h it queries
  `https://api.github.com/repos/LuyiTian/bioM-feishu-node/releases/latest`
  and accepts only tags shaped `vX.Y.Z`. Main-branch commits are never
  auto-installed.
- **Push**: bot operator runs `/node upgrade [<node_id>]` in a Feishu group;
  the node receives a control message, exits with code 75, and the launcher
  pip-installs the latest tag and respawns.

Register as an OS-native service (no third-party dependencies):

```bash
feishu-node-launcher install-service --service-name <short-name> -- \
  --server wss://feishu.biom.autos \
  --name <node-name> \
  --allow-dir <absolute-project-path>
```

Per-OS effect — Linux: systemd user unit (no sudo); macOS: LaunchAgent
(no root); Windows: Task Scheduler ONLOGON. Uninstall mirror:
`feishu-node-launcher uninstall-service --service-name <short-name>`.

Disable auto-upgrade on a specific node: `--no-auto-upgrade`.

## Documentation

- [UPGRADE.md](UPGRADE.md): cheat sheet for upgrading an existing node (agent-readable)
- [User Guide](docs/USER_GUIDE.md): end-user onboarding and `feishu.biom.autos` workflow
- [Operations Guide](docs/OPERATIONS.md): pairing, multi-folder strategy, service install, agent handoff
- [Local Runbook Template](docs/LOCAL_RUNBOOK_TEMPLATE.md): template for machine-specific notes that should stay out of git
- [Release Guide](docs/RELEASE.md): how to cut a new `vX.Y.Z` tag

## Security Notes

- Never paste real gateway tokens in screenshots, tickets, or public chats.
- Prefer `BIOM_GATEWAY_TOKEN` env var instead of putting token directly in command history.
- Local token is stored at `~/.feishu-node/config.json` with restrictive permissions on Linux/macOS.
- The node only accesses directories that you explicitly allow.
- Use `--no-shell` if you want to disable remote command execution.
- Auto-upgrade trusts whoever can push `vX.Y.Z` tags to the public repo —
  same trust level as `pip install git+...`. Protect tag-push permissions
  on the GitHub side (branch/tag protection) accordingly.

## CLI

### `feishu-node-launcher` (recommended)

```bash
feishu-node-launcher [LAUNCHER OPTIONS] -- [FEISHU-NODE OPTIONS]
```

Launcher options:
- `--repo <owner>/<repo>`: override the upgrade source (default `LuyiTian/bioM-feishu-node`)
- `--check-interval-seconds <N>`: poll cadence (default `86400` = 1 day)
- `--no-auto-upgrade`: disable GitHub polling; still respects child exit 75
- `-v, --verbose`: debug logs

Subcommands:
- `install-service --service-name <short> -- [FEISHU-NODE OPTIONS]`: register OS-native auto-start
- `uninstall-service --service-name <short>`: remove what `install-service` registered
- `run`: explicit form of the default (run the launcher loop)

### `feishu-node` (the worker, usually invoked by the launcher)

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
