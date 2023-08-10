import pytest

import mytools


def test_metric_formatter():
    assert mytools.pretty_metric(0) == "0"
    assert mytools.pretty_metric(1) == "1.00"
    assert mytools.pretty_metric(1000) == "1.00 k"
    assert mytools.pretty_metric(1010) == "1.01 k"
    assert mytools.pretty_metric(0.1) == "100 m"
    assert mytools.pretty_metric(0.01, "m") == "10.0 mm"
    assert mytools.pretty_metric(2**30) == "1.07 G"
    assert mytools.pretty_metric(1e-30) == "1e-12 a"
    assert mytools.pretty_metric(1e30) == "1e+12 E"


def test_time_formatter():
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

    assert mytools.pretty_duration(0) == "0 s"
    assert mytools.pretty_duration(1e-10) == "100 ps"
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


@pytest.fixture
def db():
    import sqlite3

    # save references
    aref = sqlite3.adapters
    cref = sqlite3.converters
    # save existing state
    astate = dict(aref)
    cstate = dict(cref)
    # let the user go with the database
    yield sqlite3.connect(":memory:", detect_types=sqlite3.PARSE_COLNAMES)
    # try and undo anything they did
    aref.clear()
    cref.clear()
    aref.update(astate)
    cref.update(cstate)
    sqlite3.adapters = aref
    sqlite3.converters = cref


def test_sqlite_types(db):
    from datetime import UTC, datetime, timedelta, timezone

    mytools.register_sqlite3_datetime_types()

    PLUS4 = timezone(timedelta(hours=4), "plus4")

    good_datetimes = (
        ("2000-01-01T00:00:00Z", datetime(2000, 1, 1, tzinfo=UTC)),
        ("2000-01-01T00:00:00+04:00", datetime(2000, 1, 1, tzinfo=PLUS4)),
    )

    for text, value in good_datetimes:
        # test converter
        [[result]] = db.execute('SELECT :text "[datetime]"', locals())
        assert result == value

        # test adapter
        [[result]] = db.execute("SELECT :value", locals())
        assert result == text

    with pytest.raises(ValueError):
        [row] = db.execute(
            'SELECT :s "[datetime]"', dict(s="2000-01-01T00:00:00")
        )
        print(row)
