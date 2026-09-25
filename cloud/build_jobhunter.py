"""Build do JobHunter Cloud v1.1. Não realiza deploy."""
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "cloud" / "jobhunter"
DIST = ROOT / "cloud" / "dist"


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def build(python=sys.executable):
    required = [
        SOURCE / "lambda_function.py",
        SOURCE / "worker.py",
        SOURCE / "requirements.txt",
    ]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)

    DIST.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="jobhunter-cloud-v1-1-") as temp:
        package = Path(temp) / "package"
        package.mkdir()

        subprocess.run([
            python, "-m", "pip", "install",
            "--disable-pip-version-check", "--no-input",
            "--platform", "manylinux2014_x86_64",
            "--python-version", "3.13",
            "--implementation", "cp",
            "--only-binary=:all:",
            "--target", str(package),
            "-r", str(SOURCE / "requirements.txt"),
        ], check=True)

        provisional = DIST / "jobhunter_cloud_v1_1.zip"
        with zipfile.ZipFile(provisional, "w", zipfile.ZIP_DEFLATED) as z:
            for path in sorted(package.rglob("*")):
                if (
                    path.is_file()
                    and "__pycache__" not in path.parts
                    and path.suffix != ".pyc"
                ):
                    z.write(path, path.relative_to(package).as_posix())
            z.write(SOURCE / "lambda_function.py", "lambda_function.py")
            z.write(SOURCE / "worker.py", "worker.py")

        digest = sha256(provisional)
        final = DIST / f"jobhunter_cloud_v1_1_{digest[:12]}.zip"
        provisional.replace(final)

    with zipfile.ZipFile(final) as z:
        if z.testzip():
            raise RuntimeError("ZIP inválido.")
        if not {"lambda_function.py", "worker.py"}.issubset(z.namelist()):
            raise RuntimeError("ZIP incompleto.")

    manifest = {
        "version": "1.1",
        "runtime": "python3.13",
        "architecture": "x86_64",
        "file": str(final),
        "s3_key": f"cloud/packages/jobhunter/{final.name}",
        "sha256": digest,
        "size_mb": round(final.stat().st_size / 1024 / 1024, 2),
    }
    (DIST / "jobhunter_build.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    print(json.dumps(manifest, indent=2))
    print("Nenhum deploy, Gemini, Telegram, banco ou recurso existente foi alterado.")
    return final


if __name__ == "__main__":
    build()
