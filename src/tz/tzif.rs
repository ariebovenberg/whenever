use crate::common::parse::Scan;
use crate::tz::posix;
use crate::{Ambiguity, EpochSeconds, Offset};
use std::fmt;

#[derive(Debug, PartialEq, Eq)]
pub struct TZif {
    pub key: String, // The IANA tz ID (e.g. "Europe/Amsterdam")
    // The following two fields are used to map UTC time to local time and vice versa.
    // Read each vector (X, Y) as "from time X onwards (expressed in epoch seconds) the offset is Y".
    // For UTC -> local, the transition is unambiguous and simple.
    offsets_by_utc: Vec<(EpochSeconds, Offset)>,
    // For local -> UTC, the transition is may be ambiguous and therefore requires extra information.
    offsets_by_local: Vec<(EpochSeconds, (Offset, OffsetChange))>,
    end: posix::TZ,
}

/// The size of a UTC offset change. "gaps" are positive, "folds" are negative.
type OffsetChange = i32;

impl TZif {
    /// Get the UTC offset at the given moment in time
    pub(crate) fn offset_for_instant(&self, t: EpochSeconds) -> Offset {
        // OPTIMIZE: this could be made a bit smarter. E.g. starting
        // with a reasonable guess.
        bisect_index(&self.offsets_by_utc, t)
            .map(|i| self.offsets_by_utc[i].1)
            // TODO: spread checked types!
            .unwrap_or_else(|| self.end.offset_for_instant(t.try_into().unwrap()).get())
    }

    pub fn ambiguity_for_local(&self, t: EpochSeconds) -> Ambiguity {
        bisect_index(&self.offsets_by_local, t)
            .map(|i| {
                let (transition, (offset, change)) = self.offsets_by_local[i];
                let ambiguity = (t < transition + change.abs() as i64) as i32 * change;
                use std::cmp::Ordering::*;
                match ambiguity.cmp(&0) {
                    Equal => Ambiguity::Unambiguous(offset),
                    Less => Ambiguity::Fold(offset - ambiguity, offset),
                    Greater => Ambiguity::Gap(offset, offset - ambiguity),
                }
            })
            // TODO: spread checked types!
            .unwrap_or_else(|| self.end.ambiguity_for_local(t.try_into().unwrap()))
    }
}

// Bisect the array of (time, value) pairs to find the INDEX at the given time.
// Return None if after the last entry.
#[inline]
pub fn bisect_index<T>(arr: &[(EpochSeconds, T)], x: EpochSeconds) -> Option<usize>
where
    T: Copy,
{
    let mut size = arr.len();
    let mut left = 0;
    let mut right = size;
    while left < right {
        let mid = left + size / 2;

        if arr[mid].0 <= x {
            left = mid + 1;
        } else {
            right = mid;
        }
        size = right - left;
    }
    (left != arr.len()).then_some(left.saturating_sub(1))
}

pub fn parse(s: &[u8], key: &str) -> ParseResult<TZif> {
    let mut scan = Scan::new(s);
    let header = parse_header(&mut scan)?;
    debug_assert!(header.version >= 2);
    parse_content(header, &mut scan, key)
}

#[derive(Debug, Clone, PartialEq, Eq, Copy)]
struct Header {
    version: u8,
    isutcnt: i32,
    isstdcnt: i32,
    leapcnt: i32,
    timecnt: i32,
    typecnt: i32,
    charcnt: i32,
}

fn check_magic_bytes(s: &mut Scan) -> bool {
    s.take(4) == Some(b"TZif")
}

fn parse_version(s: &mut Scan) -> Option<u8> {
    let version = match &s.take(1)? {
        [0] => 1,
        [n] if n.is_ascii_digit() => n - b'0',
        _ => None?,
    };
    s.take(15)?;
    Some(version)
}

fn parse_header(s: &mut Scan) -> ParseResult<Header> {
    if !check_magic_bytes(s) {
        return Err(ErrorCause::MagicValue);
    }
    let version = parse_version(s).ok_or(ErrorCause::Version)?;
    let content = s.take(24).ok_or(ErrorCause::Body)?;
    Ok(Header {
        version,
        isutcnt: i32::from_be_bytes(content[0..4].try_into().unwrap()),
        isstdcnt: i32::from_be_bytes(content[4..8].try_into().unwrap()),
        leapcnt: i32::from_be_bytes(content[8..12].try_into().unwrap()),
        timecnt: i32::from_be_bytes(content[12..16].try_into().unwrap()),
        typecnt: i32::from_be_bytes(content[16..20].try_into().unwrap()),
        charcnt: i32::from_be_bytes(content[20..24].try_into().unwrap()),
    })
}

