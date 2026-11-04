"""Explicit public evaluation downloads; references are never used as ASR prompts.

German neural-network subtitles are labeled DRAFT by the publisher: provisional
reference only, NOT a claimed human-verified benchmark. See manifest and report.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request
import requests

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "tests/fixtures/public-m1"
ITEMS = [
    {"id": "de-open-source-firmware", "language": "de", "title": "Open Source Firmware (35C3)",
     "speaker": "see publisher event credits", "page": "https://media.ccc.de/v/35c3-9778-open_source_firmware",
     "media": "https://cdn.media.ccc.de/congress/2018/mp3/35c3-9778-deu-Open_Source_Firmware_mp3.mp3",
     "reference": "https://media.ccc.de/srt/congress/2018/35c3-9778-deu-eng-Open_Source_Firmware.de.srt",
     "media_file": "de-open-source-firmware.mp3", "reference_file": "de-open-source-firmware.srt",
     "license": "CCC event recording; retain publisher attribution, check event terms before redistribution",
     "reference_quality": "publisher subtitle without DRAFT/todo label; not independently human rechecked in this project"},
    {"id": "en-linear-algebra", "language": "en", "title": "MIT 18.06 Lecture 1: The geometry of linear equations",
     "speaker": "Gilbert Strang", "page": "https://ocw.mit.edu/courses/18-06-linear-algebra-spring-2010/resources/lecture-1-the-geometry-of-linear-equations/",
     "media": "https://archive.org/download/MIT18.06S05_MP4/01.mp4",
     "reference": "https://ocw.mit.edu/courses/18-06-linear-algebra-spring-2010/d292ec07b3ed5124ae1409dc520e61fe_J7DzL2_Na80.vtt",
     "media_file": "en-linear-algebra.mp4", "reference_file": "en-linear-algebra.vtt",
     "license": "MIT OCW CC BY-NC-SA; see publisher terms", "reference_quality": "publisher captions; not independently human rechecked in this project"},
    {"id": "de-neural-networks", "language": "de", "title": "Lass mal das Innere eines Neuronalen Netzes ansehen!",
     "speaker": "Annika Rüll", "page": "https://media.ccc.de/v/37c3-11784-lass_mal_das_innere_eines_neuronalen_netzes_ansehen",
     "media": "https://cdn.media.ccc.de/congress/2023/mp3/37c3-11784-deu-Lass_mal_das_Innere_eines_Neuronalen_Netzes_ansehen_mp3.mp3",
     "reference": "https://media.ccc.de/srt/congress/2023/DRAFT_37c3-11784-deu-eng-Lass_mal_das_Innere_eines_Neuronalen_Netzes_ansehen.de_DRAFT.srt",
     "media_file": "de-neural-networks.mp3", "reference_file": "de-neural-networks.srt",
     "license": "CCC publisher recording; verify event license before redistribution",
     "reference_quality": "publisher DRAFT/todo subtitles: provisional scoring only; NOT human gold"},
]


def fetch(item):
    result = dict(item)
    for kind in ("media", "reference"):
        path = DEST / item[kind + "_file"]
        if not path.exists():
            temporary = path.with_suffix(".part")
            with requests.get(item[kind], timeout=120, stream=True) as response, temporary.open("wb") as out:
                response.raise_for_status()
                for block in response.iter_content(2 * 1024 * 1024):
                    out.write(block)
            temporary.replace(path)
        with path.open("rb") as f:
            result[kind + "_sha256"] = hashlib.file_digest(f, "sha256").hexdigest()
        result[kind + "_bytes"] = path.stat().st_size
    print(json.dumps(result, ensure_ascii=True), flush=True)
    return result


if __name__ == "__main__":
    DEST.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(fetch, ITEMS))
    (DEST / "manifest.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
