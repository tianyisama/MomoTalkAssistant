from pathlib import Path

import cv2
import numpy as np
import pytest

from momotalk_assistant.models import Scene
from momotalk_assistant.vision import Detector,Frame,read_image

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def detector(): return Detector()


def source(sequence,number):
    path=ROOT/f"_analysis/{sequence}/frame_{number:03d}.jpg"
    if not path.is_file(): pytest.skip("Local recording fixtures are not included in source distribution")
    return read_image(path)


@pytest.mark.parametrize("number,scene,target",[
    (1,Scene.HOME,"open_momo"),(3,Scene.MOMO,"sort_button"),
    (4,Scene.MOMO,"reply_first"),(7,Scene.MOMO,"reply_first"),
    (13,Scene.MOMO,"reply_first"),(16,Scene.MOMO,"reply_first"),
    (19,Scene.MOMO,"bond_enter"),(20,Scene.STORY_INFO,"story_start"),
    (24,Scene.STORY,"story_menu"),(27,Scene.STORY_MENU,"fast_forward"),
    (28,Scene.SKIP_CONFIRM,"skip_ok"),(30,Scene.REWARD,"reward_touch")])
def test_recorded_game_states(detector,number,scene,target):
    obs=detector.observe(Frame.from_image(source("video_review",number)))
    assert obs.scene==scene
    assert target in obs.targets


@pytest.mark.parametrize("width",[960,1280,1600,1920,2560,3840])
@pytest.mark.parametrize("number,target",[(7,"reply_first"),(19,"bond_enter"),(28,"skip_ok"),(30,"reward_touch")])
def test_resolution_changes_preserve_target_and_device_mapping(detector,width,number,target):
    original=source("video_review",number)
    baseline=Frame.from_image(original)
    base_obs=detector.observe(baseline)
    expected=baseline.device_point(base_obs.targets[target].box.center)
    resized=cv2.resize(original,(width,round(width*9/16)),interpolation=cv2.INTER_AREA)
    frame=Frame.from_image(resized); obs=detector.observe(frame)
    assert target in obs.targets
    point=frame.device_point(obs.targets[target].box.center)
    assert abs(point[0]-expected[0]*width/1920)<width*.012
    assert abs(point[1]-expected[1]*width/1920)<width*.012


def test_letterboxed_reply_uses_capture_offsets(detector):
    original=source("video_review",7)
    letterbox=cv2.copyMakeBorder(original,180,180,0,0,cv2.BORDER_CONSTANT,value=(0,0,0))
    frame=Frame.from_image(letterbox); obs=detector.observe(frame)
    assert "reply_first" in obs.targets
    point=frame.device_point(obs.targets["reply_first"].box.center)
    assert abs(point[1]-(477+180))<16


def test_options_can_appear_in_middle_or_bottom(detector):
    middle=detector.observe(Frame.from_image(source("video_review",7)))
    bottom=detector.observe(Frame.from_image(source("video_review",4)))
    assert middle.targets["reply_first"].box.y+100<bottom.targets["reply_first"].box.y


@pytest.mark.parametrize("number,selected",[(9,False),(14,False),(17,True),(18,True)])
def test_sort_dialog_uses_actual_selected_option(detector,number,selected):
    obs=detector.observe(Frame.from_image(source("filter_review",number)))
    assert obs.scene==Scene.SORT
    assert obs.meta["unread_selected"] is selected
    assert "sort_unread" in obs.targets and "sort_ok" in obs.targets
    assert "first_unread" not in obs.targets


def test_typing_frames_do_not_invent_reply_buttons(detector):
    for number in [11,12,14,15,17,18]:
        obs=detector.observe(Frame.from_image(source("video_review",number)))
        assert "reply_first" not in obs.targets


def test_reward_overlay_does_not_expose_the_chat_underneath(detector):
    obs=detector.observe(Frame.from_image(source("video_review",30)))
    assert obs.scene==Scene.REWARD
    assert not ({"first_unread","reply_first","sort_button"}&obs.targets.keys())
    assert obs.targets["reward_touch"].box.y>500


def test_colored_noise_without_ui_context_is_not_actionable(detector):
    image=np.full((720,1280,3),125,np.uint8)
    for x,y in [(100,200),(800,300),(1180,600)]:
        cv2.rectangle(image,(x,y),(x+60,y+40),(155,134,254),-1)
        cv2.rectangle(image,(x,y+50),(x+60,y+80),(255,221,122),-1)
    obs=detector.observe(Frame.from_image(image))
    assert obs.scene==Scene.UNKNOWN
    assert obs.targets=={}


@pytest.mark.parametrize("width",[960,1280,1920,3840])
def test_home_badge_is_checked_next_to_the_momo_icon(detector,width):
    original=source("video_review",1)
    image=cv2.resize(original,(width,round(width*9/16)),interpolation=cv2.INTER_AREA)
    obs=detector.observe(Frame.from_image(image))
    assert obs.scene==Scene.HOME
    assert obs.meta["home_unread"] is True


def test_no_home_badge_is_distinguished_from_no_home_ui(detector):
    original=source("video_review",1)
    mask=np.zeros(original.shape[:2],np.uint8)
    cv2.rectangle(mask,(202,142),(250,179),255,-1)
    image=cv2.inpaint(original,mask,4,cv2.INPAINT_TELEA)
    obs=detector.observe(Frame.from_image(image))
    assert obs.scene==Scene.HOME
    assert obs.meta["home_unread"] is False


def test_momo_close_comes_from_the_window_header(detector):
    obs=detector.observe(Frame.from_image(source("video_review",4)))
    assert "momo_close" in obs.targets
    target=obs.targets["momo_close"].box
    assert target.center[0]>obs.window.x+obs.window.w*.9
    assert target.center[1]<obs.window.y+obs.window.h*.12
