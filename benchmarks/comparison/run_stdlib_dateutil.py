# See Makefile for how to run this
import pyperf

runner = pyperf.Runner()

runner.timeit(
    "parse + convert + add",
    "datetime.fromisoformat('2020-04-05 22:04:00-04:00')"
    ".astimezone(ZoneInfo('Europe/Amsterdam'))"
    " + timedelta(days=30)",
    "from datetime import datetime, timedelta; from zoneinfo import ZoneInfo",
)

runner.timeit(
    "new date",
    "date(2020, 2, 29)",
    "from datetime import date",
)

runner.timeit(
    "date add",
    "d + relativedelta(years=-4, months=59, weeks=-7, days=3)",
    setup="import datetime; from dateutil.relativedelta import relativedelta;"
    "d = datetime.date(1987, 3, 31)",
)

runner.timeit(
    "date diff",
    "relativedelta(d1, d2)",
    setup="from datetime import date; from dateutil.relativedelta import relativedelta;"
    "d1 = date(2020, 2, 29); d2 = date(2025, 2, 28)",
)

runner.timeit(
    "parse date",
    "f('2020-02-29')",
    setup="from datetime import date; f = date.fromisoformat",
)

runner.timeit(
    "change tz",
    "dt.astimezone(ZoneInfo('America/New_York'))",
    setup="from datetime import datetime; from zoneinfo import ZoneInfo; "
    "dt = datetime(2020, 3, 20, 12, 30, 45, tzinfo=ZoneInfo('Europe/Amsterdam'))",
)
