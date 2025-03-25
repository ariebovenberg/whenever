// FUTURE:
// - find a better way to access function other than making them public
// - find a better way to organize these benchmarks
use criterion::{black_box, criterion_group, criterion_main, Criterion};

use _whenever::common::math::{EpochSecs, UnixDays};
use _whenever::common::math::{Month, Year};
use _whenever::date::Date;
use _whenever::local_datetime;
use _whenever::tz::posix;
use _whenever::tz::tzif;

pub fn date_from_unix_days(c: &mut Criterion) {
    c.bench_function("unix day to date", |b| {
        let d = UnixDays::new_unchecked(30179);
        b.iter(|| black_box(d).date())
    });
}

pub fn parse_local_datetime(c: &mut Criterion) {
    c.bench_function("Parse local datetime", |b| {
        b.iter(|| {
            local_datetime::parse_date_and_time(black_box(b"2023-03-02 02:09:09")).unwrap();
        })
    });
}

pub fn parse_posix_tz(c: &mut Criterion) {
    c.bench_function("Parse POSIX TZ", |b| {
        b.iter(|| posix::parse(black_box(b"PST8PDT,M3.2.0,M11.1.0")).unwrap())
    });
}

pub fn offset_for_local_datetime(c: &mut Criterion) {
    const TZ_AMS: &[u8] = include_bytes!("../../tests/tzif/Amsterdam.tzif");
    let tzif = tzif::parse(TZ_AMS, "Europe/Amsterdam").unwrap();

    c.bench_function("offset for local", |b| {
        let t = EpochSecs::new(1719946800).unwrap();
        b.iter(|| tzif.ambiguity_for_local(black_box(t)))
    });
}

pub fn tomorrow(c: &mut Criterion) {
    c.bench_function("tomorrow for date", |b| {
        let date = black_box(Date::new(Year::new_unchecked(2023), Month::March, 2).unwrap());
        b.iter(|| {
            date.tomorrow().unwrap();
        })
    });
}

criterion_group!(
    benches,
    date_from_unix_days,
    parse_local_datetime,
    parse_posix_tz,
    offset_for_local_datetime,
    tomorrow,
);
criterion_main!(benches);
