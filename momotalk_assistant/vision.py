from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json

import cv2
import numpy as np

from .models import Box, Observation, Scene, Target
from .paths import resource_dir


def read_image(path: str | Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取图片：{path}")
    return image


def write_image(path: str | Path, image: np.ndarray) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, data = cv2.imencode(path.suffix or ".png", image)
    if not ok:
        raise ValueError("无法编码截图")
    data.tofile(str(path))


@dataclass
class Frame:
    image: np.ndarray
    viewport: Box
    original_size: tuple[int, int]

    @classmethod
    def from_image(cls, image: np.ndarray) -> Frame:
        if image is None or image.ndim != 3 or min(image.shape[:2]) < 160:
            raise ValueError("截图尺寸过小或格式不正确")
        h, w = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # Remove genuine, uniform black borders only. A dark game screen alone
        # never changes the touch mapping. Each mapping belongs to this frame.
        rows = np.mean(gray > 8, axis=1) > .015
        cols = np.mean(gray > 8, axis=0) > .015
        ys, xs = np.flatnonzero(rows), np.flatnonzero(cols)
        viewport = Box(0, 0, w, h)
        if len(xs) and len(ys):
            candidate = Box(int(xs[0]), int(ys[0]), int(xs[-1]-xs[0]+1), int(ys[-1]-ys[0]+1))
            if (candidate.w >= .6*w and candidate.h >= .6*h
                    and (candidate.w < .96*w or candidate.h < .96*h)
                    and 1.3 <= candidate.w/candidate.h <= 2.5):
                viewport = candidate
        normalized = cv2.resize(viewport.crop(image), (1280, round(viewport.h*1280/viewport.w)),
                                interpolation=cv2.INTER_AREA if viewport.w > 1280 else cv2.INTER_CUBIC)
        return cls(normalized, viewport, (w, h))

    def device_point(self, point: tuple[int, int]) -> tuple[int, int]:
        nh, nw = self.image.shape[:2]
        x, y = point
        if not (0 <= x < nw and 0 <= y < nh):
            raise ValueError("识别目标不在当前截图内，拒绝发送触控")
        return (min(self.original_size[0]-1, round(self.viewport.x+x*self.viewport.w/nw)),
                min(self.original_size[1]-1, round(self.viewport.y+y*self.viewport.h/nh)))


class TemplateBank:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or resource_dir()/"assets/templates"
        self.manifest = json.loads((self.directory/"manifest.json").read_text(encoding="utf-8"))
        self.templates = {}
        self.color_templates = {}
        self.resized = {}
        for name, item in self.manifest.items():
            image = read_image(self.directory/item["file"])
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            if float(gray.std()) < 5:
                raise ValueError(f"无有效特征的模板：{name}")
            self.templates[name] = gray
            self.color_templates[name] = image

    def find(self, name: str, gray: np.ndarray, roi: Box, scale: float = 1,
             scales: tuple[float, ...] = (.97, 1., 1.03), threshold: float | None = None) -> Target | None:
        ih, iw = gray.shape
        roi = Box(max(0, roi.x), max(0, roi.y),
                  min(iw, roi.right)-max(0, roi.x), min(ih, roi.bottom)-max(0, roi.y))
        if roi.w <= 0 or roi.h <= 0:
            return None
        source = roi.crop(gray)
        best = None
        base = self.templates[name]
        for variation in scales:
            factor = round(scale*variation, 3)
            key = name, factor
            if key not in self.resized:
                self.resized[key] = cv2.resize(base, (max(2, round(base.shape[1]*factor)),
                                                      max(2, round(base.shape[0]*factor))),
                                               interpolation=cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC)
            template = self.resized[key]
            th, tw = template.shape
            if th > roi.h or tw > roi.w:
                continue
            result = cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED)
            _, value, _, location = cv2.minMaxLoc(result)
            if np.isfinite(value) and (best is None or value > best.confidence):
                best = Target(name, Box(roi.x+location[0], roi.y+location[1], tw, th), float(value))
        limit = threshold if threshold is not None else self.manifest[name]["threshold"]
        return best if best and best.confidence >= limit else None

    def any(self, names: tuple[str, ...], *args, **kwargs) -> Target | None:
        matches = [self.find(name, *args, **kwargs) for name in names]
        return max((x for x in matches if x), key=lambda x:x.confidence, default=None)


