# Feishu Node Operations Guide

This document is the tracked, general-purpose operations guide for `bioM-feishu-node`.

Use it for:

- initial node setup
- pairing a machine into a Feishu group
- deciding whether to use one node or many
- handing the task to another coding agent

Do not put machine-specific secrets, pairing codes, or local process notes here. Keep those in a local runbook under `docs/local/`, which is gitignored.

## Core Model

The deployment model has three separate concepts:

1. A local `feishu-node` process
2. A node identity: `server_url + node_name`
3. A Feishu group remote root: `<node>:<path>`

Important consequences:

- Pairing is attached to a node identity, not directly to a folder.
- A node can expose one or more local folders through repeated `--allow-dir`.
- A Feishu group chooses one concrete remote root with `/project init remote <node>:<path>`.
- Starting a new node does not stop or invalidate an existing node unless you stop that process yourself.

The local persistent profile lives in `~/.feishu-node/config.json` and stores:

- `server_url`
- `node_name`
- saved node token
- `allowed_dirs`

## Recommended Layout

Both layouts are supported.

### Option A: One node per project or group

Example:

```bash
feishu-node --server wss://feishu.biom.autos --name megatron-nanobody-ai --allow-dir /path/to/nanobody_ai
feishu-node --server wss://feishu.biom.autos --name megatron-rvq-train --allow-dir /path/to/rvq_train
```

Use this when:

- different Feishu groups should stay isolated
- different coding agents work on different repos
- you want smaller permission scope
- you want simpler troubleshooting

This is the default recommendation.

### Option B: One node with multiple folders

Example:

```bash
feishu-node \
  --server wss://feishu.biom.autos \
  --name megatron-workspace \
  --allow-dir /path/to/nanobody_ai \
  --allow-dir /path/to/rvq_train
```

Use this when:

- one operator owns several related repos
- you want fewer long-running processes
- the same trust boundary is acceptable across folders

Tradeoffs:

- wider file access if the node is compromised or misused
- easier to confuse projects when using relative paths
- harder to explain ownership across multiple Feishu groups

## Setup Checklist

This is the standard flow a coding agent should follow.

1. Confirm repo location and Python environment.
2. Confirm gateway URL and whether `BIOM_GATEWAY_TOKEN` is required.
3. Choose a node name that is unique on that machine.
4. Choose the allowed directory or directories.
5. Decide whether this should be a dedicated node or a shared multi-folder node.
6. Start the process in a long-running supervisor such as `tmux`.
7. Capture the pairing code from the terminal or log.
8. In the target Feishu group, run `/node pair <pairing-code>`.
9. In the same group, run `/project init remote <node>:<path>`.
10. Verify with `/project info`.
11. Verify locally that logs show `Connected and authenticated.` and `Node '<name>' is online and serving requests.`
12. Record machine-specific commands and paths in `docs/local/<machine>.md`.

## Commands to Know

Start a dedicated node:

```bash
feishu-node \
  --server wss://feishu.biom.autos \
  --name <node-name> \
  --allow-dir <absolute-project-path>
```

Start a multi-folder node:

```bash
feishu-node \
  --server wss://feishu.biom.autos \
  --name <node-name> \
  --allow-dir <absolute-path-a> \
  --allow-dir <absolute-path-b>
```

Pair in Feishu:

```text
/node pair <pairing-code>
```

Bind the current group to a remote root:

```text
/project init remote <node>:<path>
```

Inspect current binding:

```text
/project info
```

## Auto-upgrade and Service Installation

`feishu-node` ships with a companion entry point, `feishu-node-launcher`, that supervises the node process: it auto-restarts on crash and pulls released upgrades from GitHub. For new operators this is the recommended way to run a node — `feishu-node` directly is still supported, but you have to wire up your own supervision and upgrade story.

### Recommended Quickstart

A launcher session in `tmux` or `screen` gets you crash-restart plus auto-upgrade with zero OS-specific config:

```bash
tmux new -s feishu-node
feishu-node-launcher -- \
  --server wss://feishu.biom.autos \
  --name megatron-nanobody-ai \
  --allow-dir /path/to/nanobody_ai
```

Everything after the `--` is forwarded verbatim to `feishu-node`, so multi-folder works the same way:

```bash
feishu-node-launcher -- \
  --server wss://feishu.biom.autos \
  --name megatron-workspace \
  --allow-dir /path/to/nanobody_ai \
  --allow-dir /path/to/rvq_train
```

For long-lived hosts, prefer `install-service` (below) over leaving a `tmux` session attached to a login shell.

### Auto-upgrade Behavior

By default the launcher polls `https://api.github.com/repos/LuyiTian/bioM-feishu-node/releases/latest` once every 24 hours.

