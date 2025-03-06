use std::{fmt::Debug, ops::RangeInclusive};

#[derive(PartialEq, Eq)]
pub(crate) struct Scan<'a>(&'a [u8]);

impl<'a> Scan<'a> {
    /// Create a new scanner from a byte slice, checking that it is ASCII.
    pub(crate) fn new(inner: &'a [u8]) -> Option<Self> {
        inner.is_ascii().then_some(Self(inner))
    }
    pub(crate) fn peek(&self) -> Option<u8> {
        self.0.first().copied()
    }

    pub(crate) fn next(&mut self) -> Option<u8> {
        let a = self.peek()?;
        self.0 = &self.0[1..];
        Some(a)
    }

    fn rest(&self) -> &[u8] {
        self.0
    }

    pub(crate) fn take_unchecked(&mut self, n: usize) -> &'a [u8] {
        let (a, b) = self.0.split_at(n);
        self.0 = b;
        a
    }

    /// Advance the scanner only if the next byte is the expected one.
    pub(crate) fn advance_on(&mut self, x: u8) -> Option<bool> {
        self.peek().map(|b| {
            if b == x {
                self.take_unchecked(1);
                true
            } else {
                false
            }
        })
    }

    /// Advance the scanner if the next byte is the expected one.
    pub(crate) fn expect(&mut self, c: u8) -> Option<()> {
        self.advance_on(c).filter(|&b| b).map(|_| ())
    }

    pub(crate) fn digit(&mut self) -> Option<u8> {
        self.transform(|c| c.is_ascii_digit().then(|| c - b'0'))
    }

    pub(crate) fn digit_ranged(&mut self, range: RangeInclusive<u8>) -> Option<u8> {
        self.next().filter(|c| range.contains(c)).map(|c| c - b'0')
    }

    pub(crate) fn digits00_59(&mut self) -> Option<u8> {
        self.digit_ranged(b'0'..=b'5')
            .and_then(|tens| self.digit().map(|ones| tens * 10 + ones))
    }

    pub(crate) fn up_to_3_digits(&mut self) -> Option<u16> {
        let mut result = 0;
        for _ in 0..3 {
            match self.digit() {
                Some(digit) => result = result * 10 + digit as u16,
                None => return Some(result),
            }
        }
        Some(result)
    }

    pub(crate) fn up_to_2_digits(&mut self) -> Option<u8> {
        let mut result = 0;
        for _ in 0..2 {
            match self.digit() {
                Some(digit) => result = result * 10 + digit,
                None => return Some(result),
            }
        }
        Some(result)
    }

    /// Apply a function to the next byte in the scanner,
    /// returning the result if it is Some.
    /// Also returns None if the scanner is empty.
    pub(crate) fn transform<F, T>(&mut self, f: F) -> Option<T>
    where
        F: FnMut(u8) -> Option<T>,
    {
        match self.peek().and_then(f) {
            Some(result) => {
                self.take_unchecked(1);
                Some(result)
            }
            None => None,
        }
    }

    /// Take bytes from the scanner until a predicate is true.
    /// Returns None if the predicate is never true.
    pub(crate) fn take_until<F>(&mut self, mut f: F) -> Option<&[u8]>
    where
        F: FnMut(u8) -> bool,
    {
        self.rest()
            .iter()
            .position(|&b| f(b))
            .map(|i| self.take_unchecked(i))
    }

    /// Check if the scanner is done (empty).
    pub(crate) fn is_done(&self) -> bool {
        self.peek().is_none()
    }
}

impl<'a> Debug for Scan<'a> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Scan")
            .field("s", unsafe {
                &std::str::from_utf8_unchecked(self.0).to_string()
            })
            .finish()
    }
}
