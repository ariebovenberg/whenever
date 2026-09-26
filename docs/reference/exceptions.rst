.. meta::
   :description: Reference for whenever's exceptions and warnings, including RepeatedTime, SkippedTime, InvalidOffsetError, TimeZoneNotFoundError, and the WheneverWarning hierarchy.

Exceptions and warnings
=======================

.. currentmodule:: whenever

A value outside its domain raises ``ValueError``, on both backends; the four
exceptions below refine it, so one ``except ValueError`` catches everything
parsing and conversion can raise. ``OverflowError`` escapes only for an
integer too large for the backend's machine integer. An argument of the wrong
type usually raises ``TypeError`` (sometimes ``AttributeError``); that is not
guaranteed, so rely on a type checker to catch it.

Warnings
--------

.. autoexception:: WheneverWarning
   :show-inheritance:

.. autoexception:: PotentialDstBugWarning
   :show-inheritance:

.. autoexception:: DaysAssumed24HoursWarning
   :show-inheritance:

.. autoexception:: StaleOffsetWarning
   :show-inheritance:

.. autoexception:: NaiveArithmeticWarning
   :show-inheritance:

.. autoexception:: ImplicitDisambiguationWarning
   :show-inheritance:

.. autoexception:: CalendarUnitCompositionWarning
   :show-inheritance:

.. autoexception:: PickleOffsetMismatchWarning
   :show-inheritance:

.. autoexception:: WheneverDeprecationWarning
   :show-inheritance:


Exceptions
----------

.. autoexception:: RepeatedTime
   :show-inheritance:

.. autoexception:: SkippedTime
   :show-inheritance:

.. autoexception:: InvalidOffsetError
   :show-inheritance:

.. autoexception:: TimeZoneNotFoundError
   :show-inheritance:
