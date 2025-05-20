//! Functionality for declaring the `whenever` module in Python and its
//! associated methods.
mod def;
mod patch;
mod tzconf;
mod utils;

pub(crate) use def::{MODULE_DEF, State};
