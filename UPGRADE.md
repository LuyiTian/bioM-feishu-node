# Upgrading an existing feishu-node (for AI coding agents)

You are running on a machine that has an older `feishu-node` process. Your
task is to upgrade it to the latest tagged release and (optionally) put it
under the auto-upgrading launcher so a human never has to do this again.

The repo is **public**: `https://github.com/LuyiTian/bioM-feishu-node`.
No credentials needed.

---

## 1. Identify the current node

```bash
# Find the process and how it was started
ps -ef | grep -E "feishu[-_]node|feishu_node" | grep -v grep

# Find which Python env owns the package
which feishu-node && feishu-node --help | head -1
python -m pip show biom-feishu-node | grep -E "^(Version|Location)"
```

Record three things before changing anything:

| Field | Why |
|---|---|
| Full launch command (incl. `--server`, `--name`, every `--allow-dir`, any `--no-shell` / `--ui` flags) | Need to re-launch with the same args |
| Python interpreter / venv path | Upgrade must hit the *same* Python |
| Process supervisor in use (systemd? launchd? schtasks? tmux? bare nohup?) | Determines how to restart |

---

## 2. Decide which path applies

```
Is the current process `feishu-node-launcher ...`?
├── yes → SKIP TO STEP 5 (it auto-upgrades; you can also force it with `/node upgrade` from a Feishu group)
└── no  → continue
```

---

## 3. Upgrade the package

Use the **same Python** that currently owns `feishu-node`. Don't use system
pip blindly — it may target the wrong interpreter.

```bash
# Replace /path/to/python with the interpreter from step 1.
/path/to/python -m pip install --upgrade --force-reinstall \
  "git+https://github.com/LuyiTian/bioM-feishu-node.git@v0.2.0"
```

Verify:

```bash
/path/to/python -m pip show biom-feishu-node | grep ^Version
# Expect: Version: 0.2.0  (or higher)
which feishu-node-launcher
# Expect: a real path; means the new entry point is installed
```

If `feishu-node-launcher` is not on PATH but the version is right, fall
back to `python -m feishu_node.launcher` everywhere `feishu-node-launcher`
appears below.

---

## 4. Switch to the launcher

Stop the old `feishu-node` process first, by the same mechanism it was
started:

```bash
# systemd:    sudo systemctl stop <unit>     # (or:  systemctl --user stop <unit>)
# launchd:    launchctl unload <plist>
# schtasks:   schtasks /End /TN <task-name>
# tmux/nohup: pkill -f feishu-node           # (verify it's gone with ps -ef | grep feishu-node)
```

Re-launch with the **same arguments** you recorded, but using the
launcher entry point. Put the node args after `--`:

```bash
feishu-node-launcher -- \
  --server wss://feishu.biom.autos \
  --name <NODE-NAME-FROM-STEP-1> \
  --allow-dir <PATH-1> \
  --allow-dir <PATH-2>
```

Run it under `tmux new -s feishu-node` (or `screen -S feishu-node`) so it
survives logout. Don't background it with `&` alone — stdout/stderr
should stay attached for the first ~5 min of monitoring.

---

## 5. (Optional) Register as an auto-start service

Skip if the operator already has their own supervisor (systemd unit they
maintain, Ansible role, Docker compose, etc.). Otherwise:

```bash
feishu-node-launcher install-service --service-name <SHORT-NAME> -- \
  --server wss://feishu.biom.autos \
  --name <NODE-NAME-FROM-STEP-1> \
  --allow-dir <PATH-1> \
  --allow-dir <PATH-2>
```

Per-OS effect:

- **Linux** — writes `~/.config/systemd/user/feishu-node-<short>.service`
  and runs `systemctl --user enable && systemctl --user start`. No sudo.
  On server hosts also run `loginctl enable-linger $USER` so the unit
  survives logout.
- **macOS** — writes `~/Library/LaunchAgents/com.biom.feishu-node.<short>.plist`
  and runs `launchctl load`. No root.
- **Windows** — registers a Scheduled Task `feishu-node-<short>` that
  runs at user logon. Use `schtasks /Run /TN feishu-node-<short>` to
  start it now without waiting for the next logon.

Uninstall mirror: `feishu-node-launcher uninstall-service --service-name <SHORT-NAME>`.

---

## 6. Verify

```bash
# Confirm the launcher (or service) is running
ps -ef | grep feishu-node | grep -v grep
# Expect TWO processes: the launcher and its child feishu-node

# Check version in logs / output
feishu-node --help | head -1
# (or read the launcher's stdout — it logs "feishu-node-launcher v0.2.0 starting ...")
```

In the Feishu group bound to this node, send `/node list` — the node
should show as `online`.

---

## Rules

- **Use the same Python interpreter** that owns the existing install.
  Don't introduce a new venv unless the operator asks for it.
- **Don't downgrade.** If the current version is already ≥ the target,
  stop and report.
- **Don't change `--name`.** The node identity is part of the existing
  Feishu group binding; renaming breaks the binding.
- **Don't remove existing `--allow-dir` paths.** Keep every directory
  the old command had; users have ongoing chats that rely on them.
- **If unsure which Python to upgrade**, ask the operator before running
  `pip install`.

---

## What you should NOT do

- Don't `pip install biom-feishu-node` (PyPI) — this package is not on PyPI.
- Don't pull from `main` branch directly. Use the `@v0.2.0` (or newer)
  tag pin. The launcher itself only trusts tags shaped `vX.Y.Z`.
- Don't add `--no-shell` if the existing command didn't have it (and
  vice versa). Keep the security posture identical.
