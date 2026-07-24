// FUTURE:
// - find a better way to access function other than making them public
// - find a better way to organize these benchmarks
use criterion::{Criterion, criterion_group, criterion_main};

use _whenever::classes::date::Date;
use _whenever::classes::plain_datetime::PlainDateTime;
use _whenever::domain::scalar::UnixDays;
use _whenever::domain::scalar::{Month, Year};
use _whenever::tz::posix::TzStr;
use _whenever::tz::tzif::TimeZone;
use std::hint::black_box;

pub fn date_from_unix_days(c: &mut Criterion) {
    c.bench_function("unix day to date", |b| {
        let d = UnixDays::new_unchecked(30179);
        b.iter(|| black_box(d).date())
    });
}

pub fn parse_plain_datetime(c: &mut Criterion) {
    c.bench_function("Parse plain datetime", |b| {
        b.iter(|| {
            PlainDateTime::parse(black_box(b"2023-03-02 02:09:09")).unwrap();
        })
    });
}

pub fn parse_posix_tz(c: &mut Criterion) {
    c.bench_function("Parse POSIX TZ", |b| {
        b.iter(|| TzStr::parse(black_box(b"PST8PDT,M3.2.0,M11.1.0")).unwrap())
    });
}

pub fn offset_for_local_time(c: &mut Criterion) {
    const TZ_AMS: &[u8] = include_bytes!("../../tests/tzif/Amsterdam.tzif");
    let tzif = TimeZone::parse_tzif(TZ_AMS, None).unwrap();

    c.bench_function("offset for local", |b| {
        let t = PlainDateTime::parse(b"2024-07-02 23:00:00")
            .unwrap()
            .local_seconds();
        b.iter(|| tzif.mapping_for_local(black_box(t)))
    });
}

pub fn tomorrow(c: &mut Criterion) {
    c.bench_function("tomorrow for date", |b| {
        let date = black_box(Date::new(Year::new(2023).unwrap(), Month::March, 2).unwrap());
        b.iter(|| {
            date.tomorrow().unwrap();
        })
    });
}

criterion_group!(
    benches,
    date_from_unix_days,
    parse_plain_datetime,
    parse_posix_tz,
    offset_for_local_time,
    tomorrow,
);
criterion_main!(benches);
