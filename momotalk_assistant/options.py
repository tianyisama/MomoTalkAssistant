import math
import threading


DEFAULT_IDLE_SECONDS = 8.0


class RunOptions:
    """Settings shared with an active runner, without restarting its state."""
    def __init__(self, idle_seconds: float = DEFAULT_IDLE_SECONDS):
        self._lock = threading.Lock()
        self._idle_seconds = DEFAULT_IDLE_SECONDS
        self.set_idle_seconds(idle_seconds)

    @property
    def idle_seconds(self) -> float:
        with self._lock:
            return self._idle_seconds

    def set_idle_seconds(self, value: float) -> None:
        value = float(value)
        if not math.isfinite(value) or not 1 <= value <= 120:
            raise ValueError("无后续消息等待时间应为 1–120 秒。")
        with self._lock:
            self._idle_seconds = value
