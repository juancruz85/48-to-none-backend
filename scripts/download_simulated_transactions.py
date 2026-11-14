"""Safely download Kaggle v1 and atomically publish only transactions.csv."""

import shutil
import urllib.request
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEST_DIR = PROJECT_ROOT / "data" / "external" / "simulated-transactions"
DEST_FILE = DEST_DIR / "transactions.csv"
URL = "https://www.kaggle.com/api/v1/datasets/download/conorsully1/simulated-transactions?datasetVersionNumber=1"
EXPECTED_ZIP_BYTES = 5_725_992_721  # Confirmed by Kaggle's range response before downloading.
EXPECTED_CSV_BYTES = 22_285_422_463  # Kaggle v1 metadata.
RESERVE_BYTES = 30 * 1024**3
CHUNK_BYTES = 1024**2


def free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def require_space(path: Path, needed: int, stage: str) -> None:
    available = free_bytes(path)
    if available < needed + RESERVE_BYTES:
        raise OSError(
            f"insufficient free space during {stage}: {available / 1024**3:.1f} GiB free; "
            f"need {needed / 1024**3:.1f} GiB plus a 30 GiB reserve"
        )


def download() -> Path:
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    if DEST_FILE.exists():
        raise FileExistsError(f"refusing to overwrite existing file: {DEST_FILE}")
    archive = DEST_DIR / ".transactions.zip.part"
    extracted = DEST_DIR / ".transactions.csv.part"
    for partial in (archive, extracted):
        if partial.exists():
            raise FileExistsError(f"partial file already exists; inspect or remove it before retrying: {partial}")

    require_space(DEST_DIR, EXPECTED_ZIP_BYTES + EXPECTED_CSV_BYTES, "preflight")
    try:
        request = urllib.request.Request(URL, headers={"User-Agent": "48-to-none dataset importer"})
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.status != 200:
                raise OSError(f"Kaggle returned HTTP {response.status}, expected 200")
            if response.headers.get_content_type() != "application/zip":
                raise OSError(f"Kaggle returned unexpected content type: {response.headers.get_content_type()}")
            declared = response.headers.get("Content-Length")
            if declared is None or int(declared) != EXPECTED_ZIP_BYTES:
                raise OSError(f"unexpected archive size header: {declared!r}")
            received = 0
            with archive.open("xb") as output:
                while block := response.read(CHUNK_BYTES):
                    require_space(DEST_DIR, EXPECTED_CSV_BYTES + EXPECTED_ZIP_BYTES - received, "download")
                    output.write(block)
                    received += len(block)
                    if received % (256 * 1024**2) < CHUNK_BYTES:
                        print(f"Downloaded {received / 1024**3:.2f} / {EXPECTED_ZIP_BYTES / 1024**3:.2f} GiB", flush=True)
        if received != EXPECTED_ZIP_BYTES:
            raise OSError(f"download ended at {received} bytes; expected {EXPECTED_ZIP_BYTES}")

        print("Checking ZIP integrity and expected CSV entry...", flush=True)
        with zipfile.ZipFile(archive) as bundle:
            matches = [item for item in bundle.infolist() if Path(item.filename).name == "transactions.csv"]
            if len(matches) != 1 or matches[0].file_size != EXPECTED_CSV_BYTES:
                raise OSError("archive does not contain exactly one expected-size transactions.csv")
            bad_member = bundle.testzip()
            if bad_member is not None:
                raise OSError(f"ZIP CRC check failed for {bad_member}")
            require_space(DEST_DIR, EXPECTED_CSV_BYTES, "extraction")
            with bundle.open(matches[0]) as source, extracted.open("xb") as output:
                written = 0
                while block := source.read(CHUNK_BYTES):
                    require_space(DEST_DIR, EXPECTED_CSV_BYTES - written, "extraction")
                    output.write(block)
                    written += len(block)
                    if written % (1024**3) < CHUNK_BYTES:
                        print(f"Extracted {written / 1024**3:.1f} / {EXPECTED_CSV_BYTES / 1024**3:.1f} GiB", flush=True)
        if written != EXPECTED_CSV_BYTES:
            raise OSError(f"extracted {written} bytes; expected {EXPECTED_CSV_BYTES}")

        with extracted.open("r", encoding="utf-8-sig", newline="") as check:
            header = check.readline().strip().split(",")
            expected = {"CUST_ID", "DATE", "EXP_TYPE", "AMOUNT"}
            if not expected.issubset(header):
                raise OSError(f"CSV header is missing expected columns: {sorted(expected - set(header))}")
        extracted.replace(DEST_FILE)
        archive.unlink()
        return DEST_FILE
    except Exception:
        for partial in (archive, extracted):
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
        raise


if __name__ == "__main__":
    path = download()
    print(f"Verified dataset saved to {path}")
