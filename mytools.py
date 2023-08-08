import sys
from typing import Callable


def _unzip(*args):
    return zip(*args)


_TIME_VALS, _TIME_SUFFIX = _unzip(
    (1e0, "s"),
    (1e3, "ms"),
    (1e6, "µs"),
    (1e9, "ns"),
)


def hhmmss_formatter(seconds: float) -> str:
    "format seconds as 'HH:MM:SS hours'"
    value, ss = divmod(round(abs(seconds)), 60)
    hh, mm = divmod(value, 60)
    sign = "-" if seconds < 0 else ""
    return f"{sign}{hh}:{mm:02}:{ss:02} hours"


def mmss_formatter(seconds: float) -> str:
    "format seconds as 'MM:SS minutes'"
    mm, ss = divmod(round(abs(seconds)), 60)
    sign = "-" if seconds < 0 else ""
    return f"{sign}{mm}:{ss:02} minutes"


def duration_formatter(seconds: float) -> Callable[[float], str]:
    "return a formatter suitable for a given duration"
    seconds = abs(seconds)
    if seconds > 0:
        from bisect import bisect

        idx = bisect(_TIME_VALS, 1 / seconds)
    else:
        idx = 0

    if idx == 0:
        if seconds > 3600:
            return hhmmss_formatter
        if seconds > 60:
            return mmss_formatter

    def tiny(seconds):
        return f"{seconds * 1e9} ns"

    def si(seconds: float) -> str:
        seconds *= _TIME_VALS[idx]
        if seconds < 1.2:
            return f"{seconds:.2f} {_TIME_SUFFIX[idx]}"
        if seconds < 12:
            return f"{seconds:.1f} {_TIME_SUFFIX[idx]}"
        return f"{seconds:.0f} {_TIME_SUFFIX[idx]}"

    return tiny if idx == len(_TIME_VALS) else si


def pretty_duration(seconds):
    "format seconds in a nice human readable format"
    return duration_formatter(seconds)(seconds)


def signif(values, digits=3):
    "Round value(s) to a given number of significant digits."
    from math import log10

    try:
        absvalues = map(abs, values)
    except TypeError:
        # should get a TypeError when iterating a float
        n = int(digits - log10(abs(values)))
        return round(values, n)

    n = int(digits - log10(max(absvalues)))
    return [round(v, n) for v in values]


def _is_current_process_main() -> bool:
    import multiprocessing

    try:
        parent = multiprocessing.parent_process
    except AttributeError:
        # via: https://stackoverflow.com/a/50435263/1358308
        proc = multiprocessing.current_process()
        return proc.name == "MainProcess"
    else:
        return parent is None


def _debug_dumps(obj, protocol=None, *, dumps, timer):
    t0 = timer()
    buf = dumps(obj, protocol)
    dt = timer() - t0
    if dt > 0.1 or len(buf) > 2**16:
        from os import getpid

        name = "parent" if _is_current_process_main() else "child"
        sys.stderr.write(
            f"big multiprocessing IO: {len(buf)/2**20:.2f} MiB, "
            f"encode took {pretty_duration(dt)}, "
            f"in {name} pid={getpid()}\n"
        )
    return buf


def hook_multiprocessing_dumps_time(*, force=False):
    import functools
    import time
    from multiprocessing.reduction import ForkingPickler as cls

    "cause multiprocessing to output a message when pickling large messages"
    if cls.dumps.__module__ != "multiprocessing.reduction" and not force:
        import warnings

        warnings.warn(
            "multiprocessing already seems to be hooked, pass force=True to override"
        )
        return

    cls.dumps = functools.partial(
        _debug_dumps, dumps=cls.dumps, timer=time.perf_counter
    )


class ContextTimer:
    "context manager for recording time taken to run code"

    def __init__(self, message=None, *, file=sys.stderr):
        self.message = message
        self.file = file

    def __enter__(self):
        from os import times

        self.start = times()

    def __exit__(self, exc_type, exc_value, traceback):
        from os import times

        self.stop = times()
        if self.file is None:
            return

        message = self.message
        t0 = self.start
        t1 = self.stop

        wall = t1.elapsed - t0.elapsed
        user = t1.user - t0.user
        system = t1.system - t0.system
        total = user + system

        cuser = t1.children_user - t0.children_user
        csystem = t1.children_system - t0.children_system
        ctotal = cuser + csystem

        fmt = duration_formatter(max(total, ctotal))

        lines = []
        if message:
            lines.append(f" === {message} ===\n")
        lines.append(
            f"CPU times: user {fmt(user)}, sys {fmt(system)}, total {fmt(total)}\n"
        )
        if ctotal > 0:
            lines.append(
                f"Child CPU: user {fmt(cuser)}, sys {fmt(csystem)}, total {fmt(ctotal)}\n"
            )
        lines.append(f"Wall time: {pretty_duration(wall)}\n")
        self.file.write("".join(lines))
