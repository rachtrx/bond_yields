from datetime import datetime, timedelta
import pytz
import logging

def current_sg_time(dt_type=None, hour_offset = None):
    singapore_tz = pytz.timezone('Asia/Singapore')

    dt = datetime.now(singapore_tz)

    if hour_offset:
        dt = dt.replace(hour=hour_offset, minute=0, second=0, microsecond=0)

    if dt_type:
        return dt.strftime(dt_type)
    else:
        return dt
    
timeframes = {
    '4H': 240,
    '2H': 120,
    '1H': 60,
    '30M': 30,
    '15M': 15,
    '5M': 5,
    '1M': 1
}