- Only releases tagged in the `vX.Y.Z` semver pattern are accepted. Anything else (release candidates, branch-name tags, pre-release flags) is ignored.
- Main-branch commits are **never** auto-deployed. To push code, cut a tagged release on GitHub.
- When a newer tag than the installed version is seen, the launcher runs `pip install --upgrade --force-reinstall --no-deps git+https://github.com/LuyiTian/bioM-feishu-node.git@<tag>` against the same Python interpreter, then signals the child to exit cleanly and respawns it from the new install.
- The bot operator can also push an upgrade on demand from a Feishu group:

  ```text
  /node upgrade            # upgrade every node bound to this group
  /node upgrade <node_id>  # upgrade a specific node
  ```

  Under the hood the bot sends a `request_upgrade` WebSocket control message; the node exits with code 75 (`EX_TEMPFAIL`) and the launcher performs the same pip install + respawn dance.

Exit-code contract between child and launcher:

- `0`   → clean shutdown, launcher exits too
- `75`  → upgrade requested, launcher reinstalls and respawns
- other → crash, launcher respawns with exponential backoff; gives up after 5 consecutive crashes

### OS-native Service Install

`install-service` writes the host's native auto-start descriptor and starts it immediately. No root or sudo is required on Linux or macOS. The `--service-name` suffix lets one host run multiple nodes side by side.

#### Linux (systemd user unit)

```bash
feishu-node-launcher install-service --service-name nanobody-ai -- \
  --server wss://feishu.biom.autos \
  --name megatron-nanobody-ai \
  --allow-dir /path/to/nanobody_ai
```

Writes `~/.config/systemd/user/feishu-node-nanobody-ai.service` and runs `systemctl --user daemon-reload && systemctl --user enable --now feishu-node-nanobody-ai.service`. To survive logout on a server, run `loginctl enable-linger $USER` once.

#### macOS (LaunchAgent)

```bash
feishu-node-launcher install-service --service-name nanobody-ai -- \
  --server wss://feishu.biom.autos \
  --name megatron-nanobody-ai \
  --allow-dir /Users/me/code/nanobody_ai
```

Writes `~/Library/LaunchAgents/com.biom.feishu-node.nanobody-ai.plist` and `launchctl load`s it. LaunchAgents (not LaunchDaemons) — runs as the logged-in user, no root required.

#### Windows (Task Scheduler, ONLOGON)

```powershell
feishu-node-launcher install-service --service-name nanobody-ai -- ^
  --server wss://feishu.biom.autos ^
  --name megatron-nanobody-ai ^
  --allow-dir C:\code\nanobody_ai
```

Registers scheduled task `feishu-node-nanobody-ai` to run at user logon at LIMITED elevation. Start it now without waiting for the next logon with `schtasks /Run /TN feishu-node-nanobody-ai`.

### Manual Upgrade

For hosts where auto-upgrade is disabled, or for operators who run `feishu-node` directly without the launcher:

```bash
pip install --upgrade --force-reinstall "git+https://github.com/LuyiTian/bioM-feishu-node.git"
```

Then restart the process by your usual means (`tmux` re-attach + Ctrl-C + relaunch, `systemctl --user restart`, `launchctl kickstart`, etc.). Pin to a specific tag with `...git.git@v1.2.3` if you need reproducibility.

### Operator Escape Hatches

- `--no-auto-upgrade` — disable the GitHub poll entirely; launcher only handles crash-restart.
- `--check-interval-seconds <N>` — change poll cadence (default 86400). Set high for stable production, low for staging.
- `--repo <owner>/<repo>` — point the upgrade poll at a fork or internal mirror, e.g. `--repo myorg/bioM-feishu-node-fork`.
- `feishu-node-launcher uninstall-service --service-name <suffix>` — back out an `install-service` registration (removes the unit/plist/task and stops the service).

## Local-Only Artifacts

These are machine-specific and should not be committed:

- real gateway tokens
- actual pairing codes
- `tmux` session names chosen for one machine
- concrete log file paths for one machine
- local process recovery notes
- screenshots or copied terminal output from a live machine

Keep those notes in `docs/local/` using the local runbook template.

## Handoff Notes for Another Coding Agent

If a Codex-like agent is asked to set up a node, it should gather these facts before acting:

- repo path
- virtualenv or interpreter path
- gateway URL
- whether gateway auth is enforced
- target Feishu group
- desired node name
- allowed local path or paths
- whether shell access should stay enabled
- how the process should be supervised: `tmux`, systemd, or another runner

The agent should then produce or update:

- the live process
- a local runbook in `docs/local/`
- a short verification note: node name, allowed dirs, pairing status, log location

## Policy Recommendation

Use one node per project or per Feishu group unless you have a clear reason to share a node across folders.

That keeps:

- permissions narrow
- remote roots obvious
- incidents easier to isolate
- handoff to other agents simpler
