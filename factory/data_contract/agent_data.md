# Market data and strategy-time contract

<!-- GENERATED from factory/data_contract/contract.yaml; do not edit. -->
Schema version: 1.0.0. Source SHA-256: `83beaf06c001264fced1d032085580c9313b983db2eef3af4ffbbb464536374c`.

## Meaning and use

- Minute timestamps label bar START, with a left-inclusive and right-exclusive interval. The close becomes usable one minute after its label.
- XNYS regular sessions contain 09:30 through 15:59 New York labels; there is no 16:00 bar. A 13:00 early close ends with the 12:59 label.
- Daily timestamps label the session date at New York midnight (04:00Z in daylight time, 05:00Z in standard time); they are neither trading times nor availability times.
- Daily bars are provider day aggregates, not reductions of retained regular-session minutes. Extended-hours volume, trade-condition rules and revisions can differ. Final daily OHLCV is not guaranteed available at the regular-session close; this is a historical, not point-in-time, dataset.
- Session offsets describe the bar START. For minute decisions, add one minute to minutes_since_open to obtain elapsed time when that bar closes. Daily offsets describe the session open, with both boundary flags true.
- Session boundary flags use scheduled calendar slots, never the first or last observed row in a slice. Missing bars and truncated evaluation slices do not move the session boundaries.
- A target at t earns the next bar's close-to-close return through the engine's one-row execution lag. Do not shift target weights forward. The engine does not flatten overnight; an intraday strategy must set its last-session target to zero.
- Example for a full session, long from 10:00 through 15:30 New York time; set target one where minutes_since_open is at least 29 and less than 359. Those labels close at 10:00 through 15:29; the target is zero on the 15:29 label whose close is at 15:30.
- Only missing minutes following an observed close within the same session can be filled, for at most five consecutive minutes. Filled OHLC equal that prior close and volume is zero. Daily bars are never locally filled. Remaining gaps stay absent.
- is_filled identifies repository synthesis only. A provider row with zero volume may be real or upstream synthetic; is_filled false does not prove trading occurred.
- Alpaca SIP adjustment all applies split, dividend and spin-off price adjustments. Volume is split-adjusted shares; dividends and spin-offs do not rescale volume. Raw factors and historical revision times are not retained.
- All prices use USD per share. Current S&P membership in the daily universe introduces survivorship bias. Provider symbol mapping and final adjusted histories are not point-in-time instrument membership.
- IS, OOS and HOLDOUT are disjoint chronological 60/20/20 slices of the shared expected tier grid; they may bisect sessions and differ across tiers. Workers receive IS only. HOLDOUT is sealed from strategy/model runs.
- Session columns and is_filled are preserved through execution. Derived session columns are read-only inputs; changing or deleting them causes a contract error before strategy output is accepted.
- Strategy activity is a bug check on IS target weights only. A traded day is an exchange date with any nonzero target, including held exposure; this is not a performance or turnover threshold.

## Calendar and activity settings

```json
{
  "calendar": {
    "name": "XNYS",
    "timezone": "America/New_York",
    "library": "exchange-calendars",
    "version": "4.13.2",
    "timestamp_timezone": "UTC",
    "minute_duration": 1,
    "fill_limit": 5
  },
  "activity": {
    "minimum_days": 5,
    "status": "INACTIVE",
    "message": "strategy never trades; check session-time logic"
  }
}
```

## Instrument

An equity or ETF identified in a provider snapshot, not a point-in-time constituent history.

| Field | dtype | Units | Constraints | Meaning |
|---|---|---|---|---|
| `symbol` | `string` | identifier | {"pattern": "^[A-Z][A-Z0-9.]{0,14}$"} | Provider symbol including share-class dots. |
| `asset_class` | `string` | category | {"allowed": ["equity", "etf"]} | Instrument classification. |
| `currency` | `string` | ISO4217 | {"allowed": ["USD"]} | Currency of every price. |
| `calendar` | `string` | identifier | {"allowed": ["XNYS"]} | Session calendar used by this dataset. |
| `timezone` | `string` | IANA | {"allowed": ["America/New_York"]} | Exchange timezone for session dates and offsets. |

## Session

Scheduled trading interval from the pinned exchange calendar, including early closes and holidays.

| Field | dtype | Units | Constraints | Meaning |
|---|---|---|---|---|
| `session_date` | `datetime64[ns, America/New_York]` | exchange_date | {} | Exchange date represented at local midnight. |
| `open` | `datetime64[ns, UTC]` | instant | {} | Scheduled regular-session opening instant. |
| `close` | `datetime64[ns, UTC]` | instant | {} | Scheduled regular-session closing instant. |
| `duration_minutes` | `int64` | minutes | {"minimum": 1} | Actual scheduled close minus open in minutes. |

## Bar

One retained price aggregate with explicit local synthesis provenance.

