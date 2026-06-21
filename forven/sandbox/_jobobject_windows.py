"""Windows Job Object wrapper for sandboxed strategy execution (P2-T06).

A thin ctypes layer over the Win32 Job Object API. The runner spawns the
child suspended, assigns it to a Job Object configured with memory + CPU
limits + KILL_ON_JOB_CLOSE, then resumes the thread. On wall-clock timeout
the runner calls :func:`terminate_job` which kills every process in the
job — leader plus any grandchildren — in one shot.

This module is a no-op on non-Windows platforms; importers should gate on
``sys.platform == 'win32'``. All ctypes calls are wrapped in try/except so
import never raises on a host where ``kernel32`` happens to be missing.

Phase 0's :mod:`forven.sandbox` already has a similar Job Object plumbing
for ``run_code(...)``. This module duplicates a small slice of that surface
because it adds:

* ``CREATE_SUSPENDED`` spawn + ``ResumeThread`` (so we can assign-then-run
  rather than racing the child).
* CPU time accounting via ``QueryInformationJobObject``.
* Peak memory readback via ``JobObjectExtendedLimitInformation``.
"""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from dataclasses import dataclass

log = logging.getLogger("forven.sandbox.jobobject")

IS_WINDOWS = sys.platform == "win32"

# --- Win32 constants -------------------------------------------------------
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_JOB_TIME = 0x00000004
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800

JobObjectExtendedLimitInformation = 9
JobObjectBasicAccountingInformation = 1

CREATE_SUSPENDED = 0x00000004


if IS_WINDOWS:

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_int64),
            ("TotalKernelTime", ctypes.c_int64),
            ("ThisPeriodTotalUserTime", ctypes.c_int64),
            ("ThisPeriodTotalKernelTime", ctypes.c_int64),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]


@dataclass
class JobObject:
    handle: int
    kernel32: object


def create_job_with_limits(
    *, mem_mb: int, cpu_s: int
) -> JobObject | None:
    """Create a Job Object enforcing memory + CPU + kill-on-close.

    Returns None if the host is not Windows or any Win32 call fails.
    """
    if not IS_WINDOWS:
        return None

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ]

        h_job = kernel32.CreateJobObjectW(None, None)
        if not h_job:
            log.debug("CreateJobObjectW failed (errno=%s)", ctypes.get_last_error())
            return None

        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | JOB_OBJECT_LIMIT_JOB_TIME
            | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        # JOB_TIME is in 100-ns ticks.
        info.BasicLimitInformation.PerJobUserTimeLimit = cpu_s * 10_000_000
        info.ProcessMemoryLimit = mem_mb * 1024 * 1024

        ok = kernel32.SetInformationJobObject(
            h_job, JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info),
        )
        if not ok:
            log.debug("SetInformationJobObject failed (errno=%s)", ctypes.get_last_error())
            kernel32.CloseHandle(h_job)
            return None

        return JobObject(handle=h_job, kernel32=kernel32)
    except Exception as exc:  # noqa: BLE001
        log.debug("Job object creation failed: %s", exc)
        return None


def assign_pid_to_job(job: JobObject, pid: int) -> bool:
    if not IS_WINDOWS or not job or not pid:
        return False
    try:
        k32 = job.kernel32
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

        h_proc = k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not h_proc:
            return False
        try:
            return bool(k32.AssignProcessToJobObject(job.handle, h_proc))
        finally:
            k32.CloseHandle(h_proc)
    except Exception as exc:  # noqa: BLE001
        log.debug("AssignProcessToJobObject failed: %s", exc)
        return False


def terminate_job(job: JobObject, exit_code: int = 124) -> bool:
    """Kill EVERY process in the job. Returns True on success."""
    if not IS_WINDOWS or not job:
        return False
    try:
        k32 = job.kernel32
        k32.TerminateJobObject.restype = wintypes.BOOL
        k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        return bool(k32.TerminateJobObject(job.handle, exit_code))
    except Exception as exc:  # noqa: BLE001
        log.debug("TerminateJobObject failed: %s", exc)
        return False


def query_job_telemetry(job: JobObject) -> tuple[int | None, float | None]:
    """Return (peak_memory_mb, cpu_seconds) for *job*, or (None, None) on failure.

    Reads ``JobObjectExtendedLimitInformation.PeakJobMemoryUsed`` and
    ``JobObjectBasicAccountingInformation.TotalUserTime + TotalKernelTime``.
    """
    if not IS_WINDOWS or not job:
        return None, None
    try:
        k32 = job.kernel32
        k32.QueryInformationJobObject.restype = wintypes.BOOL
        k32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        ]

        ext = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        returned = wintypes.DWORD(0)
        ok_mem = k32.QueryInformationJobObject(
            job.handle, JobObjectExtendedLimitInformation,
            ctypes.byref(ext), ctypes.sizeof(ext), ctypes.byref(returned),
        )
        peak_mb: int | None = None
        if ok_mem:
            peak_mb = int(ext.PeakJobMemoryUsed) // (1024 * 1024)

        acct = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        ok_acct = k32.QueryInformationJobObject(
            job.handle, JobObjectBasicAccountingInformation,
            ctypes.byref(acct), ctypes.sizeof(acct), ctypes.byref(returned),
        )
        cpu_s: float | None = None
        if ok_acct:
            # 100-ns ticks → seconds.
            cpu_s = float(acct.TotalUserTime + acct.TotalKernelTime) / 1e7

        return peak_mb, cpu_s
    except Exception as exc:  # noqa: BLE001
        log.debug("QueryInformationJobObject failed: %s", exc)
        return None, None


def close_job(job: JobObject | None) -> None:
    if not IS_WINDOWS or not job:
        return
    try:
        job.kernel32.CloseHandle(job.handle)
    except Exception:  # noqa: BLE001
        pass
