import re
import warnings
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import Enum
from typing import Iterable, Optional, Self

NMEA_TALKER_DESCRIPTIONS = {
    # Combination of multiple satellite systems (NMEA 1083)
    "GN": "GNSS",
    # Global navigation satellite systems
    "GP": "GPS",  # USA
    "GL": "GLONASS",  # Russian
    "GA": "Galileo",  # European
    "GB": "BeiDou",  # Chinese
    # Regional navigation satellite systems
    "GI": "NavIC",  # Indian
    "GQ": "QZSS",  # Japanese
}

NMEA_TYPE_DESCRIPTIONS = {
    "DTM": "Datum Reference",
    "GGA": "Global Positioning System Fix Data",
    "GNS": "Fix data",
    "GSA": "GPS DOP and active satellites",
    "GSV": "Satellites in view",
    "RMC": "Recommended Minimum Navigation Information",
    "VTG": "Track made good and Ground speed",
}


# Maximum NMEA sentence length, including the $ and <CR><LF> is 82 bytes.
NMEA_SENTENCE = re.compile(r"\$(.{,120})\*([0-9A-F]{2})", re.IGNORECASE)
NMEA_FIELDSEP = re.compile(r"\s*,\s*")

# Pxxx   = Vendor specific
# U[0-9] = User configured
NMEA_COMMON_TALKERS = re.compile(r"^[A-OQ-TV-Z][A-Z]$")

# R00 is a rare enough to ignore
NMEA_COMMON_TYPES = re.compile(r"^[A-Z]{3}$")

NMEA_TAG_FIELD = re.compile(r"^\$([A-OQ-Z][A-Z]|U[0-9])([A-Z]{3}|R00),")


def nmea_calc_checksum(sentence: str) -> int:
    m = NMEA_SENTENCE.match(sentence)
    if not m or m.end() != len(sentence):
        raise ValueError(f"{sentence!r} is not an NMEA sentence")
    result = 0
    for code in m.group(1).encode("ascii"):
        result ^= code
    return result


def read_nmea_sentences(
    lines: Iterable[str], *, accept_types=(), warn: bool = True
) -> Iterable[str]:
    accept_set = set(accept_types)
    if warn:
        for code in accept_set:
            if not NMEA_COMMON_TYPES.match(code):
                warnings.warn(
                    f"{code!r} in accept_types is unlikely to match anything"
                )
    for line in lines:
        if m := NMEA_SENTENCE.search(line):
            sentence = m.group(0)
            if accept_set:
                if tt := NMEA_TAG_FIELD.match(sentence):
                    talker, type = tt.groups()
                    # only checking type field at the moment
                    if type not in accept_set:
                        continue
                else:
                    if warn:
                        start = f"{sentence:.10}..."
                        warnings.warn(
                            f"unusual NMEA tag formatting {start!r}, ignoring sentence"
                        )
                    continue
            expected = int(m.group(2), 16)
            calculated = nmea_calc_checksum(sentence)
            if expected == calculated:
                yield sentence
            elif warn:
                warnings.warn(
                    f"NMEA checksum invalid for {sentence!r}, {expected=:02x} != {calculated=:02x}"
                )


def parse_fields(sentence: str) -> list[str]:
    if m := NMEA_SENTENCE.match(sentence):
        return NMEA_FIELDSEP.split(m.group(1))
    raise ValueError(f"{sentence!r} is not an NMEA sentence")


class FaaModeIndicator(Enum):
    AUTONOMOUS = "A"
    QUECTEL_QUERK_CAUTION = "C"
    DIFFERENTIAL = "D"
    ESTIMATED = "E"
    RTK_FLOAT = "F"
    MANUAL_INPUT = "M"
    NOT_VALID = "N"
    PRECISE = "P"
    RTK_INTEGER = "R"
    SIMULATED = "S"
    QUECTEL_QUERK_UNSAFE = "U"


def parse_packed_ddmm(value: str, nsew: str) -> float:
    # TODO: reorganise code to have more float precision
    degs, mins = divmod(float(value), 100)
    # TODO: should this validation be tightened up?
    if not (0 <= degs <= 360):
        raise ValueError("degrees not between 0 and 360")
    if not (0 <= mins <= 60):
        raise ValueError("minutes not between 0 and 60")
    result = degs + mins / 60
    match nsew.casefold():
        case "n" | "e":
            return result
        case "s" | "w":
            return -result
        case _:
            raise ValueError("unsupported cardinal direction")


def parse_deg(value: str, nsew: str) -> float:
    degs = float(value)
    # TODO: should this validation be tightened up?
    if not (0 <= degs <= 360):
        raise ValueError(f"degrees should be in [0, 360] (not {degs})")
    match nsew.casefold():
        case "n" | "e":
            return degs
        case "s" | "w":
            return -degs
        case _:
            raise ValueError("unsupported cardinal direction")


def parse_utc_time(hhmmss: str) -> time:
    return datetime.strptime(hhmmss, "%H%M%S.%f").time().replace(tzinfo=UTC)


class GgaQualityIndicator(Enum):
    FIX_NOT_AVAILABLE = 0
    GPS_FIX = 1
    DIFFERENTIAL_GPS_FIX = 2
    # values above 2 are 2.3 features
    PPS_FIX = 3
    REAL_TIME_KINEMATIC = 4
    FLOAT_RTK = 5
    ESTIMATED = 6
    MANUAL_INPUT_MODE = 7
    SIMULATION_MODE = 8


