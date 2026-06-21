"""Bot process manager — spawn, stop, monitor, and recover bot subprocesses."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

import psutil

from forven.config import FORVEN_HOME
from forven.db import (
    get_bot,
    get_running_bots,
    log_activity,
    reconcile_orphaned_bot_trades,
    set_bot_status,
)

logger = logging.getLogger(__name__)

# How often to check heartbeats (seconds)
_MONITOR_INTERVAL = 30
# How long before a heartbeat is considered stale
# Must be generous — LLM calls + market data fetch can take 30-60s per tick
_HEARTBEAT_STALE_SECONDS = 180


def _is_pid_alive(pid: int) -> bool:
    """Check if a process is alive by PID."""
    if pid <= 0:
        return False
    try:
        process = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    try:
        if not process.is_running():
            return False
        if process.status() == psutil.STATUS_ZOMBIE:
            return False
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    except psutil.AccessDenied:
        return True
    return True


def _build_isolated_env(bot_config: dict) -> dict[str, str]:
    """Build a minimal environment for the bot subprocess.

    Only passes FORVEN_HOME, BOT_ID, and the specific LLM API key
    the bot needs. Does NOT inherit the parent's full environment.
    """
    env = {
        "FORVEN_HOME": str(FORVEN_HOME),
        "BOT_ID": bot_config["id"],
        # Minimal system env needed for Python to function
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
        # Windows needs these for Path.home() and user-level operations
        "USERPROFILE": os.environ.get("USERPROFILE", ""),
        "HOMEDRIVE": os.environ.get("HOMEDRIVE", ""),
        "HOMEPATH": os.environ.get("HOMEPATH", ""),
        "APPDATA": os.environ.get("APPDATA", ""),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
    }

    # Pass only the LLM API key the bot's model requires
    model = (bot_config.get("model") or "").lower()
    if "gpt" in model or "openai" in model or "o3" in model or "o4" in model:
        key = os.environ.get("OPENAI_API_KEY")
        if key:
            env["OPENAI_API_KEY"] = key
    elif "gemini" in model or "google" in model:
        key = os.environ.get("GOOGLE_API_KEY")
        if key:
            env["GOOGLE_API_KEY"] = key
    elif "minimax" in model:
        key = os.environ.get("MINIMAX_API_KEY")
        if key:
            env["MINIMAX_API_KEY"] = key
    else:
        # Unknown model — pass OpenAI key as default
        key = os.environ.get("OPENAI_API_KEY")
        if key:
            env["OPENAI_API_KEY"] = key

    return env


def _bot_log_path(bot_id: str) -> Path:
    """Get the log file path for a bot subprocess."""
    log_dir = FORVEN_HOME / "logs" / "bots"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"bot-{bot_id}.log"


class BotManager:
    """Manages bot subprocess lifecycles."""

    _instance: BotManager | None = None
    _processes: dict[str, subprocess.Popen]

    def __init__(self):
        self._processes = {}
        self._monitor_task: asyncio.Task | None = None

    @classmethod
    def get_instance(cls) -> BotManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start_bot(self, bot_id: str) -> dict:
        """Spawn a bot subprocess with isolated credentials."""
        bot = get_bot(bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} not found")

        status = bot.get("runtime_status") or bot.get("status", "stopped")
        if status == "running":
            raise ValueError(f"Bot {bot_id} is already running")

        env = _build_isolated_env(bot)
        log_path = _bot_log_path(bot_id)

        # H-R1: open the log file, hand it to Popen, then close OUR copy so the
        # FD doesn't leak if we repeatedly start/restart bots. The child keeps
        # its inherited copy. If Popen itself raises, we still close in `finally`.
        log_handle = log_path.open("a", encoding="utf-8")
        popen_kwargs = {
            "env": env,
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
            "close_fds": True,
        }

        if os.name == "nt":
            creationflags = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            )
            popen_kwargs["creationflags"] = creationflags
        else:
            popen_kwargs["start_new_session"] = True

        try:
            process = subprocess.Popen(
                [
                    sys.executable, "-m", "forven.bot_factory.runner",
                    "--bot-id", bot_id,
                    "--parent-pid", str(os.getpid()),
                ],
                **popen_kwargs,
            )
        finally:
            try:
                log_handle.close()
            except Exception:
                pass

        self._processes[bot_id] = process
        set_bot_status(bot_id, "running", pid=process.pid)
        log_activity(
            "info", "bot_factory",
            f"Bot '{bot.get('name', bot_id)}' started (PID {process.pid})",
            {"bot_id": bot_id, "pid": process.pid},
        )

        return {"status": "started", "pid": process.pid, "log_path": str(log_path)}

    def stop_bot(self, bot_id: str, timeout: float = 5.0) -> dict:
        """Stop a bot subprocess.

        On Windows, uses kill() directly since terminate() with
        CREATE_NEW_PROCESS_GROUP can be unreliable. Targets only the
        specific PID to avoid killing the parent process.
        """
        process = self._processes.get(bot_id)
        pid = None

        if process and process.poll() is None:
            pid = process.pid
        else:
            from forven.db import get_bot_status as _get_status
            status = _get_status(bot_id)
            if status and status.get("pid"):
                pid = status["pid"]

        if pid and _is_pid_alive(pid):
            # Safety: never kill our own process
            if pid == os.getpid():
                logger.error("Refusing to kill own PID %d for bot %s", pid, bot_id)
            else:
                try:
                    p = psutil.Process(pid)
                    # Verify this is actually a Python/bot process, not something else
                    try:
                        cmdline = p.cmdline()
                        if not any("bot_factory" in arg or "forven" in arg for arg in cmdline):
                            logger.warning("PID %d doesn't look like a bot process, skipping kill", pid)
                        else:
                            p.kill()  # Direct kill — most reliable on Windows
                            try:
                                p.wait(timeout=3)
                            except psutil.TimeoutExpired:
                                pass
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        p.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        self._processes.pop(bot_id, None)
        set_bot_status(bot_id, "stopped")

        bot = get_bot(bot_id)
        log_activity(
            "info", "bot_factory",
            f"Bot '{(bot or {}).get('name', bot_id)}' stopped",
            {"bot_id": bot_id},
        )
        return {"status": "stopped"}

    def kill_all(self) -> dict:
        """Stop all running bots immediately."""
        running = get_running_bots()
        stopped = 0
        for bot_info in running:
            try:
                self.stop_bot(bot_info["bot_id"], timeout=5.0)
                stopped += 1
            except Exception as e:
                logger.error("Failed to stop bot %s: %s", bot_info["bot_id"], e)
        log_activity(
            "warning", "bot_factory",
            f"Kill-all: stopped {stopped} bots",
            {"stopped_count": stopped},
        )
        return {"stopped": stopped}

    async def monitor_bots(self) -> None:
        """Background loop that checks heartbeats and marks stale bots as error."""
        from datetime import datetime, timezone

        while True:
            try:
                running = get_running_bots()
                now = datetime.now(timezone.utc)

                for bot_info in running:
                    bot_id = bot_info["bot_id"]
                    pid = bot_info.get("pid")
                    last_hb = bot_info.get("last_heartbeat")

                    # Check if PID is alive
                    if pid and not _is_pid_alive(pid):
                        logger.warning("Bot %s PID %s is dead", bot_id, pid)
                        set_bot_status(bot_id, "error", error_message="Process died unexpectedly")
                        log_activity(
                            "error", "bot_factory",
                            f"Bot '{bot_info.get('name', bot_id)}' process died (PID {pid})",
                            {"bot_id": bot_id, "pid": pid},
                        )
                        self._processes.pop(bot_id, None)
                        continue

                    # Check heartbeat staleness
                    if last_hb:
                        try:
                            hb_time = datetime.fromisoformat(last_hb.replace("Z", "+00:00"))
                            age = (now - hb_time).total_seconds()
                            if age > _HEARTBEAT_STALE_SECONDS:
                                logger.warning(
                                    "Bot %s heartbeat stale (%.0fs old)", bot_id, age
                                )
                                set_bot_status(
                                    bot_id, "error",
                                    error_message=f"Heartbeat stale ({int(age)}s)",
                                )
                                log_activity(
                                    "warning", "bot_factory",
                                    f"Bot '{bot_info.get('name', bot_id)}' heartbeat stale ({int(age)}s)",
                                    {"bot_id": bot_id, "stale_seconds": int(age)},
                                )
                        except (ValueError, TypeError):
                            pass

            except Exception as e:
                logger.error("Bot monitor error: %s", e)

            await asyncio.sleep(_MONITOR_INTERVAL)

    def recover_bots(self) -> dict:
        """On startup, recover bots that should be running.

        Recovers bots with status 'running' (crash mid-run), 'error'
        (heartbeat stale / process died), or that were stopped by
        shutdown_all during a clean restart. Uses a separate flag
        to track which bots were intentionally running.
        """
        from forven.db import get_db

        # Find all bots that were running or errored (not manually stopped)
        with get_db() as conn:
            rows = conn.execute(
                """SELECT s.bot_id, s.pid, s.status, c.name
                   FROM bot_status s
                   JOIN bot_configs c ON s.bot_id = c.id
                   WHERE s.status IN ('running', 'error')
                      OR (s.status = 'stopped' AND s.started_at IS NOT NULL
                          AND s.pid IS NOT NULL)"""
            ).fetchall()
            candidates = [dict(r) for r in rows]

        recovered = 0
        cleaned = 0

        for bot_info in candidates:
            bot_id = bot_info["bot_id"]
            pid = bot_info.get("pid")

            if pid and _is_pid_alive(pid):
                logger.info("Bot %s is still alive (PID %s), skipping recovery", bot_id, pid)
                continue

            # Bot was running but process is dead — re-spawn
            try:
                logger.info("Recovering bot %s (status: %s, old PID %s)", bot_id, bot_info.get("status"), pid)
                set_bot_status(bot_id, "stopped")
                self.start_bot(bot_id)
                recovered += 1
                log_activity(
                    "info", "bot_factory",
                    f"Bot '{bot_info.get('name', bot_id)}' auto-recovered after restart",
                    {"bot_id": bot_id},
                )
            except Exception as e:
                logger.error("Failed to recover bot %s: %s", bot_id, e)
                set_bot_status(bot_id, "error", error_message=f"Recovery failed: {e}")
                cleaned += 1

        # Close OPEN trades whose bot we did not bring back. After
        # recovery, `self._processes` has every bot we expect to be live.
        # Also include every still-alive pre-existing PID — those are bots
        # we didn't touch but that are still running the previous process.
        try:
            with get_db() as conn:
                alive_rows = conn.execute(
                    """SELECT bot_id, pid FROM bot_status
                        WHERE status = 'running' AND pid IS NOT NULL"""
                ).fetchall()
            still_alive = {
                r["bot_id"] for r in alive_rows
                if r["pid"] and _is_pid_alive(r["pid"])
            }
            active_ids = set(self._processes.keys()) | still_alive
            orphans = reconcile_orphaned_bot_trades(active_bot_ids=active_ids)
            if orphans:
                logger.info(
                    "Orphan reconcile on startup: closed %d trade(s) for bots not recovered",
                    len(orphans),
                )
                log_activity(
                    "warning", "bot_factory",
                    f"Orphan reconcile: closed {len(orphans)} bot trades at startup",
                    {"count": len(orphans)},
                )
        except Exception as e:
            logger.error("Orphan reconcile failed: %s", e)

        return {"recovered": recovered, "failed": cleaned}

    def shutdown_all(self) -> None:
        """Gracefully stop all bot processes during server shutdown.

        Kills processes but does NOT update DB status — so that
        recover_bots() on next startup sees them as needing restart.
        """
        running = get_running_bots()
        for bot_info in running:
            bot_id = bot_info["bot_id"]
            pid = bot_info.get("pid")
            if pid and _is_pid_alive(pid):
                try:
                    p = psutil.Process(pid)
                    p.terminate()
                    try:
                        p.wait(timeout=5.0)
                    except psutil.TimeoutExpired:
                        p.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            self._processes.pop(bot_id, None)
