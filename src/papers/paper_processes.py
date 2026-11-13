"""Runs the checks of several papers at the same time, each call in one of a few processes that stay for further
calls. A process that ends or runs out of time costs only its own paper."""

from __future__ import annotations

import concurrent.futures
import multiprocessing
import os
import signal
import threading
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess

# Seconds that a process gets to start, which is the time to import the checks.
START_SECONDS = 120


def processors() -> int:
    """Return the number of processors that this run may use, which a container may set below those of the machine."""
    return getattr(os, "process_cpu_count", os.cpu_count)() or 1


class Failed(Exception):
    """A call did not return: its process ended, ran out of time, or raised an error."""


class PaperProcesses(concurrent.futures.Executor):
    """Runs each submitted call in a process, one process per thread of the pool, started with its first call.

    The processes end when the pool shuts down, also in the middle of a call, and when the process that started
    them is gone."""

    def __init__(self, workers: int, seconds: float):
        self._threads = concurrent.futures.ThreadPoolExecutor(workers)
        self._seconds = seconds
        self._own = threading.local()
        self._processes: list[BaseProcess] = []
        self._lock = threading.Lock()
        self._ended = False

    def submit(self, fn, /, *args, **kwargs):
        """Return the future of a call, which fails with Failed when the call does not return."""
        return self._threads.submit(self._call, fn, args, kwargs)

    def shutdown(self, wait=True, *, cancel_futures=False):
        """End every process at once and drop the calls that still wait."""
        with self._lock:
            self._ended = True
            for process in self._processes:
                process.kill()
        self._threads.shutdown(wait=True, cancel_futures=True)
        for process in self._processes:
            process.join()

    def _call(self, fn, args, kwargs):
        process, connection = self._process()
        try:
            connection.send((fn, args, kwargs))
            if not connection.poll(self._seconds):
                raise Failed(f"the checks did not finish within {self._seconds:g} seconds")
            returned, outcome = connection.recv()
        except (EOFError, OSError, Failed) as failure:
            # The process is gone or hangs, therefore the next call of this thread starts a new one.
            self._own.process = None
            process.kill()
            if isinstance(failure, Failed):
                raise
            raise Failed("the checks stopped while they read the PDF") from None
        if not returned:
            raise Failed(outcome)
        return outcome

    def _process(self) -> tuple[BaseProcess, Connection]:
        """Return the process of this thread and the connection to it, and start one when the thread has none."""
        if getattr(self._own, "process", None) is None:
            # A started process imports the checks anew, which also works where a process cannot fork, as on Windows.
            context = multiprocessing.get_context("spawn")
            ours, theirs = context.Pipe()
            process = context.Process(target=_work, args=(theirs,))
            with self._lock:
                if self._ended:
                    raise Failed("the run ended before the checks started")
                process.start()
                self._processes.append(process)
            theirs.close()
            try:
                if not ours.poll(START_SECONDS):
                    raise EOFError
                ours.recv()
            except (EOFError, OSError):
                process.kill()
                raise RuntimeError("a process of the paper checks did not start") from None
            self._own.process = (process, ours)
        return self._own.process


def _work(connection: Connection) -> None:
    """Run each call that comes in and send back its result or the text of its error."""
    end_with_starter()
    connection.send(None)
    while True:
        try:
            fn, args, kwargs = connection.recv()
        except EOFError:
            return
        try:
            outcome = (True, fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            outcome = (False, f"{type(exc).__name__}: {exc}")
        try:
            connection.send(outcome)
        except Exception as exc:  # noqa: BLE001
            # A result that cannot cross to the other process, such as an object of a C library.
            connection.send((False, f"{type(exc).__name__}: {exc}"))


def end_with_starter() -> None:
    """Let this process end once the process that started it is gone, such as after Ctrl+C or a kill."""
    # Ctrl+C reaches every process of a terminal. This process and the ones it starts leave it to the starter.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    threading.Thread(target=_end_after, args=(multiprocessing.parent_process(),), daemon=True).start()


def _end_after(starter: BaseProcess) -> None:
    starter.join()
    os._exit(1)
