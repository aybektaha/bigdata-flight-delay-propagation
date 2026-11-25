# Checking flight timestamps

After the [first data audit](DATA_AUDIT.md), we started turning clock fields into dated timestamps. This page explains the model and its initial small examples. We have since applied it to [the full 2022 file](FULL_DATA_TIMESTAMPS.md); final aircraft sequences are still pending.

## Why this is needed

Departure and arrival clocks use local time. `0730` at JFK and `0730` at LAX are not the same instant. Flights can cross midnight or be delayed across a daylight-saving change.

We use signed `DepDelay` and `ArrDelay`. The `*DelayMinutes` fields set early departures or arrivals to zero, which loses information needed here. See the [BTS field definitions](https://transtats.bts.gov/Fields.asp?gnoyr_VQ=FGJ).

## New code

| File | Purpose |
|---|---|
| [`src/timestamps.py`](../src/timestamps.py) | Builds candidate UTC timestamps for one flight and checks the reported clocks. |
| [`src/time_audit.py`](../src/time_audit.py) | Checks time relationships across the file, then reconstructs one tail/date sample. |
| [`tests/test_timestamps.py`](../tests/test_timestamps.py) | Tests midnight, early departures, multi-day delays, DST, and inconsistent inputs. |

`clock_minutes()` converts HHMM to minutes from midnight. It rejects invalid values and treats `2400` as 1,440 minutes. For a scheduled departure, this means midnight at the start of the next day relative to `FlightDate`. Our file has no scheduled `2400` values, so that branch has only been checked with a constructed example.

`utc_candidates()` finds the possible UTC instants for the scheduled local departure. During an autumn clock change, a clock may occur twice; during a spring change, it may not exist. We try both possibilities and check that converting back gives the original clock. This uses Python's [zoneinfo and fold support](https://docs.python.org/3.9/library/zoneinfo.html).

`reconstruct()` then applies these relationships, with additions done in UTC:

```text
scheduled arrival = scheduled departure + CRSElapsedTime
actual departure  = scheduled departure + DepDelay
actual arrival    = actual departure + ActualElapsedTime
```

The results are converted back to the appropriate airport zone and compared with `CRSArrTime`, `DepTime`, and `ArrTime`. An actual `2400` is compared as a midnight clock; its date comes from the duration/delay calculation. We also check:

```text
ArrDelay - DepDelay = ActualElapsedTime - CRSElapsedTime
```

A passing result is called `consistent_candidate`. It means the supplied fields agree under our assumptions, not that we independently proved the timestamps or aircraft assignment. A wrong zone could still produce consistent records in some cases.

Other statuses explain why a row was not accepted:

| Status | Meaning |
|---|---|
| `excluded` | Cancelled or diverted flight. |
| `unmapped_airport` | An airport zone was not supplied. |
| `invalid_input` | A required date, clock, delay, or duration is missing or invalid. |
| `invalid_duration` | A scheduled or actual duration is not positive. |
| `duration_delay_mismatch` | The duration/delay equation does not balance. |
| `nonexistent_local_departure` | The local departure does not exist under the supplied zone rules. |
| `clock_mismatch` | Derived clocks do not match the reported ones. |
| `ambiguous_local_departure` | More than one UTC candidate fits. |

Checks run in order, so the status is not a list of every possible issue. Records are reported, not deleted or repaired.

## Run the sample

Use the environment from [the audit instructions](DATA_AUDIT.md#how-to-run-the-checks). From the repository root:

```bash
.venv/bin/python -m src.time_audit data/raw/Combined_Flights_2022.parquet \
  --tail N102NN --date 2022-01-04 \
  --airport-zone JFK=America/New_York \
  --airport-zone LAX=America/Los_Angeles \
  --output data/processed/audits/2022_time_sample.json
```

The command runs the basic audit and file-wide time checks, then reconstructs the selected tail/date rows and the naive-clock flagged records. The JSON includes the input hash, package versions, airport-zone arguments, raw sample rows, and statuses. Its sample rows are still in query order, not a finalized flight sequence. Reusing an output path replaces that report.

These original examples supply zones manually. We now also have a [shared lookup](AIRPORT_TIMEZONES.md) covering all 375 airport codes in this file. Use `--airport-map reference/airport_timezones.json` instead of the individual `--airport-zone` arguments to use it. The code now reads IANA 2025b rules directly from the pinned `tzdata==2025.2` package, so update the requirements before running it.

## File-wide results

These counts cover 3,944,916 flights where both cancellation and diversion flags are false. A known tail number is not required here.

| Check | Result |
|---|---:|
| Missing scheduled / actual elapsed time | 0 / 0 |
| Nonpositive scheduled elapsed time | 1 |
| Nonpositive actual elapsed time | 0 |
| Nonzero duration/delay residual | 78 |
| Naive departure-clock mismatch | 22 |
| Minimum / maximum departure delay | -78 / 7,223 minutes |

Flags can overlap, so these are not counts to add together. The negative scheduled duration is `-48` minutes for `N635RW`, BNA to EWR, on January 21, 2022. We keep it flagged rather than guess a replacement.

The naive clock check adds `DepDelay` to the scheduled local clock and compares the result modulo 24 hours with `DepTime`. It ignores clock changes. Its 22 mismatches are investigation candidates, not automatic data errors.

## The JFK/LAX example

Both rows passed the consistency checks. All times below are UTC on January 4, 2022, unless another date is shown.

| Flight | Scheduled departure | Scheduled arrival | Actual departure | Actual arrival |
|---|---|---|---|---|
| AA 1, JFK → LAX | 12:30 | 19:04 | 12:27 | 18:51 |
| AA 28, LAX → JFK | 15:30 | 20:45 | 19:37 | January 5, 01:04 |

The actual gap at LAX is **46 minutes**, but the scheduled gap is **-214 minutes**. The second scheduled departure is before the first scheduled arrival.

An observed tail number does not by itself establish a feasible planned rotation. We cannot use this scheduled difference as a normal turnaround buffer. Aircraft reassignment or other operational changes might explain it, but these rows do not establish the cause. We need separate rules for actual sequence linking and scheduled-buffer eligibility.

## A real DST example

For `N364NW`, ATL to TYS, on March 12, 2022, scheduled departure is 22:48 and actual departure is 04:09 with a 261-minute delay. Simple local-clock addition gives 03:09. Using `America/New_York` rules gives March 13 at 08:09 UTC, or 04:09 local time. Both arrival clocks also match.

This explains this one naive-clock mismatch. With the shared lookup, we have now checked all 22 flagged rows: 21 produce consistent candidates, while one still has an arrival-clock mismatch. The remaining record is N341DN, LGA to MCO, on March 12, 2022. It remains flagged; we have not guessed a corrected arrival time.

```bash
.venv/bin/python -m src.time_audit data/raw/Combined_Flights_2022.parquet \
  --tail N364NW --date 2022-03-12 \
  --airport-zone ATL=America/New_York \
  --airport-zone TYS=America/New_York \
  --output data/processed/audits/2022_dst_sample.json
```

That tail/date has six records: one consistent candidate, four with unmapped airports, and one excluded flight. We did not guess zones for airports outside the supplied map.

## Tests and next steps

```bash
.venv/bin/python -m unittest discover -s tests -v
```

All 14 current tests passed, including quality, airport-mapping, and batch-output tests. Timestamp tests cover both real examples, overnight and multi-day delays, early departure, scheduled and actual midnight, spring and autumn clock changes, invalid input, and SQL flag counts.

Before applying this to every flight, we need to:

1. Review historical airport identity assumptions when adding more years. Current code coverage is complete, but that is not full historical validation.
2. Use the completed full-file status counts to choose records for detailed review.
3. Inspect flagged records and define analysis-specific handling rules.
4. Check more aircraft sequences and separate actual links from feasible scheduled turnaround pairs.

The raw file is unchanged. The full-file output retains every row and adds timestamps and statuses; validated rotations are not available yet. This reconstructs events using observed delays; it is not a prediction model.
