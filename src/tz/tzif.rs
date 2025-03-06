use crate::tz::posix;
use crate::{EpochSeconds, Offset};
use std::fmt;
use std::io::{self, BufRead, BufReader, Read, Seek, SeekFrom};

#[derive(Debug, Clone, PartialEq, Eq, Copy)]
pub(crate) struct Header {
    version: u8,
    isutcnt: i32,
    isstdcnt: i32,
    leapcnt: i32,
    timecnt: i32,
    typecnt: i32,
    charcnt: i32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct TZif {
    header: Header,
    transitions: Vec<EpochSeconds>,
    offsets: Vec<Offset>,
    end: posix::TZ,
}

#[allow(dead_code)]
pub(crate) fn parse(mut s: impl Read + Seek) -> ParseResult<TZif> {
    let header = parse_header(&mut s)?;
    debug_assert_eq!(header.version, 2);
    parse_content(header, &mut s)
}

fn check_magic_bytes(mut s: impl Read) -> ParseResult<()> {
    let mut buffer = [0u8; 4];
    s.read_exact(&mut buffer)?;
    if &buffer != b"TZif" {
        Err(ErrorCause::MagicValue)?;
    }
    Ok(())
}

fn parse_version(mut s: impl Read + Seek) -> ParseResult<u8> {
    let mut buffer = [0u8; 1];
    s.read_exact(&mut buffer)?;
    s.seek(SeekFrom::Current(15))?;
    Ok(match buffer[0] {
        0 => 1,
        n if n.is_ascii_digit() => n - b'0',
        _ => Err(ErrorCause::Version)?,
    })
}

fn parse_header(mut s: impl Read + Seek) -> ParseResult<Header> {
    check_magic_bytes(&mut s)?;
    let version = parse_version(&mut s)?;
    let mut buffer = [0u8; 24];
    s.read_exact(&mut buffer)?;
    Ok(Header {
        version,
        isutcnt: i32::from_be_bytes(buffer[0..4].try_into().unwrap()),
        isstdcnt: i32::from_be_bytes(buffer[4..8].try_into().unwrap()),
        leapcnt: i32::from_be_bytes(buffer[8..12].try_into().unwrap()),
        timecnt: i32::from_be_bytes(buffer[12..16].try_into().unwrap()),
        typecnt: i32::from_be_bytes(buffer[16..20].try_into().unwrap()),
        charcnt: i32::from_be_bytes(buffer[20..24].try_into().unwrap()),
    })
}

fn parse_transitions(header: Header, mut s: impl Read + Seek) -> ParseResult<Vec<EpochSeconds>> {
    debug_assert_eq!(header.version, 2);
    let mut result = Vec::with_capacity(header.timecnt as usize);
    let mut buffer = [0u8; std::mem::size_of::<EpochSeconds>()];
    for _ in 0..header.timecnt {
        s.read_exact(&mut buffer)?;
        result.push(EpochSeconds::from_be_bytes(buffer));
    }
    Ok(result)
}

fn parse_offset_indices(header: Header, mut s: impl Read + Seek) -> ParseResult<Vec<u8>> {
    debug_assert_eq!(header.version, 2);
    // OPTIMIZE: how about using smallvec?
    let mut result = Vec::with_capacity(header.timecnt as usize);
    let mut buffer = [0u8; std::mem::size_of::<u8>()];
    for _ in 0..header.timecnt {
        s.read_exact(&mut buffer)?;
        result.push(u8::from_be_bytes(buffer));
    }
    Ok(result)
}

fn parse_content(first_header: Header, mut s: impl Read + Seek) -> ParseResult<TZif> {
    s.seek(SeekFrom::Current(
        (first_header.timecnt * 5
            + first_header.typecnt * 6
            + first_header.charcnt
            + first_header.leapcnt * 8
            + first_header.isstdcnt
            + first_header.isutcnt) as i64,
    ))?;
    // This "second" header is not the same as the first one
    let header = parse_header(&mut s)?;
    let transitions = parse_transitions(header, &mut s)?;
    let offset_indices = parse_offset_indices(header, &mut s)?;
    debug_assert!(header.typecnt > 0 && header.typecnt < 1_000);
    let offset_values = parse_offsets(header.typecnt as usize, header.charcnt, &mut s)?;
    // Skip unused metadata
    debug_assert_eq!(header.version, 2);
    s.seek(SeekFrom::Current(
        (header.isutcnt + header.isstdcnt + header.leapcnt * 12
         // the extra newline
         + 1)
        .into(),
    ))?;
    let end = parse_posix_tz(&mut s)?;
    Ok(TZif {
        header,
        transitions,
        offsets: load_offsets(&offset_values, &offset_indices)?,
        end,
    })
}

fn load_offsets(offsets: &[Offset], indices: &[u8]) -> ParseResult<Vec<Offset>> {
    let mut trans = Vec::with_capacity(indices.len());
    for &idx in indices {
        if let Some(&offset) = offsets.get(idx as usize) {
            trans.push(offset);
        } else {
            Err(ErrorCause::Body)?;
        }
    }
    Ok(trans)
}

fn parse_posix_tz(s: impl Read) -> ParseResult<posix::TZ> {
    // Most POSIX TZ strings are less than 32 bytes
    let mut buf = BufReader::with_capacity(32, s);
    let mut tz_str = Vec::with_capacity(32);
    buf.read_until(b'\n', &mut tz_str)?;

    // Remove the newline character if present
    if tz_str.last() == Some(&b'\n') {
        tz_str.pop();
    }
    Ok(posix::parse(&tz_str).ok_or(ErrorCause::TzString)?)
}

fn parse_offsets(typecnt: usize, charcnt: i32, mut s: impl Read + Seek) -> ParseResult<Vec<i32>> {
    let mut utcoff = Vec::with_capacity(typecnt);
    let mut buffer = [0u8; 6];
    for _ in 0..typecnt {
        s.read_exact(&mut buffer)?;
        utcoff.push(i32::from_be_bytes(buffer[0..4].try_into().unwrap()));
        // We skip parsing the other fields (isdst, abbrind) for now
    }
    // Skip character section
    s.seek(SeekFrom::Current(charcnt.into()))?;
    Ok(utcoff)
}

#[derive(Debug, Clone, PartialEq, Eq, Copy)]
pub enum ErrorCause {
    MagicValue,
    Version,
    Body,
    TzString,
}

impl std::error::Error for ErrorCause {}

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

#[derive(Debug)]
pub enum ParseError {
    Io(io::Error),
    Parse(ErrorCause),
}

impl ParseError {
    #[allow(dead_code)]
    pub(crate) fn io_error_kind(&self) -> Option<io::ErrorKind> {
        match self {
            ParseError::Io(err) => Some(err.kind()),
            _ => None,
        }
    }

