use crate::{common::scalar::DeltaField, py::*, pymodule::State};

pub(crate) use crate::domain::itemized_date_delta::ItemizedDateDelta;

impl ItemizedDateDelta {
    pub(crate) fn extract(obj: PyObj, state: &State) -> PyResult<Option<Self>> {
        if obj.type_().as_py_obj() != state.itemized_date_delta_type.get()? {
            return Ok(None);
        }
        let tup = obj.getattr(c"_to_tuple")?.call0()?.to_tuple()?;
        debug_assert!(tup.len() == 4);
        let mut iter = tup.iter();
        Ok(Some(Self {
            years: DeltaField::from_py_opt(iter.next().unwrap())?,
            months: DeltaField::from_py_opt(iter.next().unwrap())?,
            weeks: DeltaField::from_py_opt(iter.next().unwrap())?,
            days: DeltaField::from_py_opt(iter.next().unwrap())?,
        }))
    }

    pub(crate) fn to_obj(self, state: &State) -> PyReturn {
        state.unpickle_itemized_date_delta.get()?.call_args([
            *self.years.to_py()?,
            *self.months.to_py()?,
            *self.weeks.to_py()?,
            *self.days.to_py()?,
        ])
    }
}
