# See Makefile for how to run this
import pyperf

runner = pyperf.Runner()


runner.timeit(
    "parse + convert + add",
    "arrow.get('2020-04-05 22:04:00-04:00')"
    ".to('Europe/Amsterdam')"
    ".shift(days=30)",
    "import arrow",
)



runner.timeit(
    "new date",
    "get(2020, 2, 29)",
    "from arrow import get",
)

runner.timeit(
    "date add",
    "d.shift(years=-4, months=59, weeks=-7, days=3)",
    setup="from arrow import get; d = get(1987, 3, 31)",
)

runner.timeit(
    "parse date",
    "get('2020-02-29')",
    setup="from arrow import get",
)

runner.timeit(
    "change tz",
    "dt.to('America/New_York')",
    setup="import arrow; dt = arrow.get(2020, 3, 20, 12, 30, 45, 0, tz='Europe/Amsterdam'); ",
)
