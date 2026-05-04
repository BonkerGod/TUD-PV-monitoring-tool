'''
Tools for determining when to take measurements. Including:

datetime_range()
'''

from datetime import datetime, timedelta, timezone
from math import ceil


def datetime_range(
    start: datetime,
    end: datetime,
    interval: timedelta,
    origin: datetime = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    include_start_point: bool = True,
    include_end_point: bool = True
):
    '''Returns a list of datetime objects starting at `start_date`,  spaced
    `interval` apart, ending on or before `end_date`. Works fine with tz-aware
    datetime objects. Avoids unix timestamps and error-prone timezone
    double-conversions.

    Intervals are aligned starting at `origin`, which is by default the start
    of the Unix epoch.'''
    result = []
    if origin:
        moment = next_occurrence(start, interval, origin)
    else:
        moment = start
    if (not include_start_point) and (moment == start):
        moment += interval
    if include_end_point:
        while moment <= end:
            result.append(moment)
            moment += interval
    else:
        while moment < end:
            result.append(moment)
            moment += interval
    return result


def next_occurrence(
    start: datetime,
    interval: timedelta,
    origin: datetime = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
):
    '''Returns the next occurrence, after `start`, of a recurring event that
    started at `origin` and occurs every `interval`'''
    return origin + ceil((start - origin) / interval) * interval


def seconds(td):
    '''Given a timedelta `td`, returns the eqivalent number of seconds.'''
    return td / timedelta(seconds=1)


def present():
    '''Returns a tz-aware datetime object for the present time in UTC'''
    return datetime.now(timezone.utc)
