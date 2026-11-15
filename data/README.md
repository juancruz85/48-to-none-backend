# External data staging

The Kaggle [Simulated Transactions dataset](https://www.kaggle.com/datasets/conorsully1/simulated-transactions) is a 22.3 GB synthetic expenditure dataset. Its published schema includes customer IDs, dates, expenditure categories, and amounts. It has no verified fraud labels, so it cannot establish fraud detection accuracy.

Download the pinned version into `data/external/simulated-transactions/transactions.csv` with the guarded downloader:

```powershell
python scripts/download_simulated_transactions.py
```

It checks available disk space, expected archive and CSV sizes, ZIP integrity, and CSV headers. It uses temporary files and publishes the final CSV only after validation. The raw folder is Git-ignored and outside `purchase_data/`, which the running application loads as input. Do not move the raw file into `purchase_data/`.

Prepare a bounded sample in a separate, ignored staging folder:

```powershell
python scripts/prepare_simulated_transactions.py --customers 1 --rows-per-customer 10 --output data/staging/simulated-transactions-ten
```

The script streams a bounded prefix of the source (Kaggle v1 groups rows by customer), writes up to five separate customer sheets using the app's `Date, Description, Amount` columns, converts the positive expenditure amounts to negative bank-export outflows (the app normalizes them back to positive spending), hashes customer IDs in filenames, and records a source hash and sampling limits in `manifest.json`. The sample is not a fraud benchmark. The source file itself is about 22 GB, but sample memory stays bounded.

To feed those isolated sheets through the program's normal pipeline, run:

```powershell
python -m src.main --data-dir data/staging/simulated-transactions
```

This runs the normal analysis/model flow over the staged customer sheet. It loads the local model, which may use several GB of RAM. Keep the sample small to limit CPU inference time. The default app command still reads only `purchase_data/`. The converter refuses to overwrite a non-empty staging folder; choose a new ignored output folder for a fresh sample.

The analysis result includes a versioned per-sheet baseline summary: overall and monthly median/MAD spend, median transaction spacing, plus per-description count, median/MAD, 95th percentile, and median spacing. The transaction shortlist now scores each purchase against earlier purchases of the same description only. Amount scoring starts after 3 earlier purchases and flags values above the prior median plus the larger of 3 scaled MADs or 50% of the median. Exact repeated charges and high same-day activity use earlier same-day rows only. A new description or unseen price alone is no longer suspicious. These are starter heuristics, not calibrated fraud thresholds; the model receives the prior-only stats for each candidate. The full-history summary marks overall readiness after 10 paid transactions but does not leak future rows into historical candidate scoring.

## Multi-account profile experiment

`scripts/profile_model_experiment.py --prepare` creates eight seeded scenarios with three account CSVs per scenario and a separate hidden-label manifest: two clean controls, two all-fraud controls, and four scenarios with one randomly selected fraudulent account. The theoretical profile has two Personal accounts and one Cleaning business account. Generated files are Git-ignored.

After reviewing the generated scenarios and ensuring at least 8.5 GiB of free RAM, run `python scripts/profile_model_experiment.py --run-model`. It evaluates the three accounts through the current backend one scenario at a time and writes the prediction table to ignored `logs/profile-model-experiment.json`. Labels are stored in the manifest, outside the CSV input folders, and are not sent to the model.

## Fraud Dataset Benchmark: credit-card sample

FDB dataset #2 (`mlg-ulb/creditcardfraud`) is the best first rights-cleared candidate: the benchmark lists an Open Database Contents License and describes 284,807 anonymized rows with `Time`, `Amount`, PCA features, and `Class`. It has no merchant or account ID, so it cannot validate personal-history behavior. Dataset #1 requires joining a Kaggle competition; dataset #3 has no source license listed by FDB. See [the benchmark's dataset table and source notes](https://github.com/amazon-science/fraud-dataset-benchmark).

To download the public 151 MB archive and create a reproducible 100-per-class sample outside the app's live input folder, run:

```powershell
python scripts/prepare_fdb_creditcard.py
```

The downloader caps the archive at 300 MiB, uses a temporary file, verifies the ZIP CRC and source schema, and refuses to overwrite staged files. The app-format CSV is `data/staging/fdb-creditcardfraud/balanced_sample.csv`; class labels are separate in `labels.json`. The adapter omits PCA features and synthesizes an anchor date from the source's relative seconds. A preflight marked 192/200 rows as heuristic candidates, including 99 normal examples, so this sample is retained for ingestion inspection and should not be sent to the LLM.

## Fraud Dataset Benchmark: Sparkov sample

FDB dataset #4 is synthetic card data with merchant, category, amount, date, and fraud labels; FDB lists CC0 as its source license. The records include customer card numbers and names, so the adapter strips those fields, removes the `fraud_` merchant prefix, and keeps fraud labels in a separate manifest. See [the FDB source description](https://github.com/amazon-science/fraud-dataset-benchmark#data-sources).

Download version 1 and stage two labeled fraud targets plus one clean control:

```powershell
python scripts/prepare_fdb_sparkov.py
```

The archive is capped at 400 MiB, downloaded to a temporary file, and CRC checked. Each staged account CSV contains 25 earlier, source-labeled-clean transactions followed by one held-out test target; labels are in `evaluation_labels.json`, never in the CSV. Files are under ignored `data/staging/fdb-sparkov/`, outside `purchase_data/`.

In a seeded search over 30 eligible fraud-target accounts, none of the target rows entered the app's heuristic shortlist. Under the current conservative shortlist rules, those targets receive no model verdict. A separate single clean account was run through the normal app pipeline one at a time: the heuristic shortlisted six historically normal purchases, and the LLM flagged five. This is a small synthetic smoke test, not a fraud-accuracy estimate. The captured console output is in ignored `logs/fdb-sparkov-clean.out`.
