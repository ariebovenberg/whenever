use super::{
    date::Date,
    offset_datetime::OffsetDateTime,
    plain_datetime::PlainDateTime,
    scalar::{EpochSecs, Offset, SubSecNanos},
};

#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
#[repr(transparent)]
pub struct LocalSeconds(EpochSecs);

impl LocalSeconds {
    #[inline]
    pub(crate) fn from_instant_saturating(epoch: EpochSecs, offset: Offset) -> Self {
        Self(epoch.saturating_shift_by_offset(offset))
    }

    #[inline]
    pub(crate) const fn assume_utc(self) -> EpochSecs {
        self.0
    }

    #[inline]
    pub(crate) fn to_epoch(self, offset: Offset) -> Option<EpochSecs> {
        self.0.shift_by_offset(-offset)
    }

    #[inline]
    pub(crate) fn to_epoch_saturating(self, offset: Offset) -> EpochSecs {
        self.0.saturating_shift_by_offset(-offset)
    }

    pub(crate) const fn get(self) -> i64 {
        self.0.get()
    }

    pub(crate) fn saturating_add_i32(self, seconds: i32) -> Self {
        Self(self.0.saturating_add_i32(seconds))
    }

    pub(crate) fn datetime(self, subsec: SubSecNanos) -> PlainDateTime {
        self.0.datetime(subsec)
    }

    pub(crate) fn date(self) -> Date {
        self.0.date()
    }
}

impl PlainDateTime {
    #[inline]
    pub fn local_seconds(self) -> LocalSeconds {
        LocalSeconds(self.date.epoch_at(self.time))
    }
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum LocalMapping {
    Unique {
        offset: Offset,
    },
    Gap {
        transition: LocalSeconds,
        before: Offset,
        after: Offset,
    },
    Fold {
        transition: LocalSeconds,
        before: Offset,
        after: Offset,
    },
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) enum Disambiguation {
    Compatible,
    Earlier,
    Later,
    Reject,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) enum ResolvePolicy {
    Disambiguate(Disambiguation),
    PreserveOffset(Offset),
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub(crate) enum ResolveError {
    Gap,
    Fold,
    OutOfRange,
}

impl LocalMapping {
    #[inline]
    pub(crate) fn resolve(
        self,
        local: PlainDateTime,
        policy: ResolvePolicy,
    ) -> Result<OffsetDateTime, ResolveError> {
        let resolved = match self {
            Self::Unique { offset } => local.assume_offset(offset),
            Self::Fold { before, after, .. } => {
                let offset = match policy {
                    ResolvePolicy::Disambiguate(Disambiguation::Earlier)
                    | ResolvePolicy::Disambiguate(Disambiguation::Compatible) => before,
                    ResolvePolicy::Disambiguate(Disambiguation::Later) => after,
                    ResolvePolicy::Disambiguate(Disambiguation::Reject) => {
                        return Err(ResolveError::Fold);
                    }
                    ResolvePolicy::PreserveOffset(preferred) => {
                        if preferred == after {
                            after
                        } else {
                            before
                        }
                    }
                };
                local.assume_offset(offset)
            }
            Self::Gap { before, after, .. } => {
                let shift = after.sub(before);
                let (shift, offset) = match policy {
                    ResolvePolicy::Disambiguate(Disambiguation::Earlier) => (-shift, before),
                    ResolvePolicy::Disambiguate(Disambiguation::Reject) => {
                        return Err(ResolveError::Gap);
                    }
                    ResolvePolicy::Disambiguate(
                        Disambiguation::Compatible | Disambiguation::Later,
                    )
                    | ResolvePolicy::PreserveOffset(_) => (shift, after),
                };
                local
                    .shift_by_offset(shift)
                    .and_then(|dt| dt.assume_offset(offset))
            }
        };
        resolved.ok_or(ResolveError::OutOfRange)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn transition() -> LocalSeconds {
        LocalSeconds(EpochSecs::new_unchecked(0))
    }

    fn local() -> PlainDateTime {
        EpochSecs::new_unchecked(0).datetime(SubSecNanos::MIN)
    }

    #[test]
    fn resolve_fold() {
        let before = Offset::new_unchecked(7_200);
        let after = Offset::new_unchecked(3_600);
        let mapping = LocalMapping::Fold {
            transition: transition(),
            before,
            after,
        };
        let local = local();

        for disambiguation in [Disambiguation::Compatible, Disambiguation::Earlier] {
            assert_eq!(
                mapping.resolve(local, ResolvePolicy::Disambiguate(disambiguation)),
                Ok(local.assume_offset(before).unwrap())
            );
        }
        assert_eq!(
            mapping.resolve(local, ResolvePolicy::Disambiguate(Disambiguation::Later)),
            Ok(local.assume_offset(after).unwrap())
        );
        assert_eq!(
            mapping.resolve(local, ResolvePolicy::Disambiguate(Disambiguation::Reject)),
            Err(ResolveError::Fold)
        );
        assert_eq!(
            mapping.resolve(local, ResolvePolicy::PreserveOffset(after)),
            Ok(local.assume_offset(after).unwrap())
        );
        assert_eq!(
            mapping.resolve(local, ResolvePolicy::PreserveOffset(Offset::ZERO)),
            Ok(local.assume_offset(before).unwrap())
        );
    }

    #[test]
    fn resolve_gap() {
        let before = Offset::new_unchecked(3_600);
        let after = Offset::new_unchecked(7_200);
        let mapping = LocalMapping::Gap {
            transition: transition(),
            before,
            after,
        };
        let local = local();
        let shift = after.sub(before);

        for policy in [
            ResolvePolicy::Disambiguate(Disambiguation::Compatible),
            ResolvePolicy::Disambiguate(Disambiguation::Later),
            ResolvePolicy::PreserveOffset(before),
        ] {
            assert_eq!(
                mapping.resolve(local, policy),
                Ok(local
                    .shift_by_offset(shift)
                    .unwrap()
                    .assume_offset(after)
                    .unwrap())
            );
        }
        assert_eq!(
            mapping.resolve(local, ResolvePolicy::Disambiguate(Disambiguation::Earlier)),
            Ok(local
                .shift_by_offset(-shift)
                .unwrap()
                .assume_offset(before)
                .unwrap())
        );
        assert_eq!(
            mapping.resolve(local, ResolvePolicy::Disambiguate(Disambiguation::Reject)),
            Err(ResolveError::Gap)
        );
    }

    #[test]
    fn resolve_range_edges() {
        let gap = LocalMapping::Gap {
            transition: transition(),
            before: Offset::ZERO,
            after: Offset::new_unchecked(3_600),
        };
        assert_eq!(
            gap.resolve(
                PlainDateTime::MAX,
                ResolvePolicy::Disambiguate(Disambiguation::Compatible)
            ),
            Err(ResolveError::OutOfRange)
        );
        assert_eq!(
            gap.resolve(
                PlainDateTime::MIN,
                ResolvePolicy::Disambiguate(Disambiguation::Earlier)
            ),
            Err(ResolveError::OutOfRange)
        );
    }
}
