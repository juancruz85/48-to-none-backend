"""Build a small AWS Lambda ZIP for the profile API handler."""

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "src"
REQUIREMENTS = ROOT / "lambda-requirements.txt"
OUTPUT = ROOT / "dist" / "profile-lambda.zip"
MODULES = (
    "profile_handler.py",
    "profile_repository.py",
    "profiles.py",
)


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="profile-lambda-") as temp_dir:
        staging = Path(temp_dir)
        package_src = staging / "src"
        package_src.mkdir()
        (package_src / "__init__.py").write_text(
            '"""Profile API Lambda package."""\n', encoding="utf-8"
        )

        for module in MODULES:
            source = SOURCE_DIR / module
            if not source.is_file():
                raise FileNotFoundError(f"Required Lambda module is missing: {source}")
            shutil.copy2(source, package_src / module)

        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--requirement",
                str(REQUIREMENTS),
                "--target",
                str(staging),
            ],
            check=True,
        )

        temp_zip = OUTPUT.with_suffix(".zip.tmp")
        try:
            with zipfile.ZipFile(
                temp_zip, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for path in staging.rglob("*"):
                    if path.is_file() and "__pycache__" not in path.parts:
                        archive.write(path, path.relative_to(staging).as_posix())

            with zipfile.ZipFile(temp_zip) as archive:
                bad_entry = archive.testzip()
                if bad_entry:
                    raise RuntimeError(f"Corrupt ZIP entry: {bad_entry}")
                required_entries = {
                    "src/__init__.py",
                    "src/profile_handler.py",
                    "src/profile_repository.py",
                    "src/profiles.py",
                }
                missing = required_entries.difference(archive.namelist())
                if missing:
                    raise RuntimeError(
                        "Lambda package is missing: " + ", ".join(sorted(missing))
                    )

            temp_zip.replace(OUTPUT)
        finally:
            if temp_zip.exists():
                temp_zip.unlink()

    print(f"Created {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")
    print("Lambda handler: src.profile_handler.handler")


if __name__ == "__main__":
    main()
