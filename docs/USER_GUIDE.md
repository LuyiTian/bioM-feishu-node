# Feishu Node User Guide

This guide is for end users who need to connect their own machine to the Feishu coding assistant.

## 1. What You Need

- Python 3.10+
- Access to your organization's `feishu.biom` admin website
- A gateway token from an administrator
- At least one local folder you want the assistant to access

## 2. Open `feishu.biom` and Prepare Pairing

1. Sign in to your `feishu.biom` web console.
2. Go to the **Node Pairing** page.
3. Copy the connection command template shown on that page.
4. Replace placeholders with your own values:

```bash
feishu-node \
  --server wss://<gateway-host> \
  --name <my-laptop> \
  --gateway-token <token-from-admin> \
  --allow-dir ~/projects
```

Notes:
- `--name` should be unique per machine.
- You can repeat `--allow-dir` multiple times.
- If you are not sure which folder to allow first, start with one project folder only.

## 3. Start the Node Locally

Run the command in your local terminal.

When the node starts, it prints:
- connection target
- allowed directories
- a **pairing code** (6 characters)

## 4. Confirm Pairing in Website

1. Return to the **Node Pairing** page in `feishu.biom`.
2. Enter the pairing code from terminal.
3. Click confirm.
4. The terminal should show node is connected and authenticated.

## 5. Manage Allowed Directories

You can manage allowed folders in two ways:

- From `feishu.biom` admin pages (recommended for admins)
- From local web UI: `http://127.0.0.1:9201`

Local UI supports:
- add directory
- remove directory
- browse folders
- view connection status

## 6. Safe Configuration Recommendations

- Prefer project-level folders, not your whole home directory.
- Keep gateway token private.
- Rotate tokens if leaked.
- Use `--no-shell` in high-security environments.
- Stop the process when not needed.

## 7. Common Commands

Start with shell enabled:

```bash
feishu-node --server wss://<host> --name laptop --gateway-token <token> --allow-dir ~/projects
```

Start with shell disabled:

```bash
feishu-node --server wss://<host> --name laptop --gateway-token <token> --allow-dir ~/projects --no-shell
```

Change local UI port:

```bash
feishu-node --server wss://<host> --name laptop --gateway-token <token> --port 9301
```

## 8. Troubleshooting

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
- check network connectivity to gateway host
- confirm firewall allows outbound websocket traffic
- verify gateway token is still valid

### Permission denied on files
- add that folder to allowed directories first
- ensure folder exists and your OS user can access it
