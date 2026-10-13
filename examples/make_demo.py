"""Generate synthetic media and a mixed-track manifest; no downloads or real faces."""
import argparse
import json
import subprocess
from pathlib import Path


def make_demo(output, font, ffmpeg="ffmpeg"):
    output, font = Path(output).resolve(), Path(font).resolve()
    if output.exists():
        raise FileExistsError(output)
    if not font.is_file():
        raise FileNotFoundError(font)
    output.mkdir(parents=True)
    def render(source, filename, *options):
        subprocess.run([str(ffmpeg), "-v", "error", "-f", "lavfi", "-i", source, *options, str(output / filename)], check=True)
    render("color=c=0x202938:s=360x640:r=30:d=8", "background.mp4", "-c:v", "libx264", "-pix_fmt", "yuv420p")
    render("testsrc2=s=360x640:r=30:d=2", "unit.mp4", "-c:v", "libx264", "-pix_fmt", "yuv420p")
    render("color=c=yellow@0.7:s=180x180:r=30:d=1,format=rgba", "card.png", "-frames:v", "1")
    render("sine=frequency=440:duration=8", "tone.wav", "-c:a", "pcm_s16le")
    (output / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nNative subtitles\n\n2\n00:00:05,000 --> 00:00:07,000\nEdit this text\n", encoding="utf-8")
    manifest = {"width": 360, "height": 640, "fps": 30, "font": str(font),
        "text_style": {"size": 8, "align": 1}, "tracks": [
        {"name": "Main background", "type": "mixed", "clips": [{"kind": "video", "path": "background.mp4", "start": 0, "end": 8}]},
        {"name": "Text image gap video", "type": "mixed", "clips": [
            {"kind": "text", "text": "Editable title", "start": 0, "end": 2},
            {"kind": "image", "path": "card.png", "start": 2, "end": 4},
            {"kind": "video", "path": "unit.mp4", "start": 5, "end": 7,
             "clip": {"scale_x": 0.7, "scale_y": 0.7},
             "keyframes": [{"property": "position_x", "time": 0, "value": -0.2}, {"property": "position_x", "time": 0.3, "value": 0}]}]},
        {"name": "Removable empty overlay", "type": "mixed", "clips": []},
        {"name": "Captions", "type": "mixed", "srt": "captions.srt", "clips": []},
        {"name": "Synthetic audio", "type": "audio", "clips": [{"kind": "audio", "path": "tone.wav", "start": 0, "end": 8, "volume": 0.05}]}]}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return output / "manifest.json"


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--font", type=Path, required=True)
    p.add_argument("--ffmpeg", default="ffmpeg")
    a = p.parse_args()
    print(make_demo(a.output, a.font, a.ffmpeg))
