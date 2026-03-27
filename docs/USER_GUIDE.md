# Feishu Node User Guide

This guide is for end users who need to connect their own machine to the Feishu coding assistant.

## 1. Big Picture

1. You run `feishu-node` on your machine.
2. Your node connects outbound to `feishu.biom.autos` gateway.
3. In the target Feishu group, you confirm pairing with `/node pair <pairing-code>`.
4. In the same group, you initialize remote root with `/project init remote <node>:<path>`.
5. The assistant can then operate inside your allowed directories.

## 2. What You Need

- Python 3.10+
- Access to your organization's `feishu.biom.autos` website
- A gateway token from an administrator (only if your server enforces gateway auth)
- At least one local folder you want the assistant to access
- Access to the target Feishu group where you will run slash commands

## 3. Install from GitHub

```bash
pip install "git+https://github.com/LuyiTian/bioM-feishu-node.git"
```

Upgrade later:

```bash
pip install --upgrade "git+https://github.com/LuyiTian/bioM-feishu-node.git"
```

## 4. Open `feishu.biom.autos` and Prepare Startup Command

1. Sign in to `feishu.biom.autos`.
2. Go to **Node Pairing** page.
3. Copy the startup command template shown in the page.
4. Set gateway token in your current shell session (recommended):

```bash
read -s -p "Gateway token: " BIOM_GATEWAY_TOKEN; echo
export BIOM_GATEWAY_TOKEN
```

If your server does not require gateway auth, skip this step.

## 5. Start the Node Locally

```bash
feishu-node \
  --server wss://feishu.biom.autos \
  --name <node-name> \
  --allow-dir <absolute-project-path>
```

Notes:
- `--name` should be unique per machine.
- You can repeat `--allow-dir` multiple times.
- Start with one project folder if you are unsure.
- You can still pass token directly if needed: `--gateway-token <token>`.

When started, terminal shows:
- connection target
- allowed directories
- a pairing code (6 characters)

## 6. Confirm Pairing in Feishu Group

In the target Feishu group:

```text
/node pair <pairing-code>
```

## 7. Initialize Remote Root in the Same Group

In the same Feishu group:

```text
/project init remote <node>:<path>
```

Verify:

```text
/project info
```

## 8. Manage Allowed Directories

You can manage allowed folders in two ways:

- At startup with repeated `--allow-dir` flags
- Optional local web UI (disabled by default)

Local UI supports:
- add directory
- remove directory
- browse folders
- view connection status

To use local UI, start node with `--ui`, then open `http://127.0.0.1:9201`.

## 9. Security Boundaries

- Prefer project-level folders, not your whole home directory.
- Keep gateway token private.
- Rotate tokens if leaked.
- Use `--no-shell` in high-security environments.
- Stop the process when not needed.

## 10. Common Commands

Start with shell enabled:

```bash
feishu-node --server wss://feishu.biom.autos --name laptop --allow-dir ~/projects
```

Start with shell disabled:

```bash
feishu-node --server wss://feishu.biom.autos --name laptop --allow-dir ~/projects --no-shell
```

Start with local UI enabled:

```bash
feishu-node --server wss://feishu.biom.autos --name laptop --allow-dir ~/projects --ui
```

Change local UI port:

```bash
feishu-node --server wss://feishu.biom.autos --name laptop --allow-dir ~/projects --ui --port 9301
```

Feishu group commands:

```text
/node pair <pairing-code>
/project init remote <node>:<path>
/project info
```

## 11. Troubleshooting

### "Port is in use"
Use another UI port:

```bash
feishu-node ... --port 9301
```

### Pairing fails
- confirm pairing code is fresh (codes expire quickly)
- run `/node pair <pairing-code>` in the correct target group
- confirm server URL and gateway token are correct
- verify system time is correct

### Remote root not effective
- run `/project init remote <node>:<path>` in the same group after pairing
- run `/project info` and confirm node/path
- verify `<path>` is under node allowed directories

### Node reconnect loops
- check network connectivity to `feishu.biom.autos`
- confirm firewall allows outbound websocket traffic
- verify gateway token is still valid (if enabled)

### Permission denied on files
- add that folder to allowed directories first
- ensure folder exists and your OS user can access it
