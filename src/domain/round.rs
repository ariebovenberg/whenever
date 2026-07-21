#[derive(Debug, Copy, Clone, Eq, PartialEq)]
pub(crate) enum Mode {
    Floor,
    Ceil,
    Trunc,
    Expand,
    HalfFloor,
    HalfCeil,
    HalfEven,
    HalfTrunc,
    HalfExpand,
}

#[derive(Debug, Copy, Clone, Eq, PartialEq)]
pub(crate) enum AbsMode {
    Trunc,
    Expand,
    HalfTrunc,
    HalfExpand,
    HalfEven,
}

impl Mode {
    pub(crate) fn to_abs_euclid(self, is_negative: bool) -> AbsMode {
        match (self, is_negative) {
            (Self::Floor, _) | (Self::Trunc, false) | (Self::Expand, true) => AbsMode::Trunc,
            (Self::Ceil, _) | (Self::Expand, false) | (Self::Trunc, true) => AbsMode::Expand,
            (Self::HalfFloor, _) | (Self::HalfTrunc, false) | (Self::HalfExpand, true) => {
                AbsMode::HalfTrunc
            }
            (Self::HalfCeil, _) | (Self::HalfExpand, false) | (Self::HalfTrunc, true) => {
                AbsMode::HalfExpand
            }
            (Self::HalfEven, _) => AbsMode::HalfEven,
        }
    }

    pub(crate) fn to_abs_trunc(self, neg: bool) -> AbsMode {
        match (self, !neg) {
            (Self::Trunc, _) | (Self::Floor, true) | (Self::Ceil, false) => AbsMode::Trunc,
            (Self::Expand, _) | (Self::Ceil, true) | (Self::Floor, false) => AbsMode::Expand,
            (Self::HalfTrunc, _) | (Self::HalfFloor, true) | (Self::HalfCeil, false) => {
                AbsMode::HalfTrunc
            }
            (Self::HalfExpand, _) | (Self::HalfCeil, true) | (Self::HalfFloor, false) => {
                AbsMode::HalfExpand
            }
            (Self::HalfEven, _) => AbsMode::HalfEven,
        }
    }
}
