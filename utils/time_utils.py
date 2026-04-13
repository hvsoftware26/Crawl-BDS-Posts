# Time utilities
from datetime import datetime, timedelta, timezone
from typing import Optional
from logging import getLogger
HANOI_TIMEZONE = timezone(timedelta(hours=7))
FACEBOOK_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
DISPLAY_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

logger = getLogger(__name__)

def caclulate_next_run(groups_count: int, cycle_time: int):
    """
    cycle_time: hours
    return: minutes for next run
    """
    return cycle_time * 60.0 / groups_count


def format_facebook_created_time(created_time: Optional[str]):
    """
    Convert Facebook UTC datetime strings to Hanoi datetime format.
    """
    if not created_time:
        return None

    parsed_time = datetime.strptime(created_time, FACEBOOK_TIME_FORMAT)
    return parsed_time.astimezone(HANOI_TIMEZONE).strftime(DISPLAY_DATE_FORMAT)


def parse_created_time(created_time: Optional[str]):
    """
    Parse supported post datetime strings.
    """
    if not created_time:
        return None

    for time_format in (DISPLAY_DATE_FORMAT, FACEBOOK_TIME_FORMAT):
        try:
            return datetime.strptime(created_time, time_format)
        except ValueError:
            continue

    return None


def is_created_time_within_delay_window(
    created_time: Optional[str],
    delay_seconds: int,
    now: Optional[datetime] = None,
):
    """
    Check whether created_time is within [now - delay_seconds, now].
    """
    parsed_time = parse_created_time(created_time)
    if not parsed_time:
        return False

    reference_time = now or datetime.now(HANOI_TIMEZONE)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=HANOI_TIMEZONE)

    parsed_time = parsed_time.astimezone(reference_time.tzinfo)
    window_start = reference_time - timedelta(seconds=max(delay_seconds, 0))
    #window_start = reference_time - timedelta(hours=10)
    if not (window_start <= parsed_time <= reference_time):
        logger.debug(
            "Post created_time %s is outside the delay window: parsed_time=%s window_start=%s reference_time=%s",
            created_time,
            parsed_time.isoformat(),
            window_start.isoformat(),
            reference_time.isoformat(),
        )
    return window_start <= parsed_time <= reference_time
