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
