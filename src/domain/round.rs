use std::cmp::Ordering;

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

impl AbsMode {
    /// Whether a magnitude steps away from zero, to the next multiple.
    ///
    /// Every rounding in the library is this decision plus the caller's own
    /// arithmetic. `half_cmp` compares the remainder past the multiple below
    /// with what is left to the next one: `r.cmp(&(span - r))`, which
    /// divides nothing, so an odd span is not truncated. They need not be in
    /// the unit that is rounded: months round by the time between two dates.
    /// `quotient_odd` is the parity of the multiple below, for a tie.
    pub(crate) fn rounds_up(
        self,
        has_remainder: bool,
        half_cmp: Ordering,
        quotient_odd: bool,
    ) -> bool {
        match self {
            Self::Trunc => false,
            Self::Expand => has_remainder,
            Self::HalfTrunc => half_cmp == Ordering::Greater,
            Self::HalfExpand => half_cmp != Ordering::Less,
            Self::HalfEven => {
                half_cmp == Ordering::Greater || (half_cmp == Ordering::Equal && quotient_odd)
            }
        }
    }
}

impl Mode {
    /// What the mode means for the magnitude of a value with the given
    /// sign. A point on the timeline is never negative.
    pub(crate) fn to_abs(self, neg: bool) -> AbsMode {
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
