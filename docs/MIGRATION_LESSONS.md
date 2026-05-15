# Migrating an old feishu-node host to the launcher system

This note is a general migration record for operators and coding agents. It is
intentionally free of private host paths, project names, gateway tokens, pairing
codes, and local runbook details.

Use this when a host is already running one or more old `feishu-node` worker
processes and needs to move to the newer `feishu-node-launcher` model.

## What changed

Old model:

- A long-running process invoked `feishu-node` or `python -m feishu_node`
  directly.
- Process supervision was external and site-specific: `tmux`, `nohup`,
  systemd, launchd, Task Scheduler, Docker, or a custom script.
- Upgrades required a human or agent to reinstall the package and restart each
  process manually.

New model:

- `feishu-node-launcher` is the long-running parent process.
- The launcher starts the real `feishu-node` worker as a child.
- The launcher restarts the worker on crash.
- The launcher supports tag-only auto-upgrades from GitHub releases.
- The gateway can request an upgrade; the worker exits with code `75`, and the
  launcher performs the reinstall and respawn.

After a successful migration, each node normally has two processes:

```text
feishu-node-launcher -- --server <gateway-wss-url> --name <node-name> --allow-dir <path>
└─ python -m feishu_node --server <gateway-wss-url> --name <node-name> --allow-dir <path>
```

## Migration goals

Preserve these exactly:

- `--server`
- `--name`
- every `--allow-dir`
- `--no-shell` / shell-enabled posture
- `--ui` / UI-disabled posture
- gateway token environment
- saved node token/config
- existing process supervisor ownership

Change only the process entrypoint:

```text
old: feishu-node ...
new: feishu-node-launcher -- ...
```

or, if the entrypoint script is not on `PATH`:

```text
old: python -m feishu_node ...
new: python -m feishu_node.launcher -- ...
```

## Step-by-step checklist

1. Find current processes.

   ```bash
   ps -ef | grep -E "feishu[-_]node|feishu_node" | grep -v grep
   ```

2. Record the full launch command for every running node.

   Capture the gateway URL, node name, all allowed directories, and security
   flags. Do not redact this in your local private runbook, but do not paste it
   into public docs if it contains private paths.

3. Identify the owning Python environment.

   ```bash
   /path/to/python -m pip show biom-feishu-node
   /path/to/python -m feishu_node --help
   ```

   Use the same interpreter for upgrade. Do not switch venvs during migration
   unless that is an explicit goal.

4. Identify the supervisor.

   Check whichever applies:

   ```bash
   systemctl --user list-units --type=service --all | grep -i feishu
   systemctl --user list-unit-files | grep -i feishu
   tmux list-sessions
   launchctl list | grep -i feishu
   schtasks /Query /FO LIST | findstr /I feishu
   ```

5. Protect local state before editing.

   Preserve:

   - package repo or install directory
   - virtualenv
   - supervisor unit/plist/task/script
   - gateway token env file or secret injection mechanism
   - `~/.feishu-node/config.json`
   - recent logs

6. Upgrade the same Python environment.

   Production should pin a release tag:

   ```bash
   /path/to/python -m pip install --upgrade --force-reinstall \
     "git+https://github.com/LuyiTian/bioM-feishu-node.git@v0.2.0"
   ```

   For an editable source checkout:

   ```bash
   git fetch --prune origin
   git pull --ff-only
   /path/to/python -m pip install -e /path/to/bioM-feishu-node
   ```

7. Verify the launcher exists.

   ```bash
   /path/to/python -m pip show biom-feishu-node | grep '^Version:'
   /path/to/venv/bin/feishu-node-launcher --help
   /path/to/python -m feishu_node.launcher --help
   ```

8. Change the supervisor command.

   Keep the old node arguments after a `--` separator:

   ```bash
   /path/to/python -u -m feishu_node.launcher -- \
     --server <gateway-wss-url> \
     --name <same-node-name> \
     --allow-dir <same-absolute-path>
   ```

   Repeat `--allow-dir` exactly as before for multi-folder nodes.

9. Reload and restart the supervisor.

   Linux user systemd example:

   ```bash
   systemctl --user daemon-reload
   systemctl --user restart <unit-name>
   systemctl --user status <unit-name> --no-pager
   ```

10. Verify runtime shape and health.

    ```bash
    ps -ef | grep -E "feishu-node-launcher|feishu_node" | grep -v grep
    journalctl --user -u <unit-name> -n 80 --no-pager
    ```

    Healthy evidence:

    - one launcher parent process
    - one worker child process per node
    - launcher log says `feishu-node-launcher v... starting`
    - launcher log says `spawning child: ... -m feishu_node ...`
    - worker log says `Connected and authenticated.`
    - Feishu `/node list` shows the node online

## Lessons learned

- Do not migrate by only changing source code. The installed package metadata
  and console scripts must also be refreshed in the active Python environment.
- Do not replace the Python interpreter during a routine migration. The saved
  tokens and the service environment may depend on the existing user context.
- Do not change node names. Feishu pairing and remote-root bindings depend on
  the node identity.
- Do not remove allowed directories while migrating. Existing chats may rely on
  those roots.
- Expect one noisy stop when replacing an old worker that was not written for
  the launcher lifecycle. Focus on whether the new launcher/worker pair starts
  cleanly afterward.
- Logs that still show an old `feishu-node v...` banner can mislead operators.
  Verify package version through `pip show` and launcher startup logs.
- If systemd remains stuck in `deactivating`, verify whether the child already
  exited and only the old launcher is left. A bounded `systemctl --user kill`
  followed by `reset-failed` and `start` is often safer than editing unrelated
  state.
- The launcher auto-upgrade trust boundary is GitHub release tags matching
  `vX.Y.Z`. Protect tag publishing as production deploy authority.

## Rollback

Rollback is simply restoring the prior supervisor command and restarting:

```text
old launcher command:
  python -m feishu_node.launcher -- <node args>

rollback command:
  python -m feishu_node <same node args>
```

This removes launcher auto-upgrade and crash-restart behavior, but it should
preserve the same node identity and saved pairing token as long as `--server`
and `--name` are unchanged.

## Public documentation hygiene

Keep these out of shared migration docs:

- real hostnames that are not part of the public service contract
- local usernames
- absolute private project paths
- gateway tokens
- pairing codes
- project-specific chat or customer names
- copied logs containing private file names or command payloads

Put sensitive details in a private local runbook instead.
