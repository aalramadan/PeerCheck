"""Tests of the processes that run the checks of several papers at the same time."""

from __future__ import annotations

import multiprocessing
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from peercheck.papers import paper_processes
from peercheck.papers.paper_processes import Failed, PaperProcesses

ON_WINDOWS = os.name == "nt"
STARTER = """
import sys
import time

from peercheck.papers.paper_processes import PaperProcesses
from test_paper_processes import _pid_after

if __name__ == "__main__":
    pool = PaperProcesses(2, 600)
    print(*(job.result() for job in [pool.submit(_pid_after, 0.5), pool.submit(_pid_after, 0.5)]), flush=True)
    for _number in range(2):
        pool.submit(_pid_after, 600)
    time.sleep(600)
"""


def _pid_of(number):
    return number, os.getpid()


def _pid_after(seconds):
    time.sleep(seconds)
    return os.getpid()


def _ending_on_2(number):
    if number == 2:
        os._exit(1)
    return number


def _raising(number):
    raise ValueError(f"made-up error {number}")


def _unsendable():
    return threading.Lock()


def _exit_code_of_a_process_of_its_own():
    process = multiprocessing.get_context("spawn").Process(target=_interrupting_itself, daemon=True)
    process.start()
    process.join()
    return process.exitcode


def _interrupting_itself():
    if not ON_WINDOWS:
        os.kill(os.getpid(), signal.SIGINT)
    time.sleep(0.2)


def _ending_at_once(connection):
    os._exit(1)


def _gone(pid: int) -> bool:
    """Tell whether a process ended, also where no process has collected its exit code yet."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    state = Path(f"/proc/{pid}/stat")
    return state.is_file() and state.read_text(encoding="utf-8").rsplit(")", 1)[1].split()[0] == "Z"


def _all_gone(pids, seconds: float = 20) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end and not all(map(_gone, pids)):
        time.sleep(0.1)
    return all(map(_gone, pids))


def test_run_may_use_at_least_one_processor_and_at_most_those_of_the_machine():
    assert 1 <= paper_processes.processors() <= os.cpu_count()


def test_each_call_returns_its_own_result_from_one_of_the_processes():
    with PaperProcesses(2, 60) as pool:
        results = [job.result() for job in [pool.submit(_pid_of, number) for number in range(6)]]
    assert [number for number, _pid in results] == list(range(6))
    pids = {pid for _number, pid in results}
    assert len(pids) <= 2 and os.getpid() not in pids


def test_calls_run_in_as_many_processes_as_the_pool_has_at_the_same_time():
    with PaperProcesses(3, 60) as pool:
        pids = {job.result() for job in [pool.submit(_pid_after, 1) for _number in range(3)]}
    assert len(pids) == 3


def test_call_whose_process_ends_fails_alone_while_the_other_calls_return():
    with PaperProcesses(2, 60) as pool:
        jobs = [pool.submit(_ending_on_2, number) for number in range(1, 6)]
        with pytest.raises(Failed, match="the checks stopped while they read the PDF"):
            jobs[1].result()
        assert [job.result() for job in jobs[:1] + jobs[2:]] == [1, 3, 4, 5]


def test_call_that_runs_out_of_time_fails_alone_and_its_process_ends():
    with PaperProcesses(1, 1) as pool:
        pid = pool.submit(_pid_after, 0).result()
        slow, quick = pool.submit(_pid_after, 60), pool.submit(_pid_after, 0)
        with pytest.raises(Failed, match="the checks did not finish within 1 seconds"):
            slow.result()
        assert quick.result() != pid
        assert _all_gone([pid])


def test_call_that_raises_fails_with_the_text_of_its_error_and_its_process_stays():
    with PaperProcesses(1, 60) as pool:
        first, second, third = pool.submit(_pid_of, 1), pool.submit(_raising, 2), pool.submit(_pid_of, 3)
        with pytest.raises(Failed, match="ValueError: made-up error 2"):
            second.result()
        assert first.result()[1] == third.result()[1]


def test_result_that_cannot_cross_to_the_starting_process_fails_its_call_alone():
    with PaperProcesses(1, 60) as pool:
        with pytest.raises(Failed, match="TypeError: cannot pickle"):
            pool.submit(_unsendable).result()
        assert pool.submit(_pid_of, 1).result()[0] == 1


def test_call_starts_a_process_of_its_own_which_an_interrupt_leaves_running_as_well():
    with PaperProcesses(1, 60) as pool:
        assert pool.submit(_exit_code_of_a_process_of_its_own).result() == 0


def test_pool_that_shuts_down_ends_its_processes_in_the_middle_of_a_call():
    start = time.monotonic()
    with pytest.raises(KeyboardInterrupt), PaperProcesses(2, 600) as pool:
        pids = [job.result() for job in [pool.submit(_pid_after, 0.5), pool.submit(_pid_after, 0.5)]]
        waiting = [pool.submit(_pid_after, 600) for _number in range(6)]
        raise KeyboardInterrupt
    assert time.monotonic() - start < 60
    assert len(set(pids)) == 2 and _all_gone(pids, seconds=0)
    assert all(job.cancelled() or isinstance(job.exception(), Failed) for job in waiting)


def test_process_that_does_not_start_stops_its_call_with_an_error_of_the_run(monkeypatch):
    monkeypatch.setattr(paper_processes, "_work", _ending_at_once)
    with PaperProcesses(1, 60) as pool, pytest.raises(RuntimeError, match="a process of the paper checks did not"):
        pool.submit(_pid_of, 1).result()


@pytest.mark.skipif(ON_WINDOWS, reason="Windows sends no interrupt to a single process")
def test_interrupt_leaves_a_process_at_its_call_since_the_pool_ends_the_processes():
    with PaperProcesses(1, 600) as pool:
        pid = pool.submit(_pid_after, 0).result()
        slow = pool.submit(_pid_after, 2)
        time.sleep(0.5)
        os.kill(pid, signal.SIGINT)
        assert slow.result(timeout=60) == pid


@pytest.mark.skipif(ON_WINDOWS, reason="the test asks the system whether a process is gone")
def test_processes_end_once_the_process_that_started_them_is_gone(tmp_path):
    script = tmp_path / "starter.py"
    script.write_text(STARTER, encoding="utf-8")
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, sys.path))}
    with subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True, env=environment) as starter:
        pids = [int(pid) for pid in starter.stdout.readline().split()]
        starter.kill()
    assert len(set(pids)) == 2
    assert _all_gone(pids)
