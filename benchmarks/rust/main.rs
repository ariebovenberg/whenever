#![feature(test)]

extern crate test;

use _whenever::date::ord_to_ymd;
use _whenever::naive_datetime;
use test::{black_box, Bencher};

#[bench]
fn date_ord_to_ymd(bench: &mut Bencher) {
    let ord = black_box(730179);
    bench.iter(|| {
        let (year, month, day) = ord_to_ymd(ord);
        black_box((year, month, day));
    })
}

#[bench]
fn parse_naive_datetime(bench: &mut Bencher) {
    let s = black_box("2023-03-02 02:09:09");
    bench.iter(|| {
        let (date, time) = black_box(naive_datetime::parse(s.as_bytes()).unwrap());
        black_box((date, time));
    })
}
