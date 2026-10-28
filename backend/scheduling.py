from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
TZ = ZoneInfo('Asia/Taipei')
def window_start(now, start, end):
    s, e = time.fromisoformat(start), time.fromisoformat(end)
    t = now.time().replace(tzinfo=None)
    base = now.replace(hour=s.hour, minute=s.minute, second=0, microsecond=0)
    if s < e:
        return base if s <= t < e else None
    if s > e:
        return base if t >= s else base-timedelta(days=1) if t < e else None
    return None

def slot(now, start, end, minutes):
    base = window_start(now, start, end)
    if base is None:
        return None
    n = int((now-base).total_seconds()) // (minutes*60)
    return (base+timedelta(minutes=n*minutes)).isoformat()
