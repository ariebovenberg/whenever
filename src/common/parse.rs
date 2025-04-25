use crate::SubSecNanos;
use std::{
    fmt::Debug,
    ops::{Index, RangeInclusive, RangeTo},
};

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

    pub(crate) fn get(&self, n: usize) -> Option<u8> {
        self.0.get(n).copied()
    }

    pub(crate) fn skip(&mut self, n: usize) -> &mut Self {
        self.0 = &self.0[n..];
        self
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
    /// Some(true) -> the expected byte was consumed
    /// Some(false) -> the expected byte was not consumed
    /// None -> the scanner is empty
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
        match self.0 {
            [a @ b'0'..=b'5', b @ b'0'..=b'9', ..] => {
                self.0 = &self.0[2..];
                Some((a - b'0') * 10 + b - b'0')
            }
            _ => None,
        }
    }

    pub(crate) fn digits00_23(&mut self) -> Option<u8> {
        match self.0 {
            [a @ b'0'..=b'2', b @ b'0'..=b'9', ..] => {
                self.0 = &self.0[2..];
                Some((a - b'0') * 10 + b - b'0').filter(|&n| n < 24)
            }
            _ => None,
        }
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

    /// Parse '.' and up to 9 digits after it. If empty, return 0.
    pub(crate) fn subsec(&mut self) -> Option<SubSecNanos> {
        Some(match self.advance_on(b'.') {
            Some(true) => {
                // If there's a decimal point, the first digit is required
                let mut total = self.digit()? as i32 * 100_000_000;
                for (byte, pwr) in self.0.iter().zip((0..8).rev()) {
                    if byte.is_ascii_digit() {
                        total += (byte - b'0') as i32 * 10_i32.pow(pwr);
                    } else {
                        self.0 = &self.0[(7 - pwr) as usize..];
                        // Safe: 9 digits are always in range of SubSecNanos
                        return Some(SubSecNanos::new_unchecked(total));
                    }
                }
                // At this point, we've parsed up to 9 characters
                // OR we've reached the end of the scanner.
                // Remember we've already skipped the first digit,
                // so we skip ahead 8 more (at most).
                self.0 = &self.0[self.0.len().min(8)..];
                SubSecNanos::new_unchecked(total)
            }
            // No decimal point, so subsec is 0
            _ => SubSecNanos::MIN,
        })
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

    pub(crate) fn len(&self) -> usize {
        self.0.len()
    }

    pub(crate) fn parse_all<F, R>(&mut self, mut f: F) -> Option<R>
    where
        F: FnMut(&mut Self) -> Option<R>,
    {
        let result = f(self)?;
        self.is_done().then_some(result)
    }
}

impl Index<RangeInclusive<usize>> for Scan<'_> {
    type Output = [u8];

    fn index(&self, index: RangeInclusive<usize>) -> &[u8] {
        let start = *index.start();
        let end = *index.end();
        &self.0[start..=end]
    }
}

impl Index<RangeTo<usize>> for Scan<'_> {
    type Output = [u8];

    fn index(&self, index: RangeTo<usize>) -> &[u8] {
        &self.0[..index.end]
    }
}

