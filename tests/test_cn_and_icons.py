from pathlib import Path

import cv2
import numpy as np
import pytest

from momotalk_assistant.models import Scene
from momotalk_assistant.servers import template_profile,server_for,can_automate
from momotalk_assistant.vision import Detector,AutoDetector,Frame,read_image

ROOT=Path(__file__).resolve().parents[1]


def sample(name):
    path=ROOT/"_analysis/cn"/(name+".png")
    if not path.exists(): pytest.skip("Local CN capture is not included")
    return read_image(path)


def jp_home():
    path=ROOT/"_analysis/video_review/frame_001.jpg"
    if not path.exists(): pytest.skip("Local JP recording fixture is not included")
    return read_image(path)


@pytest.fixture(scope="module")
def cn(): return Detector(profile="cn")


@pytest.mark.parametrize("name,scene,key",[
    ("01_home",Scene.HOME,"open_momo"),("03_people",Scene.MOMO,"chat_tab"),
    ("04_chat_ready",Scene.MOMO,"first_unread"),("05_sort_ready",Scene.SORT,"sort_unread"),
    ("06_sort_latest",Scene.SORT,"sort_ok"),("07_latest_chat",Scene.MOMO,"sort_button"),
    ("08_reply",Scene.MOMO,"reply_first"),("09_bond",Scene.MOMO,"bond_enter"),
    ("10_story_info",Scene.STORY_INFO,"story_start"),("11_story_menu",Scene.STORY,"story_menu"),
    ("12_expanded_menu",Scene.STORY_MENU,"fast_forward"),("13_skip_confirm",Scene.SKIP_CONFIRM,"skip_ok"),
    ("14_reward",Scene.REWARD,"reward_touch")])
def test_cn_localized_controls(cn,name,scene,key):
    obs=cn.observe(Frame.from_image(sample(name)))
    assert obs.scene==scene
    assert key in obs.targets


@pytest.mark.parametrize("width",[960,1280,1920,3840])
def test_cn_reply_and_reward_rescale(cn,width):
    for name,key in [("08_reply","reply_first"),("14_reward","reward_touch")]:
        image=cv2.resize(sample(name),(width,round(width*9/16)))
        assert key in cn.observe(Frame.from_image(image)).targets


def test_bilibili_package_uses_same_chinese_profile_but_is_not_marked_tested():
    package="com.RoamingStar.BlueArchive.bilibili"
    assert can_automate(package)
    assert template_profile(package)==template_profile("com.RoamingStar.BlueArchive")=="cn"
    assert not server_for(package).tested
    assert template_profile("com.YostarJP.BlueArchive")=="jp"


def test_offline_detection_chooses_chinese_landmarks():
    obs=AutoDetector().observe(Frame.from_image(sample("08_reply")))
    assert obs.meta["profile"]=="cn" and "reply_first" in obs.targets


@pytest.mark.parametrize("profile",["jp","cn"])
def test_home_entry_does_not_need_the_notice_icon(profile):
    image=sample("01_home") if profile=="cn" else jp_home()
    cv2.rectangle(image,(20,145),(150,275),(70,100,130),-1)
    obs=Detector(profile=profile).observe(Frame.from_image(image))
    assert obs.scene==Scene.HOME and "open_momo" in obs.targets


@pytest.mark.parametrize("profile",["jp","cn"])
def test_home_phone_can_move_to_the_other_half_of_the_screen(profile):
    image=sample("01_home") if profile=="cn" else jp_home()
    detector=Detector(profile=profile)
    initial=detector.observe(Frame.from_image(image))
    assert "open_momo" in initial.targets
    original=Frame.from_image(image).device_point(initial.targets["open_momo"].box.center)
    patch=image[130:270,155:290].copy()
    cv2.rectangle(image,(145,125),(300,280),(70,100,130),-1)
    image[400:540,1350:1485]=patch
    frame=Frame.from_image(image); obs=detector.observe(frame)
    assert obs.scene==Scene.HOME
    point=frame.device_point(obs.targets["open_momo"].box.center)
    assert abs(point[0]-(original[0]+1350-155))<10
    assert abs(point[1]-(original[1]+400-130))<10
    assert obs.meta["home_unread"] is True


def test_a_dimmed_phone_under_an_overlay_is_not_actionable():
    image=jp_home()
    image=(image*.4).astype(np.uint8)
    assert "open_momo" not in Detector().observe(Frame.from_image(image)).targets


def test_two_equally_plausible_phone_icons_are_not_guessed():
    image=jp_home()
    image[400:540,1350:1485]=image[130:270,155:290].copy()
    assert "open_momo" not in Detector().observe(Frame.from_image(image)).targets
