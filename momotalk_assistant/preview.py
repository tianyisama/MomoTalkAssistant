from __future__ import annotations

from dataclasses import dataclass
import threading

from .adb import AdbClient, AdbError, select_display
from .vision import Detector, Frame, annotate
from .servers import server_for,template_profile


@dataclass(frozen=True)
class PreviewRequest:
    generation: int
    serial: str
    adb_path: str
    display_id: int | None = None
    fallback_to_desktop: bool = False


class PreviewService:
    """One read-only worker; rapid device changes replace pending requests.

    Results carry their device and generation so a late screenshot can never
    appear as the preview of a subsequently selected device.
    """
    def __init__(self, emit, loader=None):
        self.emit = emit
        self.loader = loader or self._capture
        self._condition = threading.Condition()
        self._generation = 0
        self._pending = None
        self._closed = False
        self._thread = None
        self._detectors = {}

    def request(self, serial: str, adb_path: str = "", display_id: int | None = None,
                *,fallback_to_desktop: bool = False) -> int:
        with self._condition:
            if self._closed: return self._generation
            self._generation += 1
            self._pending = PreviewRequest(self._generation, serial, adb_path,display_id,fallback_to_desktop)
            if self._thread is None:
                self._thread = threading.Thread(target=self._work, daemon=True)
                self._thread.start()
            self._condition.notify()
            return self._generation

    def invalidate(self):
        with self._condition:
            self._generation += 1
            self._pending = None

    def is_current(self, generation: int) -> bool:
        with self._condition:
            return not self._closed and generation == self._generation

    def close(self):
        with self._condition:
            self._closed = True
            self._pending = None
            self._condition.notify()

    def _work(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda:self._pending is not None or self._closed)
                if self._closed: return
                request, self._pending = self._pending, None
            try:
                event = {"kind":"device_preview", **self.loader(request)}
            except Exception as exc:
                event = {"kind":"device_preview_error", "message":str(exc)}
            event.update(generation=request.generation, serial=request.serial,requested_display=request.display_id)
            if self.is_current(request.generation): self.emit(event)

    def _capture(self, request: PreviewRequest) -> dict:
        client = AdbClient(request.adb_path, request.serial)
        if ":" in request.serial and not any(d.serial==request.serial and d.state=="device" for d in client.devices()):
            client.connect(request.serial)
        targets=client.display_targets()
        try: target=select_display(targets,request.display_id)
        except AdbError:
            if not request.fallback_to_desktop: raise
            target=select_display(targets,None)
        client.bind_display(target.logical_id,expected_package=target.package)
        image = client.screenshot()
        frame = Frame.from_image(image)
        server=server_for(target.package)
        if server:
            profile=template_profile(target.package)
            if profile not in self._detectors: self._detectors[profile]=Detector(profile=profile)
            obs=self._detectors[profile].observe(frame)
            rendered,scene=annotate(frame,obs),str(obs.scene)
            message=f"已选择{server.name}，可以开始处理未读"
            if not server.tested:
                message+="（使用国服模板，完整流程未实测）" if profile=="cn" else "（完整流程尚未实测）"
        else:
            rendered,scene=frame.image,target.label.split("  ·  ")[0]
            message="已显示所选画面；选择支持的游戏后可开始自动处理"
        return {"image":rendered, "scene":scene,
                "resolution":frame.original_size, "message":message,"targets":targets,"target":target}