fn parse_transition_times(header: Header, s: &mut Scan) -> ParseResult<Vec<EpochSeconds>> {
    let mut result = Vec::with_capacity(header.timecnt as usize);
    const I64_SIZE: usize = std::mem::size_of::<i64>();
    let values = s
        .take(header.timecnt as usize * I64_SIZE)
        .ok_or(ErrorCause::Body)?;
    // NOTE: we assume the values are sorted
    for i in 0..header.timecnt {
        result.push(EpochSeconds::from_be_bytes(
            values[i as usize * I64_SIZE..(i + 1) as usize * I64_SIZE]
                .try_into()
                .unwrap(),
        ));
    }
    Ok(result)
}

fn parse_offset_indices(header: Header, s: &mut Scan) -> ParseResult<Vec<u8>> {
    let mut result = Vec::with_capacity(header.timecnt as usize);
    let values = s.take(header.timecnt as usize).ok_or(ErrorCause::Body)?;
    for i in 0..header.timecnt {
        result.push(u8::from_be_bytes(
            values[i as usize..(i + 1) as usize].try_into().unwrap(),
        ));
    }
    Ok(result)
}

fn parse_content(first_header: Header, s: &mut Scan, key: &str) -> ParseResult<TZif> {
    s.take(
        (first_header.timecnt * 5
            + first_header.typecnt * 6
            + first_header.charcnt
            + first_header.leapcnt * 8
            + first_header.isstdcnt
            + first_header.isutcnt) as _,
    )
    .ok_or(ErrorCause::Body)?;
    // This "second" header is not the same as the first one
    let header = parse_header(s)?;
    let transition_times = parse_transition_times(header, s)?;
    let offset_indices = parse_offset_indices(header, s)?;
    debug_assert!(header.typecnt > 0 && header.typecnt < 1_000);
    let offsets = parse_offsets(header.typecnt as usize, header.charcnt, s)?;
    // Skip unused metadata
    s.take(
        (header.isutcnt + header.isstdcnt + header.leapcnt * 12
         // the extra newline
         + 1) as usize,
    )
    .ok_or(ErrorCause::Body)?;
    let offsets_by_utc = load_transitions(&transition_times, &offsets, &offset_indices)?;
    Ok(TZif {
        key: key.to_string(),
        offsets_by_local: local_transitions(&offsets_by_utc),
        offsets_by_utc,
        end: parse_posix_tz(s)?,
    })
}

fn local_transitions(
    transitions: &[(EpochSeconds, Offset)],
) -> Vec<(EpochSeconds, (Offset, OffsetChange))> {
    let mut result = Vec::with_capacity(transitions.len());
    if transitions.is_empty() {
        return result;
    }
    // The first entry is special, as there's no transition
    let (epoch0, offset0) = transitions[0];
    result.push((epoch0 + offset0 as i64, (offset0, 0)));

    let mut offset_prev = offset0;
    for &(epoch, offset) in transitions[1..].iter() {
        // NOTE: we don't check for "impossible" gaps or folds
        result.push((
            epoch + offset_prev.min(offset) as i64,
            (offset, offset - offset_prev),
        ));
        offset_prev = offset;
    }
    result
}

fn load_transitions(
    transition_times: &[EpochSeconds],
    offsets: &[Offset],
    indices: &[u8],
) -> ParseResult<Vec<(EpochSeconds, Offset)>> {
    let mut trans = Vec::with_capacity(indices.len());
    for (&idx, &epoch) in indices.iter().zip(transition_times) {
        if let Some(&offset) = offsets.get(usize::from(idx)) {
            trans.push((epoch, offset));
        } else {
            // The supplied index is out of bounds
            Err(ErrorCause::Body)?;
        }
    }
    Ok(trans)
}

fn parse_posix_tz(s: &mut Scan) -> ParseResult<posix::TZ> {
    let tz_str = match s.take_until(|b| b == b'\n') {
        Some(x) => x,
        None => s.rest(),
    };
    posix::parse(tz_str).ok_or(ErrorCause::TzString)
}

