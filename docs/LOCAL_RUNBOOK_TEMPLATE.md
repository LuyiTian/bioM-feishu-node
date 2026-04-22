# Local Runbook Template

Copy this file to `docs/local/<machine-or-owner>.md` and fill it in.

The `docs/local/` directory is gitignored on purpose. It is for machine-specific notes that should stay local.

## Machine

- Hostname:
- Owner:
- Workspace root:
- Repo path:
- Virtualenv path:
- Gateway URL:
- Gateway auth required: yes or no

## Node Inventory

### Node 1

- Node name:
- Allowed dirs:
- Feishu group:
- tmux session:
- Log file:
- Shell enabled: yes or no
- Pairing completed: yes or no

Start command:

```bash
```

Health check:

```bash
```

### Node 2

- Node name:
- Allowed dirs:
- Feishu group:
- tmux session:
- Log file:
- Shell enabled: yes or no
- Pairing completed: yes or no

Start command:

```bash
```

Health check:

```bash
```

## Feishu Commands

Pair:

```text
/node pair <pairing-code>
```

Bind remote root:

```text
/project init remote <node>:<path>
```

Inspect current remote:

```text
/project info
```

## Recovery Notes

- What to restart first:
- Where pairing code appears:
- Expected healthy log lines:
- Anything special about this machine:
