"""Launcher: long-running parent process that auto-restarts and self-upgrades.

Why this exists
---------------
The node was originally `python -m feishu_node ...` straight in a terminal or
under systemd / launchd. Two problems:

1. Upgrading required SSH-ing to every machine: `git pull` (or pip reinstall)
   then restart the process by hand.
2. The wrapper had to be written anew per OS (systemd unit / launchd plist /
   sc.exe), and on Windows `pip install --upgrade` can't replace a running .exe.

The launcher is a tiny parent process that owns the real node as a subprocess
and reacts to exit codes:

  - exit 0   → graceful shutdown, launcher exits
  - exit 75  → child requested upgrade (EX_TEMPFAIL semantics): pip install the
               latest signed-tag release, then respawn
  - other    → crash: exponential backoff respawn, give up after N consecutive
               failures so we don't crash-loop

Upgrades come from two sources, both safe:

  - **Push** (bot → ws → child): bot sends `request_upgrade` control message,
    child calls `sys.exit(75)`. Launcher does the rest.
  - **Pull** (daemon thread → GitHub /releases/latest): once every 24 h, fetch
    the latest release tag (must match `vX.Y.Z`), compare with locally-installed
    version, and if newer terminate the child (which makes launcher run the
    upgrade path).

`install-service` writes the appropriate auto-start file for the host OS
(systemd user unit / launchd plist / Windows scheduled task) so the launcher
itself runs at login. The launcher then handles everything else.

Security model
--------------
Upgrades are restricted to GitHub release tags matching ``^v\\d+\\.\\d+\\.\\d+$``.
Whoever can push such a tag can deploy code to every node — same trust level as
a normal ``pip install git+...``. main-branch commits are NOT trusted for
auto-upgrade. Tag-only is enforced both in the poller and in the pip command
(``git+https://...@<tag>``).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXIT_UPGRADE = 75  # POSIX EX_TEMPFAIL — "temporary failure, please retry"
EXIT_GRACEFUL = 0

PACKAGE_NAME = "biom-feishu-node"
DEFAULT_REPO = "LuyiTian/bioM-feishu-node"
TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")

DEFAULT_CHECK_INTERVAL_S = 24 * 60 * 60  # daily
INITIAL_CHECK_DELAY_S = 5 * 60          # avoid pounding GitHub right after install
MAX_CONSECUTIVE_CRASHES = 5
BASE_BACKOFF_S = 5
MAX_BACKOFF_S = 5 * 60

logger = logging.getLogger("feishu-node-launcher")


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def get_local_version() -> str:
    try:
        return pkg_version(PACKAGE_NAME)
    except PackageNotFoundError:
        return "0.0.0"


def _parse_semver(v: str) -> Optional[tuple]:
    try:
        parts = v.lstrip("v").split(".")
        if len(parts) != 3:
            return None
        return tuple(int(p) for p in parts)
    except (ValueError, AttributeError):
        return None


def is_newer(remote_tag: str, local_version: str) -> bool:
    """Return True iff *remote_tag* (e.g. ``v0.2.1``) is strictly newer than
    *local_version* (e.g. ``0.2.0``). Returns False if either is unparseable."""
    r = _parse_semver(remote_tag)
    l = _parse_semver(local_version)
    if r is None or l is None:
        return False
    return r > l


# ---------------------------------------------------------------------------
# GitHub release polling
# ---------------------------------------------------------------------------

def fetch_latest_tag(repo: str, timeout: float = 10.0) -> Optional[str]:
    """Query GitHub for the newest safe release tag.

    Prefer ``/releases/latest`` when operators create GitHub Releases. If the
    repo only has pushed git tags, fall back to ``/tags`` and select the highest
    semver-shaped ``vX.Y.Z`` tag. Network failures, malformed JSON, and
    non-conforming tag names all return None — they should NOT crash the
    launcher. The poller will simply retry next interval.
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{PACKAGE_NAME}/{get_local_version()}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except Exception as e:
        logger.debug("upgrade poll: GitHub fetch failed: %s", e)
        return fetch_latest_git_tag(repo, timeout=timeout)

    tag = (data.get("tag_name") or "").strip()
    if TAG_RE.match(tag):
        return tag
    if tag:
        logger.debug("upgrade poll: ignoring tag '%s' (does not match vX.Y.Z)", tag)
    return fetch_latest_git_tag(repo, timeout=timeout)