fn parse_offsets(typecnt: usize, charcnt: i32, s: &mut Scan) -> ParseResult<Vec<Offset>> {
    let mut utcoff = Vec::with_capacity(typecnt);
    let values = s.take(typecnt * 6).ok_or(ErrorCause::Body)?;
    for i in 0..typecnt {
        // Note: we only parse the first field, skipping the others (for now)
        utcoff.push(i32::from_be_bytes(
            values[i * 6..(i + 1) * 6 - 2].try_into().unwrap(),
        ));
    }
    // Skip character section
    s.take(charcnt as _).ok_or(ErrorCause::Body)?;
    Ok(utcoff)
}

#[derive(Debug, Clone, PartialEq, Eq, Copy)]
pub enum ErrorCause {
    MagicValue,
    Version,
    Body,
    TzString,
}

impl fmt::Display for ErrorCause {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ErrorCause::Version => write!(f, "Invalid header"),
            ErrorCause::MagicValue => write!(f, "Invalid magic value"),
            ErrorCause::Body => write!(f, "Invalid or currupted data"),
            ErrorCause::TzString => write!(f, "Invalid POSIX TZ string"),
        }
    }
}

type ParseResult<T> = Result<T, ErrorCause>;

#[cfg(test)]
mod tests {
    use super::*;

    const TZ_AMS: &[u8] = include_bytes!("../../tests/tzif/Amsterdam.tzif");
    const TZ_UTC: &[u8] = include_bytes!("../../tests/tzif/UTC.tzif");
    const TZ_FIXED: &[u8] = include_bytes!("../../tests/tzif/GMT-13.tzif");

    #[test]
    fn test_no_magic_header() {
        // empty
        assert_eq!(parse(b"", "Foo").unwrap_err(), ErrorCause::MagicValue);
        // too small
        assert_eq!(parse(b"TZi", "Foo").unwrap_err(), ErrorCause::MagicValue);
        // wrong magic value
        assert_eq!(
            parse(b"this-is-not-tzif-file", "Foo").unwrap_err(),
            ErrorCause::MagicValue
        );
    }

    #[test]
    fn test_binary_search() {
        let arr = &[(4, 10), (9, 20), (12, 30), (16, 40), (24, 50)];
        // middle of the array
        assert_eq!(bisect_index(arr, 10), Some(1));
        assert_eq!(bisect_index(arr, 12), Some(2));
        assert_eq!(bisect_index(arr, 15), Some(2));
        assert_eq!(bisect_index(arr, 16), Some(3));
        // end of the array
        assert_eq!(bisect_index(arr, 24), None);
        assert_eq!(bisect_index(arr, 30), None);
        // start of the array
        assert_eq!(bisect_index(arr, -99), Some(0));
        assert_eq!(bisect_index(arr, 3), Some(0));
        assert_eq!(bisect_index(arr, 4), Some(0));
        assert_eq!(bisect_index(arr, 5), Some(0));

        // emtpy case
        assert_eq!(bisect_index::<i64>(&[], 25), None);
    }

    #[test]
    fn test_utc() {
        let tzif = parse(TZ_UTC, "UTC").unwrap();
        assert_eq!(tzif.offsets_by_utc, &[]);
        assert_eq!(tzif.end, posix::parse(b"UTC0").unwrap());

        assert_eq!(tzif.offset_for_instant(2216250001), 0);
        assert_eq!(
            tzif.ambiguity_for_local(2216250000),
            Ambiguity::Unambiguous(0)
        )
    }

    #[test]
    fn test_fixed() {
        let tzif = parse(TZ_FIXED, "GMT-13").unwrap();
        assert_eq!(tzif.offsets_by_utc, &[]);
        assert_eq!(tzif.end, posix::parse(b"<+13>-13").unwrap());

        assert_eq!(tzif.offset_for_instant(2216250001), 13 * 3_600);
        assert_eq!(
            tzif.ambiguity_for_local(2216250000),
            Ambiguity::Unambiguous(13 * 3_600)
        )
    }

