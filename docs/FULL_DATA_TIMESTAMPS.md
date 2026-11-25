# Timestamp preparation for the full 2022 file

We have now run the timestamp model on all **4,078,318 rows** in our January–July 2022 Parquet file. This is the stopping point for this version: a reproducible timestamp table with explicit statuses, before flight linking.

The table is not a final cleaned dataset. Every source row is kept, including cancelled flights and records that failed a check. We have not guessed replacements for inconsistent values.

## Run it

Install the versions in `requirements-audit.txt` and use the raw file described in [the audit notes](DATA_AUDIT.md). Run from the repository root:

```bash
.venv/bin/python -m src.prepare_timestamps data/raw/Combined_Flights_2022.parquet \
  --airport-map reference/airport_timezones.json \
  --output-dir data/processed/2022_timestamps_v1
```

The output directory must not already exist. Choose a new directory for a new run; the command will not overwrite an earlier run. It also requires the input file's hash to match the file reviewed for the airport map. For a different input file, rebuild and review its map first.

The output directory contains:

- `flights.parquet`: original fields plus timestamp results.
- `report.json`: status counts, sample failures, input/output hashes, map hash, time-zone version, Python/PyArrow versions, processing settings, and code-file hashes.

During processing, the table is named `flights.partial.parquet`. The final report is written only after processing finishes. If a run stops early, do not treat a partial file or a directory without the completed report as a successful output. Use a new directory when retrying.

The command processes 50,000 rows at a time by default. `--batch-size` can change that. It keeps source columns in Arrow and converts only the fields needed by the time model into Python records. It uses the same per-flight rules as the [sample timestamp model](TIME_MODEL.md), with [pinned airport and time-zone references](AIRPORT_TIMEZONES.md).

## What the output adds

All 62 source columns are retained. These eight columns are added:

| Field | Meaning |
|---|---|
| `source_row_number` | Zero-based row position in the exact input file, for tracing a result back to its source. |
| `timestamp_status` | Result of the timestamp checks. |
| `timestamp_details` | JSON details for flagged or excluded records; null for consistent candidates. |
| `has_tail_number` | Whether a nonblank tail number is available. This is separate from timestamp consistency. |
| `scheduled_departure_utc` | Candidate scheduled departure. |
| `scheduled_arrival_utc` | Candidate scheduled arrival. |
| `actual_departure_utc` | Candidate actual departure. |
| `actual_arrival_utc` | Candidate actual arrival. |

The four timestamp fields use Arrow's UTC timestamp type with microsecond precision. They are null unless the status is `consistent_candidate`. We do not write one of several possible times into a row marked ambiguous.

`source_row_number` identifies a position in this file, not a permanent flight ID across different exports. Keep the input hash with any use of that number.

## Results

| Status | Rows |
|---|---:|
| `consistent_candidate` | 3,944,622 |
| `excluded` | 133,402 |
| `clock_mismatch` | 216 |
| `duration_delay_mismatch` | 77 |
| `invalid_duration` | 1 |
| **Total** | **4,078,318** |

There were no unmapped-airport, invalid-input, nonexistent-clock, or ambiguous-clock statuses in this run. That does not prove those cases cannot occur in other years.

Of the 3,944,916 flights that were neither cancelled nor diverted, 294 did not produce a consistent candidate. The earlier duration audit reported 78 nonzero residuals. Here, one of those records is assigned `invalid_duration` first, leaving 77 under `duration_delay_mismatch`. These statuses are mutually exclusive because the checks run in order.

A consistent result means the supplied clocks, durations, delays, and zone rules agree. It does not independently establish that the source record is correct or that the aircraft belongs in a particular sequence. Current airport-reference coverage is also not full historical validation.

## Validate the generated table

```bash
.venv/bin/python -m src.validate_timestamps data/raw/Combined_Flights_2022.parquet \
  --output-dir data/processed/2022_timestamps_v1
```

The validator reads the source and output in batches and checks:

1. Input/output file hashes and row counts match the completed report.
2. Every original column value is unchanged, in the same row order.
3. Source row numbers run from zero through the final input row.
4. UTC fields have the expected type and are populated only for consistent candidates.
5. UTC differences agree with `DepDelay`, `ArrDelay`, `CRSElapsedTime`, and `ActualElapsedTime`.
6. Status counts in the table match the report.

This is separate from rebuilding the timestamps. It checks preservation and arithmetic, but it does not independently validate the airport zones or the original reported clocks.

The validator passed on all 4,078,318 output rows. Every source value and row number was preserved, and the UTC nullability and arithmetic checks both found zero errors. All 3,944,622 consistent candidates also had nonblank tail numbers in this run.

Run the small tests too:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The batch test uses several small batches and checks that failures stay in the output, source fields stay unchanged, missing tail numbers remain visible, existing output directories are rejected, a wrong input hash is rejected, and a modified output is detected by the validator.

All 14 current tests passed.

## How the team can continue

The large Parquet output and run report stay under `data/`, outside Git. Each teammate can reproduce them with the same raw file, code, requirements, and reference map. The source and output hashes in the report help identify which run was used. Code-file hashes preserve that information even when running local changes before a commit.

The next task is actual flight linking. Start with timestamp-consistent records that have tail numbers, but decide how excluded and flagged flights interrupt a sequence before filtering them away. Otherwise, a window operation could incorrectly connect flights across a missing leg.

After actual links are checked, define which pairs can be used for scheduled-ground-time analysis. Our earlier JFK/LAX example shows that actual links can have overlapping planned times. Those cases need an explicit rule rather than treating a negative scheduled interval as a usable buffer.

Spark processing, additional years, benchmarks, and scenario analysis are still ahead. This version provides the timestamp preparation and its checks, not the completed research pipeline.