def pink_mask(image: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, (163, 40, 165), (179, 200, 255))


def components(mask: np.ndarray, offset: tuple[int, int] = (0, 0)) -> list[Box]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return [Box(x+offset[0], y+offset[1], w, h) for contour in contours
            for x, y, w, h in [cv2.boundingRect(contour)]]


class Detector:
    def __init__(self, templates: TemplateBank | None = None, *, profile: str = "jp", home_icons: TemplateBank | None = None):
        if profile not in ("jp","cn","tw"): raise ValueError("Unknown template profile")
        self.profile=profile
        directory=resource_dir()/({"jp":"assets/templates","cn":"assets/templates_cn","tw":"assets/templates_tw"}[profile])
        self.bank = templates or TemplateBank(directory)
        self.home_icons=home_icons or TemplateBank(resource_dir()/"assets/home_icons")

    def observe(self, frame: Frame) -> Observation:
        image = frame.image
        h, w = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        whole = Box(0, 0, w, h)
        obs = Observation()
        central = whole.relative(.2, .1, .6, .8)
        # High-priority overlays must be resolved before the still-visible UI
        # underneath them can yield any actionable targets.
        reward = self.bank.find("reward_title", gray, whole.relative(.2, .06, .6, .36))
        if reward:
            obs.scene = Scene.REWARD
            obs.targets["reward_title"] = reward
            touch = self.bank.find("reward_touch", gray, whole.relative(.2, .69, .6, .3))
            if touch:
                obs.targets["reward_touch"] = touch
            return obs
        skip = self.bank.find("skip_question", gray, central)
        if skip:
            obs.scene = Scene.SKIP_CONFIRM
            obs.targets["skip_question"] = skip
            ok = self.bank.find("skip_ok", gray, whole.relative(.48, .53, .27, .31))
            if ok:
                obs.targets["skip_ok"] = ok
            return obs

        headers = [b for b in components(pink_mask(image))
                   if b.w > .4*w and 12 <= b.h <= .18*h and b.w/b.h > 8 and b.y < .6*h]
        if headers:
            header = max(headers, key=lambda b:b.w)
            scale = header.w/1024
            logo = self.bank.find("momo_logo", gray, header.expanded(4, 4), scale,
                                  scales=(.94, .98, 1., 1.02, 1.06))
            if logo:
                window = Box(header.x, header.y, header.w, min(h-header.y, round(header.w*.529)))
                obs.scene, obs.window = Scene.MOMO, window
                obs.targets["momo_logo"] = logo
                obs.meta["ui_scale"] = scale
                self._momo(image, gray, obs, header, scale)
                return obs

        menu = self.bank.any(("menu_light", "menu_dark"), gray, whole.relative(.72, .0, .28, .19))
        if menu:
            obs.scene = Scene.STORY
            obs.targets["story_menu"] = menu
            fast = self.bank.find("fast_forward", gray, whole.relative(.72, .06, .28, .23))
            if fast:
                obs.scene = Scene.STORY_MENU
                obs.targets["fast_forward"] = fast
            return obs
        phone = self._home_phone(image,gray,whole)
        if phone:
            obs.scene = Scene.HOME
            obs.targets["open_momo"] = phone
            scale = phone.box.w/self.home_icons.templates[phone.name].shape[1]
            obs.meta["home_icon_variant"]=phone.name
            badge_area = Box(round(phone.box.x+.2*phone.box.w),
                             round(phone.box.y-.85*phone.box.h),
                             round(phone.box.w*1.5),round(phone.box.h))
            visible=badge_area.x>=0 and badge_area.y>=0 and badge_area.right<=w and badge_area.bottom<=h
            obs.meta["home_unread"] = bool(self._badges(image,badge_area,scale)) if visible else None
        return obs

    def _home_phone(self,image,gray,whole):
        scales=(.6,.7,.8,.9,.95,1.,1.05,1.1,1.2,1.35,1.5)
        candidates=[self.home_icons.find(name,gray,whole,scales=scales) for name in self.home_icons.templates]
        candidates=[candidate for candidate in candidates if candidate and self._valid_home_icon(image,candidate)]
        if not candidates: return None
        phone=max(candidates,key=lambda candidate:candidate.confidence)
        suppressed=gray.copy()
        erase=phone.box.expanded(round(phone.box.w*.25),round(phone.box.h*.25))
        x0,y0=max(0,erase.x),max(0,erase.y)
        suppressed[y0:min(gray.shape[0],erase.bottom),x0:min(gray.shape[1],erase.right)]=int(np.median(gray))
        for name in self.home_icons.templates:
            second=self.home_icons.find(name,suppressed,whole,scales=scales)
            if second and second.confidence>=phone.confidence-.04 and self._valid_home_icon(image,second): return None
        return phone

    def _valid_home_icon(self,image,phone):
        template=self.home_icons.color_templates[phone.name]
        target=phone.box.crop(image)
        resized=cv2.resize(template,(phone.box.w,phone.box.h))
        hsv=cv2.cvtColor(resized,cv2.COLOR_BGR2HSV)
        # Check the handset's pink and white surfaces, not background pixels or
        # an unrelated home icon. This also rejects icons beneath a dim overlay.
        mask=((hsv[:,:,0]>160)&(hsv[:,:,1]>35)&(hsv[:,:,2]>120))|(np.min(resized,axis=2)>190)
        if mask.sum()<20: return False
        delta=np.abs(cv2.cvtColor(target,cv2.COLOR_BGR2LAB).astype(float)-cv2.cvtColor(resized,cv2.COLOR_BGR2LAB))
        return bool(np.median(delta[mask].mean(axis=1))<=30)

    def _momo(self, image, gray, obs, header, scale):
        win = obs.window
        assert win is not None
        body = Box(win.x, header.bottom, win.w, win.bottom-header.bottom)
        nav = body.relative(0, 0, .086, 1)
        left = body.relative(.085, 0, .455, 1)
        right = body.relative(.541, 0, .457, 1)
        obs.right_panel = right
        close = self.bank.find("momo_close",gray,header.relative(.90,0,.10,1),scale)
        if close: obs.targets["momo_close"] = close
        people = self.bank.any(("people_idle", "people_active"), gray, nav.relative(0, 0, 1, .24), scale)
        chat = self.bank.any(("chat_idle", "chat_active"), gray, nav.relative(0, .18, 1, .25), scale)
        if people: obs.targets["people_tab"] = people
        if chat: obs.targets["chat_tab"] = chat
        student_label = self.bank.find("people_label", gray, left.relative(0, 0, .3, .15), scale)
        latest = self.bank.find("filter_latest", gray, left.relative(.53, 0, .31, .14), scale)
        unread = self.bank.find("filter_unread", gray, left.relative(.53, 0, .31, .14), scale)
        if latest or unread:
            selected = max([t for t in (latest, unread) if t], key=lambda t:t.confidence)
            obs.meta["sort"] = "unread" if selected.name == "filter_unread" else "latest"
            obs.meta["tab"] = "chat"
            obs.targets["sort_button"] = selected
        elif student_label:
            obs.meta["tab"] = "people"

        sort_title = self.bank.find("sort_title", gray, left, scale)
        if sort_title:
            obs.scene = Scene.SORT
            obs.targets["sort_title"] = sort_title
            sort_body = Box(left.x, sort_title.box.bottom, left.w,
                            min(left.bottom-sort_title.box.bottom, round(280*scale)))
            choice = self.bank.any(("sort_unread_idle", "sort_unread_active"), gray,
                                   sort_body.relative(.5, 0, .5, .55), scale)
            if choice:
                obs.targets["sort_unread"] = choice
                around = choice.box.expanded(round(25*scale), round(8*scale)).crop(image)
                obs.meta["unread_selected"] = bool(around.size and np.mean(pink_mask(around)>0) > .3)
            ok = self.bank.find("sort_ok", gray, sort_body.relative(0, .4, 1, .6), scale)
            if ok: obs.targets["sort_ok"] = ok
            return

        empty = self.bank.find("empty_chat", gray, right, scale)
        obs.meta["empty_chat"] = bool(empty)
        if empty: obs.targets["empty_chat"] = empty
        rows = self._badges(image, left.relative(.83, .12, .17, .88), scale)
        nav_badges = self._badges(image, nav.relative(.25, .16, .75, .28), scale)
        obs.meta["row_badges"] = len(rows)
        obs.meta["nav_unread"] = bool(nav_badges)
        if rows:
            badge = min(rows, key=lambda b:b.y)
            obs.add("first_unread", Box(left.x+round(left.w*.08), badge.y,
                                        round(left.w*.65), badge.h), .97)
            # A stable avatar signature catches repeated refreshes that make no
            # progress, without depending on a student's name or badge digits.
            avatar = Box(left.x+round(12*scale), max(left.y, badge.y-round(10*scale)),
                         round(60*scale), round(60*scale)).crop(gray)
            if avatar.size:
                small = cv2.resize(avatar, (12, 12))
                obs.meta["first_signature"] = hashlib.sha1((small//32).tobytes()).hexdigest()[:16]

        story_start = self.bank.find("story_start", gray, right.relative(0, .45, 1, .55), scale)
        if story_start:
            obs.scene = Scene.STORY_INFO
            obs.targets["story_start"] = story_start
            return
        bond = self.bank.find("bond_label", gray, right, scale)
        if bond:
            below = Box(right.x, bond.box.bottom, right.w, min(right.bottom-bond.box.bottom, round(110*scale)))
            pinks = [b for b in components(pink_mask(below.crop(image)), (below.x, below.y))
                     if b.w > right.w*.55 and 14*scale <= b.h <= 70*scale]
            if pinks:
                obs.add("bond_enter", max(pinks, key=lambda b:b.w), min(.98, bond.confidence))
        reply = self.bank.find("reply_label", gray, right, scale)
        if reply:
            obs.targets["reply_label"] = reply
            search = Box(right.x, reply.box.bottom+round(5*scale), right.w,
                         max(1, right.bottom-reply.box.bottom-round(8*scale)))
            patch = search.crop(image)
            white = np.uint8(np.min(patch, axis=2)>237)*255
            white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((3, 7), np.uint8))
            options = [b for b in components(white, (search.x, search.y))
                       if b.w > .57*right.w and 25*scale <= b.h <= 100*scale
                       and b.y >= reply.box.bottom and b.bottom < right.bottom-round(3*scale)]
            if options:
                first = min(options, key=lambda b:b.y)
                obs.add("reply_first", first, min(.98, reply.confidence))
        # This is diagnostic progress only; frame stability never authorizes a
        # touch or declares a conversation complete.
        thumb = cv2.resize(right.crop(gray), (40, 40))
        obs.meta["chat_fingerprint"] = hashlib.sha1((thumb//24).tobytes()).hexdigest()[:12]

    @staticmethod
    def _badges(image, roi, scale):
        crop = roi.crop(image)
        if not crop.size: return []
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (0, 150, 180), (18, 255, 255))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        return [b for b in components(mask, (roi.x, roi.y))
                if 8*scale <= b.w <= 65*scale and 12*scale <= b.h <= 55*scale
                and .45 <= b.w/b.h <= 2.8]


class AutoDetector:
    """Offline screenshots have no package name; compare language landmarks."""
    def __init__(self):
        self.detectors={profile:Detector(profile=profile) for profile in ("jp","cn","tw")}

    def observe(self,frame: Frame) -> Observation:
        observations=[(profile,detector.observe(frame)) for profile,detector in self.detectors.items()]
        specific={"sort_button","sort_title","reply_label","bond_enter","story_start","skip_question","reward_title","open_momo"}
        def score(item):
            _,obs=item
            return sum(target.confidence for name,target in obs.targets.items() if name in specific)+(.2 if obs.scene!=Scene.UNKNOWN else 0)+(.1 if obs.meta.get("tab") else 0)
        profile,obs=max(observations,key=score)
        obs.meta["profile"]=profile
        return obs


def annotate(frame: Frame, obs: Observation, selected: str | None = None) -> np.ndarray:
    output = frame.image.copy()
    if obs.window:
        b = obs.window
        cv2.rectangle(output, (b.x, b.y), (b.right, b.bottom), (150, 145, 130), 1)
    for key, target in obs.targets.items():
        if key in ("momo_logo", "empty_chat", "reply_label", "reward_title", "skip_question", "sort_title"):
            continue
        b = target.box
        color = (80, 210, 255) if key == selected else (145, 205, 75)
        cv2.rectangle(output, (b.x, b.y), (b.right, b.bottom), color, 2)
        cv2.putText(output, f"{key} {target.confidence:.2f}", (b.x, max(14, b.y-5)),
                    cv2.FONT_HERSHEY_SIMPLEX, .40, color, 1, cv2.LINE_AA)
    return output
