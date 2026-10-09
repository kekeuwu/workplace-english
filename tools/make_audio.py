"""產生對話音檔（MP3）。

從 index.html 找出所有對話句（主對話＋延伸小測驗），每個角色用固定的聲音，
存到 audio/ 資料夾，並產生 audio/manifest.js 讓網頁知道哪一句對應哪個檔案。

用法（在專案資料夾執行）：
    pip install edge-tts
    python tools/make_audio.py

檔名是「角色＋英文句子」的雜湊值，所以：
- 句子沒改的音檔會直接沿用，不會重新下載。
- 改了句子，只會產生新的那幾句，舊檔案會被清掉。
"""
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "index.html"
OUT = ROOT / "audio"

VOICES = {
    "Emma": "en-US-AriaNeural",         # 主管，自信的女聲
    "Emily": "en-US-AvaNeural",           # 規劃團隊，親切的女聲
    "Ryan": "en-US-ChristopherNeural",  # 工程師，低沉穩重的男聲
    "Alex": "en-US-BrianNeural",        # 你，年輕隨和的男聲
}
RATE = "-5%"  # 稍微放慢，方便學習
CONCURRENCY = 4

LINE_RE = re.compile(r'\["(Emma|Ryan|Alex|Emily)","((?:[^"\\]|\\.)*)","')


def collect_lines(html: str):
    seen, lines = set(), []
    for who, text in LINE_RE.findall(html):
        text = text.encode().decode("unicode_escape") if "\\" in text else text
        if (who, text) not in seen:
            seen.add((who, text))
            lines.append((who, text))
    return lines


def file_name(who: str, text: str) -> str:
    digest = hashlib.sha1(f"{VOICES[who]}|{RATE}|{text}".encode("utf-8")).hexdigest()[:12]
    return f"{who.lower()}-{digest}.mp3"


async def synth(sem, who, text, path, retries=3):
    async with sem:
        for attempt in range(1, retries + 1):
            try:
                await edge_tts.Communicate(text, VOICES[who], rate=RATE).save(str(path))
                return
            except Exception as e:  # network hiccups: retry a few times
                if attempt == retries:
                    raise RuntimeError(f"{who}: {text!r} failed: {e}") from e
                await asyncio.sleep(2 * attempt)


async def main():
    html = HTML.read_text(encoding="utf-8")
    lines = collect_lines(html)
    OUT.mkdir(exist_ok=True)

    manifest, todo = {}, []
    for who, text in lines:
        name = file_name(who, text)
        manifest[f"{who}|{text}"] = f"audio/{name}"
        if not (OUT / name).exists():
            todo.append((who, text, OUT / name))

    print(f"對話句數：{len(lines)}，需要產生：{len(todo)}")
    sem = asyncio.Semaphore(CONCURRENCY)
    done = 0

    async def run(item):
        nonlocal done
        await synth(sem, *item)
        done += 1
        if done % 20 == 0 or done == len(todo):
            print(f"  {done}/{len(todo)}")

    await asyncio.gather(*(run(t) for t in todo))

    keep = {Path(p).name for p in manifest.values()}
    removed = 0
    for f in OUT.glob("*.mp3"):
        if f.name not in keep:
            f.unlink()
            removed += 1

    (OUT / "manifest.js").write_text(
        "/* 由 tools/make_audio.py 自動產生，請勿手動修改 */\nwindow.AUDIO = "
        + json.dumps(manifest, ensure_ascii=False, indent=0)
        + ";\n",
        encoding="utf-8",
    )
    size = sum(f.stat().st_size for f in OUT.glob("*.mp3")) / 1024 / 1024
    print(f"完成：{len(keep)} 個音檔，共 {size:.1f} MB，清掉舊檔 {removed} 個")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
