import time
from datetime import datetime, timezone, timedelta

MYT_OFFSET = timedelta(hours=8)


def now_ms() -> int:
    """Epoch milliseconds UTC."""
    return int(time.time() * 1000)


def now_local_str() -> str:
    """Current time as ISO-8601 string in MYT (UTC+8), for human-readable fields."""
    return (datetime.now(timezone.utc) + MYT_OFFSET).strftime("%Y-%m-%d %H:%M:%S MYT")


def ms_to_local_str(ms: int) -> str:
    """Convert epoch ms UTC to MYT ISO-8601 string."""
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc) + MYT_OFFSET
    return dt.strftime("%Y-%m-%d %H:%M:%S MYT")
