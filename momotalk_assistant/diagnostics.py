from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from pathlib import Path
import json
import threading

import cv2
from PIL import Image, ImageDraw, ImageFont

from .vision import Detector, AutoDetector, Frame, annotate, read_image, write_image


def inspect_image(path: Path, detector: Detector | None = None):
    detector = detector or AutoDetector()
    frame = Frame.from_image(read_image(path))
    observation = detector.observe(frame)
    return frame, observation


def analyze_video(path: Path, output_dir: Path, emit=lambda event: None,
                  stop: threading.Event | None = None, interval: float = .5) -> dict:
    stop = stop or threading.Event()
    output_dir.mkdir(parents=True, exist_ok=True)
    # VideoCapture accepts Unicode paths in current OpenCV Windows builds.
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened(): raise ValueError("无法打开录屏文件。")
    detector = AutoDetector()
    fps = capture.get(cv2.CAP_PROP_FPS) or 30
    total = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = total/fps
    records, samples, counts = [], [], Counter()
    try:
        timestamp = 0.
        while timestamp < duration and not stop.is_set():
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp*1000)
            ok, raw = capture.read()
            if not ok: break
            frame = Frame.from_image(raw)
            obs = detector.observe(frame)
            counts[str(obs.scene)] += 1
            record = {"seconds": round(timestamp, 2), "scene": str(obs.scene),
                      "targets": {k:{"box":v.box.as_list(), "confidence":round(v.confidence,4)}
                                  for k,v in obs.targets.items()}, "meta":obs.meta}
            records.append(record)
            annotated = annotate(frame, obs)
            if not samples or samples[-1][1] != str(obs.scene) or timestamp-samples[-1][0] >= 5:
                samples.append((timestamp, str(obs.scene), annotated))
            emit({"kind":"frame", "image":annotated, "scene":str(obs.scene),
                  "status":f"录屏识别 · {timestamp:.1f} / {duration:.1f} 秒 · 不发送触控",
                  "resolution":frame.original_size, "stats":{}})
            timestamp += interval
    finally:
        capture.release()
    summary = {"file":path.name, "duration":round(duration,2), "samples":len(records),
               "scenes":dict(counts), "touches_sent":0, "stopped":stop.is_set(), "frames":records}
    (output_dir/"report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if samples:
        width, height = 640, 384
        sheet = Image.new("RGB", (width*2, height*((len(samples)+1)//2)), "#172333")
        draw = ImageDraw.Draw(sheet)
        try: font=ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 15)
        except OSError: font=ImageFont.load_default()
        for i,(stamp,scene,image) in enumerate(samples):
            x,y=i%2*width,i//2*height
            picture=Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
            picture.thumbnail((640,360))
            draw.text((x+8,y+3),f"{stamp:.1f}s  {scene}",font=font,fill="white")
            sheet.paste(picture,(x,y+24))
        sheet.save(output_dir/"overview.jpg", quality=90)
    return summary
