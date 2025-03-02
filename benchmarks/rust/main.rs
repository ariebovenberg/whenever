// FUTURE:
// - find a better way to access function other than making them public
// - find a better way to organize these benchmarks
use criterion::{black_box, criterion_group, criterion_main, Criterion};

use _whenever::date::Date;
use _whenever::local_datetime;
use _whenever::tz::posix;

pub fn date_from_ord(c: &mut Criterion) {
    c.bench_function("Date from ord", |b| {
        b.iter(|| Date::from_ord_unchecked(black_box(730179)))
    });
}

pub fn parse_local_datetime(c: &mut Criterion) {
    c.bench_function("Parse local datetime", |b| {
        b.iter(|| {
            let s = black_box("2023-03-02 02:09:09");
            let (date, time) = local_datetime::parse_date_and_time(s.as_bytes()).unwrap();
            black_box((date, time));
        })
    });
}

pub fn parse_posix_tz(c: &mut Criterion) {
    c.bench_function("Parse POSIX TZ", |b| {
        b.iter(|| {
            let tz = posix::parse(black_box(b"PST8PDT,M3.2.0,M11.1.0")).unwrap();
            black_box(tz);
        })
    });
}

criterion_group!(benches, date_from_ord, parse_local_datetime, parse_posix_tz);
criterion_main!(benches);
