"""Keep the already-installed unpacked extension path on the current version."""
from pathlib import Path
import shutil
import json

ROOT=Path(__file__).resolve().parents[1]


def sync():
    source=ROOT/'app/web_follow/extension';target=ROOT/'experiments/lookahead/extension'
    catalogue=json.loads((ROOT/'app/locales/en.json').read_text(encoding='utf-8'))
    runtime=(ROOT/'app/web_follow/web/locale-runtime.js').read_text(encoding='utf-8')
    bundle='globalThis.__ELT_ENGLISH_UI='+json.dumps(catalogue,ensure_ascii=False,separators=(',',':'))+';\n'+runtime
    (source/'ui-locale.js').write_text(bundle,encoding='utf-8')
    (ROOT/'app/web_follow/web/ui-locale.js').write_text(bundle,encoding='utf-8')
    target.mkdir(parents=True,exist_ok=True)
    for path in source.iterdir():
        if path.is_file() and path.suffix in ('.js','.json','.html','.css','.md','.png','.svg'):shutil.copy2(path,target/path.name)


if __name__=='__main__':sync()
