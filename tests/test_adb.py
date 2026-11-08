from pathlib import Path
import threading

import cv2
import numpy as np
import pytest

from momotalk_assistant.adb import (AdbClient,AdbError,Device,DisplayBinding,is_game_package,
                                  physical_displays,resumed_displays,select_display)


@pytest.fixture
def client(tmp_path):
    executable=tmp_path/"adb.exe"; executable.write_bytes(b"test-placeholder")
    client=AdbClient(str(executable),"test-device")
    client.binding=DisplayBinding(4,"4619827144452474627","com.YostarJP.BlueArchive")
    return client


def test_multidisplay_mapping_keeps_launcher_cn_and_jp_separate():
    activities="""Display #0 (activities from top to bottom):
 topResumedActivity=ActivityRecord{abc u0 com.saggitt.omega/.OmegaLauncher t2}
Display #4 (activities from top to bottom):
 topResumedActivity=ActivityRecord{def u0 com.YostarJP.BlueArchive/com.yostarjp.bluearchive.MxUnityPlayerActivity t286}
Display #3 (activities from top to bottom):
 topResumedActivity=ActivityRecord{ghi u0 com.RoamingStar.BlueArchive/com.tech.sdk.bridge.Main t285}
"""
    displays="""mViewports=[DisplayViewport{type=INTERNAL, displayId=0, uniqueId='local:111', orientation=1}, DisplayViewport{type=INTERNAL, displayId=4, uniqueId='local:444', orientation=1}]
"""
    assert resumed_displays(activities)=={0:"com.saggitt.omega",4:"com.YostarJP.BlueArchive",3:"com.RoamingStar.BlueArchive"}
    assert physical_displays(displays)=={0:"111",4:"444"}


def test_screenshot_strips_android_warning_and_uses_physical_display(client,monkeypatch):
    image=np.full((240,320,3),(60,100,150),np.uint8)
    _,encoded=cv2.imencode(".png",image)
    calls=[]
    def run(*args,**kwargs):
        calls.append(args)
        return b"[Warning] Multiple displays were found\n"+encoded.tobytes()
    monkeypatch.setattr(client,"_run",run)
    assert np.array_equal(client.screenshot(),image)
    assert calls[0]==("exec-out","screencap","-p","-d","4619827144452474627")


def test_tap_and_swipe_use_same_logical_display(client,monkeypatch):
    calls=[]; monkeypatch.setattr(client,"_run",lambda *args,**kwargs:calls.append(args) or b"")
    client.tap((120,200)); client.swipe((120,200),(120,100))
    assert calls[0]==("shell","input","-d","4","tap","120","200")
    assert calls[1][:5]==("shell","input","-d","4","swipe")


def test_read_only_preview_can_show_device_without_a_running_game(client,monkeypatch):
    client.binding=None
    monkeypatch.setattr(client,"display_targets",lambda:[DisplayBinding(0,"111","com.android.launcher3")])
    image=np.full((240,320,3),120,np.uint8)
    _,encoded=cv2.imencode(".png",image)
    calls=[]
    monkeypatch.setattr(client,"_run",lambda *args,**kwargs:calls.append(args) or encoded.tobytes())
    assert np.array_equal(client.screenshot(allow_default=True),image)
    assert calls==[("exec-out","screencap","-p","-d","111")]
    assert client.binding.logical_id==0


def test_explicit_cn_selection_keeps_capture_and_touch_on_cn_display(client,monkeypatch):
    screens=[DisplayBinding(0,"111","com.android.launcher3"),
             DisplayBinding(3,"333","com.RoamingStar.BlueArchive"),
             DisplayBinding(4,"444","com.YostarJP.BlueArchive")]
    monkeypatch.setattr(client,"display_targets",lambda:screens)
    image=np.full((240,320,3),80,np.uint8); _,encoded=cv2.imencode(".png",image)
    calls=[]
    monkeypatch.setattr(client,"_run",lambda *args,**kwargs:calls.append(args) or encoded.tobytes())
    client.bind_display(3,expected_package="com.RoamingStar.BlueArchive")
    client.screenshot(); client.tap((120,130))
    assert calls[0]==("exec-out","screencap","-p","-d","333")
    assert calls[1]==("shell","input","-d","3","tap","120","130")


