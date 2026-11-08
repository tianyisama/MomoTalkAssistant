from __future__ import annotations

from .models import Action, Observation, RunStats, Scene, Target, Box
from .options import DEFAULT_IDLE_SECONDS, RunOptions


class Planner:
    """State transitions are confirmed from observations, not assumed sleeps.

    Refresh and filtering are mandatory gates before any list-row selection.
    All returned touch targets originate from the current observation.
    """
    def __init__(self, idle_seconds: float = DEFAULT_IDLE_SECONDS, options: RunOptions | None = None):
        self.stats = RunStats()
        self.options = options or RunOptions(idle_seconds)
        self.filter_verified = False
        self.refresh_stage = ""
        self.refresh_since = 0.
        self.refresh_reason = "初始化未读列表"
        self.in_chat = False
        self.chat_since = 0.
        self.last_progress = 0.
        self.last_fingerprint = ""
        self.reward_pending = False
        self.skip_pending = False
        self.pending_reply = False
        self.chat_clear_since: float | None = None
        self.chat_clear_frames = 0
        self.home_clear_since: float | None = None
        self.home_clear_frames = 0
        self.checking_home = False
        self.no_progress_rounds = 0
        self.round_progress = False
        self.status = "准备识别"
        self.scrolls = 0

    @property
    def idle_seconds(self) -> float:
        return self.options.idle_seconds

    @idle_seconds.setter
    def idle_seconds(self, value: float):
        self.options.set_idle_seconds(value)

    @staticmethod
    def touch(obs: Observation, key: str, message: str) -> Action | None:
        target = obs.targets.get(key)
        return Action(key, message, target) if target else None

    def start_refresh(self, reason: str, now: float):
        self.refresh_stage = "people"
        self.refresh_reason = reason
        self.refresh_since = now
        self.in_chat = False
        self.chat_clear_since = None
        self.chat_clear_frames = 0

    def propose(self, obs: Observation, now: float) -> Action | None:
        self.status = str(obs.scene)
        if obs.scene != Scene.HOME:
            self.home_clear_since = None
            self.home_clear_frames = 0
        if (obs.scene != Scene.MOMO or obs.meta.get("nav_unread") is not False
                or any(key in obs.targets for key in ("reply_first","reply_label","bond_enter"))):
            self.chat_clear_since = None
            self.chat_clear_frames = 0
        # Only the associated overlay's own controls are actionable.
        if obs.scene == Scene.REWARD:
            return self.touch(obs, "reward_touch", "确认奖励，点击展示带下方 TOUCH")
        if obs.scene == Scene.SKIP_CONFIRM:
            return self.touch(obs, "skip_ok", "确认跳过羁绊剧情")
        if obs.scene == Scene.STORY_MENU:
            return self.touch(obs, "fast_forward", "打开剧情跳过确认")
        if obs.scene == Scene.STORY:
            return self.touch(obs, "story_menu", "展开剧情 MENU")
        if obs.scene == Scene.STORY_INFO:
            return self.touch(obs, "story_start", "开始羁绊剧情")
        if obs.scene == Scene.HOME:
            self.filter_verified = False
            self.refresh_stage = ""
            self.in_chat = False
            if obs.meta.get("home_unread") is False:
                if self.home_clear_since is None: self.home_clear_since = now
                self.home_clear_frames += 1
                if self.home_clear_frames >= 2 and now-self.home_clear_since >= 1:
                    return Action("done", "已回到主页确认桃信入口的红色数字消失，全部未读已处理完成。", kind="done")
                self.status = "正在主页确认桃信入口已无未读数字"
                return None
            self.home_clear_since = None
            self.home_clear_frames = 0
            if obs.meta.get("home_unread") is None:
                self.status = "等待确认主页桃信入口的未读标记"
                return None
            self.checking_home = False
            return self.touch(obs, "open_momo", "从主页打开桃信")
        if obs.scene == Scene.SORT:
            self.filter_verified = False
            if obs.meta.get("unread_selected"):
                return self.touch(obs, "sort_ok", "确认未读排序设置")
            return self.touch(obs, "sort_unread", "将排序方式设为未读")
        if obs.scene != Scene.MOMO:
            self.status = "等待加载或可识别的游戏界面"
            return None

        if self.reward_pending:
            self.reward_pending = False
            if self.skip_pending:
                self.stats.stories += 1
                self.skip_pending = False
            self.round_progress = True
            self.no_progress_rounds = 0
            self.start_refresh("领奖后刷新未读列表", now)

        if self.pending_reply and "reply_first" not in obs.targets:
            self.pending_reply = False
            self.stats.replies += 1
            self.round_progress = True
            self.last_progress = now

        if self.checking_home:
            self.status = "关闭桃信，返回主页确认未读标记"
            return self.touch(obs, "momo_close", "关闭桃信，回主页确认是否全部读完")

        if (obs.meta.get("tab") == "chat" and obs.meta.get("nav_unread") is False
                and not any(key in obs.targets for key in ("reply_first","reply_label","bond_enter"))):
            return self._confirm_chat_clear(obs, now)

        # If a user changes sorting while a run is active, revoke the gate.
        if obs.meta.get("tab") == "chat" and obs.meta.get("sort") == "latest":
            self.filter_verified = False
            self.refresh_stage = ""
            return self.touch(obs, "sort_button", "打开排序，准备切换为未读")

        if self.refresh_stage:
            return self._refresh(obs, now)

        if not self.filter_verified:
            if obs.meta.get("tab") == "people":
                return self.touch(obs, "chat_tab", "打开聊天标签")
            if obs.meta.get("sort") == "unread":
                self.start_refresh("确认未读设置后刷新列表", now)
                return self._refresh(obs, now)
            self.status = "等待确认聊天列表与排序按钮"
            return None

        # A list can be visited manually during a run. Always return through a
        # refresh and recheck sorting rather than using stale row coordinates.
        if obs.meta.get("tab") == "people":
            self.start_refresh("返回聊天列表", now)
            self.refresh_stage = "chat"
            return self._refresh(obs, now)
        if obs.meta.get("sort") != "unread":
            self.status = "未能确认未读排序，暂停操作"
            return None

        if self.in_chat:
            fingerprint = obs.meta.get("chat_fingerprint", "")
            if fingerprint and fingerprint != self.last_fingerprint:
                self.last_fingerprint = fingerprint
                self.last_progress = now
            if "bond_enter" in obs.targets:
                return self.touch(obs, "bond_enter", "进入羁绊剧情")
            if "reply_first" in obs.targets:
                return self.touch(obs, "reply_first", "选择第一个可用回复")
            if "reply_label" in obs.targets and obs.right_panel and self.scrolls < 2:
                panel = obs.right_panel
                start = panel.relative(.4, .72, .2, .1)
                end = panel.relative(.4, .3, .2, .1).center
                return Action("reveal_reply", "向上滑动聊天，显示回复选项", Target("reveal_reply", start), "swipe", end)
            # An idle period triggers a fresh list inspection, not a claim that
            # the conversation is complete. Repeated no-progress visits stop.
            if now-self.last_progress >= self.idle_seconds:
                if not self.round_progress: self.no_progress_rounds += 1
                else: self.no_progress_rounds = 0
                if self.no_progress_rounds >= 3:
                    return Action("stalled", "多轮未找到回复或剧情入口，已停止；请查看识别预览。", kind="error")
                self.start_refresh("聊天暂时无可操作项，刷新后重新检查", now)
                return self._refresh(obs, now)
            if now-self.chat_since > 240:
                return Action("stalled", "当前聊天等待超过四分钟，已停止并保留截图。", kind="error")
            remaining = max(0, self.idle_seconds-(now-self.last_progress))
            self.status = f"等待后续消息或回复 · {remaining:.1f} 秒后刷新检查"
            return None

        if "first_unread" in obs.targets:
            return self.touch(obs, "first_unread", "打开第一条未读聊天")
        if obs.meta.get("nav_unread"):
            self.status = "未读标记仍存在，等待列表加载"
            return None
        self.status = "等待确认聊天标签的未读标记"
        return None

    def _confirm_chat_clear(self, obs: Observation, now: float) -> Action | None:
        if self.chat_clear_since is None: self.chat_clear_since = now
        self.chat_clear_frames += 1
        self.status = "聊天未读数字已消失，准备回主页确认"
        if self.chat_clear_frames >= 2 and now-self.chat_clear_since >= 1:
            return self.touch(obs, "momo_close", "关闭桃信，回主页确认是否全部读完")
        return None

    def _refresh(self, obs: Observation, now: float) -> Action | None:
        self.status = self.refresh_reason
        if now-self.refresh_since > 35:
            return Action("refresh_failed", "未能确认标签切换，已停止；请检查识别预览。", kind="error")
        if self.refresh_stage in ("people", "await_people"):
            if obs.meta.get("tab") == "people":
                self.refresh_stage = "chat"
            else:
                return self.touch(obs, "people_tab", "切换头像标签，刷新未读列表")
        if self.refresh_stage in ("chat", "await_chat"):
            if obs.meta.get("tab") == "chat" and obs.meta.get("sort") == "unread":
                self.refresh_stage = "settle"
                self.refresh_since = now
            else:
                return self.touch(obs, "chat_tab", "切回聊天标签")
        if self.refresh_stage == "settle":
            if now-self.refresh_since < 1.5:
                self.status = "等待刷新后的未读列表"
                return None
            self.filter_verified = True
            self.refresh_stage = ""
            self.stats.refreshes += 1
        return None

    def committed(self, action: Action, obs: Observation, now: float):
        self.stats.touches += 1
        if action.key == "people_tab" and self.refresh_stage:
            self.refresh_stage = "await_people"
        elif action.key == "chat_tab" and self.refresh_stage:
            self.refresh_stage = "await_chat"
        elif action.key == "first_unread":
            self.in_chat = True
            self.chat_since = self.last_progress = now
            self.round_progress = False
            self.scrolls = 0
            self.last_fingerprint = obs.meta.get("chat_fingerprint", "")
        elif action.key == "reply_first":
            self.pending_reply = True
            self.last_progress = now
        elif action.key == "reveal_reply":
            self.scrolls += 1
        elif action.key == "skip_ok":
            self.skip_pending = True
        elif action.key == "reward_touch":
            self.reward_pending = True
        elif action.key == "momo_close":
            self.checking_home = True
            self.filter_verified = False
            self.refresh_stage = ""
            self.in_chat = False
