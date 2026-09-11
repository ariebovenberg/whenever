.. meta::
   :description: Reference for whenever's enums, unions, and string literal types, including Weekday, RoundModeStr, DisambiguationStr, and OffsetMismatchStr.

Other types
===========

This section contains API documentation for choice and other types, 
i.e. enums, unions, and literals.

.. currentmodule:: whenever

.. autoclass:: Weekday
   :members:

``Weekday`` is a plain :class:`~enum.Enum`: members neither compare with
integers nor order, and ``.value`` is the ISO number, Monday 1 through
Sunday 7. The module constants are the members:

.. data:: MONDAY
.. data:: TUESDAY
.. data:: WEDNESDAY
.. data:: THURSDAY
.. data:: FRIDAY
.. data:: SATURDAY
.. data:: SUNDAY

   The members of :class:`Weekday`, importable from the module namespace.


.. autotype:: RoundModeStr

   See :ref:`rounding-modes` for more information.

.. autotype:: DisambiguationStr

   See :ref:`ambiguity` for more information.

.. autotype:: DisambiguateStr

   Deprecated alias of :class:`DisambiguationStr`.


.. autotype:: DeltaUnitStr
.. autotype:: DeltaTotalUnitStr
.. autotype:: DateDeltaUnitStr
.. autotype:: ExactDeltaUnitStr
.. autotype:: OffsetMismatchStr
.. autotype:: TimestampUnitStr