| Field | dtype | Units | Constraints | Meaning |
|---|---|---|---|---|
| `timestamp` | `datetime64[ns, UTC]` | instant | {"location": "index"} | Minute interval start or daily New York midnight label. |
| `open` | `float64` | USD/share | {} | Adjusted first eligible price or prior close for a filled bar. |
| `high` | `float64` | USD/share | {} | Adjusted maximum eligible price or prior close for a filled bar. |
| `low` | `float64` | USD/share | {} | Adjusted minimum eligible price or prior close for a filled bar. |
| `close` | `float64` | USD/share | {} | Adjusted last eligible price or prior close for a filled bar. |
| `volume` | `float64` | shares | {} | Split-adjusted provider volume or zero for a filled bar. |
| `is_filled` | `bool` | flag | {} | Whether this repository synthesized the row. |
| `session_date` | `datetime64[ns, America/New_York]` | exchange_date | {"derive": "local_date", "read_only": true} | Scheduled session date at exchange-local midnight. |
| `minutes_since_open` | `int64` | minutes | {"derive": "elapsed_start", "read_only": true} | Minutes from scheduled open to minute label; zero for a daily bar. |
| `minutes_to_close` | `int64` | minutes | {"derive": "remaining_start", "read_only": true} | Minutes from minute label to scheduled close; full session duration for a daily bar. |
| `is_first_bar` | `bool` | flag | {"derive": "scheduled_first", "read_only": true} | Whether this is the scheduled first slot; true for a daily bar. |
| `is_last_bar` | `bool` | flag | {"derive": "scheduled_last", "read_only": true} | Whether this is the scheduled last slot; true for a daily bar. |

## Dataset

A validated immutable data file and its per-file provenance manifest.

| Field | dtype | Units | Constraints | Meaning |
|---|---|---|---|---|
| `name` | `string` | identifier | {} | Dataset name used in all validation errors. |
| `kind` | `string` | category | {"allowed": ["price_bars", "events"]} | Selects the generated dataset validator. |
| `schema_version` | `string` | version | {"allowed": ["1.0.0"]} | Contract schema used to validate this dataset. |
| `source` | `string` | provenance | {} | Provider or approved source URL without credentials. |
| `feed` | `string` | identifier | {"allowed": ["sip", "user_supplied"]} | Provider feed or user supplied event source. |
| `adjustment` | `string` | category | {"allowed": ["all", "not_applicable"]} | Price and volume adjustment convention; not applicable for events. |
| `date_range` | `object` | UTC_bounds | {} | Inclusive actual first and last timestamps as start and end UTC ISO strings. |
| `row_count` | `int64` | rows | {"minimum": 1} | Exact count of physically stored rows. |
| `fill_rate` | `float64` | fraction | {"minimum": 0, "maximum": 1} | Locally filled rows divided by expected price grid length; zero for events. |
| `created_at` | `utc_string` | instant | {} | Original dataset write timestamp when known. |
| `sha256` | `string` | digest | {"pattern": "^[a-f0-9]{64}$"} | SHA-256 fingerprint of the stored file bytes. |
| `frequency` | `string` | interval | {"allowed": ["1min", "1day", "event"]} | Price aggregation interval or event data. |
| `start` | `date_string` | exchange_date | {} | Inclusive requested start date. |
| `through` | `date_string` | exchange_date | {} | Inclusive requested final date. |
| `calendar` | `string` | identifier | {"allowed": ["XNYS"]} | Calendar identity used to validate labels. |
| `calendar_version` | `string` | version | {"allowed": ["4.13.2"]} | Pinned exchange calendar library version. |

## Split

Inclusive boundaries on the shared tier grid; not independently computed per symbol.

| Field | dtype | Units | Constraints | Meaning |
|---|---|---|---|---|
| `name` | `string` | category | {"allowed": ["IS", "OOS", "HOLDOUT"]} | Partition visibility label. |
| `start` | `utc_string` | instant | {} | Inclusive first timestamp in this partition. |
| `end` | `utc_string` | instant | {} | Inclusive last timestamp in this partition. |
| `fraction` | `float64` | fraction | {"allowed": [0.6, 0.2]} | Requested fraction of expected tier rows. |

## Dataset kind: price_bars

Extra columns allowed: False.

Invariants:

- `price_bars.nonempty`: Stored datasets contain at least one row.
- `price_bars.columns`: Physical columns and index match Bar fields and exact dtypes.
- `price_bars.timestamp_order`: Timestamps are UTC nanoseconds with no NaT or duplicates and strictly increasing order.
- `price_bars.finite`: Every OHLCV value is finite.
- `price_bars.positive`: Every price is strictly positive.
- `price_bars.nonnegative`: Volume is nonnegative.
- `price_bars.ohlc_bounds`: High is at least open/close/low and low is at most open/close/high.
- `price_bars.calendar`: Every label lies on the expected XNYS grid within requested dates.
- `price_bars.fill_shape`: Filled rows have flat OHLC and zero volume; daily rows are never filled.
- `price_bars.fill_history`: Full stored minute files exactly reproduce the declared within-session fill rule from their observed rows.

## Dataset kind: events

Extra columns allowed: True.
- `available_at`: `datetime64[ns, UTC]`, instant. Earliest timestamp when the information could have been known.
- `symbol`: `string`, identifier. Instrument symbol to which the event applies.
Extension dtypes: float64, int64, bool, string, datetime64[ns, UTC].

Invariants:

- `events.nonempty`: Stored event datasets contain at least one row.
- `events.columns`: Events require UTC available_at and a string symbol; extensions use declared scalar dtypes.
- `events.availability_order`: Availability timestamps are non-null and in nondecreasing order.
- `events.symbol`: Event symbols use the supported instrument-symbol syntax.
- `events.event_values`: Event cells are non-null and numeric values are finite.

## Record and strategy invariants

- `entity_fields`: Every ontology record has all required fields with declared types and allowed values.
- `session_interval`: Session open and close match the pinned calendar and duration is their difference.
- `split_interval`: Split start is no later than end and its fraction matches its name.
- `manifest_content`: Manifest schema and provenance match the validated file fingerprint
- `session_derivation`: Derived session fields equal their calendar-based definitions and cannot be changed by strategies.
- `activity`: Full IS target weights must be nonzero on at least five exchange dates; otherwise status is INACTIVE and self-heal receives the specified message.
