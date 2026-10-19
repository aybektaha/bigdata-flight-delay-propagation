# Distributed Analysis of Aircraft Turnaround Buffers and Reactionary Delay Propagation

[![Course](https://img.shields.io/badge/Course-YZV411E%20Big%20Data%20Analytics-blue.svg)](https://itu.edu.tr)
[![Engine](https://img.shields.io/badge/Engine-Apache%20Spark%20%2F%20PySpark-orange.svg)](https://spark.apache.org/)
[![Storage](https://img.shields.io/badge/Format-Apache%20Parquet-green.svg)](https://parquet.apache.org/)
[![Dataset](https://img.shields.io/badge/Dataset-BTS%20Flight%20Delays%20(2018--2022)-red.svg)](https://www.kaggle.com/datasets/robikscube/flight-delay-dataset-20182022)

An end-to-end Big Data project investigating how flight disruptions propagate across multi-leg aircraft itineraries and hub networks in the United States airspace. Rather than framing flight delays as an isolated classification task, this study tracks unique airframes (`Tail_Number`) across ~31.7 million flights to model turnaround buffer absorption and reactionary delays at scale.

---

## 1. Motivation and Research Questions

In commercial aviation, an aircraft rarely flies an isolated route; it executes a chained sequence of flights across multiple hubs each day. When leg $k$ incurs a primary delay (due to weather, ATC restrictions, or mechanical maintenance), this disruption affects leg $k+1$ unless absorbed by the scheduled ground turnaround buffer.

Traditional academic approaches suffer from a pronounced bifurcation:
1. **Machine Learning studies** frequently treat flights as independent rows (i.i.d.), training classifiers to predict 15-minute delays while ignoring aircraft rotation dependencies.
2. **Operations Research (OR) and Network Theory models** simulate delay propagation trees, but rely on single-machine solvers that cannot scale beyond small subsets or single-day timeframes.

### Core Research Questions
* **Buffer Thresholds:** What is the critical scheduled turnaround buffer ($B_{sched}$) required at major hubs to absorb incoming delays with high statistical confidence?
* **Hub Resilience Taxonomy:** Which hub airports act as systemic *delay absorbers* versus *delay amplifiers* across different hours and seasons?
* **Reactionary Multipliers:** What is the decay rate of primary delay minutes across consecutive flight legs throughout an airframe's daily itinerary?

---

## 2. Big Data Rationale & Computational Architecture

* **Data Volume:** 5 years of U.S. Bureau of Transportation Statistics (BTS) records (2018–2022), spanning **~31.7 million records** and **~9.8 GB** uncompressed CSV (~1.06 GB compressed Parquet).
* **Distributed Windowing:** Reconstructing flight itineraries requires a stateful, distributed window operation partitioned by unique airframe and ordered chronologically:
  ```python
  from pyspark.sql.window import Window
  import pyspark.sql.functions as F

  aircraft_window = Window.partitionBy("Tail_Number").orderBy("FlightDate", "CRSDepTime")
  ```
* **Memory & Shuffle Scaling:** Attempting this global window operation on 31.7 million records in a single-machine Pandas environment triggers severe Out-Of-Memory (OOM) failures or swap thrashing. PySpark distributes hash partitions across worker cores, leverages disk spill mechanisms, and uses Catalyst query optimization for partition pruning.

---

## 3. Mathematical & Operational Formulations

For an aircraft with registration `Tail_Number` operating consecutive legs $k \rightarrow k+1$ on date $t$:

1. **Scheduled Turnaround Buffer ($B_{sched}$):**
   $$B_{sched} = \text{CRSDepTime}_{k+1} - \text{CRSArrTime}_k$$
2. **Actual Turnaround Time ($T_{act}$):**
   $$T_{act} = \text{DepTime}_{k+1} - \text{ArrTime}_k$$
3. **Net Delay Variation ($\Delta D$):**
   $$\Delta D = \text{DepDelay}_{k+1} - \text{ArrDelay}_k$$
   * If $\Delta D \le 0$: The ground buffer **absorbed** the incoming disruption.
   * If $\Delta D > 0$: The turnaround **amplified** the disruption (e.g., gate congestion, slow baggage transfer, crew unavailability).
4. **Reactionary Multiplier ($R_0$):**
   The expected downstream delay minutes generated per minute of initial root-cause disruption:
   $$R_0 = \frac{\sum_{j=1}^{M} \text{DepDelay}_{k+j}}{\text{PrimaryDelay}_k}$$

---

## 4. Repository Structure

```
├── data/
│   ├── raw/             # Raw BTS CSV/Parquet files (gitignored)
│   └── processed/       # Curated Parquet tables partitioned by Year/Month
├── docs/                # Project documentation & literature notes
├── notebooks/           # Exploratory data analysis & sample verification
├── proposal/            # LaTeX project proposal files
│   └── proposal.tex
├── src/                 # PySpark modular ETL & analysis pipeline
│   ├── __init__.py
│   ├── ingestion.py     # Schema validation & Parquet conversion
│   ├── sequence.py      # Aircraft windowing & consecutive leg pairing
│   └── benchmark.py     # Spark vs. Single-Node baseline benchmarking
├── .gitignore
├── proposal.tex         # Root course template copy
└── README.md
```

---

## 5. Dataset Ingestion

The dataset is hosted on Kaggle: [Flight Delay Dataset 2018–2022](https://www.kaggle.com/datasets/robikscube/flight-delay-dataset-20182022).

### Option A: Kaggle CLI
Ensure `~/.kaggle/kaggle.json` is configured, then run:
```bash
kaggle datasets download -d robikscube/flight-delay-dataset-20182022 -p data/raw --unzip
```

### Option B: Direct Parquet Download
For rapid ingestion and testing, download the Parquet distribution (~1.06 GB total across 5 files), which retains the full 61-column BTS schema with significant I/O savings.

---

## 6. Project Roadmap

- [x] Research problem framing & literature gap definition
- [x] Course LaTeX proposal (`proposal.tex`) authoring
- [x] Git repository initialization and baseline structure
- [ ] Ingestion script: Parquet schema validation & missingness audit
- [ ] PySpark sequence linking pipeline (`Tail_Number` windowing)
- [ ] Single-machine (Pandas) vs. PySpark benchmark suite
- [ ] Hub resilience taxonomy & interactive visualizations
