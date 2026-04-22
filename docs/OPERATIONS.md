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
