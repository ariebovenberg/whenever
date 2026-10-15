/* The whenever C API, version 1.
 *
 * A table of function pointers through which an extension module converts
 * whenever values to and from plain records without Python calls. Import it
 * with
 *
 *     const Whenever_CAPI *api = PyCapsule_Import("whenever.C_API_v1", 0);
 *
 * which fails with AttributeError when the pure-Python backend is installed.
 * Check `magic` and `struct_size` before using any other field.
 *
 * Stability: within v1 the records never change and the table only grows at
 * the end. `version_minor` and `struct_size` say how far it goes. A
 * breaking change ships as a second capsule next to this one. Every
 * function takes the table as its first argument; always pass the pointer
 * the capsule handed out.
 *
 * Threads: constructors require an attached thread state (the GIL on
 * default builds). Extractors do not: they make no CPython call, and may be
 * called from any thread while the caller holds a strong reference to the
 * object. That reference also keeps an extracted `tz_id` alive.
 *
 * Lifetime: the table and the type objects belong to the `whenever._whenever`
 * module. A consumer that keeps the pointer past the import holds a reference
 * to that module alongside it, so that an unload of whenever cannot free the
 * table under it.
 *
 * Only the Rust backend provides the table. The same records are available
 * from both backends as bytes through `to_bytes()` and `from_bytes()`.
 */
#ifndef WHENEVER_H
#define WHENEVER_H

#include <Python.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define WHENEVER_CAPSULE_NAME "whenever.C_API_v1"

/* --- records: the fields of the pickle payloads, by value ----------------- */

typedef struct {
    uint16_t year;  /* 1..=9999 */
    uint8_t month;  /* 1..=12 */
    uint8_t day;    /* 1..=31, valid for the month */
} Whenever_Date;

typedef struct {
    uint8_t hour;         /* 0..=23 */
    uint8_t minute;       /* 0..=59 */
    uint8_t second;       /* 0..=59 */
    uint32_t nanosecond;  /* 0..=999999999 */
} Whenever_Time;

typedef struct {
    Whenever_Date date;
    Whenever_Time time;
} Whenever_PlainDateTime;

typedef struct {
    int64_t epoch_second;  /* -62135596800..=253402300799 (year 1 to 9999 UTC) */
    uint32_t nanosecond;   /* 0..=999999999 */
} Whenever_Instant;

typedef struct {
    Whenever_PlainDateTime local;
    int32_t offset_second;  /* -86399..=86399 */
} Whenever_OffsetDateTime;

typedef struct {
    Whenever_OffsetDateTime odt;
    /* ASCII, NOT NUL-terminated, in the spelling of the time zone database.
     * The record never owns it. Extracted, it points into the object and is
     * valid while the caller holds a reference; NULL for a system time zone
     * without a time zone ID. Passed to a constructor, it is the caller's
     * memory, read during the call only: whenever keeps its own copy. */
    const char *tz_id;
    uint8_t tz_id_len;  /* 1..=99; 0 when tz_id is NULL */
} Whenever_ZonedDateTime;

/* total = second * 1e9 + nanosecond; nanosecond is never negative */
typedef struct {
    int64_t second;
    uint32_t nanosecond;  /* 0..=999999999 */
} Whenever_TimeDelta;

/* --- policies for zoned_datetime_new ------------------------------------- */

typedef enum {
    WHENEVER_OFFSET_MISMATCH_RAISE = 0,
    WHENEVER_OFFSET_MISMATCH_KEEP_INSTANT = 1,
    WHENEVER_OFFSET_MISMATCH_KEEP_LOCAL = 2
} Whenever_OffsetMismatch;

typedef enum {
    WHENEVER_DISAMBIGUATION_COMPATIBLE = 0,
    WHENEVER_DISAMBIGUATION_EARLIER = 1,
    WHENEVER_DISAMBIGUATION_LATER = 2,
    WHENEVER_DISAMBIGUATION_RAISE = 3
} Whenever_Disambiguation;

/* --- the table ----------------------------------------------------------- */

typedef struct Whenever_CAPI Whenever_CAPI;

/* 0: written. 1: `obj` is not exactly this type; nothing is written and no
 * exception is set. Never fails otherwise. */
#define WHENEVER_EXTRACT(record, name) \
    int (*name)(const Whenever_CAPI *, PyObject *, record *)

/* A new reference, or NULL with an exception set. The record is validated:
 * out-of-range fields raise ValueError. */
#define WHENEVER_NEW(record, name) \
    PyObject *(*name)(const Whenever_CAPI *, const record *)

struct Whenever_CAPI {
    const char *magic;     /* WHENEVER_CAPSULE_NAME */
    int32_t struct_size;   /* sizeof(Whenever_CAPI) of the providing build */
    int32_t version_minor; /* bumped when fields are appended */

    /* This interpreter's type objects, borrowed. Compare with Py_TYPE(obj)
     * to dispatch; the types have no subclasses. */
    PyTypeObject *DateType;
    PyTypeObject *TimeType;
    PyTypeObject *PlainDateTimeType;
    PyTypeObject *InstantType;
    PyTypeObject *OffsetDateTimeType;
    PyTypeObject *ZonedDateTimeType;
    PyTypeObject *TimeDeltaType;

    WHENEVER_EXTRACT(Whenever_Date, date_extract);
    WHENEVER_EXTRACT(Whenever_Time, time_extract);
    WHENEVER_EXTRACT(Whenever_PlainDateTime, plain_datetime_extract);
    WHENEVER_EXTRACT(Whenever_Instant, instant_extract);
    WHENEVER_EXTRACT(Whenever_OffsetDateTime, offset_datetime_extract);
    WHENEVER_EXTRACT(Whenever_ZonedDateTime, zoned_datetime_extract);
    WHENEVER_EXTRACT(Whenever_TimeDelta, time_delta_extract);

    WHENEVER_NEW(Whenever_Date, date_new);
    WHENEVER_NEW(Whenever_Time, time_new);
    WHENEVER_NEW(Whenever_PlainDateTime, plain_datetime_new);
    WHENEVER_NEW(Whenever_Instant, instant_new);
    WHENEVER_NEW(Whenever_OffsetDateTime, offset_datetime_new);
    WHENEVER_NEW(Whenever_TimeDelta, time_delta_new);

    /* The instant in the named time zone; the local fields are computed
     * with whenever's time zone data. Raises TimeZoneNotFoundError for an
     * unknown ID. */
    PyObject *(*zoned_datetime_from_instant)(const Whenever_CAPI *,
                                             const Whenever_Instant *,
                                             const char *tz_id,
                                             uint8_t tz_id_len);

    /* The record as written. When (local, offset) identifies no occurrence
     * of that local time in the zone, `offset_mismatch` decides;
     * `disambiguation` is consulted only when KEEP_LOCAL then lands in a
     * gap or fold. Both are required. Raises ValueError for an unknown
     * policy, TimeZoneNotFoundError for an unknown ID, InvalidOffsetError
     * under RAISE, and RepeatedTime or SkippedTime under
     * WHENEVER_DISAMBIGUATION_RAISE. */
    PyObject *(*zoned_datetime_new)(const Whenever_CAPI *,
                                    const Whenever_ZonedDateTime *,
                                    int offset_mismatch,
                                    int disambiguation);
};

#undef WHENEVER_EXTRACT
#undef WHENEVER_NEW

#ifdef __cplusplus
}
#endif

#endif /* WHENEVER_H */
