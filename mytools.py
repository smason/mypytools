from typing import Callable
import bisect
import sys
import os
import time
import pickle
import warnings
import functools

_TIME_VALS, _TIME_SUFFIX = zip(*[
    (1e0, 's'),
    (1e3, 'ms'),
    (1e6, 'µs'),
    (1e9, 'ns'),
])


def hhmmss_formatter(seconds: float) -> str:
    "format seconds as HH:MM:SS"
    value, ss = divmod(seconds, 60)
    hh, mm = divmod(value, 60)
    return f'{hh}:{mm:02}:{ss:02.0f} hours'


def mmss_formatter(seconds: float) -> str:
    mm, ss = divmod(seconds, 60)
    return f'{mm}:{ss:02.0f} minutes'


def duration_formatter(seconds: float) -> Callable[[float], str]:
    "return a formatter suitable for a given duration"
    i = bisect.bisect(_TIME_VALS, 1.1 / seconds)

    if i == 0:
        if seconds > 3600:
            return hhmmss_formatter
        if seconds > 60:
            return mmss_formatter

    if i == len(_TIME_VALS):
        return lambda s: f'{s * 1e9:f} ns'

    def fn(seconds: float) -> str:
        seconds *= _TIME_VALS[i]
        if seconds < 2:
            return f'{seconds:.2f} {_TIME_SUFFIX[i]}'
        return f'{seconds:.1f} {_TIME_SUFFIX[i]}'

    return fn


def pretty_duration(seconds):
    "format seconds in a nice human readable format"
    return duration_formatter(seconds)(seconds)


def debug_dumps(obj, protocol=None, *, dumps=pickle.dumps):
    t0 = time.perf_counter()
    buf = dumps(obj, protocol)
    dt = time.perf_counter() - t0
    if dt > 0.1 or len(buf) > 2**16:
        print(
            f"{os.getpid()}) large/slow pickler.dumps() => {len(buf)/2**20:.2f} MiB"
            f", took {pretty_duration(dt)}",
            file=sys.stderr,
        )
    return buf


def hook_multiprocessing_dumps_time(*, force=True):
    import multiprocessing
    cls = multiprocessing.reduction.ForkingPickler
    if cls.dumps.__module__ != 'multiprocessing.reduction' and not force:
        warnings.warn("dumps already seems to be hooked, pass force=True to override")
        return
    cls.dumps = functools.partial(debug_dumps, dumps=cls.dumps)


class ProcessTimer:
    "context manager for recording time taken to run code"
    def __init__(self, message, *, file=sys.stderr, prefix=None):
        self.message = message
        self.prefix = prefix or ('  ' if message else '')
        self.file = file

    def __enter__(self):
        self.start = os.times()

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop = os.times()
        if self.file is None:
            return

        message = self.message
        prefix = self.prefix
        t0 = self.start
        t1 = self.stop

        wall = t1.elapsed - t0.elapsed
        user = t1.user - t0.user
        system = t1.system - t0.system
        total = user + system

        cuser = t1.children_user - t0.children_user
        csystem = t1.children_system - t0.children_system
        ctotal = cuser + csystem

        lines = []
        if message:
            lines.append(
                f"=== {message} ==="
            )
        fmt = duration_formatter(max(total, ctotal))
        lines.append(
            f"{prefix}CPU times: user {fmt(user)}, sys {fmt(system)}, total {fmt(total)}"
        )
        if ctotal > 0:
            lines.append(
                f"{prefix}Child CPU: user {fmt(cuser)}, sys {fmt(csystem)}, total {fmt(ctotal)} s"
            )
        lines.append(
            f"{prefix}Wall time: {pretty_duration(wall)}"
        )
        print('\n'.join(lines), file=self.file)