def test_default_display_is_desktop_even_when_jp_is_running():
    screens=[DisplayBinding(4,"444","com.YostarJP.BlueArchive"),DisplayBinding(0,"111","com.android.launcher3")]
    assert select_display(screens,None).logical_id==0
    with pytest.raises(AdbError): select_display(screens,3)


def test_unbound_client_never_automatically_picks_jp_on_another_display(client,monkeypatch):
    client.binding=None
    screens=[DisplayBinding(0,"111","com.android.launcher3"),DisplayBinding(4,"444","com.YostarJP.BlueArchive")]
    monkeypatch.setattr(client,"display_targets",lambda:screens)
    assert client.bind_game_display() is None
    assert client.binding is None
    assert client.foreground_package()==""


def test_missing_multidisplay_mapping_does_not_capture_an_arbitrary_display(client,monkeypatch):
    client.binding=None
    screens=[DisplayBinding(0,None,"com.android.launcher3"),DisplayBinding(4,"444","com.YostarJP.BlueArchive")]
    monkeypatch.setattr(client,"display_targets",lambda:screens)
    with pytest.raises(AdbError): client.bind_display(0)
    assert client.binding is None


def test_changed_app_on_selected_display_does_not_bind_another_game(client,monkeypatch):
    screens=[DisplayBinding(3,"333","com.RoamingStar.BlueArchive"),DisplayBinding(4,"444","com.YostarJP.BlueArchive")]
    monkeypatch.setattr(client,"display_targets",lambda:screens)
    with pytest.raises(AdbError): client.bind_display(3,expected_package="com.YostarJP.BlueArchive")


def test_aliases_of_one_running_vm_are_grouped(client,monkeypatch):
    boot=b"343d2652-67ea-44ba-a5da-39ad8256c493\n"
    monkeypatch.setattr(AdbClient,"_run",lambda self,*args,**kwargs:boot)
    devices=[Device("127.0.0.1:16416","device","SM S9210"),Device("127.0.0.1:7555","device","SM S9210"),Device("emulator-5556","device","SM S9210")]
    grouped=client.group_devices(devices)
    assert len(grouped)==1 and grouped[0].serial=="emulator-5556"
    assert grouped[0].matches("127.0.0.1:7555")
    assert grouped[0].aliases==("127.0.0.1:16416","127.0.0.1:7555")


def test_same_model_with_different_boots_remains_separate(client,monkeypatch):
    boot_ids={"emulator-1":b"343d2652-67ea-44ba-a5da-39ad8256c493", "emulator-2":b"2477d717-8d90-46ce-b6cd-7da07fdc011b"}
    monkeypatch.setattr(AdbClient,"_run",lambda self,*args,**kwargs:boot_ids[self.serial])
    grouped=client.group_devices([Device(key,"device","Same model") for key in boot_ids])
    assert len(grouped)==2


def test_missing_identity_does_not_merge_unrelated_devices(client,monkeypatch):
    monkeypatch.setattr(AdbClient,"_run",lambda self,*args,**kwargs:b"")
    grouped=client.group_devices([Device("emulator-1","device","Same model"),Device("emulator-2","device","Same model")])
    assert len(grouped)==2


def test_stop_prevents_any_new_input(client,monkeypatch):
    calls=[]; monkeypatch.setattr(client,"_run",lambda *args,**kwargs:calls.append(args) or b"")
    client.stop=threading.Event(); client.stop.set()
    with pytest.raises(InterruptedError): client.tap((1,1))
    with pytest.raises(InterruptedError): client.swipe((1,1),(2,2))
    assert calls==[]


@pytest.mark.parametrize("endpoint",["127.0.0.1:1234; shell input tap 1 1","host:0","host:99999","a b:1234"])
def test_endpoint_is_data_not_shell_code(client,endpoint):
    with pytest.raises(AdbError): client.connect(endpoint)


def test_game_check_rejects_android_launcher_and_other_apps():
    assert is_game_package("com.YostarJP.BlueArchive")
    assert not is_game_package("com.saggitt.omega")
    assert not is_game_package("")
