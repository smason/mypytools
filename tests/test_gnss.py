import math
from datetime import UTC, date, time


def test_nmea_rmc():
    from mytools import gnss

    sentence = "$GNRMC,153523.00,A,6401.148556,N,02113.221761,W,46.1,40.8,220823,18.2,W,A,V*67"
    assert gnss.nmea_calc_checksum(sentence) == 0x67
    obj = gnss.NmeaRmc.parse(sentence)
    assert obj.talker_id == "GN"
    assert obj.time_utc == time(15, 35, 23, tzinfo=UTC)
    assert obj.status == gnss.RmcStatus.VALID
    assert math.isclose(obj.latitude, 64 + 1.148556 / 60)
    assert math.isclose(obj.longitude, -(21 + 13.221761 / 60))
    assert math.isclose(obj.speed_knots, 46.1)
    assert math.isclose(obj.track_made_good, 40.8)
    assert obj.date == date(2023, 8, 22)
    assert math.isclose(obj.magnetic_variation, -18.2)
    assert obj.faa_mode == gnss.FaaModeIndicator.AUTONOMOUS
    assert obj.nav_status == gnss.RmcNavStatus.VALID


def test_nmea_gga():
    from mytools import gnss

    sentence = "$GNGGA,001043.00,4404.14036,N,12118.85961,W,1,12,0.98,1113.0,M,-21.3,M*47"
    assert gnss.nmea_calc_checksum(sentence) == 0x47
    obj = gnss.NmeaGga.parse(sentence)
    assert obj.talker_id == "GN"
    assert obj.time_utc == time(0, 10, 43, tzinfo=UTC)
    assert math.isclose(obj.latitude, 44 + 4.14036 / 60)
    assert math.isclose(obj.longitude, -(121 + 18.85961 / 60))
    assert obj.quality_indicator == gnss.GgaQualityIndicator.GPS_FIX
    assert obj.num_satellites_in_use == 12
    assert math.isclose(obj.horizontal_dop, 0.98)
    assert math.isclose(obj.altitude, 1113.0)
    assert obj.altitude_units == "M"
    assert math.isclose(obj.geoidal_separation, -21.3)
    assert obj.geoidal_separation_units == "M"
