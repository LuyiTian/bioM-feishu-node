# Feishu Node User Guide

This guide is for end users who need to connect their own machine to the Feishu coding assistant.

## 1. Big Picture

1. You run `feishu-node` on your machine.
2. Your node connects outbound to `feishu.biom.autos` gateway.
3. You confirm pairing in `feishu.biom.autos` web console.
4. Gateway routes Feishu assistant actions to your node.
5. Node only reads/writes inside directories you allow.

## 2. What You Need

- Python 3.10+
- Access to your organization's `feishu.biom.autos` website
- A gateway token from an administrator
- At least one local folder you want the assistant to access

## 3. Install from GitHub

```bash
pip install "git+https://github.com/LuyiTian/bioM-feishu-node.git"
```

Upgrade later:

```bash
pip install --upgrade "git+https://github.com/LuyiTian/bioM-feishu-node.git"
```

## 4. Open `feishu.biom.autos` and Prepare Pairing

1. Sign in to `feishu.biom.autos`.
2. Go to **Node Pairing** page.
3. Copy the setup command template shown in the page.
4. Replace placeholders and run locally:

```bash
feishu-node \
  --server wss://feishu.biom.autos \
  --name <my-laptop> \
  --gateway-token <token-from-admin> \
  --allow-dir ~/projects
```

Notes:
- `--name` should be unique per machine.
- You can repeat `--allow-dir` multiple times.
- Start with one project folder if you are unsure.

## 5. Start the Node Locally

When started, terminal shows:
- connection target
- allowed directories
- a pairing code (6 characters)

## 6. Confirm Pairing in Website

1. Return to the **Node Pairing** page in `feishu.biom.autos`.
2. Enter the pairing code from terminal.
3. Click confirm.
4. The terminal should show node is connected and authenticated.

## 7. Manage Allowed Directories

You can manage allowed folders in two ways:

- From `feishu.biom.autos` admin pages
- From local web UI: `http://127.0.0.1:9201`

Local UI supports:
- add directory
- remove directory
- browse folders
- view connection status

## 8. Security Boundaries

- Prefer project-level folders, not your whole home directory.
- Keep gateway token private.
- Rotate tokens if leaked.
- Use `--no-shell` in high-security environments.
- Stop the process when not needed.

## 9. Common Commands

Start with shell enabled:

```bash
feishu-node --server wss://feishu.biom.autos --name laptop --gateway-token <token> --allow-dir ~/projects
```

Start with shell disabled:

```bash
feishu-node --server wss://feishu.biom.autos --name laptop --gateway-token <token> --allow-dir ~/projects --no-shell
```

Change local UI port:

```bash
feishu-node --server wss://feishu.biom.autos --name laptop --gateway-token <token> --port 9301
```

## 10. Troubleshooting

### "Port is in use"
Use another UI port:

```bash
feishu-node ... --port 9301
```

### Pairing fails
- confirm pairing code is fresh (codes expire quickly)
- confirm server URL and gateway token are correct
- verify system time is correct

### Node reconnect loops
- check network connectivity to `feishu.biom.autos`
- confirm firewall allows outbound websocket traffic
- verify gateway token is still valid

### Permission denied on files
- add that folder to allowed directories first
- ensure folder exists and your OS user can access it
