# First data checks

We started by checking the 2022 flight file before writing the cleaning and flight-linking code. This note explains what we added, how to run it, and what we found. The next stage is documented in [Checking flight timestamps](TIME_MODEL.md).

The audit scripts only read the raw data. They do not remove rows, change timestamps, or produce cleaned flight tables. Their JSON files contain audit results. A later [full-file preparation step](FULL_DATA_TIMESTAMPS.md) now writes a separate Parquet table with added UTC candidates and statuses while preserving the source fields.

## Files added

| File | What it does |
|---|---|
| [`src/audit.py`](../src/audit.py) | Checks the file identity, schema, dates, missing values, monthly counts, and a first same-day continuity calculation. |
| [`src/quality.py`](../src/quality.py) | Runs the basic audit and adds duplicate checks, tied departure groups, and clock-format checks. |
| [`requirements-audit.txt`](../requirements-audit.txt) | Lists the audit packages and the pinned time-zone data used by the timestamp stage. |
| [`tests/test_quality.py`](../tests/test_quality.py) | Checks the quality code against a small dataset with known cases. |

The current code uses DuckDB for SQL queries and PyArrow for Parquet metadata. We have not implemented the Spark pipeline or run a Spark benchmark yet. Some files shown in the main README's planned repository structure do not exist yet; the table above lists the audit code that is actually available.

## The file we checked

