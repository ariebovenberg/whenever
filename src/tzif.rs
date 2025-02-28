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
}

#[allow(dead_code)]
pub(crate) fn parse(mut s: impl Read + Seek) -> ParseResult<TZif> {
    let header = parse_header(&mut s)?;
    debug_assert_eq!(header.version, 2);
    parse_data(header, &mut s)?;
    Ok(TZif { header })
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

fn parse_data(header: Header, mut s: impl Read + Seek) -> ParseResult<()> {
    s.seek(SeekFrom::Current(
        (header.timecnt * 5
            + header.typecnt * 6
            + header.charcnt
            + header.leapcnt * 8
            + header.isstdcnt
            + header.isutcnt) as i64,
    ))?;
    let header = parse_header(&mut s)?;
    println!("{:?}", header);
    Ok(())
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
        assert_eq!(
            parse(&mut Cursor::new(TZFILE)).unwrap(),
            TZif {
                header: Header {
                    version: 2,
                    isutcnt: 11,
                    isstdcnt: 11,
                    leapcnt: 0,
                    timecnt: 184,
                    typecnt: 11,
                    charcnt: 22
                }
            }
        );
    }
}
