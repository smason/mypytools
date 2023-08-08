import mytools


def test_formatter():
    assert mytools.hhmmss_formatter(-1) == "-0:00:01 hours"
    assert mytools.hhmmss_formatter(0) == "0:00:00 hours"
    assert mytools.hhmmss_formatter(0.4) == "0:00:00 hours"
    assert mytools.hhmmss_formatter(0.6) == "0:00:01 hours"
    assert mytools.hhmmss_formatter(1) == "0:00:01 hours"
    assert mytools.hhmmss_formatter(60) == "0:01:00 hours"
    assert mytools.hhmmss_formatter(3600) == "1:00:00 hours"
    assert mytools.hhmmss_formatter(-3600) == "-1:00:00 hours"

    assert mytools.mmss_formatter(-1) == "-0:01 minutes"
    assert mytools.mmss_formatter(0) == "0:00 minutes"
    assert mytools.mmss_formatter(0.4) == "0:00 minutes"
    assert mytools.mmss_formatter(0.6) == "0:01 minutes"
    assert mytools.mmss_formatter(1) == "0:01 minutes"
    assert mytools.mmss_formatter(60) == "1:00 minutes"
    assert mytools.mmss_formatter(-60) == "-1:00 minutes"

    assert mytools.pretty_duration(0) == "0.00 s"
    assert mytools.pretty_duration(1e-10) == "0.1 ns"
    assert mytools.pretty_duration(1e-9) == "1.00 ns"
    assert mytools.pretty_duration(1e-8) == "10.0 ns"
    assert mytools.pretty_duration(1e-7) == "100 ns"
    assert mytools.pretty_duration(1e-6) == "1.00 µs"
    assert mytools.pretty_duration(1e-5) == "10.0 µs"
    assert mytools.pretty_duration(1e-4) == "100 µs"
    assert mytools.pretty_duration(1e-3) == "1.00 ms"
    assert mytools.pretty_duration(1e-2) == "10.0 ms"
    assert mytools.pretty_duration(1e-1) == "100 ms"
    assert mytools.pretty_duration(1) == "1.00 s"
    assert mytools.pretty_duration(10) == "10.0 s"
    assert mytools.pretty_duration(100) == "1:40 minutes"


def test_signif():
    assert mytools.signif(1.234) == 1.23
    assert mytools.signif(1234) == 1230
    assert mytools.signif([1, 10, 100]) == [1, 10, 100]
    assert mytools.signif([0.1, 1, 10], 2) == [0, 1, 10]