@dataclass(slots=True)
class NmeaGga:
    "Global Positioning System Fix Data"
    talker_id: str

    time_utc: Optional[time] = None

    # north = positive latitude, south = negative latitude
    # east = positive longitude, west = negaite longitude
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    quality_indicator: Optional[GgaQualityIndicator] = None

    # DOP = "dilution of precision"
    num_satellites_in_use: Optional[int] = None
    horizontal_dop: Optional[float] = None

    # note that altitude refers to the antenna
    # positive when above mean-sea-level, negative when below
    altitude: Optional[float] = None
    # not sure why this wouldn't be "M" for meters!
    altitude_units: Optional[str] = None

    # difference between the WGS-84 earth ellipsoid and mean-sea-level.
    # negative when geoid is below WGS-84 ellipsoid
    geoidal_separation: Optional[float] = None
    # not sure why this wouldn't be "M" for meters!
    geoidal_separation_units: Optional[str] = None

    # DGPS = Differential GPS
    # time in seconds since last SC104 type 1 or 9 update, null field when DGPS is not used
    dgps_data_age: Optional[float] = None
    dgps_reference_station_id: Optional[str] = None

    @classmethod
    def parse(cls, sentence: str) -> Self:
        match parse_fields(sentence):
            case [
                # fmt: off
                tag, time, lat, ns, lon, ew, quality, nsats, hdop,
                altitude, altunits, geoidsep, geoidsepunits, *remain,
                # fmt: on
            ] if tag.endswith("GGA"):
                result = cls(talker_id=tag[:-3])
            case _:
                raise ValueError(f"{sentence!r} not a GGA sentence")
        if time:
            result.time_utc = parse_utc_time(time)
        if lat:
            result.latitude = parse_packed_ddmm(lat, ns)
        if lon:
            result.longitude = parse_packed_ddmm(lon, ew)
        if quality:
            result.quality_indicator = GgaQualityIndicator(int(quality))
        if nsats:
            result.num_satellites_in_use = int(nsats)
        if hdop:
            result.horizontal_dop = float(hdop)
        if altitude:
            result.altitude = float(altitude)
        if altunits:
            if altunits.casefold() != "m":
                warnings.warn(
                    f"NMEA GGA altitude units not using meters ({altunits!r})"
                )
            result.altitude_units = altunits
        if geoidsep:
            result.geoidal_separation = float(geoidsep)
        if geoidsepunits:
            if altunits and geoidsepunits != altunits:
                warnings.warn(
                    "NMEA GGA altitude and geoid seperation units different "
                    f"({altunits!r} != {geoidsepunits!r})"
                )
            result.geoidal_separation_units = geoidsepunits
        match remain:
            case [dgps_age, dgps_ref, *remain]:
                if dgps_age:
                    result.dgps_data_age = float(dgps_age)
                if dgps_ref:
                    result.dgps_reference_station_id = dgps_ref
        if remain:
            warnings.warn(
                f"{len(remain)} NMEA GGA fields remain after parsing, {remain=}"
            )
        return result


class RmcStatus(Enum):
    VALID = "A"
    WARNING = "V"


class RmcNavStatus(Enum):
    AUTONOMOUS = "A"
    DIFFERENTIAL = "D"
    ESTIMATED = "E"  # also known as "dead reckoning"
    MANUAL_INPUT = "M"
    SIMULATOR = "S"
    NOT_VALID = "N"
    VALID = "V"


@dataclass(slots=True)
class NmeaRmc:
    "System Recommended Minimum Navigation Information"
    talker_id: str

    time_utc: Optional[time] = None
    status: Optional[RmcStatus] = None

    # north = positive latitude, south = negative latitude
    # east = positive longitude, west = negaite longitude
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # speed over ground
    speed_knots: Optional[float] = None
    track_made_good: Optional[float] = None
    date: Optional[date] = None

    # east positive, west negative
    magnetic_variation: Optional[float] = None

    faa_mode: Optional[FaaModeIndicator] = None
    nav_status: Optional[RmcNavStatus] = None

    @classmethod
    def parse(cls, sentence: str) -> Self:
        match parse_fields(sentence):
            case [
                # fmt: off
                tag, time, status, lat, ns, lon, ew,
                speed, tmg, date, magvar, magvar_ew, *remain,
                # fmt: on
            ] if tag.endswith("RMC"):
                result = cls(talker_id=tag[:-3])
            case _:
                raise ValueError(f"{sentence!r} not a RMC sentence")
        if time:
            result.time_utc = parse_utc_time(time)
        if status:
            result.status = RmcStatus(status)
        if lat:
            result.latitude = parse_packed_ddmm(lat, ns)
        if lon:
            result.longitude = parse_packed_ddmm(lon, ew)
        if speed:
            result.speed_knots = float(speed)
        if tmg:
            result.track_made_good = float(tmg)
        if date:
            result.date = datetime.strptime(date, "%d%m%y").date()
        if magvar:
            result.magnetic_variation = parse_deg(magvar, magvar_ew)
        match remain:
            case [faa_mode, *remain] if faa_mode:
                result.faa_mode = FaaModeIndicator(faa_mode)
        match remain:
            case [nav_status, *remain] if nav_status:
                result.nav_status = RmcNavStatus(nav_status)
        if remain:
            warnings.warn(
                f"{len(remain)} NMEA RMC fields remain after parsing, {remain=}"
            )
        return result
