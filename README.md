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

## Claude Code Session Monitoring

When `--monitor-claude` is enabled, the node watches Claude Code sessions
running in its allowed directories, pushes a summary to the bound Feishu chat
when a session finishes, and lets you reply with `/cc <instruction>` to inject
text back into the live session.

### Deploy (unattended — no manual hook copying)

Adding `--monitor-claude` is **all** the per-machine setup. On startup the node
self-installs everything into the running user's home (idempotent, safe to
re-run, refreshed automatically on every node upgrade):

- writes `~/.claude/hooks/cc-event-hook.py` (the Stop-hook spooler),
- merges a `Stop` hook into `~/.claude/settings.json` (preserving any existing
  config; an unparseable settings file is left untouched and only logged),
- creates the `~/.feishu-node/claude-events/` spool dir.

```bash
feishu-node \
  --server wss://your-gateway.example.com \
  --name my-node \
  --allow-dir /path/to/project \
  --monitor-claude
# then just run Claude Code in tmux inside an allowed dir:
tmux new -s my-project
cd /path/to/project && claude --dangerously-skip-permissions
```

Opt out of the auto-install with `--no-claude-hook-install` (e.g. you manage
`~/.claude/settings.json` yourself). To install the hook manually without
running a node: `feishu-node-install-hook`.

> The hook only takes effect for Claude Code sessions run by the **same user**
> as the node (it lives in that user's `~/.claude`). Run the node and Claude as
> the same account.

### How it works

```
Claude Code (in tmux, cwd under an allowed dir)
  │  Stop event → JSON on stdin
  ▼
~/.claude/hooks/cc-event-hook.py        # resolves its tmux pane, writes an event
  │  writes ~/.feishu-node/claude-events/<ts>.json
  ▼
node (_session_monitor_loop, polls every --claude-poll-interval s)
  │  drain → security gate (cwd ∈ allowed_dirs) → 30s debounce
  │  → read transcript summary → WS {"method":"notify", ...}
  ▼
gateway → resolve (node_id, realpath) → Feishu chat bound to that folder
  ▲
  │  reply flow: /cc <text> → WS {"method":"inject_claude_session", ...}
  └─ node → tmux send-keys -l <text> ; Enter  (into the resolved pane)
```

- **Folder-scoped**: only the chat bound to the exact project folder is
  notified — no cross-folder leakage (enforced on both node and gateway).
- **Debounced**: a notification fires 30 s after the *last* Stop in a session,
  so rapid back-to-back turns collapse into one message.
- **Multi-session**: `/cc list` shows known sessions; `/cc <tmux-target> <text>`
  targets a specific one; bare `/cc <text>` targets the most recent.

### Requirements

- Claude Code v2.1+ with `Stop` hook support
- tmux — **required for `/cc`** (the hook identifies the pane); notifications
  work without it (no reply hint is shown)
- The Feishu chat must be bound to the project folder using the path the node
  reports, i.e. its **realpath** (`/project init remote <node>:<realpath>`).
  The gateway cannot resolve symlinks on the node's filesystem, so a symlinked
  bind path silently drops notifications.
- Gateway must support the `notify` WebSocket message (feishu_agent ≥ 2026-06-19)

### Extending / maintaining (for the next agent)

| Concern | Where |
|---|---|
| Stop-hook spooler (runs on the GPU box) | `feishu_node/cc_event_hook.py` — **canonical source**, stdlib-only, also runnable standalone. Edit here; it ships in the package and is what the installer writes out. |
| Unattended installer + `~/.claude/settings.json` merge | `feishu_node/claude_hook.py` (`install_claude_hook`, `STOP_HOOK_COMMAND`, `hook_source()`) |
| Monitor loop, debounce, notify send, `/cc` injection, idle check | `feishu_node/node_client.py` (`_session_monitor_loop`, `_drain_event_spool`, `_schedule_debounced_notify`, `_fire_notification`, `_send_notification`, `_inject_claude_message`, `_check_session_idle`, `_is_cwd_allowed`) |
| Transcript → summary | `feishu_node/file_ops.py` (`read_transcript_summary`) |
| Notification text | `node_client._format_notification` — **the node owns formatting**; the gateway forwards it verbatim, so format here, not on the gateway. |
| Capability advertised to the gateway | `node_client._detect_capabilities` → `claude_monitor` |
| WS protocol | node→gw `{"method":"notify","params":{type,message,project_path,session_info}}`; gw→node `{"method":"inject_claude_session","params":{project_path,message,tmux_target}}` — both fire-and-forget (no `id`). |

Critical implementation notes (hard-won — don't regress):

- **tmux-target resolution must NOT use `os.ttyname(0)`.** Claude Code pipes the
  Stop-event JSON to the hook's stdin, so fd 0 is a pipe and `os.ttyname(0)`
  raises `ENOTTY`; opening `/dev/tty` returns the literal `/dev/tty` (device
  5:0), not the pts. The hook derives the controlling terminal from
  `/proc/self/stat`'s `tty_nr` → `/dev/pts/N` and matches it against
  `#{pane_tty}`. Without this, `/cc` is dead (no target is ever captured).
- **Frame limit** (`MAX_WS_MESSAGE_BYTES`, 96 MiB) must stay in sync with the
  gateway's; it bounds binary pushes to the node.
- Keep `cc_event_hook.py` **stdlib-only** — it is copied out and run by the
  system `python3`, not from this venv.

After changing any of the above, cut a release (see [Release Guide](docs/RELEASE.md));
nodes auto-upgrade and re-install the refreshed hook on next start.

### Troubleshooting

- **No notification arrives** → binding path mismatch: the chat must be bound
  with the node's realpath. Check the node log for `not in allowed dirs` and
  the gateway log for `No chat bound … dropping notification`.
- **`/cc` says sent but nothing happens** → the session isn't in tmux, or the
  hook didn't capture a target. Verify the session runs under tmux and the
  installed hook is current (`feishu-node-install-hook` re-installs it).
- **`settings.json left untouched` in the log** → your `~/.claude/settings.json`
  isn't valid JSON; fix it and restart the node (we never overwrite it).

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
- `--monitor-claude`: monitor Claude Code sessions and notify Feishu on completion; auto-installs the Stop hook (see [Claude Code Session Monitoring](#claude-code-session-monitoring))
- `--claude-poll-interval <int>`: seconds between event spool checks (default `5`)
- `--no-claude-hook-install`: with `--monitor-claude`, skip auto-installing the hook into `~/.claude` (manage it yourself)
- `--no-shell`: disable shell command execution
- `--ui`: enable local web UI (`127.0.0.1`, disabled by default)
- `--port <int>`: local web UI port when `--ui` is enabled (default `9201`)
- `-v, --verbose`: debug logs

### `feishu-node-install-hook`

```bash
feishu-node-install-hook
```

Manually install/refresh the Claude Code Stop hook, the
`~/.claude/settings.json` entry, and the event spool dir — the same idempotent
step the node runs automatically under `--monitor-claude`. Useful for a one-off
install on a machine that doesn't run a node.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pytest
```