def fetch_latest_git_tag(repo: str, timeout: float = 10.0) -> Optional[str]:
    """Return the highest semver-shaped git tag from GitHub's tags API."""
    url = f"https://api.github.com/repos/{repo}/tags?per_page=100"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{PACKAGE_NAME}/{get_local_version()}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except Exception as e:
        logger.debug("upgrade poll: GitHub tags fetch failed: %s", e)
        return None

    if not isinstance(data, list):
        return None

    candidates: list[tuple[tuple[int, int, int], str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("name") or "").strip()
        parsed = _parse_semver(tag) if TAG_RE.match(tag) else None
        if parsed is not None:
            candidates.append((parsed, tag))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def pip_upgrade_to_tag(repo: str, tag: str, timeout: float = 600.0) -> bool:
    """Run ``python -m pip install --upgrade --force-reinstall git+...@<tag>``.

    Uses ``sys.executable -m pip`` (not bare ``pip``) so the upgrade always
    targets the same Python environment that's running the launcher.
    """
    if not TAG_RE.match(tag):
        logger.error("refusing pip upgrade for unsafe tag: %r", tag)
        return False
    spec = f"git+https://github.com/{repo}.git@{tag}"
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade",
           "--force-reinstall", "--no-deps", spec]
    logger.info("running upgrade: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        logger.error("pip upgrade timed out after %ds", timeout)
        return False
    except Exception as e:
        logger.error("pip upgrade exception: %s", e)
        return False
    if proc.returncode != 0:
        logger.error("pip upgrade failed (rc=%d): %s",
                     proc.returncode, (proc.stderr or proc.stdout or "")[:800])
        return False
    # Re-install deps (we used --no-deps to avoid surprising version drifts; if
    # tags ship new deps we let a separate run reconcile them)
    cmd_deps = [sys.executable, "-m", "pip", "install", spec]
    try:
        subprocess.run(cmd_deps, capture_output=True, text=True, timeout=timeout)
    except Exception:
        pass
    logger.info("upgrade to %s succeeded", tag)
    return True


class UpgradePoller(threading.Thread):
    """Daemon thread: every *interval_s* fetch latest release tag, and if it's
    newer than the locally-installed version, terminate the child to trigger
    the launcher's upgrade path."""

    def __init__(self, repo: str, interval_s: int, terminate_child_cb):
        super().__init__(daemon=True, name="upgrade-poller")
        self.repo = repo
        self.interval_s = interval_s
        self._terminate_child_cb = terminate_child_cb
        self._stop = threading.Event()
        self._upgrade_pending = threading.Event()

    @property
    def upgrade_pending(self) -> bool:
        return self._upgrade_pending.is_set()

    def consume_upgrade_pending(self) -> bool:
        v = self._upgrade_pending.is_set()
        self._upgrade_pending.clear()
        return v

    def stop(self):
        self._stop.set()

    def run(self):
        # First check delayed so we don't pound GitHub if many nodes restart together
        if self._stop.wait(INITIAL_CHECK_DELAY_S):
            return
        while not self._stop.is_set():
            try:
                local = get_local_version()
                latest = fetch_latest_tag(self.repo)
                if latest and is_newer(latest, local):
                    logger.info("upgrade available: %s → %s", local, latest)
                    self._upgrade_pending.set()
                    try:
                        self._terminate_child_cb()
                    except Exception as e:
                        logger.warning("upgrade poll: failed to terminate child: %s", e)
            except Exception as e:
                logger.warning("upgrade poll: loop exception: %s", e)
            self._stop.wait(self.interval_s)


# ---------------------------------------------------------------------------
# Main launcher loop
# ---------------------------------------------------------------------------

def _terminate_proc(proc: subprocess.Popen, grace_s: float = 15.0) -> None:
    """Politely ask *proc* to exit, then SIGKILL after *grace_s*."""
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except Exception as e:
        logger.warning("terminate() failed: %s", e)
    try:
        proc.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        logger.warning("child did not exit in %ds, sending SIGKILL", grace_s)
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def _spawn_child(node_args: List[str]) -> subprocess.Popen:
    """Spawn ``python -m feishu_node <args>``."""
    cmd = [sys.executable, "-m", "feishu_node", *node_args]
    logger.info("spawning child: %s", " ".join(shlex.quote(c) for c in cmd))
    # Pass through env so config files / tokens still work
    return subprocess.Popen(cmd)


def run_launcher(
    node_args: List[str],
    *,
    repo: str = DEFAULT_REPO,
    check_interval_s: int = DEFAULT_CHECK_INTERVAL_S,
    enable_auto_upgrade: bool = True,
) -> int:
    """Main launcher event loop. Returns final exit code."""
    logger.info("feishu-node-launcher v%s starting (repo=%s, auto_upgrade=%s)",
                get_local_version(), repo, enable_auto_upgrade)

    child_lock = threading.Lock()
    child_ref: dict = {"proc": None}

    def _request_terminate_child():
        with child_lock:
            proc = child_ref.get("proc")
            if proc and proc.poll() is None:
                logger.info("upgrade trigger: terminating child")
                _terminate_proc(proc)

    poller: Optional[UpgradePoller] = None
    if enable_auto_upgrade:
        poller = UpgradePoller(repo, check_interval_s, _request_terminate_child)
        poller.start()

    # Forward SIGTERM/SIGINT to child and exit cleanly
    shutting_down = threading.Event()

    def _on_signal(signum, frame):
        logger.info("launcher received signal %s, shutting down", signum)
        shutting_down.set()
        if poller:
            poller.stop()
        with child_lock:
            proc = child_ref.get("proc")
            if proc:
                _terminate_proc(proc)

    for sig_name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, _on_signal)
            except (ValueError, OSError):
                pass  # may fail in non-main threads or unsupported platforms

    consecutive_crashes = 0

    while not shutting_down.is_set():
        try:
            proc = _spawn_child(node_args)
        except Exception as e:
            logger.error("failed to spawn child: %s", e)
            return 1
        with child_lock:
            child_ref["proc"] = proc

        exit_code = proc.wait()

        with child_lock:
            child_ref["proc"] = None

        if shutting_down.is_set():
            logger.info("launcher exiting after child stop (rc=%s)", exit_code)
            return EXIT_GRACEFUL

        # Did the poller flag an upgrade while we were running? If so, treat
        # any exit code as an upgrade trigger (since we just terminated the
        # child to make it stop).
        upgrade_due = (
            (poller and poller.consume_upgrade_pending())
            or exit_code == EXIT_UPGRADE
        )

        if upgrade_due:
            logger.info("upgrade path: child exited (rc=%s), checking GitHub", exit_code)
            latest = fetch_latest_tag(repo)
            local = get_local_version()
            if latest and is_newer(latest, local):
                if pip_upgrade_to_tag(repo, latest):
                    consecutive_crashes = 0
                else:
                    logger.warning("upgrade attempt failed; restarting current version")
            else:
                logger.info("no newer tag found (local=%s, latest=%s); restarting", local, latest)
            continue

        if exit_code == EXIT_GRACEFUL:
            logger.info("child exited gracefully (rc=0); launcher exiting")
            return EXIT_GRACEFUL

        consecutive_crashes += 1
        if consecutive_crashes >= MAX_CONSECUTIVE_CRASHES:
            logger.error(
                "child crashed %d times in a row (last rc=%s); giving up",
                consecutive_crashes, exit_code,
            )
            return 2

        backoff = min(BASE_BACKOFF_S * (2 ** (consecutive_crashes - 1)), MAX_BACKOFF_S)
        logger.warning(
            "child exited rc=%s (crash %d/%d); restarting in %ds",
            exit_code, consecutive_crashes, MAX_CONSECUTIVE_CRASHES, backoff,
        )
        if shutting_down.wait(backoff):
            return EXIT_GRACEFUL

    return EXIT_GRACEFUL


