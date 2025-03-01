use std::fmt;
use std::io::{self, Read, Seek, SeekFrom};

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
    trans_utc: Vec<i64>,
    trans_idx: Vec<u8>,
}

#[allow(dead_code)]
pub(crate) fn parse(mut s: impl Read + Seek) -> ParseResult<TZif> {
    let header = parse_header(&mut s)?;
    debug_assert_eq!(header.version, 2);
    parse_content(header, &mut s)
}

// Check if the magic bytes are present
fn parse_magic(mut s: impl Read) -> ParseResult<()> {
    let mut buffer = [0u8; 4];
    s.read_exact(&mut buffer)?;
    if &buffer != b"TZif" {
        Err(ParsingIssue::InvalidMagicValue)?;
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
        _ => Err(ParsingIssue::InvalidVersion)?,
    })
}

fn parse_header(mut s: impl Read + Seek) -> ParseResult<Header> {
    parse_magic(&mut s)?;
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

fn parse_trans_utc(header: Header, mut s: impl Read + Seek) -> ParseResult<Vec<i64>> {
    debug_assert_eq!(header.version, 2);
    debug_assert!(header.timecnt > 0);
    // OPTIMIZE: how about using smallvec?
    let mut result = Vec::with_capacity(header.timecnt as usize);
    let mut buffer = [0u8; std::mem::size_of::<i64>()];
    for _ in 0..header.timecnt {
        s.read_exact(&mut buffer)?;
        result.push(i64::from_be_bytes(buffer));
    }
    Ok(result)
}

fn parse_trans_idx(header: Header, mut s: impl Read + Seek) -> ParseResult<Vec<u8>> {
    debug_assert_eq!(header.version, 2);
    debug_assert!(header.timecnt > 0);
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
    Ok(TZif {
        header,
        trans_utc: parse_trans_utc(header, &mut s)?,
        trans_idx: parse_trans_idx(header, &mut s)?,
    })
}

#[derive(Debug, Clone, PartialEq, Eq, Copy)]
pub enum ParsingIssue {
    InvalidMagicValue,
    InvalidVersion,
}

impl std::error::Error for ParsingIssue {}

impl fmt::Display for ParsingIssue {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ParsingIssue::InvalidVersion => write!(f, "Invalid header"),
            ParsingIssue::InvalidMagicValue => write!(f, "Invalid magic value"),
        }
    }
}

#[derive(Debug)]
pub enum ParseError {
    Io(io::Error),
    Parse(ParsingIssue),
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
    pub(crate) fn parsing_failure(&self) -> Option<ParsingIssue> {
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

impl From<ParsingIssue> for ParseError {
    fn from(err: ParsingIssue) -> Self {
        ParseError::Parse(err)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    const TZFILE: &[u8] = include_bytes!("../tests/tzif/Amsterdam.tzif");

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
            ParsingIssue::InvalidMagicValue
        );
    }

    #[test]
    fn test_example() {
        let tzif = parse(&mut Cursor::new(TZFILE)).unwrap();
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
            tzif.trans_utc,
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
            tzif.trans_idx,
            &[
                1, 2, 3, 6, 3, 4, 5, 4, 5, 9, 7, 8, 7, 8, 7, 8, 7, 8, 7, 8, 7, 8, 7, 8, 7, 8, 7, 8,
                7, 8, 7, 8, 7, 8, 7, 8, 7, 8, 7, 8, 7, 8, 7, 8, 7, 8, 7, 8, 7, 8, 7, 8, 7, 4, 5, 4,
                5, 4, 5, 4, 5, 4, 5, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10,
                11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11,
                10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10,
                11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11,
                10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10,
                11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11,
                10, 11
            ]
        )
    }
}