impl Index<usize> for Scan<'_> {
    type Output = u8;

    fn index(&self, index: usize) -> &u8 {
        &self.0[index]
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_peek_next_take() {
        let mut scan = Scan::new(b"1234");
        assert_eq!(scan.peek(), Some(b'1'));
        assert_eq!(scan.next(), Some(b'1'));
        assert_eq!(scan.peek(), Some(b'2'));
        assert_eq!(scan.take(2).unwrap(), b"23");
        assert_eq!(scan.peek(), Some(b'4'));
        assert_eq!(scan.take(2), None);
        assert_eq!(scan.peek(), Some(b'4'));
        assert!(!scan.is_done());
        assert_eq!(scan.take(1).unwrap(), b"4");
        assert!(scan.is_done());
        assert_eq!(scan.peek(), None);
        assert_eq!(scan.take(1), None);
    }

    #[test]
    fn test_scan_advance_on() {
        let mut scan = Scan::new(b"1234");
        assert_eq!(scan.advance_on(b'1'), Some(true));
        assert_eq!(scan.rest(), b"234");
        assert_eq!(scan.advance_on(b'2'), Some(true));
        assert_eq!(scan.advance_on(b'2'), Some(false));
        assert_eq!(scan.rest(), b"34");
        scan.take(2);
        assert_eq!(scan.advance_on(b'4'), None);
    }

    #[test]
    fn test_scan_expect() {
        let mut scan = Scan::new(b"1234");
        assert_eq!(scan.expect(b'1'), Some(()));
        assert_eq!(scan.expect(b'2'), Some(()));
        assert_eq!(scan.expect(b'2'), None);
        scan.take(2);
        assert_eq!(scan.expect(b'9'), None);
    }

    #[test]
    fn test_scan_digit() {
        let mut scan = Scan::new(b"12a4");
        assert_eq!(scan.digit(), Some(1));
        assert_eq!(scan.digit(), Some(2));
        assert_eq!(scan.digit(), None);
        assert_eq!(scan.digit(), None);
        scan.next();
        assert_eq!(scan.digit(), Some(4));
        assert_eq!(scan.digit(), None);
    }

    #[test]
    fn test_scan_digit_ranged() {
        let mut scan = Scan::new(b"12a4");
        assert_eq!(scan.digit_ranged(b'1'..=b'3'), Some(1));
        assert_eq!(scan.digit_ranged(b'1'..=b'2'), Some(2));
        assert_eq!(scan.digit_ranged(b'1'..=b'9'), None); // no digit at all
        scan.expect(b'a');
        assert_eq!(scan.digit_ranged(b'1'..=b'3'), None);
        assert_eq!(scan.digit_ranged(b'1'..=b'4'), Some(4));
        assert_eq!(scan.digit_ranged(b'1'..=b'9'), None);
    }

    #[test]
    fn test_scan_digits00_59() {
        let mut scan = Scan::new(b"12a455z492");
        assert_eq!(scan.digits00_59(), Some(12));
        assert_eq!(scan.digits00_59(), None);
        scan.expect(b'a');
        assert_eq!(scan.digits00_59(), Some(45));
        assert_eq!(scan.digits00_59(), None);
        assert_eq!(scan.rest(), b"5z492");
        scan.take(2);
        assert_eq!(scan.digits00_59(), Some(49));
        assert_eq!(scan.digits00_59(), None);
        assert_eq!(scan.digits00_59(), None);
    }

    #[test]
    fn test_scan_up_to_3_digits() {
        let mut scan = Scan::new(b"1234_k00z92");
        assert_eq!(scan.up_to_3_digits(), Some(123));
        assert_eq!(scan.up_to_3_digits(), Some(4));
        assert_eq!(scan.up_to_3_digits(), None);
        scan.expect(b'_');
        assert_eq!(scan.up_to_3_digits(), None);
        scan.expect(b'k');
        assert_eq!(scan.up_to_3_digits(), Some(0));
        scan.expect(b'z');
        assert_eq!(scan.up_to_3_digits(), Some(92));
        assert_eq!(scan.up_to_3_digits(), None);
    }

    #[test]
    fn test_scan_up_to_2_digits() {
        let mut scan = Scan::new(b"1234_k0z2");
        assert_eq!(scan.up_to_2_digits(), Some(12));
        assert_eq!(scan.up_to_2_digits(), Some(34));
        assert_eq!(scan.up_to_2_digits(), None);
        scan.expect(b'_');
        assert_eq!(scan.up_to_2_digits(), None);
        scan.expect(b'k');
        assert_eq!(scan.up_to_2_digits(), Some(0));
        scan.expect(b'z');
        assert_eq!(scan.up_to_2_digits(), Some(2));
        assert_eq!(scan.up_to_2_digits(), None);
    }

    #[test]
    fn test_scan_transform() {
        let mut scan = Scan::new(b"1234");
        assert_eq!(scan.transform(|c| (c == b'2').then_some(8)), None);
        assert_eq!(scan.peek(), Some(b'1'));
        assert_eq!(
            scan.transform(|c| (c == b'1').then_some("foo")),
            Some("foo")
        );
        assert_eq!(scan.peek(), Some(b'2'));
        scan.take(3);
        assert_eq!(scan.transform(|c| (c == b'4').then_some(9)), None);
    }

    #[test]
    fn test_scan_take_until() {
        let mut scan = Scan::new(b"1234_k00z92");
        assert_eq!(scan.take_until(|c| c == b'_').unwrap(), b"1234");
        assert_eq!(scan.take_until(|c| c == b'Z'), None);
        scan.expect(b'_');
        assert_eq!(scan.take_until(|c| c == b'2').unwrap(), b"k00z9");
        assert_eq!(scan.take_until(|c| c == b'2').unwrap(), b"");
    }

    #[test]
    fn test_scan_take_until_inclusive() {
        let mut scan = Scan::new(b"1234_k00z92");
        assert_eq!(scan.take_until_inclusive(|c| c == b'_').unwrap(), b"1234_");
        scan.expect(b'k');
        assert_eq!(scan.take_until_inclusive(|c| c == b'Z'), None);
        scan.expect(b'0');
        assert_eq!(scan.take_until_inclusive(|c| c == b'2').unwrap(), b"0z92");
        assert_eq!(scan.take_until_inclusive(|c| c == b'2'), None);
    }
}
