# See Makefile for how to run this
import pyperf

runner = pyperf.Runner()

runner.timeit(
    "various operations",
    "d = parse('2020-04-05T22:04:00-04:00')"
    ".in_tz('UTC');"
    "d.diff();"
    "d.add(hours=4, minutes=30)"
    ".in_tz('Europe/Amsterdam')"
    ".to_iso8601_string()",
    setup="from pendulum import parse, DateTime",
)

# runner.timeit(
#     "new date",
#     "Date(2020, 2, 29)",
#     "from pendulum import Date",
# )


# runner.timeit(
#     "date add",
#     "d.add(years=-4, months=59, weeks=-7, days=3)",
#     setup="from pendulum import Date; d = Date(1987, 3, 31)",
# )

# runner.timeit(
#     "date diff",
#     "d1 - d2",
#     setup="from pendulum import Date; d1 = Date(2020, 2, 29); d2 = Date(2025, 2, 28)",
# )

# runner.timeit(
#     "parse date",
#     "f('2020-02-29')",
#     setup="from pendulum import Date; f = Date.fromisoformat",
# )

# runner.timeit(
#     "parse date delta",
#     "f('P5Y2M4D')",
#     setup="from pendulum import parse as f",
# )

# runner.timeit(
#     "change tz",
#     "dt.in_tz('America/New_York')",
#     setup="from pendulum import datetime; dt = datetime(2020, 3, 20, 12, 30, 45, tz='Europe/Amsterdam')",
# )
