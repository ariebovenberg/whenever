//! Helpers for writing formatted strings

// Static table for formatting 2-digit numbers. Avoids division/modulo operations.
pub(crate) static DIGITS: &[u8; 200] = b"00010203040506070809101112131415161718192021222324252627282930313233343536373839404142434445464748495051525354555657585960616263646566676869707172737475767778798081828384858687888990919293949596979899";

pub(crate) fn format_2_digits(n: u8) -> [u8; 2] {
    debug_assert!(n < 100);
    let i = n as usize * 2;
    [DIGITS[i], DIGITS[i + 1]]
}

pub(crate) fn format_4_digits(n: u16) -> [u8; 4] {
    debug_assert!(n < 10000);
    // use static digits table
    let first = format_2_digits((n / 100) as u8);
    let second = format_2_digits((n % 100) as u8);
    [first[0], first[1], second[0], second[1]]
}

/// Something you can write bytes into.
pub(crate) trait Sink {
    fn write_byte(&mut self, b: u8);
    fn write(&mut self, s: &[u8]);
}

/// Something with a fixed length that can write itself into a `Sink`.
/// Used for "fast" formatting of known-size chunks.
pub(crate) trait Chunk {
    fn len(&self) -> usize;
    fn write(&self, b: &mut impl Sink);
}

impl<T: AsRef<[u8]>> Chunk for &T {
    fn len(&self) -> usize {
        self.as_ref().len()
    }
    fn write(&self, b: &mut impl Sink) {
        b.write(self.as_ref());
    }
}

impl Chunk for u8 {
    fn len(&self) -> usize {
        1
    }

    fn write(&self, b: &mut impl Sink) {
        b.write_byte(*self);
    }
}

macro_rules! impl_chunk_for_tuples {
    ( $( $name:ident : $idx:tt ),+ ) => {
        impl<$( $name: Chunk ),+> Chunk for ( $( $name ),+ ) {
            fn len(&self) -> usize {
                0 $( + self.$idx.len() )+
            }

            fn write(&self, b: &mut impl Sink) {
                $( self.$idx.write(b); )+
            }
        }
    };
}

// Generate the impls
impl_chunk_for_tuples!(T0:0, T1:1);
impl_chunk_for_tuples!(T0:0, T1:1, T2:2);
impl_chunk_for_tuples!(T0:0, T1:1, T2:2, T3:3);
impl_chunk_for_tuples!(T0:0, T1:1, T2:2, T3:3, T4:4);
impl_chunk_for_tuples!(T0:0, T1:1, T2:2, T3:3, T4:4, T5:5);
impl_chunk_for_tuples!(T0:0, T1:1, T2:2, T3:3, T4:4, T5:5, T6:6);
impl_chunk_for_tuples!(T0:0, T1:1, T2:2, T3:3, T4:4, T5:5, T6:6, T7:7);
impl_chunk_for_tuples!(T0:0, T1:1, T2:2, T3:3, T4:4, T5:5, T6:6, T7:7, T8:8);
impl_chunk_for_tuples!(T0:0, T1:1, T2:2, T3:3, T4:4, T5:5, T6:6, T7:7, T8:8, T9:9);

pub(crate) struct ArrayWriter<const N: usize> {
    buf: [u8; N],
    pos: usize,
}

impl<const N: usize> ArrayWriter<N> {
    pub fn new() -> Self {
        Self {
            buf: [0; N],
            pos: 0,
        }
    }

    pub fn finish(&self) -> &str {
        debug_assert!(self.pos == N);
        debug_assert!(self.buf.iter().all(|&b| b.is_ascii()));
        unsafe { std::str::from_utf8_unchecked(&self.buf[..]) }
    }
}

impl<const N: usize> Sink for ArrayWriter<N> {
    fn write_byte(&mut self, b: u8) {
        debug_assert!(self.pos < N);
        self.buf[self.pos] = b;
        self.pos += 1;
    }

    fn write(&mut self, s: &[u8]) {
        debug_assert!(self.pos + s.len() <= N);
        self.buf[self.pos..self.pos + s.len()].copy_from_slice(s);
        self.pos += s.len();
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum Precision {
    Auto,
    Nanosecond,
    Microsecond,
    Millisecond,
    Second,
    Minute,
    Hour,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_2_digits() {
        for i in 0..100 {
            let s = format_2_digits(i);
            assert_eq!(
                s,
                <[u8; 2]>::try_from(format!("{:02}", i).as_bytes()).unwrap()
            );
        }
    }

    #[test]
    fn test_format_4_digits() {
        for i in 0..10000 {
            let s = format_4_digits(i);
            assert_eq!(
                s,
                <[u8; 4]>::try_from(format!("{:04}", i).as_bytes()).unwrap()
            );
        }
    }
}
