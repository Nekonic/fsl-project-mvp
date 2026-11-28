import logging
import time

UTC9_SECONDS = 9 * 3600


class Utc9Formatter(logging.Formatter):
    default_time_format = "%Y-%m-%dT%H:%M:%S"
    default_msec_format = "%s.%03d+09:00"

    @staticmethod
    def converter(seconds):
        return time.gmtime(seconds + UTC9_SECONDS)
