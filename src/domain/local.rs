use super::{
    offset_datetime::OffsetDateTime,
    plain_datetime::PlainDateTime,
    scalar::{EpochSecs, Offset, SubSecNanos},
};

#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
#[repr(transparent)]
pub struct LocalSeconds(EpochSecs);

impl LocalSeconds {
    pub(crate) fn clamp(secs: i64) -> Self {
        Self(EpochSecs::clamp(secs))
    }

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

    #[cfg(test)]
    pub(crate) fn date(self) -> super::date::Date {
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
    /// Keep the offset in a fold where it identifies an occurrence; the
    /// disambiguation decides otherwise, and in a gap.
    PreserveOffset(Offset, Disambiguation),
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
                    ResolvePolicy::PreserveOffset(preferred, _)
                        if preferred == before || preferred == after =>
                    {
                        preferred
                    }
                    ResolvePolicy::Disambiguate(d) | ResolvePolicy::PreserveOffset(_, d) => match d
                    {
                        Disambiguation::Earlier | Disambiguation::Compatible => before,
                        Disambiguation::Later => after,
                        Disambiguation::Reject => return Err(ResolveError::Fold),
                    },
                };
                local.assume_offset(offset)
            }
            Self::Gap { before, after, .. } => {
                let shift = after.sub(before);
                let (ResolvePolicy::Disambiguate(d) | ResolvePolicy::PreserveOffset(_, d)) = policy;
                let (shift, offset) = match d {
                    Disambiguation::Earlier => (-shift, before),
                    Disambiguation::Reject => return Err(ResolveError::Gap),
                    Disambiguation::Compatible | Disambiguation::Later => (shift, after),
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
        // A preferred offset that identifies an occurrence wins over every policy
        for disambiguation in [
            Disambiguation::Compatible,
            Disambiguation::Earlier,
            Disambiguation::Later,
            Disambiguation::Reject,
        ] {
            for preferred in [before, after] {
                assert_eq!(
                    mapping.resolve(
                        local,
                        ResolvePolicy::PreserveOffset(preferred, disambiguation)
                    ),
                    Ok(local.assume_offset(preferred).unwrap())
                );
            }
        }
        // Otherwise the policy decides
        assert_eq!(
            mapping.resolve(
                local,
                ResolvePolicy::PreserveOffset(Offset::ZERO, Disambiguation::Compatible)
            ),
            Ok(local.assume_offset(before).unwrap())
        );
        assert_eq!(
            mapping.resolve(
                local,
                ResolvePolicy::PreserveOffset(Offset::ZERO, Disambiguation::Later)
            ),
            Ok(local.assume_offset(after).unwrap())
        );
        assert_eq!(
            mapping.resolve(
                local,
                ResolvePolicy::PreserveOffset(Offset::ZERO, Disambiguation::Reject)
            ),
            Err(ResolveError::Fold)
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
            ResolvePolicy::PreserveOffset(before, Disambiguation::Compatible),
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
        assert_eq!(
            mapping.resolve(
                local,
                ResolvePolicy::PreserveOffset(before, Disambiguation::Reject)
            ),
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