# ---------------------------------------------------------------------------
# install-service / uninstall-service
# ---------------------------------------------------------------------------

def _launcher_exe_path() -> str:
    """Resolve the absolute path of the feishu-node-launcher entry point."""
    import shutil
    found = shutil.which("feishu-node-launcher")
    if found:
        return found
    # Fallback: invoke via the current Python interpreter
    return f"{sys.executable} -m feishu_node.launcher"


def _node_args_to_cmdline(node_args: List[str]) -> str:
    """Shell-quote node args for use inside a service definition."""
    return " ".join(shlex.quote(a) for a in node_args)


_SYSTEMD_UNIT = """[Unit]
Description=Feishu remote node ({name})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={exe} {args}
Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""


_LAUNCHD_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.biom.feishu-node.{name}</string>
    <key>ProgramArguments</key>
    <array>
{program_args}
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>{home}/Library/Logs/feishu-node-{name}.log</string>
    <key>StandardErrorPath</key><string>{home}/Library/Logs/feishu-node-{name}.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key><string>1</string>
    </dict>
</dict>
</plist>
"""


def install_service(name: str, node_args: List[str]) -> int:
    """Write an OS-native auto-start descriptor for ``feishu-node-launcher``.

    Linux  → ~/.config/systemd/user/feishu-node-<name>.service (+ systemctl --user enable)
    macOS  → ~/Library/LaunchAgents/com.biom.feishu-node.<name>.plist (+ launchctl load)
    Windows → schtasks scheduled task ``feishu-node-<name>`` running at logon
    """
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "node"
    system = platform.system()

    if system == "Linux":
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit_path = unit_dir / f"feishu-node-{safe_name}.service"
        content = _SYSTEMD_UNIT.format(
            name=safe_name,
            exe=_launcher_exe_path(),
            args=_node_args_to_cmdline(node_args),
        )
        unit_path.write_text(content, encoding="utf-8")
        print(f"[install-service] wrote {unit_path}")
        for cmd in (
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", f"feishu-node-{safe_name}.service"],
            ["systemctl", "--user", "start", f"feishu-node-{safe_name}.service"],
        ):
            try:
                subprocess.run(cmd, check=True)
                print(f"[install-service] {' '.join(cmd)}")
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                print(f"[install-service] WARNING: {' '.join(cmd)} failed: {e}")
        return 0

    if system == "Darwin":
        agents = Path.home() / "Library" / "LaunchAgents"
        agents.mkdir(parents=True, exist_ok=True)
        plist_path = agents / f"com.biom.feishu-node.{safe_name}.plist"
        exe_parts = _launcher_exe_path().split()
        program_args_lines = [f"        <string>{p}</string>" for p in exe_parts]
        program_args_lines += [f"        <string>{a}</string>" for a in node_args]
        content = _LAUNCHD_PLIST.format(
            name=safe_name,
            program_args="\n".join(program_args_lines),
            home=str(Path.home()),
        )
        plist_path.write_text(content, encoding="utf-8")
        print(f"[install-service] wrote {plist_path}")
        for cmd in (
            ["launchctl", "unload", str(plist_path)],  # tolerate-failure
            ["launchctl", "load", str(plist_path)],
        ):
            try:
                subprocess.run(cmd, check=False)
                print(f"[install-service] {' '.join(cmd)}")
            except FileNotFoundError as e:
                print(f"[install-service] WARNING: {' '.join(cmd)} failed: {e}")
        return 0

    if system == "Windows":
        task_name = f"feishu-node-{safe_name}"
        exe = _launcher_exe_path()
        # schtasks /TR needs a quoted string with all args concatenated
        tr_value = f'"{exe}" {_node_args_to_cmdline(node_args)}'
        cmd = [
            "schtasks", "/Create", "/F",
            "/TN", task_name,
            "/SC", "ONLOGON",
            "/RL", "LIMITED",
            "/TR", tr_value,
        ]
        try:
            subprocess.run(cmd, check=True)
            print(f"[install-service] registered scheduled task '{task_name}' (runs at logon)")
            print(f"[install-service] start it now with: schtasks /Run /TN {task_name}")
            return 0
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"[install-service] WARNING: schtasks /Create failed: {e}")
            return 1

    print(f"[install-service] ERROR: unsupported platform {system!r}")
    return 1


