"""SSH client with connection multiplexing, privilege escalation, and command execution."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .state import utcnow


class SSHError(Exception):
    exit_code = 5


@dataclass
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


Runner = Callable[[list[str], int], subprocess.CompletedProcess]


def subprocess_runner(argv: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


class SSHClient:
    """Thin wrapper around ssh/scp for fleet operations.

    Supports:
    - Connection multiplexing (ControlPersist 300s).
    - Configurable connect/command timeouts.
    - Privilege escalation modes (auto, sudo, root).
    - Strict host key checking (accept-new, yes).
    """

    def __init__(
        self,
        cfg: Any,
        env: dict[str, Any],
        runner: Runner | None = None,
        log_dir: str | Path | None = None,
    ) -> None:
        self.cfg = cfg
        self.env = env
        self.runner = runner or subprocess_runner
        self.log_dir = Path(log_dir) if log_dir else None
        self.connect_timeout = int(cfg.get("ssh.connect_timeout"))
        self.command_timeout = int(cfg.get("ssh.command_timeout"))
        self.strict = str(cfg.get("ssh.strict_host_key_checking"))
        self.privilege = str(cfg.get("ssh.privilege"))
        self.redact = [str(item) for item in cfg.get("logging.redact", [])]
        self.multiplex = bool(cfg.get("ssh.multiplex", True))
        self.mux_dir: Path | None = None
        if self.multiplex:
            mux_dir = Path(tempfile.gettempdir()) / f"fleet-ssh-{os.getuid()}"
            try:
                mux_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
                self.mux_dir = mux_dir
            except OSError:
                self.multiplex = False

    def _needs_privilege(self, requested: bool) -> bool:
        if not requested:
            return False
        if self.privilege == "root":
            return False
        if self.privilege == "sudo":
            return True
        return self.env["user"] != "root"

    def _wrap(self, command: str, need_privilege: bool) -> str:
        if self._needs_privilege(need_privilege):
            return f"sudo -n sh -c {shlex.quote(command)}"
        return command

    def _common_options(self) -> list[str]:
        options = [
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={self.connect_timeout}",
            "-o", f"StrictHostKeyChecking={self.strict}",
            "-i", str(self.env["key"]),
        ]
        if self.multiplex and self.mux_dir:
            options.extend([
                "-o", "ControlMaster=auto",
                "-o", f"ControlPath={self.mux_dir / '%r@%h-%p'}",
                "-o", "ControlPersist=300",
                "-o", "ServerAliveInterval=15",
                "-o", "ServerAliveCountMax=4",
            ])
        return options

    def _ssh_argv(self, ip: str, remote: str) -> list[str]:
        return [
            "ssh", *self._common_options(),
            "-p", str(self.env["port"]),
            f"{self.env['user']}@{ip}", "--", remote,
        ]

    def _scp_argv(self, ip: str, source: str, dest: str) -> list[str]:
        return [
            "scp", *self._common_options(),
            "-P", str(self.env["port"]),
            source, dest,
        ]

    def _redact(self, text: str) -> str:
        result = text
        for needle in self.redact:
            if needle:
                result = result.replace(needle, "***")
        return result

    def _log(self, ip: str, result: CommandResult) -> None:
        if not self.log_dir:
            return
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            path = self.log_dir / f"{ip}.log"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(f"[{utcnow()}] $ {' '.join(result.argv)}\n")
                handle.write(f"exit={result.returncode}\n")
                if result.stdout:
                    handle.write(self._redact(result.stdout) + "\n")
                if result.stderr:
                    handle.write("stderr: " + self._redact(result.stderr) + "\n")
            path.chmod(0o600)
        except OSError:
            pass

    def run(
        self,
        ip: str,
        command: str,
        *,
        timeout: int | None = None,
        need_privilege: bool = False,
        check: bool = False,
    ) -> CommandResult:
        remote = self._wrap(command, need_privilege)
        argv = self._ssh_argv(ip, remote)
        try:
            completed = self.runner(argv, timeout or self.command_timeout)
        except FileNotFoundError as exc:
            raise SSHError("ssh executable not found") from exc
        except subprocess.TimeoutExpired as exc:
            result = CommandResult(argv, 124, "", f"timeout after {timeout or self.command_timeout}s")
            self._log(ip, result)
            if check:
                raise SSHError(f"ssh to {ip} timed out") from exc
            return result
        result = CommandResult(argv, completed.returncode, completed.stdout or "", completed.stderr or "")
        self._log(ip, result)
        if check and not result.ok:
            raise SSHError(f"command failed on {ip}: {result.stderr.strip() or result.stdout.strip()}")
        return result

    def download(self, ip: str, remote: str, local: str | Path) -> CommandResult:
        target = Path(local)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        argv = self._scp_argv(ip, f"{self.env['user']}@{ip}:{remote}", str(target))
        try:
            completed = self.runner(argv, self.command_timeout)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise SSHError(f"scp download from {ip} failed: {exc}") from exc
        return CommandResult(argv, completed.returncode, completed.stdout or "", completed.stderr or "")

    def upload(self, ip: str, local: str | Path, remote: str) -> CommandResult:
        argv = self._scp_argv(ip, str(local), f"{self.env['user']}@{ip}:{remote}")
        try:
            completed = self.runner(argv, self.command_timeout)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise SSHError(f"scp upload to {ip} failed: {exc}") from exc
        return CommandResult(argv, completed.returncode, completed.stdout or "", completed.stderr or "")
