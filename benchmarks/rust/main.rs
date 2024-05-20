#![feature(test)]

extern crate test;

use _whenever::date::Date;
use _whenever::naive_datetime;
use test::{black_box, Bencher};

#[bench]
fn date_from_ord(bench: &mut Bencher) {
    let ord = black_box(730179);
    bench.iter(|| {
        let date = Date::from_ord(ord);
        black_box(date);
    })
}

#[bench]
fn parse_naive_datetime(bench: &mut Bencher) {
    let s = black_box("2023-03-02 02:09:09");
    bench.iter(|| {
        let (date, time) = black_box(naive_datetime::parse_date_and_time(s.as_bytes()).unwrap());
        black_box((date, time));
    })
}