    #[test]
    fn test_ams() {
        let tzif = parse(TZ_AMS, "Europe/Amsterdam").unwrap();
        assert_eq!(
            tzif.end,
            posix::parse(b"CET-1CEST,M3.5.0,M10.5.0/3").unwrap()
        );

        let utc_cases = &[
            // before the entire range
            (-2850000000, 1050),
            // at start of range
            (-2840141851, 1050),
            (-2840141850, 1050),
            (-2840141849, 1050),
            // The first transition
            (-2450995201, 1050),
            (-2450995200, 0),
            (-2450995199, 0),
            // Arbitrary transition (fold)
            (1698541199, 7200),
            (1698541200, 3600),
            (1698541201, 3600),
            // Arbitrary transition (gap)
            (1743296399, 3600),
            (1743296400, 7200),
            (1743296401, 7200),
            // Transitions after the last explicit one need to use the POSIX TZ string
            (2216249999, 3600),
            (2216250000, 7200),
            (2216250001, 7200),
            (2645053199, 7200),
            (2645053200, 3600),
            (2645053201, 3600),
        ];

        for &(t, expected) in utc_cases {
            assert_eq!(tzif.offset_for_instant(t), expected, "t={}", t);
        }

        let local_cases = &[
            // before the entire range
            (-2850000000 + 1050, Ambiguity::Unambiguous(1050)),
            // At the start of the range
            (-2840141851 + 1050, Ambiguity::Unambiguous(1050)),
            (-2840141850 + 1050, Ambiguity::Unambiguous(1050)),
            (-2840141849 + 1050, Ambiguity::Unambiguous(1050)),
            // --- The first transition (a fold) ---
            // well before the fold (no ambiguity)
            (-2750999299 + 1050, Ambiguity::Unambiguous(1050)),
            // Just before times become ambiguous
            (-2450995201, Ambiguity::Unambiguous(1050)),
            // At the moment times becomes ambiguous
            (-2450995200, Ambiguity::Fold(1050, 0)),
            // Short before the clock change, short enough for ambiguity!
            (-2450995902 + 1050, Ambiguity::Fold(1050, 0)),
            // A second before the clock change (ambiguity!)
            (-2450995201 + 1050, Ambiguity::Fold(1050, 0)),
            // At the exact clock change (no ambiguity)
            (-2450995200 + 1050, Ambiguity::Unambiguous(0)),
            // Directly after the clock change (no ambiguity)
            (-2450995199 + 1050, Ambiguity::Unambiguous(0)),
            // --- A "gap" transition ---
            // Well before the transition
            (-1698792800, Ambiguity::Unambiguous(3600)),
            // Just before the clock change
            (-1693702801 + 3600, Ambiguity::Unambiguous(3600)),
            // At the exact clock change (ambiguity!)
            (-1693702800 + 3600, Ambiguity::Gap(7200, 3600)),
            // Right after the clock change (ambiguity)
            (-1693702793 + 3600, Ambiguity::Gap(7200, 3600)),
            // Slightly before the gap ends (ambiguity)
            (-1693702801 + 7200, Ambiguity::Gap(7200, 3600)),
            // The gap ends (no ambiguity)
            (-1693702800 + 7200, Ambiguity::Unambiguous(7200)),
            // A sample of other times
            (700387500, Ambiguity::Unambiguous(3600)),
            (701834700, Ambiguity::Gap(7200, 3600)),
            (715302300, Ambiguity::Unambiguous(7200)),
            // ---- Transitions after the last explicit one need to use the POSIX TZ string
            // before gap
            (2216249999 + 3600, Ambiguity::Unambiguous(3600)),
            // gap starts
            (2216250000 + 3600, Ambiguity::Gap(7200, 3600)),
            // gap ends
            (2216250000 + 7200, Ambiguity::Unambiguous(7200)),
            // somewhere in summer
            (2216290000, Ambiguity::Unambiguous(7200)),
            // Fold starts
            (2645056800, Ambiguity::Fold(7200, 3600)),
            // In the fold
            (2645056940, Ambiguity::Fold(7200, 3600)),
            // end of the fold
            (2645056800 + 3600, Ambiguity::Unambiguous(3600)),
        ];

        for &(t, expected) in local_cases {
            assert_eq!(tzif.ambiguity_for_local(t), expected, "t={}", t);
        }
    }

    /// Smoke test to see we don't crash parsing any TZif files in the tzdata database.
    /// It doesn't actually check whether the parsing is correct,
    /// but will give a good indication if the parser is robust.
    /// Code loosely based on github.com/BurntSushi/jiff/blob/master/src/tz/tzif.rs
    #[test]
    fn smoke_test() {
        const TZDIR: &str = "/usr/share/zoneinfo";
        for entry in walkdir::WalkDir::new(TZDIR)
            .into_iter()
            .filter_map(Result::ok)
        {
            let path = entry.path();

            // Skip unreadable files
            let Ok(bytes) = std::fs::read(path) else {
                continue;
            };

            // Skip non-TZif files
            if !bytes.starts_with(b"TZif") {
                continue;
            }

            if let Err(err) = parse(&bytes, "foo-key") {
                panic!("failed to parse TZif file {:?}: {err}", path);
            }
        }
    }
}
