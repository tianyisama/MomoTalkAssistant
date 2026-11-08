from pathlib import Path

import cv2
import pytest

from momotalk_assistant.models import Scene
from momotalk_assistant.servers import can_automate, server_for, template_profile
from momotalk_assistant.vision import AutoDetector, Detector, Frame, read_image


ROOT = Path(__file__).resolve().parents[1]


def sample(name):
    path = ROOT / "_analysis/global" / (name + ".png")
    if not path.exists():
        pytest.skip("Local international capture is not included")
    return read_image(path)


@pytest.fixture(scope="module")
def tw():
    return Detector(profile="tw")


@pytest.mark.parametrize("name,scene,key", [
    ("01_home", Scene.HOME, "open_momo"),
    ("02_people", Scene.MOMO, "chat_tab"),
    ("03_chat", Scene.MOMO, "sort_button"),
    ("04_sort_latest", Scene.SORT, "sort_unread"),
    ("05_sort_unread", Scene.SORT, "sort_ok"),
    ("06_unread_chat", Scene.MOMO, "first_unread"),
    ("07_reply", Scene.MOMO, "reply_first"),
    ("08_bond", Scene.MOMO, "bond_enter"),
    ("09_story_info", Scene.STORY_INFO, "story_start"),
    ("10_story_menu", Scene.STORY, "story_menu"),
    ("11_expanded_menu", Scene.STORY_MENU, "fast_forward"),
    ("12_skip_confirm", Scene.SKIP_CONFIRM, "skip_ok"),
    ("13_reward", Scene.REWARD, "reward_touch"),
])
def test_traditional_chinese_controls(tw, name, scene, key):
    observation = tw.observe(Frame.from_image(sample(name)))
    assert observation.scene == scene
    assert key in observation.targets


@pytest.mark.parametrize("width", [960, 1280, 1920, 3840])
def test_reply_skip_and_reward_rescale(tw, width):
    for name, key in [("07_reply", "reply_first"), ("12_skip_confirm", "skip_ok"), ("13_reward", "reward_touch")]:
        image = cv2.resize(sample(name), (width, round(width * 9 / 16)))
        assert key in tw.observe(Frame.from_image(image)).targets


def test_unread_filter_selected_state(tw):
    latest = tw.observe(Frame.from_image(sample("04_sort_latest")))
    unread = tw.observe(Frame.from_image(sample("05_sort_unread")))
    assert latest.meta["unread_selected"] is False
    assert unread.meta["unread_selected"] is True


def test_international_package_chooses_traditional_chinese():
    package = "com.nexon.bluearchive"
    assert can_automate(package)
    assert template_profile(package) == "tw"
    assert server_for(package).tested


def test_offline_detection_chooses_traditional_chinese_landmarks():
    observation = AutoDetector().observe(Frame.from_image(sample("07_reply")))
    assert observation.meta["profile"] == "tw"
    assert "reply_first" in observation.targets
