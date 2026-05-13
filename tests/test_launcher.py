"""Tests for the auto-upgrade launcher."""

from __future__ import annotations

import io
import json
import platform
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from feishu_node import launcher


# ---------------------------------------------------------------------------
# semver / tag helpers
# ---------------------------------------------------------------------------

class TestSemverHelpers:
    def test_parse_strips_v(self):
        assert launcher._parse_semver("v1.2.3") == (1, 2, 3)
        assert launcher._parse_semver("0.5.0") == (0, 5, 0)

    def test_parse_rejects_bad(self):
        assert launcher._parse_semver("v1.2") is None
        assert launcher._parse_semver("v1.2.3-rc1") is None
        assert launcher._parse_semver("latest") is None
        assert launcher._parse_semver("") is None

    def test_is_newer(self):
        assert launcher.is_newer("v0.2.0", "0.1.0") is True
        assert launcher.is_newer("v1.0.0", "0.99.99") is True
        assert launcher.is_newer("v0.2.0", "0.2.0") is False
        assert launcher.is_newer("v0.1.0", "0.2.0") is False

    def test_is_newer_handles_garbage(self):
        assert launcher.is_newer("bogus", "0.1.0") is False
        assert launcher.is_newer("v0.2.0", "bogus") is False


# ---------------------------------------------------------------------------
# fetch_latest_tag — only accepts vX.Y.Z
# ---------------------------------------------------------------------------

class _FakeUrlOpen:
    """Patch target for urllib.request.urlopen as a context manager."""

    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return io.BytesIO(self.payload)

    def __exit__(self, *args):
        return False


class TestFetchLatestTag:
    def test_accepts_clean_semver_tag(self):
        with patch("feishu_node.launcher.urllib.request.urlopen",
                   return_value=_FakeUrlOpen({"tag_name": "v0.2.1"})):
            assert launcher.fetch_latest_tag("any/repo") == "v0.2.1"

    def test_rejects_non_semver_tag(self):
        for bad in ("latest", "v1.2", "v1.2.3-rc1", "release-2026-05-13", ""):
            with patch("feishu_node.launcher.urllib.request.urlopen",
                       return_value=_FakeUrlOpen({"tag_name": bad})):
                assert launcher.fetch_latest_tag("any/repo") is None, bad

    def test_network_failure_returns_none(self):
        def boom(*a, **k):
            raise OSError("network down")
        with patch("feishu_node.launcher.urllib.request.urlopen", side_effect=boom):
            assert launcher.fetch_latest_tag("any/repo") is None


# ---------------------------------------------------------------------------
# pip_upgrade_to_tag — refuses unsafe tags
# ---------------------------------------------------------------------------

class TestPipUpgrade:
    def test_refuses_unsafe_tag(self):
        with patch("feishu_node.launcher.subprocess.run") as run:
            for bad in ("main", "../etc/passwd", "v1.2.3; rm -rf /", "v1.2"):
                ok = launcher.pip_upgrade_to_tag("any/repo", bad)
                assert ok is False, bad
            assert run.call_count == 0  # nothing executed

    def test_invokes_pip_with_pinned_tag(self):
        fake = MagicMock(returncode=0, stderr="", stdout="ok")
        with patch("feishu_node.launcher.subprocess.run", return_value=fake) as run:
            assert launcher.pip_upgrade_to_tag("foo/bar", "v0.2.1") is True
        # Verify first call was the main pip install
        assert run.call_count >= 1
        cmd = run.call_args_list[0][0][0]
        assert cmd[:3] == [launcher.sys.executable, "-m", "pip"]
        assert "install" in cmd and "--upgrade" in cmd and "--force-reinstall" in cmd
        spec = cmd[-1]
        assert spec == "git+https://github.com/foo/bar.git@v0.2.1"

    def test_pip_failure_returns_false(self):
        fake = MagicMock(returncode=1, stderr="boom", stdout="")
        with patch("feishu_node.launcher.subprocess.run", return_value=fake):
            assert launcher.pip_upgrade_to_tag("foo/bar", "v0.2.1") is False


# ---------------------------------------------------------------------------
# UpgradePoller.consume_upgrade_pending
# ---------------------------------------------------------------------------

class TestPoller:
    def test_pending_starts_false(self):
        p = launcher.UpgradePoller("r", 999, lambda: None)
        assert p.upgrade_pending is False
        assert p.consume_upgrade_pending() is False

    def test_pending_set_and_consume(self):
        p = launcher.UpgradePoller("r", 999, lambda: None)
        p._upgrade_pending.set()
        assert p.upgrade_pending is True
        assert p.consume_upgrade_pending() is True
        assert p.consume_upgrade_pending() is False  # consumed


