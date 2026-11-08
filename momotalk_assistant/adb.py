from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import hashlib
import os
import re
import shutil
import socket
import subprocess
import threading

import cv2
import numpy as np

from .paths import resource_dir
from .servers import server_for


class AdbError(RuntimeError):
    pass


@dataclass(frozen=True)
class Device:
    serial: str
    state: str
    model: str = ""
    aliases: tuple[str,...] = ()
    identity: str = ""

    @property
    def label(self) -> str:
        return f"{self.serial}  ·  {self.model or self.state}"

    def matches(self, serial: str) -> bool:
        return serial == self.serial or serial in self.aliases


@dataclass(frozen=True)
class DisplayBinding:
    logical_id: int
    physical_id: str | None
    package: str

    @property
    def label(self) -> str:
        names={"com.YostarJP.BlueArchive":"碧蓝档案（日服）",
               "com.RoamingStar.BlueArchive":"蔚蓝档案（国服）",
               "com.nexon.bluearchive":"蔚蓝档案（国际服）"}
        if self.logical_id == 0 and (not self.package or "launcher" in self.package.lower() or self.package=="com.saggitt.omega"):
            return "模拟器桌面  ·  画面 0"
        server=server_for(self.package)
        name=server.name if server else names.get(self.package,self.package or "设备当前画面")
        return f"{name}  ·  画面 {self.logical_id}"


def select_display(displays: list[DisplayBinding], logical_id: int | None) -> DisplayBinding:
    if logical_id is None:
        target=next((item for item in displays if item.logical_id==0),None)
        if target is not None: return target
        if displays: return displays[0]
    else:
        target=next((item for item in displays if item.logical_id==logical_id),None)
        if target is not None: return target
    raise AdbError("所选画面已经关闭或无法读取，请刷新画面列表后重新选择。")


def resumed_displays(output: str) -> dict[int, str]:
    current = 0
    result = {}
    for line in output.splitlines():
        display = re.search(r"Display #(\d+) \(activities", line)
        if display: current = int(display.group(1))
        if any(key in line for key in ("topResumedActivity=", "mResumedActivity:", "mResumedActivity=")):
            match = re.search(r"\b([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)/", line)
            if match: result[current] = match.group(1)
    return result


def physical_displays(output: str) -> dict[int, str]:
    result = {}
    for viewport in re.findall(r"DisplayViewport\{[^}]+\}", output):
        logical = re.search(r"displayId=(\d+)", viewport)
        physical = re.search(r"uniqueId=['\"]local:(\d+)['\"]", viewport)
        if logical and physical: result[int(logical.group(1))] = physical.group(1)
    # Some Android versions do not include viewports in dumpsys output.
    current = None
    for line in output.splitlines():
        logical = re.search(r"^\s*mDisplayId=(\d+)\s*$", line)
        if logical: current = int(logical.group(1))
        if current is not None and ("mBaseDisplayInfo=" in line or "mOverrideDisplayInfo=" in line):
            physical = re.search(r"uniqueId\s*[= ]\s*['\"]local:(\d+)['\"]", line)
            if physical: result[current] = physical.group(1)
    return result


def resolve_adb(custom: str = "") -> str:
    if custom:
        path = Path(custom.strip().strip('"')).expanduser()
        if path.is_file(): return str(path.resolve())
        found = shutil.which(custom.strip())
        if found: return found
        raise AdbError("指定的 ADB 文件不存在，请重新选择 adb.exe。")
    candidates = [resource_dir()/"assets/adb/adb.exe"]
    installed = shutil.which("adb")
    if installed: candidates.append(Path(installed))
    local = os.environ.get("LOCALAPPDATA")
    if local: candidates.append(Path(local)/"Android/Sdk/platform-tools/adb.exe")
    for path in candidates:
        if path.is_file(): return str(path)
    raise AdbError("未找到 ADB。请点击“选择文件”指定模拟器或 Android SDK 中的 adb.exe。")


