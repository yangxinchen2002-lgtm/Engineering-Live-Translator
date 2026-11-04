"""Explicit one-time download. Local audio is never uploaded."""
from pathlib import Path
import os
import json
ROOT = Path(__file__).resolve().parents[1]
os.environ["HF_HOME"] = str(ROOT / "models/hf-cache")
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_XET"] = "1"

if __name__ == "__main__":
    from huggingface_hub import snapshot_download
    repo = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
    revision = "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
    path = ROOT / "models/large-v3-turbo"
    snapshot_download(repo, revision=revision, local_dir=path,
                      allow_patterns=["config.json", "model.bin", "tokenizer.json", "preprocessor_config.json", "vocabulary.*", "README.md"])
    (path / "elt-source.json").write_text(json.dumps({"repo": repo, "revision": revision}, indent=2), encoding="utf-8")
    print(path)