We used `Combined_Flights_2022.parquet` from the project's local data folder. The dataset referenced in our proposal is [Rob Mulla's Flight Delay Dataset 2018–2022](https://www.kaggle.com/datasets/robikscube/flight-delay-dataset-20182022). We still need to finish the source and license checks for the full collection.

| Item | Value |
|---|---|
| Expected local path | `data/raw/Combined_Flights_2022.parquet` |
| File size | 149,648,506 bytes, about 142.7 MiB |
| Rows | 4,078,318 |
| Date range | January 1 to July 31, 2022 |
| Physical columns | 62 |
| Data columns | 61, excluding the saved `__index_level_0__` column |
| Parquet row groups | 1 |

The file does not cover all of 2022. We should not describe its results as full-year statistics. We also have not checked the proposal's multi-year totals against a complete local download.

The SHA-256 of the file we used is:

```text
89eac402d3d9b454c88597ed2b6fca1d8169738f698871ad7b20ad9fb5ca554f
```

This is a fingerprint of the actual file contents. If your file has a different hash, check its source and version before comparing results. A different hash does not automatically mean the file is damaged; it may be a different export.

## How to run the checks

Run these commands from the repository root. Put your copy of the Parquet file in `data/raw/` first. The raw data is not included in Git.

We tested the scripts with Python 3.9.6, DuckDB 1.4.5, and PyArrow 21.0.0. The timestamp stage also uses tzdata 2025.2. The requirements file covers the current audit and timestamp tools, not the future Spark environment.

If you do not have a virtual environment yet:

```bash
python3 -m venv .venv
```

Install the audit packages:

```bash
.venv/bin/python -m pip install -r requirements-audit.txt
```

Run the basic audit:

```bash
.venv/bin/python -m src.audit data/raw/Combined_Flights_2022.parquet --output data/processed/audits/2022_initial.json
```

Run the detailed checks:

```bash
.venv/bin/python -m src.quality data/raw/Combined_Flights_2022.parquet --output data/processed/audits/2022_quality.json
```

The detailed command also runs the basic audit, so you can run just that command if you want everything in one report. We keep the two entry points because the basic check is useful on its own.

These examples use the macOS/Linux environment path. On Windows, use `.venv\Scripts\python.exe` in place of `.venv/bin/python`.

The output folder is created automatically. Running a command again with the same output path replaces that JSON report. Use a different name if you want to keep an earlier run. Reports under `data/` stay outside Git because that directory is already ignored.

The detailed duplicate check uses a DuckDB connection with a 1 GB memory limit and a temporary folder for disk spill. This setting applies to that connection, not to the entire Python process or the preceding basic audit. Leave some temporary disk space available when running it.

## What the basic audit checks

The `audit()` function records the input path, file size, SHA-256, package versions, and report creation time. It reads the Parquet schema and counts null values in every column. It also reports the date range, rows per month, cancelled flights, diverted flights, and missing or blank tail numbers.

Its first continuity calculation works as follows:

1. Keep flights that are not cancelled or diverted and have a nonblank `Tail_Number`.
2. Group them by `Tail_Number` and sort by `FlightDate` and `CRSDepTime`.
3. Use SQL `lead()` to read the next flight's origin and date.
4. Keep pairs with the same flight date.
5. Count how often the first destination matches the next origin.

This reproduces the preliminary check in our proposal. It is not the final aircraft rotation algorithm.

## What the detailed check adds

### Duplicate records

`duplicate_summary()` groups records using a supplied list of columns. It reports the number of repeated groups, the rows in those groups, and the extra rows. For example, a group with three matching rows has two extra rows.

We check two definitions:

- **All data fields:** compare every field except `__index_level_0__`. A saved row index should not make two otherwise identical records look different.
- **Candidate flight key:** compare `FlightDate`, `Operating_Airline`, `Flight_Number_Operating_Airline`, `Origin`, `Dest`, and `CRSDepTime`.

A repeated candidate key would need inspection. The code does not assume that every repeated key is safe to delete.

### Tied departure groups

We separately look for flights sharing `Tail_Number`, `FlightDate`, and `CRSDepTime`. This check uses the same cancellation, diversion, and tail-number filters as the preliminary continuity check.

For each group, we compare the origins, destinations, and operating-airline/flight-number combinations. The report also saves every row from the first ten groups, ordered by tail number, date, and scheduled departure time, so we can inspect examples without loading the whole file.

### Clock values

We check `CRSDepTime`, `CRSArrTime`, `DepTime`, and `ArrTime`. A value must be a finite whole number with a valid hour and minute, or the special value `2400`. For example, `0930` is valid, while `1260` is not. Missing values are counted separately. Zero and `2400` are also counted separately.

This checks the format only. It does not assign a date to an arrival, convert a time zone, or prove that two flights happened in the right order.

We also count missing departure/arrival times and delays among flights where both `Cancelled` and `Diverted` are false. That subset does not require a known tail number.

## Results from our 2022 file

### Coverage and missing values

| Check | Result |
|---|---:|
| Missing or blank tail number | 26,795 |
| Cancelled flights | 123,192 |
| Diverted flights | 10,210 |
| Missing departure delay | 120,495 |
| Missing arrival delay | 133,402 |
| Flights that were neither cancelled nor diverted | 3,944,916 |

Within the last subset, `DepTime`, `ArrTime`, `DepDelay`, and `ArrDelay` each had zero missing values. This does not mean those flights pass every other quality check.

### Duplicates and tied times

| Check | Result |
|---|---:|
| Repeated groups across all 61 data fields | 0 |
| Repeated groups using the candidate flight key | 0 |
| Tied tail/date/scheduled-departure groups | 429 |
| Rows in those tied groups | 858 |
| Tied groups with different operating-airline/flight-number combinations | 429 |
| Tied groups with different origins | 385 |
| Tied groups with different destinations | 367 |

The 429 groups are not exact duplicate records. We decided not to remove them just because their scheduled clock values match.

For example, aircraft `N102NN` has these two records on January 4, 2022:

| Flight | Route | Scheduled departure | Actual departure |
|---|---|---|---|
| AA 1 | JFK → LAX | 07:30 | 07:27 |
| AA 28 | LAX → JFK | 07:30 | 11:37 |

These are different flights. BTS reports the times in local time, so matching clock values at different airports do not necessarily mean the same instant. See the [BTS on-time statistics explanation](https://transtats.bts.gov/ONTIME/). We have not established a single cause for all 429 groups.

### Clock-format results

| Field | Missing | Invalid format | Value `2400` |
|---|---:|---:|---:|
| `CRSDepTime` | 0 | 0 | 0 |
| `CRSArrTime` | 0 | 0 | 0 |
| `DepTime` | 120,433 | 0 | 374 |
| `ArrTime` | 124,239 | 0 | 2,135 |

There were no zero values in these four columns. BTS describes `2400` as midnight in its [reporting instructions](https://www.bts.gov/topics/airlines-and-airports/number-31-technical-directive-time-reporting-effective-jan-1-2019). We still need to handle its date correctly when building timestamps.

### Preliminary continuity

The first calculation found 2,954,399 same-day pairs. Of these, 2,923,579 had a matching destination and next origin: about **98.9568%**.

This is a useful starting point, but it is not an accuracy score for reconstructed rotations. There are several unresolved issues:

- Local departure times at different airports are not directly comparable.
- Equal sorting keys do not have a defined tie-break rule in the current calculation.
- Filtering flights before pairing can skip an excluded flight and connect records on either side of it.
- Overnight connections and ground-time feasibility are not checked.
- The scheduled order may differ from the order in which flights actually operated.

Until these are handled, we should not use these pairs as final input for a delay-propagation model. The exact preliminary count may also depend on how tied records are ordered.

## How we checked the code

Run the test with:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The test builds a small table in memory. It includes identical records with different saved indexes, a different flight at the same clock time, a cancelled flight, missing times, midnight values, and invalid values such as `1260`, negative numbers, fractions, infinity, and NaN.

The test passed. We also ran the scripts on the full local file and checked that each clock column's missing, valid, and invalid counts added up to 4,078,318. The input hash matched the earlier audit. These checks cover the current audit logic; they do not validate a timestamp conversion or flight-linking pipeline, since those parts have not been built yet.

## How to continue from this work

Use the same raw file and run the detailed check first. Compare the input hash, date range, and row count before comparing the other numbers. Report timestamps and local input paths can differ between machines.

Keep the raw file unchanged. Any future cleaning rule should be implemented in code and write to a separate output. That way, everyone can reproduce a change instead of passing around manually edited files.

We have now started a small [time-model prototype](TIME_MODEL.md). It checks explicit airport zones, midnight and date changes, and selected flight examples. Full airport coverage and the distinction between actual links and feasible scheduled pairs still need work before we apply it across the dataset.

The later stages now include an [airport lookup](AIRPORT_TIMEZONES.md) and a [full-file timestamp output](FULL_DATA_TIMESTAMPS.md). Flight pairs, final cleaning rules, Spark, buffer analysis, benchmarks, and multi-year ingestion remain to be done.