class AdbClient:
    def __init__(self, executable: str = "", serial: str = "", stop: threading.Event | None = None):
        self.executable = resolve_adb(executable)
        self.serial = serial
        self.stop = stop
        self.binding: DisplayBinding | None = None

    def _run(self, *arguments: str, device: bool = False, timeout: float = 8) -> bytes:
        command = [self.executable]
        if device:
            if not self.serial: raise AdbError("尚未选择设备。")
            command += ["-s", self.serial]
        command += list(arguments)
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                    stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as exc:
            raise AdbError("ADB 响应超时。请检查模拟器是否仍在运行，以及 ADB 是否可用。") from exc
        except OSError as exc:
            raise AdbError(f"无法启动 ADB：{exc}") from exc
        if result.returncode:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise AdbError(message or "ADB 命令执行失败。")
        return result.stdout

    def devices(self) -> list[Device]:
        output = self._run("devices", "-l").decode("utf-8", errors="replace")
        devices = []
        for line in output.splitlines():
            fields = line.split()
            if len(fields) < 2 or fields[0] == "List" or fields[0].startswith("*"):
                continue
            model = next((x.removeprefix("model:").replace("_", " ") for x in fields[2:] if x.startswith("model:")), "")
            devices.append(Device(fields[0], fields[1], model))
        return devices

    def group_devices(self, devices: list[Device]) -> list[Device]:
        groups={}
        for item in devices:
            if item.state!="device":
                groups["serial:"+item.serial]=[item]
                continue
            try:
                client=AdbClient(self.executable,item.serial)
                boot=client._run("shell","cat","/proc/sys/kernel/random/boot_id",device=True,timeout=3).decode("ascii",errors="replace").strip().lower()
                if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",boot):
                    raise ValueError("Missing unique boot identifier")
                identity=hashlib.sha256(boot.encode("ascii")).hexdigest()
                key="boot:"+identity
                item=replace(item,identity=identity)
            except (AdbError,ValueError):
                key="serial:"+item.serial
            groups.setdefault(key,[]).append(item)
        result=[]
        for group in groups.values():
            primary=min(group,key=lambda d:(not d.serial.startswith("emulator-"),d.serial))
            aliases=tuple(sorted({d.serial for d in group if d.serial!=primary.serial}))
            result.append(replace(primary,aliases=aliases))
        return result

    def connect(self, endpoint: str) -> str:
        endpoint = endpoint.strip()
        # Only host:port is accepted. It is passed as one argument, never through
        # a shell; malformed input cannot become an Android or Windows command.
        if not re.fullmatch(r"(?:[A-Za-z0-9_.-]+|\[[0-9a-fA-F:]+\]):[0-9]{1,5}", endpoint):
            raise AdbError("连接地址应为主机:端口，例如 127.0.0.1:16384。")
        port = int(endpoint.rsplit(":", 1)[1])
        if not 1 <= port <= 65535: raise AdbError("端口应在 1–65535 之间。")
        output = self._run("connect", endpoint, timeout=5).decode("utf-8", errors="replace").strip()
        if "connected to" not in output.lower():
            raise AdbError(output or "连接失败，请检查模拟器的 ADB 端口。")
        return output

    def discover(self, notify=lambda message: None) -> list[Device]:
        devices = self.devices()
        if any(d.state == "device" for d in devices): return self.group_devices(devices)
        # A deliberately short local-only candidate list. No LAN scan, process
        # termination, adb-server reset, or emulator configuration changes.
        ports = [16384, 7555, 5555, 5557, 5559, 5561, 62001, 62025, 21503, 16416, 16448, 16480, 16512]
        for port in ports:
            if self.stop and self.stop.is_set(): break
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.12):
                    pass
            except OSError:
                continue
            notify(f"尝试本地模拟器端口 {port}")
            try: self.connect(f"127.0.0.1:{port}")
            except AdbError: continue
        return self.group_devices(self.devices())

    def display_targets(self) -> list[DisplayBinding]:
        activities=self._run("shell","dumpsys","activity","activities",device=True,timeout=6).decode("utf-8",errors="replace")
        packages=resumed_displays(activities)
        details=self._run("shell","dumpsys","display",device=True,timeout=6).decode("utf-8",errors="replace")
        mapping=physical_displays(details)
        logical_ids=sorted(set(packages)|{0})
        return [DisplayBinding(logical,mapping.get(logical),packages.get(logical,"")) for logical in logical_ids]

    def bind_display(self, logical_id: int, *, expected_package: str | None = None) -> DisplayBinding:
        targets=self.display_targets()
        target=select_display(targets,logical_id)
        if target.physical_id is None and (logical_id!=0 or len(targets)>1):
            raise AdbError("无法匹配所选画面的截图显示器，请刷新后重新选择。")
        if expected_package is not None and target.package!=expected_package:
            raise AdbError("所选画面的应用已经改变，请重新选择并检查预览。")
        self.binding=target
        return target

    def bind_game_display(self) -> DisplayBinding | None:
        # Legacy single-screen callers may use the current default display.
        # Never search other application displays or prefer a particular server.
        target=select_display(self.display_targets(),0)
        if not is_game_package(target.package): return None
        return self.bind_display(0,expected_package=target.package)

    def screenshot(self, *, allow_default: bool = False) -> np.ndarray:
        if self.binding is None:
            if allow_default:
                self.bind_display(0)
            elif self.bind_game_display() is None:
                raise AdbError("未找到正在运行的蔚蓝档案，请先在模拟器中打开游戏。")
        command = ["exec-out", "screencap", "-p"]
        if self.binding and self.binding.physical_id:
            command += ["-d", self.binding.physical_id]
        png = self._run(*command, device=True, timeout=7)
        # Android 15's multi-display screencap may prepend a textual warning to
        # stdout even though the command succeeds. Keep the actual PNG stream.
        signature = b"\x89PNG\r\n\x1a\n"
        offset = png.find(signature)
        if 0 < offset < 4096 and b"[Warning]" in png[:offset]:
            png = png[offset:]
        image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise AdbError("设备返回的截图无效。请确认模拟器允许 ADB 截图。")
        return image

    def foreground_package(self) -> str:
        if self.binding is None:
            binding = self.bind_game_display()
            return binding.package if binding else ""
        output = self._run("shell", "dumpsys", "activity", "activities", device=True,
                           timeout=6).decode("utf-8", errors="replace")
        return resumed_displays(output).get(self.binding.logical_id, "")

    def _can_touch(self):
        if self.stop and self.stop.is_set():
            raise InterruptedError("已停止，不再发送触控。")

    def tap(self, point: tuple[int, int]):
        self._can_touch()
        if self.binding is None: raise AdbError("尚未绑定游戏显示器，拒绝发送触控。")
        display = ["-d", str(self.binding.logical_id)] if self.binding.logical_id else []
        self._run("shell", "input", *display, "tap", str(int(point[0])), str(int(point[1])), device=True, timeout=4)

    def swipe(self, start: tuple[int, int], end: tuple[int, int], duration_ms: int = 400):
        self._can_touch()
        if self.binding is None: raise AdbError("尚未绑定游戏显示器，拒绝发送触控。")
        display = ["-d", str(self.binding.logical_id)] if self.binding.logical_id else []
        self._run("shell", "input", *display, "swipe", str(int(start[0])), str(int(start[1])),
                  str(int(end[0])), str(int(end[1])), str(duration_ms), device=True, timeout=4)


def is_game_package(package: str) -> bool:
    return bool(re.search(r"blue[_\.]?archive", package, re.IGNORECASE))
