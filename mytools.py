import sys
from typing import Any, Callable, Iterable, TextIO, overload


def _unzip(*args):
    return zip(*args)


_METRIC_BASE, _METRIC_SUFFIX = _unzip(
    (1e-18, "a"),
    (1e-15, "f"),
    (1e-12, "p"),
    (1e-9, "n"),
    (1e-6, "µ"),
    (1e-3, "m"),
    (1, ""),
    (1e3, "k"),
    (1e6, "M"),
    (1e9, "G"),
    (1e12, "T"),
    (1e15, "P"),
    (1e18, "E"),
)


def metric_formatter(value: float, unit: str = "") -> Callable[[float], str]:
    value = abs(value)
    if value > 0:
        from bisect import bisect

        idx = max(0, bisect(_METRIC_BASE, value) - 1)
        base, suff = _METRIC_BASE[idx], _METRIC_SUFFIX[idx]
    else:
        base, suff = 1, ""

    suff = f" {suff}{unit}" if suff or unit else suff

    def fmt(value: float) -> str:
        value /= base
        if value < 99.5:
            if value < 9.95:
                if value > 0.001:
                    return f"{value:.2f}{suff}"
                return f"{value:.4g}{suff}"
            return f"{value:.1f}{suff}"
        if value < 9999:
            return f"{value:.0f}{suff}"
        return f"{value:.4g}{suff}"

    return fmt


def pretty_metric(value: float, unit: str = "") -> str:
    return metric_formatter(value, unit)(value)


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

    if seconds > 60:
        return hhmmss_formatter if seconds > 3600 else mmss_formatter

    return metric_formatter(seconds, "s")


def pretty_duration(seconds: float) -> str:
    "format seconds in a nice human readable format"
    return duration_formatter(seconds)(seconds)


@overload
def signif(values: float, digits: int) -> float:
    ...


@overload
def signif(values: Iterable[float], digits: int) -> list[float]:
    ...


def signif(
    values: float | Iterable[float], digits: int = 3
) -> float | list[float]:
    "Round value(s) to a given number of significant digits."
    from math import log10

    if isinstance(values, (int, float)):
        # should get a TypeError when iterating a float
        n = digits - int(log10(abs(values))) - 1
        return round(values, n)

    absvalues: Iterable[float] = map(abs, values)
    n = digits - int(log10(max(absvalues))) - 1
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


def _debug_dumps(
    obj: Any,
    protocol: str | None = None,
    *,
    dumps: Callable[..., bytes],
    timer: Callable[[], float],
) -> bytes:
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


def hook_multiprocessing_dumps_time(*, force: bool = False) -> None:
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

    def __init__(
        self, message: str = "", *, file: TextIO = sys.stderr
    ) -> None:
        self.message = message
        self.file = file

    def __enter__(self) -> None:
        from os import times

        self.start = times()

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
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
