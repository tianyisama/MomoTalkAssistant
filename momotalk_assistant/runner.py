from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import hashlib
import json
import threading
import time

import cv2
import numpy as np

from .adb import AdbClient, AdbError, is_game_package
from .models import Action, Observation, Scene
from .paths import data_dir
from .planner import Planner
from .options import RunOptions
from .servers import template_profile
from .vision import Detector, Frame, annotate, write_image


class StabilityGate:
    def __init__(self, frames: int = 2):
        self.required = frames
        self.reset()

    def reset(self):
        self.key = ""
        self.point = None
        self.count = 0

    def accept(self, action: Action | None) -> bool:
        if not action or not action.target:
            self.reset()
            return False
        point = action.target.box.center
        if self.key == action.key and self.point and max(abs(a-b) for a, b in zip(self.point, point)) <= 6:
            self.count += 1
        else:
            self.count = 1
        self.key, self.point = action.key, point
        return self.count >= self.required


class Runner:
    def __init__(self, client: AdbClient, emit, stop: threading.Event,
                 preview_only: bool = False, detector: Detector | None = None,
                 options: RunOptions | None = None):
        self.client = client
        self.client.stop = stop
        self.expected_package=client.binding.package if client.binding else None
        self.emit = emit
        self.stop = stop
        self.preview_only = preview_only
        profile=template_profile(client.binding.package) if client.binding else None
        self.detector = detector or Detector(profile=profile or "jp")
        self.options = options or RunOptions()
        self.planner = Planner(options=self.options)
        self.gate = StabilityGate()
        self.last_frame: Frame | None = None
        self.last_obs = Observation()
        self.last_message = ""
        self.log_path: Path | None = None
        self.log_file = None

    def log(self, message: str, **details):
        stamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        if self.log_file:
            self.log_file.write(json.dumps({"time": stamp, "message": message, **details}, ensure_ascii=False)+"\n")
            self.log_file.flush()
        self.emit({"kind": "log", "message": message})

    def save_failure(self) -> str:
        if self.last_frame:
            path = data_dir()/"captures"/f"stopped_{datetime.now():%Y%m%d_%H%M%S}.png"
            write_image(path, annotate(self.last_frame, self.last_obs))
            return str(path)
        return ""

    def run(self):
        logs = data_dir()/"logs"
        logs.mkdir(parents=True, exist_ok=True)
        self.log_path = logs/f"run_{datetime.now():%Y%m%d_%H%M%S_%f}.jsonl"
        outcome, message = "stopped", "已停止"
        try:
            with self.log_path.open("w", encoding="utf-8") as self.log_file:
                self.log("仅预览模式，不会发送触控。" if self.preview_only else "开始运行：先确认未读排序并刷新列表。")
                last_action_at = 0.
                last_action_signature = ""
                attempts = 0
                recognized_at = time.monotonic()
                last_interaction = recognized_at
                paused_at = None
                while not self.stop.is_set():
                    started = time.monotonic()
                    if self.preview_only and self.client.binding is not None:
                        image=self.client.screenshot()
                        frame=Frame.from_image(image)
                        obs=self.detector.observe(frame)
                        self.last_frame,self.last_obs=frame,obs
                        self.emit({"kind":"frame","image":annotate(frame,obs),"scene":str(obs.scene),
                                   "status":f"仅预览 · {self.client.binding.label}","resolution":frame.original_size,
                                   "stats":asdict(self.planner.stats)})
                        self.stop.wait(max(.15,.65-(time.monotonic()-started)))
                        continue
                    package = self.client.foreground_package()
                    if self.expected_package is None and is_game_package(package): self.expected_package=package
                    if not is_game_package(package) or package!=self.expected_package:
                        self.gate.reset()
                        if paused_at is None:
                            paused_at = started
                            self.log("所选画面已不是原来的游戏应用，已暂停触控。", package=package)
                        self.emit({"kind": "status", "message": "请回到所选游戏画面，或停止后重新选择应用", "stats": asdict(self.planner.stats)})
                        self.stop.wait(1)
                        continue
                    if paused_at is not None:
                        # Device-app changes invalidate all unconfirmed targets.
                        previous_stats = self.planner.stats
                        self.planner = Planner(options=self.options)
                        self.planner.stats = previous_stats
                        paused_at = None
                        recognized_at = started
                        last_interaction = started
                        last_action_signature = ""
                        attempts = 0
                        self.log("已回到游戏，重新确认未读排序。")
                    image = self.client.screenshot()
                    frame = Frame.from_image(image)
                    obs = self.detector.observe(frame)
                    self.last_frame, self.last_obs = frame, obs
                    now = time.monotonic()
                    if obs.scene != Scene.UNKNOWN:
                        recognized_at = now
                    elif now-recognized_at > 90:
                        raise RuntimeError("连续 90 秒未识别到可确认的界面，已停止。")
                    action = self.planner.propose(obs, now)
                    if not self.preview_only and not self.planner.in_chat and now-last_interaction > 90:
                        raise RuntimeError("连续 90 秒未能完成下一步操作，已停止；请检查当前界面。")
                    status = self.planner.status
                    if action:
                        if action.kind in ("done", "error"):
                            if self.preview_only:
                                status = "仅预览："+action.message
                                action = None
                            else:
                                outcome = "done" if action.kind == "done" else "error"
                                message = action.message
                                if outcome == "error": self.log(message, capture=self.save_failure())
                                else: self.log(message)
                                break
                        elif self.preview_only:
                            status = "仅预览：将"+action.message
                        else:
                            status = action.message
                    self.emit({"kind": "frame", "image": annotate(frame, obs, action.key if action else None),
                               "scene": str(obs.scene), "status": status,
                               "resolution": frame.original_size, "stats": asdict(self.planner.stats)})
                    if action and action.target and self.gate.accept(action) and not self.preview_only and now-last_action_at >= 1:
                        # Check the Android foreground again immediately before
                        # a touch. Windows focus and cursor position are unused.
                        if not is_game_package(self.client.foreground_package()):
                            self.gate.reset()
                            continue
                        if self.stop.is_set(): break
                        crop = action.target.box.crop(cv2.cvtColor(frame.image, cv2.COLOR_BGR2GRAY))
                        small = cv2.resize(crop, (16, 8))
                        signature = action.key+hashlib.sha1((small > small.mean()).tobytes()).hexdigest()
                        attempts = attempts+1 if signature == last_action_signature else 1
                        if attempts > 4:
                            raise RuntimeError(f"“{action.message}”重试四次仍未确认界面变化，已停止。")
                        last_action_signature = signature
                        point = frame.device_point(action.target.box.center)
                        if action.kind == "swipe":
                            assert action.end is not None
                            self.client.swipe(point, frame.device_point(action.end))
                        else:
                            self.client.tap(point)
                        self.planner.committed(action, obs, now)
                        self.log(action.message, action=action.key, point=point,
                                 confidence=round(action.target.confidence, 4), scene=str(obs.scene))
                        last_action_at = time.monotonic()
                        last_interaction = last_action_at
                        recognized_at = last_action_at
                        self.gate.reset()
                    elif not action:
                        self.gate.reset()
                    self.stop.wait(max(.15, .65-(time.monotonic()-started)))
                if self.stop.is_set():
                    self.log("已停止，不再发送触控。")
        except InterruptedError:
            outcome, message = "stopped", "已停止，不再发送触控。"
        except (AdbError, RuntimeError, ValueError, OSError) as exc:
            outcome, message = "error", str(exc)
            capture = self.save_failure()
            self.emit({"kind": "log", "message": message+(f"\n截图：{capture}" if capture else "")})
        except Exception as exc:
            outcome, message = "error", f"运行异常：{type(exc).__name__}: {exc}"
            self.save_failure()
        finally:
            self.emit({"kind": "finished", "outcome": outcome, "message": message,
                       "stats": asdict(self.planner.stats), "log_path": str(self.log_path or "")})
