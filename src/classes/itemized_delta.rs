use crate::{
    common::scalar::{DeltaField, DeltaFieldInner},
    py::*,
    pymodule::State,
};

pub(crate) use crate::domain::itemized_delta::ItemizedDelta;

impl<T: DeltaFieldInner> DeltaField<T> {
    /// Construct from a Python int or None in an itemized delta tuple.
    pub(crate) fn from_optional_py(obj: PyObj) -> PyResult<Self> {
        if obj.is_none() {
            Ok(Self::UNSET)
        } else {
            let value = obj
                .cast_allow_subclass::<PyInt>()
                .ok_or_type_err("expected int or None")?
                .to_i64()?;
            Ok(Self::new_unchecked(T::from_i64(value)))
        }
    }
}

impl<T: DeltaFieldInner> ToPy for DeltaField<T> {
    fn to_py(self) -> PyReturn {
        if self.is_set() {
            self.unwrap().to_i64().to_py()
        } else {
            Ok(none())
        }
    }
}

impl ItemizedDelta {
    pub(crate) fn extract(obj: PyObj, state: &State) -> PyResult<Option<Self>> {
        if obj.type_().as_py_obj() != state.itemized_delta_type.get()? {
            return Ok(None);
        }
        let tup = obj.getattr(c"_to_tuple")?.call0()?.to_tuple()?;
        debug_assert!(tup.len() == 8);
        let mut iter = tup.iter();
        Ok(Some(Self {
            years: DeltaField::from_optional_py(iter.next().unwrap())?,
            months: DeltaField::from_optional_py(iter.next().unwrap())?,
            weeks: DeltaField::from_optional_py(iter.next().unwrap())?,
            days: DeltaField::from_optional_py(iter.next().unwrap())?,
            hours: DeltaField::from_optional_py(iter.next().unwrap())?,
            minutes: DeltaField::from_optional_py(iter.next().unwrap())?,
            seconds: DeltaField::from_optional_py(iter.next().unwrap())?,
            nanos: DeltaField::from_optional_py(iter.next().unwrap())?,
        }))
    }

    pub(crate) fn to_obj(self, state: &State) -> PyReturn {
        state.unpickle_itemized_delta.get()?.call_args([
            *self.years.to_py()?,
            *self.months.to_py()?,
            *self.weeks.to_py()?,
            *self.days.to_py()?,
            *self.hours.to_py()?,
            *self.minutes.to_py()?,
            *self.seconds.to_py()?,
            *self.nanos.to_py()?,
        ])
    }
}
