.. meta::
   :description: Deprecated components kept for backwards compatibility: DateDelta, DateTimeDelta, the years()/months()/weeks()/days() helpers, and ImplicitlyIgnoringDST.

Deprecated components
=====================

.. autofunction:: whenever.years
.. autofunction:: whenever.months
.. autofunction:: whenever.weeks
.. autofunction:: whenever.days

.. autoexception:: whenever.ImplicitlyIgnoringDST

.. autoclass:: whenever.DateDelta
   :members:
   :special-members: __eq__, __neg__, __abs__, __add__, __sub__, __mul__, __bool__

.. autoclass:: whenever.DateTimeDelta
   :members:
   :special-members: __eq__, __neg__, __abs__, __add__, __sub__, __bool__, __mul__
