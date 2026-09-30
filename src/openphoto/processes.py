"""Owned, bounded processes. Closing a Windows job also closes native grandchildren."""

from __future__ import annotations

import ctypes
import multiprocessing
import os
import subprocess
import threading
from ctypes import wintypes


def configure_threads(limit=4):
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = str(limit)
    os.environ["HF_HUB_OFFLINE"] = "1"


class OwnedProcesses:
    def __init__(self):
        self.handle = None
        self.processes = []
        if os.name != "nt":
            return

        class Basic(ctypes.Structure):
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

        class IO(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", Basic),
                ("IoInfo", IO),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        for name, args, result in (
            ("CreateJobObjectW", [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            (
                "SetInformationJobObject",
                [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
                wintypes.BOOL,
            ),
            ("AssignProcessToJobObject", [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            (
                "IsProcessInJob",
                [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)],
                wintypes.BOOL,
            ),
            ("OpenProcess", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            ("CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
        ):
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = args, result
        self.handle = self.kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle or not self.kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def add(self, process):
        import psutil

        parent = psutil.Process(process.pid)
        self.processes.append(parent)

        def assign(member):
            handle = self.kernel.OpenProcess(0x0100 | 0x0001 | 0x0400, False, member.pid)
            try:
                already = wintypes.BOOL()
                if not handle or not self.kernel.IsProcessInJob(handle, self.handle, ctypes.byref(already)):
                    raise ctypes.WinError(ctypes.get_last_error())
                if not already.value and not self.kernel.AssignProcessToJobObject(self.handle, handle):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                if handle:
                    self.kernel.CloseHandle(handle)

        if self.handle:
            assign(parent)
            # A venv launcher may have already created the actual Python interpreter.
            # Future descendants inherit the job; attach pre-existing descendants too.
            for child in parent.children(recursive=True):
                try:
                    assign(child)
                    self.processes.append(child)
                except (psutil.NoSuchProcess, OSError):
                    if child.is_running():
                        raise

    def popen(self, args, **kwargs):
        """Attach before the first instruction, including before the venv launcher runs."""
        if os.name == "nt":
            kwargs["creationflags"] = (
                kwargs.get("creationflags", 0) | 0x00000004 | subprocess.CREATE_NO_WINDOW
            )
        process = subprocess.Popen(args, **kwargs)
        try:
            self.add(process)
            if os.name == "nt":
                import psutil

                self.kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                self.kernel.OpenThread.restype = wintypes.HANDLE
                self.kernel.ResumeThread.argtypes = [wintypes.HANDLE]
                self.kernel.ResumeThread.restype = wintypes.DWORD
                threads = psutil.Process(process.pid).threads()
                if len(threads) != 1:
                    raise RuntimeError("Expected the suspended process's initial thread")
                handle = self.kernel.OpenThread(0x0002, False, threads[0].id)
                try:
                    if not handle or self.kernel.ResumeThread(handle) == 0xFFFFFFFF:
                        raise ctypes.WinError(ctypes.get_last_error())
                finally:
                    if handle:
                        self.kernel.CloseHandle(handle)
            return process
        except BaseException:
            process.kill()
            process.wait(timeout=5)
            raise

    def close(self):
        import psutil

        owned = {}
        for process in self.processes:
            try:
                for child in [*process.children(recursive=True), process]:
                    owned[child.pid] = child
            except psutil.NoSuchProcess:
                pass
        # Capture descendants while their parent still exists; closing a Job Object
        # initiates termination and can otherwise make the ancestry disappear first.
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        for process in owned.values():
            try:
                process.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(list(owned.values()), timeout=3)
        for process in alive:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(alive, timeout=3)
        self.processes.clear()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _worker(directory, stop, admitted, idle_seconds, threads):
    if not admitted.wait(15):
        return
    configure_threads(threads)
    from pathlib import Path

    os.environ["MPLCONFIGDIR"] = str(Path(directory) / "cache" / "matplotlib")
    import cv2

    cv2.setNumThreads(threads)
    from .service import worker_loop

    worker_loop(directory, stop, idle_seconds=idle_seconds)


class WorkerSupervisor:
    """One heavy worker, started on demand and retired after inactivity."""

    def __init__(self, catalog):
        self.catalog = catalog
        self.context = multiprocessing.get_context("spawn")
        self.stop = self.context.Event()
        self.owner = OwnedProcesses()
        self.process = None
        self.thread = threading.Thread(target=self._run, name="openphoto-scheduler", daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        from .database import ProcessingJob

        try:
            while not self.stop.wait(0.5):
                if self.process:
                    if self.process.is_alive():
                        continue
                    self.process.join()
                    self.process.close()
                    self.process = None
                    self.owner.close()
                    self.owner = OwnedProcesses()
                    with self.catalog.session() as session:
                        for job in session.query(ProcessingJob).filter_by(state="running"):
                            job.state = "paused"
                            job.error = "Рабочий процесс завершился. Можно продолжить задание."
                    from .job_lifecycle import recover_exports

                    recover_exports(self.catalog)
                with self.catalog.session() as session:
                    pending = session.query(ProcessingJob).filter_by(state="queued").first() is not None
                if pending:
                    settings = self.catalog.settings()
                    admitted = self.context.Event()
                    self.process = self.context.Process(
                        target=_worker,
                        args=(
                            str(self.catalog.directory),
                            self.stop,
                            admitted,
                            settings.get("worker_idle_seconds", 120),
                            settings.get("cpu_threads", 4),
                        ),
                        daemon=True,
                    )
                    self.process.start()
                    self.owner.add(self.process)
                    admitted.set()
        except Exception:
            import logging

            logging.exception("OpenPhoto scheduler failed")
            self.stop.set()
            self.owner.close()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)
        if self.process:
            self.process.join(timeout=3)
        self.owner.close()
        if self.process:
            self.process.join(timeout=3)
            self.process.close()
            self.process = None

    def status(self):
        try:
            pid = self.process.pid if self.process else None
        except ValueError:
            pid = None
        return {
            "worker_pid": pid,
            "max_heavy_operations": 1,
            "scheduler_alive": self.thread.is_alive(),
        }
