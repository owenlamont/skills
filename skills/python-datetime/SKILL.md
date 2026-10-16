---
name: python-datetime
description: Work with dates, times, and timezones to this project's standards. Use when creating, parsing, serialising, comparing, or storing datetimes, or handling timezones.
---

# Python Datetime

Standards for dates, times, and timezones, using the standard library `datetime` and
`zoneinfo`.

## Timezones

- Always use timezone-aware datetimes; never naive ones. Attach a zone at the boundary
  where a value enters the system.
- Use the standard library `zoneinfo` for timezones, not `pytz` (whose legacy
  `localize()` dance is a frequent source of bugs).

## Serialising and parsing

- Serialise with ISO 8601 via `isoformat()` and parse with `fromisoformat()` — not
  `strftime`/`strptime` with a hand-written format, and not all-digit numeric formats. The
  rule governs the formats *you* choose, on both sides of a boundary you own.
- When the input is a third-party format you don't control — a scraped page, a vendor CSV,
  a log line — `strptime` with an explicit format string is the right tool, and no
  deviation to flag. `fromisoformat()` simply cannot read `26 Jul 26`. Parse it once at
  the boundary, attach the zone there, and keep the format string out of the rest of the
  code. Don't take on a fuzzy-parsing dependency to dodge writing the format
  (`python-libraries` weighs that trade).
- Attach the zone even when you only want the calendar day, and don't let the redundancy
  talk you out of it:

  ```python
  sold_on = datetime.strptime(raw, "%d %b %y").replace(tzinfo=SYDNEY).date()
  ```

  `replace(tzinfo=...)` reinterprets the same wall-clock reading rather than shifting it,
  so it cannot change which day `.date()` returns — but it is what clears Ruff's `DTZ007`,
  which still fires on the same chain without it, and it records whose calendar that day
  belongs to, the fact any later comparison against a timestamp depends on.
- When parsing datetimes in pandas, pass an explicit `format=` to `pd.to_datetime` rather
  than relying on inference.

## Pitfalls

- **A calendar day taken from an aware timestamp belongs to that timestamp's zone, not
  to yours.** `datetime.fromisoformat(raw).date()` gives the day in the zone the string
  carries — UTC, for a `...Z` stamp — while `.astimezone().date()` gives the local one,
  and either side of midnight the two differ. Convert whenever the result will meet
  `date.today()` or `date.fromtimestamp()`, both local by definition: an age or a day
  count mixing the two conventions is off by one and raises nothing. This is the mirror
  of the `replace(tzinfo=...)` above — `replace` reinterprets a wall-clock reading and
  *cannot* move the day, `astimezone` converts the instant and is meant to. No linter
  closes it: `DTZ` has no rule for `.date()` on an aware timestamp, so the mismatch
  surfaces only as a wrong answer.

See `python-pandas` for typing DataFrame timestamp columns as `pd.Timestamp`.
