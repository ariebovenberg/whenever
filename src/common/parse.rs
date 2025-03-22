use std::{fmt::Debug, ops::RangeInclusive};

#[derive(PartialEq, Eq)]
pub(crate) struct Scan<'a>(&'a [u8]);

impl<'a> Scan<'a> {
    /// Create a new scanner from a byte slice.
    pub(crate) fn new(inner: &'a [u8]) -> Self {
        Self(inner)
    }

    /// Return the next byte in the scanner without consuming it.
    pub(crate) fn peek(&self) -> Option<u8> {
        self.0.first().copied()
    }

    /// Consume the next byte in the scanner.
    pub(crate) fn next(&mut self) -> Option<u8> {
        let a = self.peek()?;
        self.0 = &self.0[1..];
        Some(a)
    }

    /// Return the rest of the scanner as a byte slice.
    pub(crate) fn rest(&self) -> &[u8] {
        self.0
    }

    /// Take the next `n` bytes from the scanner without checking if they exist.
    pub(crate) fn take_unchecked(&mut self, n: usize) -> &'a [u8] {
        let (a, b) = self.0.split_at(n);
        self.0 = b;
        a
    }

    /// Take the next `n` bytes from the scanner IF they exist.
    pub(crate) fn take(&mut self, n: usize) -> Option<&'a [u8]> {
        (self.0.len() >= n).then(|| self.take_unchecked(n))
    }

    /// Advance the scanner only if the next byte is the expected one.
    /// Returns true if the byte was consumed.
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
    /// Returns None if the byte was not consumed.
    pub(crate) fn expect(&mut self, c: u8) -> Option<()> {
        self.advance_on(c).filter(|&b| b).map(|_| ())
    }

    /// Consume a single ASCII digit from the scanner.
    /// Returns None if the next byte is absent or not a digit.
    pub(crate) fn digit(&mut self) -> Option<u8> {
        self.transform(|c| c.is_ascii_digit().then(|| c - b'0'))
    }

    /// Consume a single ASCII digit from the scanner within a range.
    /// Returns None if the next byte is absent or not a digit within the range.
    pub(crate) fn digit_ranged(&mut self, range: RangeInclusive<u8>) -> Option<u8> {
        self.transform(|c| range.contains(&c).then(|| c - b'0'))
    }

    pub(crate) fn digits00_59(&mut self) -> Option<u8> {
        // TODO: can get stuck halfway through
        self.digit_ranged(b'0'..=b'5')
            .and_then(|tens| self.digit().map(|ones| tens * 10 + ones))
    }

    /// Parse 1-3 digits until encountering a non-digit or end of input.
    /// Only returns None if the first character is not a digit, or if the scanner is empty.
    pub(crate) fn up_to_3_digits(&mut self) -> Option<u16> {
        // The first digit is required
        let mut total = self.digit()? as u16;
        for _ in 0..2 {
            match self.digit() {
                Some(digit) => total = total * 10 + digit as u16,
                None => break,
            }
        }
        Some(total)
    }

    /// Parse 1 or 2 digits until encountering a non-digit or end of input.
    /// Only returns None if the first character is not a digit, or if the scanner is empty.
    pub(crate) fn up_to_2_digits(&mut self) -> Option<u8> {
        // The first digit is required
        let mut total = self.digit()?;
        if let Some(d) = self.digit() {
            total = total * 10 + d
        }
        Some(total)
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

    /// Take bytes from the scanner until a predicate is true.
    /// Returns None if the predicate is never true.
    pub(crate) fn take_until_inclusive<F>(&mut self, mut f: F) -> Option<&[u8]>
    where
        F: FnMut(u8) -> bool,
    {
        self.rest()
            .iter()
            .position(|&b| f(b))
            .map(|i| self.take_unchecked(i + 1))
    }

    /// Check if the scanner is done (empty).
    pub(crate) fn is_done(&self) -> bool {
        self.peek().is_none()
    }
}

impl Debug for Scan<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Scan")
            .field("s", unsafe {
                &std::str::from_utf8_unchecked(self.0).to_string()
            })
            .finish()
    }
}