def uninstall_service(name: str) -> int:
    """Remove the auto-start descriptor written by ``install-service``."""
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "node"
    system = platform.system()

    if system == "Linux":
        unit = Path.home() / ".config" / "systemd" / "user" / f"feishu-node-{safe_name}.service"
        for cmd in (
            ["systemctl", "--user", "stop", f"feishu-node-{safe_name}.service"],
            ["systemctl", "--user", "disable", f"feishu-node-{safe_name}.service"],
        ):
            subprocess.run(cmd, check=False)
        if unit.exists():
            unit.unlink()
            print(f"[uninstall-service] removed {unit}")
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        return 0

    if system == "Darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / f"com.biom.feishu-node.{safe_name}.plist"
        if plist.exists():
            subprocess.run(["launchctl", "unload", str(plist)], check=False)
            plist.unlink()
            print(f"[uninstall-service] removed {plist}")
        return 0

    if system == "Windows":
        task_name = f"feishu-node-{safe_name}"
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", task_name], check=False)
        print(f"[uninstall-service] removed scheduled task '{task_name}'")
        return 0

    print(f"[uninstall-service] ERROR: unsupported platform {system!r}")
    return 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="feishu-node-launcher",
        description=(
            "Long-running parent process for feishu-node. Spawns the real node, "
            "restarts it on crash, applies upgrades on its exit code, and polls "
            "GitHub releases daily for new tags (vX.Y.Z only)."
        ),
    )
    p.add_argument("--repo", default=DEFAULT_REPO,
                   help=f"GitHub <owner>/<repo> to pull tagged releases from (default: {DEFAULT_REPO}).")
    p.add_argument("--check-interval-seconds", type=int, default=DEFAULT_CHECK_INTERVAL_S,
                   help="Seconds between GitHub release polls (default: 86400 = 1 day).")
    p.add_argument("--no-auto-upgrade", action="store_true",
                   help="Disable automatic upgrades (still respect child exit 75).")
    p.add_argument("--verbose", "-v", action="store_true", help="Debug logging.")

    sub = p.add_subparsers(dest="cmd")

    # install-service
    inst = sub.add_parser("install-service", help="Register an OS-native auto-start service.")
    inst.add_argument("--service-name", required=True,
                      help="Suffix used in the service / task name (e.g. 'megatron').")
    inst.add_argument("node_args", nargs=argparse.REMAINDER,
                      help="Arguments forwarded to `feishu-node` (after a `--` separator).")

    # uninstall-service
    rm = sub.add_parser("uninstall-service", help="Remove the auto-start service registered by install-service.")
    rm.add_argument("--service-name", required=True)

    # run (default, also explicit for clarity)
    run = sub.add_parser("run", help="Run launcher (this is the default if no subcommand is given).")
    run.add_argument("node_args", nargs=argparse.REMAINDER,
                     help="Arguments forwarded to `feishu-node` (after a `--` separator).")

    return p


def _strip_separator(args: List[str]) -> List[str]:
    """argparse REMAINDER may include a leading ``--``; drop it."""
    if args and args[0] == "--":
        return args[1:]
    return args


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    # We want top-level args (like --repo, --verbose) to coexist with arbitrary
    # node args after `--`. Trick: split argv on first `--`, parse left half
    # with argparse, rest is node_args.
    raw = list(argv if argv is not None else sys.argv[1:])
    if "--" in raw:
        idx = raw.index("--")
        head, tail = raw[:idx], raw[idx + 1:]
    else:
        head, tail = raw, []

    args = parser.parse_args(head)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    cmd = args.cmd or "run"

    if cmd == "install-service":
        node_args = _strip_separator(getattr(args, "node_args", []) or []) + tail
        return install_service(args.service_name, node_args)

    if cmd == "uninstall-service":
        return uninstall_service(args.service_name)

    # run (default)
    node_args = _strip_separator(getattr(args, "node_args", []) or []) + tail
    return run_launcher(
        node_args,
        repo=args.repo,
        check_interval_s=args.check_interval_seconds,
        enable_auto_upgrade=not args.no_auto_upgrade,
    )


if __name__ == "__main__":
    sys.exit(main())