    #[allow(dead_code)]
    pub(crate) fn parsing_failure(&self) -> Option<ErrorCause> {
        match self {
            ParseError::Parse(err) => Some(*err),
            _ => None,
        }
    }
}

type ParseResult<T> = Result<T, ParseError>;

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ParseError::Io(err) => write!(f, "IO error: {}", err),
            ParseError::Parse(err) => write!(f, "Parse error: {}", err),
        }
    }
}

impl std::error::Error for ParseError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            ParseError::Io(err) => Some(err),
            ParseError::Parse(err) => Some(err),
        }
    }
}

impl From<io::Error> for ParseError {
    fn from(err: io::Error) -> Self {
        ParseError::Io(err)
    }
}

impl From<ErrorCause> for ParseError {
    fn from(err: ErrorCause) -> Self {
        ParseError::Parse(err)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    const TZ_AMS: &[u8] = include_bytes!("../../tests/tzif/Amsterdam.tzif");
    const TZ_UTC: &[u8] = include_bytes!("../../tests/tzif/UTC.tzif");

    #[test]
    fn test_no_magic_header() {
        // empty
        assert!(
            parse(&mut Cursor::new(b"")).unwrap_err().io_error_kind()
                == Some(io::ErrorKind::UnexpectedEof)
        );
        // too small
        assert_eq!(
            parse(&mut Cursor::new(b"TZi")).unwrap_err().io_error_kind(),
            Some(io::ErrorKind::UnexpectedEof)
        );
        // wrong magic value
        assert_eq!(
            parse(&mut Cursor::new(&b"this-is-not-tzif-file"))
                .unwrap_err()
                .parsing_failure()
                .unwrap(),
            ErrorCause::MagicValue
        );
    }

    #[test]
    fn test_utc() {
        let tzif = parse(&mut Cursor::new(TZ_UTC)).unwrap();
        assert_eq!(
            tzif.header,
            Header {
                version: 2,
                isutcnt: 0,
                isstdcnt: 0,
                leapcnt: 0,
                timecnt: 0,
                typecnt: 1,
                charcnt: 4
            }
        );
        assert_eq!(tzif.transitions, &[]);
        assert_eq!(tzif.end, posix::parse(b"UTC0").unwrap());
    }

    #[test]
    fn test_ams() {
        let tzif = parse(&mut Cursor::new(TZ_AMS)).unwrap();
        assert_eq!(
            tzif.header,
            Header {
                version: 2,
                isutcnt: 12,
                isstdcnt: 12,
                leapcnt: 0,
                timecnt: 185,
                typecnt: 12,
                charcnt: 26
            }
        );
        assert_eq!(
            tzif.transitions,
            &[
                -2840141850,
                -2450995200,
                -1740355200,
                -1693702800,
                -1680483600,
                -1663455600,
                -1650150000,
                -1632006000,
                -1618700400,
                -1613826000,
                -1604278800,
                -1585530000,
                -1574038800,
                -1552266000,
                -1539997200,
                -1520557200,
                -1507510800,
                -1490576400,
                -1473642000,
                -1459126800,
                -1444006800,
                -1427677200,
                -1411952400,
                -1396227600,
                -1379293200,
                -1364778000,
                -1348448400,
                -1333328400,
                -1316394000,
                -1301263200,
                -1284328800,
                -1269813600,
                -1253484000,
                -1238364000,
                -1221429600,
                -1206914400,
                -1191189600,
                -1175464800,
                -1160344800,
                -1143410400,
                -1127685600,
                -1111960800,
                -1096840800,
                -1080511200,
                -1063576800,
                -1049061600,
                -1033336800,
                -1017612000,
                -1002492000,
                -986162400,
                -969228000,
                -950479200,
                -942012000,
                -934668000,
                -857257200,
                -844556400,
                -828226800,
                -812502000,
                -798073200,
                -781052400,
                -766623600,
                -745455600,
                -733273200,
                228877200,
                243997200,
                260326800,
                276051600,
                291776400,
                307501200,
                323830800,
                338950800,
                354675600,
                370400400,
                386125200,
                401850000,
                417574800,
                433299600,
                449024400,
                465354000,
                481078800,
                496803600,
                512528400,
                528253200,
                543978000,
                559702800,
                575427600,
                591152400,
                606877200,
                622602000,
                638326800,
                654656400,
                670381200,
                686106000,
                701830800,
                717555600,
                733280400,
                749005200,
                764730000,
                780454800,
                796179600,
                811904400,
                828234000,
                846378000,
                859683600,
                877827600,
                891133200,
                909277200,
                922582800,
                941331600,
                954032400,
                972781200,
                985482000,
                1004230800,
                1017536400,
                1035680400,
                1048986000,
                1067130000,
                1080435600,
                1099184400,
                1111885200,
                1130634000,
                1143334800,
                1162083600,
                1174784400,
                1193533200,
                1206838800,
                1224982800,
                1238288400,
                1256432400,
                1269738000,
                1288486800,
                1301187600,
                1319936400,
                1332637200,
                1351386000,
                1364691600,
                1382835600,
                1396141200,
                1414285200,
                1427590800,
                1445734800,
                1459040400,
                1477789200,
                1490490000,
                1509238800,
                1521939600,
                1540688400,
                1553994000,
                1572138000,
                1585443600,
                1603587600,
                1616893200,
                1635642000,
                1648342800,
                1667091600,
                1679792400,
                1698541200,
                1711846800,
                1729990800,
                1743296400,
                1761440400,
                1774746000,
                1792890000,
                1806195600,
                1824944400,
                1837645200,
                1856394000,
                1869094800,
                1887843600,
                1901149200,
                1919293200,
                1932598800,
                1950742800,
                1964048400,
                1982797200,
                1995498000,
                2014246800,
                2026947600,
                2045696400,
                2058397200,
                2077146000,
                2090451600,
                2108595600,
                2121901200,
                2140045200
            ]
        );
        assert_eq!(
            tzif.offsets,
            &[
                1050, 0, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 0, 3600, 0, 3600, 0, 3600, 0,
                3600, 0, 3600, 0, 3600, 0, 3600, 0, 3600, 0, 3600, 0, 3600, 0, 3600, 0, 3600, 0,
                3600, 0, 3600, 0, 3600, 0, 3600, 0, 3600, 0, 3600, 0, 3600, 0, 3600, 0, 3600, 0,
                3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200,
                3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200,
                3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200,
                3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200,
                3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200,
                3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200,
                3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200,
                3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200,
                3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200, 3600, 7200,
                3600, 7200, 3600, 7200, 3600, 7200, 3600
            ]
        );
        assert_eq!(
            tzif.end,
            posix::parse(b"CET-1CEST,M3.5.0,M10.5.0/3").unwrap()
        );
    }
}
