from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def crop(self, image):
        return image[max(0, self.y):self.bottom, max(0, self.x):self.right]

    def relative(self, x: float, y: float, w: float, h: float) -> Box:
        return Box(round(self.x + x * self.w), round(self.y + y * self.h),
                   max(1, round(w * self.w)), max(1, round(h * self.h)))

    def expanded(self, dx: int, dy: int) -> Box:
        return Box(self.x - dx, self.y - dy, self.w + 2 * dx, self.h + 2 * dy)

    def contains(self, point: tuple[int, int]) -> bool:
        x, y = point
        return self.x <= x < self.right and self.y <= y < self.bottom

    def as_list(self) -> list[int]:
        return [self.x, self.y, self.w, self.h]


class Scene(StrEnum):
    HOME = "主页"
    MOMO = "桃信"
    SORT = "排序设置"
    STORY_INFO = "羁绊剧情入口"
    STORY = "剧情播放"
    STORY_MENU = "剧情菜单"
    SKIP_CONFIRM = "跳过确认"
    REWARD = "领取奖励"
    LOADING = "加载中"
    UNKNOWN = "等待识别"


@dataclass(frozen=True)
class Target:
    name: str
    box: Box
    confidence: float = 1.0


@dataclass
class Observation:
    scene: Scene = Scene.UNKNOWN
    targets: dict[str, Target] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    window: Box | None = None
    right_panel: Box | None = None

    def add(self, name: str, box: Box, confidence: float = 1.0) -> None:
        self.targets[name] = Target(name, box, confidence)


@dataclass(frozen=True)
class Action:
    key: str
    message: str
    target: Target | None = None
    kind: str = "tap"
    end: tuple[int, int] | None = None


@dataclass
class RunStats:
    touches: int = 0
    replies: int = 0
    stories: int = 0
    refreshes: int = 0
