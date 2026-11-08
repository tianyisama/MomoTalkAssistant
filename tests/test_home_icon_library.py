import json

import cv2
import numpy as np
import pytest

from momotalk_assistant.models import Scene
from momotalk_assistant.vision import Detector,Frame,TemplateBank,write_image


@pytest.mark.parametrize("profile",["jp","cn","tw"])
@pytest.mark.parametrize("variant",["handset_3d","handset_flat"])
def test_every_language_profile_matches_every_shared_icon_style(profile,variant):
    detector=Detector(profile=profile)
    sprite=detector.home_icons.color_templates[variant]
    image=np.full((720,1280,3),(85,105,135),np.uint8)
    h,w=sprite.shape[:2]
    image[350:350+h,900:900+w]=sprite
    observation=detector.observe(Frame.from_image(image))
    assert observation.scene==Scene.HOME
    assert observation.meta["home_icon_variant"]==variant
    x,y=observation.targets["open_momo"].box.center
    assert abs(x-(900+w/2))<2 and abs(y-(350+h/2))<2


def test_new_shared_icon_entry_does_not_need_a_server_mapping_change(tmp_path):
    original=Detector().home_icons.color_templates["handset_3d"]
    sprite=cv2.flip(original,1)
    write_image(tmp_path/"additional.png",sprite)
    (tmp_path/"manifest.json").write_text(json.dumps({"additional_style":{"file":"additional.png","threshold":.83}}),encoding="utf-8")
    library=TemplateBank(tmp_path)
    image=np.full((720,1280,3),(85,105,135),np.uint8)
    h,w=sprite.shape[:2]; image[400:400+h,700:700+w]=sprite
    for profile in ["jp","cn","tw"]:
        observation=Detector(profile=profile,home_icons=library).observe(Frame.from_image(image))
        assert observation.scene==Scene.HOME
        assert observation.meta["home_icon_variant"]=="additional_style"


def test_two_different_shared_styles_at_separate_locations_are_ambiguous():
    detector=Detector()
    image=np.full((720,1280,3),(85,105,135),np.uint8)
    for x,name in [(300,"handset_3d"),(900,"handset_flat")]:
        sprite=detector.home_icons.color_templates[name];h,w=sprite.shape[:2]
        image[350:350+h,x:x+w]=sprite
    assert "open_momo" not in detector.observe(Frame.from_image(image)).targets
