"""Download fixed NVIDIA redistributables, verify SHA256, extract inside project.

No driver changes, no global PATH changes. Run explicitly; never run by ASR startup.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = [
    ("https://developer.download.nvidia.com/compute/cuda/redist/", "redistrib_12.4.1.json", "libcublas", None),
    ("https://developer.download.nvidia.com/compute/cuda/redist/", "redistrib_12.4.1.json", "cuda_cudart", None),
    ("https://developer.download.nvidia.com/compute/cudnn/redist/", "redistrib_9.1.0.json", "cudnn", "cuda12"),
]


def install(spec):
    base, manifest, key, variant = spec
    data = json.load(urllib.request.urlopen(base + manifest, timeout=60))
    entry = data[key]["windows-x86_64"]
    if variant:
        entry = entry[variant]
    cache = ROOT / "tools/downloads"
    cache.mkdir(exist_ok=True)
    archive = cache / Path(entry["relative_path"]).name
    if not archive.exists():
        temporary = archive.with_suffix(".part")
        with urllib.request.urlopen(base + entry["relative_path"], timeout=120) as response, temporary.open("wb") as out:
            while block := response.read(4 * 1024 * 1024):
                out.write(block)
        temporary.replace(archive)
    digest = hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()
    if digest != entry["sha256"]:
        raise RuntimeError(f"SHA256 mismatch: {archive}")
    destination = ROOT / "tools/gpu-runtime"
    destination.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            resolved = (destination / info.filename).resolve()
            if not resolved.is_relative_to(destination.resolve()):
                raise RuntimeError("unsafe archive path")
        z.extractall(destination)
    result = {"component": key, "version": data[key]["version"], **entry, "verified_sha256": digest}
    print(json.dumps(result), flush=True)
    return result


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(install, PACKAGES))
    (ROOT / "tools/gpu-runtime/manifest.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
