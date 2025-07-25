//! Helpers for writing formatted strings

pub(crate) fn write_2_digits(n: u8, buf: &mut [u8]) {
    buf[0] = n / 10 + b'0';
    buf[1] = n % 10 + b'0';
}

pub(crate) fn write_4_digits(n: u16, buf: &mut [u8]) {
    buf[0] = (n / 1000) as u8 + b'0';
    buf[1] = (n / 100 % 10) as u8 + b'0';
    buf[2] = (n / 10 % 10) as u8 + b'0';
    buf[3] = (n % 10) as u8 + b'0';
}

/// Useful for storing formatted ASCII strings with flexible length
/// (e.g. due to decimal places)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct AsciiArrayVec<const N: usize> {
    pub(crate) data: [u8; N],
    pub(crate) len: usize,
}

impl<const N: usize> std::ops::Deref for AsciiArrayVec<N> {
    type Target = [u8];

    fn deref(&self) -> &Self::Target {
        &self.data[..self.len]
    }
}

pub(crate) enum Precision {
    Hour,
    Minute,
    Second,
    Millisecond,
    Microsecond,
    Nanosecond,
    Auto,
}
