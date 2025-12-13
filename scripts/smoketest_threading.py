"""
Stress tests for thread-safety of the timezone cache.

Note this isn't a unit test, because it relies on a clean cache
"""

import sys
import time
from itertools import cycle, islice
from threading import Thread

from whenever import PlainDateTime

if not hasattr(sys, "_is_gil_enabled") or sys._is_gil_enabled():
    # Running with GIL enabled can still be useful to compare performance,
    # but be sure to warn that threading hasn't been stress tested.
    print("WARNING: Running with GIL enabled. Threading not stress tested.")


PLAIN_DT = PlainDateTime(2024, 6, 15, 12, 0)
NUM_THREADS = 16
NUM_ITERATIONS = 10_000
TIMEZONE_SAMPLE = [
    "UTC",
    "America/Guyana",
    "Etc/GMT-11",
    "Europe/Vienna",
    "America/Rainy_River",
    "Asia/Ulaanbaatar",
    "US/Alaska",
    "America/Rankin_Inlet",
    "Arctic/Longyearbyen",
    "Pacific/Bougainville",
    "Africa/Monrovia",
    "Europe/Copenhagen",
    "America/Hermosillo",
    "Africa/Brazzaville",
    "Asia/Tashkent",
    "Pacific/Saipan",
    "Europe/Tallinn",
    "Europe/Uzhgorod",
    "Africa/Nairobi",
    "America/Argentina/Ushuaia",
    "Brazil/Acre",
]
TZS = list(islice(cycle(TIMEZONE_SAMPLE), NUM_THREADS * NUM_ITERATIONS))


def touch_timezones(tzs):
    """A minimal function that triggers a timezone lookup"""
    for tz in tzs:
        zdt = PLAIN_DT.assume_tz(tz)
        del zdt


def main():
    threads = []

    start_time = time.time()

    for n in range(NUM_THREADS):
        thread = Thread(target=touch_timezones, args=(TZS[n::NUM_THREADS],))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    end_time = time.time()
    print(f"Execution time: {end_time - start_time:.2f} seconds")


if __name__ == "__main__":
    main()