# ---------------------------------------------------------------------------
# run_launcher exit-code routing — does it dispatch to upgrade vs crash vs ok?
# ---------------------------------------------------------------------------

class _ScriptedChild:
    """Simulates a sequence of child processes with predetermined exit codes.

    Each call to ``next_proc()`` returns a MagicMock whose ``wait()`` returns
    the next code from the queue. ``poll()`` returns None initially then the
    exit code (so terminate paths don't break).
    """

    def __init__(self, codes):
        self.codes = list(codes)
        self.spawned = 0

    def next_proc(self):
        if not self.codes:
            raise StopIteration
        code = self.codes.pop(0)
        m = MagicMock()
        m._waited = False

        def _wait(timeout=None):
            m._waited = True
            return code

        def _poll():
            return None if not m._waited else code

        m.wait.side_effect = _wait
        m.poll.side_effect = _poll
        m.terminate.return_value = None
        self.spawned += 1
        return m


class TestRunLauncher:
    def test_graceful_exit_stops_loop(self):
        scripted = _ScriptedChild([0])
        with patch("feishu_node.launcher._spawn_child", side_effect=lambda *_: scripted.next_proc()):
            rc = launcher.run_launcher(["--server", "ws://x", "--name", "n"], enable_auto_upgrade=False)
        assert rc == 0
        assert scripted.spawned == 1

    def test_upgrade_exit_triggers_pip_and_respawn(self):
        scripted = _ScriptedChild([75, 0])  # first child says "upgrade me", second exits clean
        # GitHub returns a newer tag; pip succeeds
        with patch("feishu_node.launcher._spawn_child", side_effect=lambda *_: scripted.next_proc()), \
             patch("feishu_node.launcher.fetch_latest_tag", return_value="v9.9.9"), \
             patch("feishu_node.launcher.is_newer", return_value=True), \
             patch("feishu_node.launcher.pip_upgrade_to_tag", return_value=True) as pip:
            rc = launcher.run_launcher(["--server", "ws://x", "--name", "n"], enable_auto_upgrade=False)
        assert rc == 0
        assert scripted.spawned == 2
        pip.assert_called_once()

    def test_crash_backoff_eventually_gives_up(self, monkeypatch):
        # Five consecutive crashes => give up; rc=2
        monkeypatch.setattr(launcher, "BASE_BACKOFF_S", 0)
        monkeypatch.setattr(launcher, "MAX_BACKOFF_S", 0)
        scripted = _ScriptedChild([1, 1, 1, 1, 1])
        with patch("feishu_node.launcher._spawn_child", side_effect=lambda *_: scripted.next_proc()):
            rc = launcher.run_launcher(["--server", "ws://x", "--name", "n"], enable_auto_upgrade=False)
        assert rc == 2
        assert scripted.spawned == 5


# ---------------------------------------------------------------------------
# install-service / uninstall-service — generate the right artifact per OS
# ---------------------------------------------------------------------------

@pytest.fixture
def _fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


class TestInstallServiceLinux:
    def test_writes_systemd_unit_and_invokes_systemctl(self, _fake_home):
        if platform.system() != "Linux":
            pytest.skip("Linux-only test")
        with patch("feishu_node.launcher.subprocess.run") as run:
            rc = launcher.install_service("megatron", ["--server", "wss://x", "--name", "megatron"])
        assert rc == 0
        unit = _fake_home / ".config" / "systemd" / "user" / "feishu-node-megatron.service"
        assert unit.exists()
        text = unit.read_text(encoding="utf-8")
        assert "ExecStart=" in text
        assert "--server" in text and "wss://x" in text
        # systemctl --user calls were attempted
        cmds = [c.args[0] for c in run.call_args_list]
        assert any("systemctl" in cmd[0] and "enable" in cmd for cmd in cmds)


class TestInstallServiceMacOS:
    def test_writes_plist_and_invokes_launchctl(self, _fake_home):
        if platform.system() != "Darwin":
            pytest.skip("macOS-only test")
        with patch("feishu_node.launcher.subprocess.run") as run:
            rc = launcher.install_service("megatron", ["--server", "wss://x", "--name", "megatron"])
        assert rc == 0
        plist = _fake_home / "Library" / "LaunchAgents" / "com.biom.feishu-node.megatron.plist"
        assert plist.exists()
        text = plist.read_text(encoding="utf-8")
        assert "<key>Label</key><string>com.biom.feishu-node.megatron</string>" in text
        assert "<string>--server</string>" in text
        cmds = [c.args[0] for c in run.call_args_list]
        assert any(cmd[0] == "launchctl" and cmd[1] == "load" for cmd in cmds)


class TestInstallServiceCrossPlatformContent:
    """Force the content-generation path for all three OSes regardless of host OS,
    by patching platform.system. Skips the actual systemctl/launchctl/schtasks
    invocations (mocked out)."""

    def test_linux_unit_content(self, _fake_home, monkeypatch):
        monkeypatch.setattr(launcher.platform, "system", lambda: "Linux")
        with patch("feishu_node.launcher.subprocess.run"):
            launcher.install_service("rvq", ["--server", "wss://a", "--allow-dir", "/d"])
        unit = _fake_home / ".config" / "systemd" / "user" / "feishu-node-rvq.service"
        assert unit.exists()
        text = unit.read_text(encoding="utf-8")
        assert "Restart=on-failure" in text
        assert "WantedBy=default.target" in text
        assert "wss://a" in text and "/d" in text

    def test_darwin_plist_content(self, _fake_home, monkeypatch):
        monkeypatch.setattr(launcher.platform, "system", lambda: "Darwin")
        with patch("feishu_node.launcher.subprocess.run"):
            launcher.install_service("rvq", ["--server", "wss://a", "--allow-dir", "/d"])
        plist = _fake_home / "Library" / "LaunchAgents" / "com.biom.feishu-node.rvq.plist"
        assert plist.exists()
        text = plist.read_text(encoding="utf-8")
        assert "<key>RunAtLoad</key><true/>" in text
        assert "<key>KeepAlive</key><true/>" in text
        assert "wss://a" in text and "/d" in text

    def test_windows_invokes_schtasks(self, _fake_home, monkeypatch):
        monkeypatch.setattr(launcher.platform, "system", lambda: "Windows")
        fake = MagicMock(returncode=0)
        with patch("feishu_node.launcher.subprocess.run", return_value=fake) as run:
            rc = launcher.install_service("rvq", ["--server", "wss://a"])
        assert rc == 0
        # First call should be schtasks /Create
        cmd = run.call_args_list[0].args[0]
        assert cmd[0] == "schtasks"
        assert "/Create" in cmd
        assert any("/TN" in part or part == "feishu-node-rvq" for part in cmd)

    def test_unknown_platform_errors(self, _fake_home, monkeypatch):
        monkeypatch.setattr(launcher.platform, "system", lambda: "Plan9")
        rc = launcher.install_service("rvq", ["--server", "wss://a"])
        assert rc == 1


class TestUninstallService:
    def test_linux_removes_unit(self, _fake_home, monkeypatch):
        monkeypatch.setattr(launcher.platform, "system", lambda: "Linux")
        unit_dir = _fake_home / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        unit = unit_dir / "feishu-node-rvq.service"
        unit.write_text("dummy", encoding="utf-8")
        with patch("feishu_node.launcher.subprocess.run"):
            rc = launcher.uninstall_service("rvq")
        assert rc == 0
        assert not unit.exists()


# ---------------------------------------------------------------------------
# CLI: argparse + node-args separator
# ---------------------------------------------------------------------------

class TestCLI:
    def test_run_default_with_separator(self, monkeypatch):
        called = {}

        def fake_run(node_args, **kw):
            called["node_args"] = node_args
            called["kw"] = kw
            return 0

        monkeypatch.setattr(launcher, "run_launcher", fake_run)
        rc = launcher.main(["--repo", "x/y", "--", "--server", "wss://a", "--name", "n"])
        assert rc == 0
        assert called["node_args"] == ["--server", "wss://a", "--name", "n"]
        assert called["kw"]["repo"] == "x/y"

    def test_install_service_via_cli(self, monkeypatch):
        called = {}

        def fake_install(name, node_args):
            called["name"] = name
            called["node_args"] = node_args
            return 0

        monkeypatch.setattr(launcher, "install_service", fake_install)
        rc = launcher.main([
            "install-service", "--service-name", "n1",
            "--", "--server", "wss://a", "--name", "n1",
        ])
        assert rc == 0
        assert called["name"] == "n1"
        assert called["node_args"] == ["--server", "wss://a", "--name", "n1"]

    def test_no_auto_upgrade_flag(self, monkeypatch):
        called = {}

        def fake_run(node_args, **kw):
            called.update(kw)
            return 0

        monkeypatch.setattr(launcher, "run_launcher", fake_run)
        launcher.main(["--no-auto-upgrade", "--", "--server", "wss://a", "--name", "n"])
        assert called["enable_auto_upgrade"] is False
