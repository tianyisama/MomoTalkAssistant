import threading

import pytest

from momotalk_assistant.options import RunOptions
from momotalk_assistant.preview import PreviewService,PreviewRequest


def test_slow_old_device_never_overwrites_latest_device_and_pending_requests_coalesce():
    entered=threading.Event(); release=threading.Event(); received=threading.Event()
    calls=[]; events=[]
    def load(request):
        calls.append(request.serial)
        if request.serial=="old":
            entered.set()
            assert release.wait(3)
        return {"message":request.serial}
    def emit(event): events.append(event); received.set()
    service=PreviewService(emit,load)
    try:
        service.request("old")
        assert entered.wait(3)
        service.request("intermediate")
        latest=service.request("latest")
        release.set()
        assert received.wait(3)
        assert calls==["old","latest"]
        assert [e["serial"] for e in events]==["latest"]
        assert events[0]["generation"]==latest
    finally:
        release.set(); service.close()


def test_starting_a_run_invalidates_an_outstanding_selection_preview():
    entered=threading.Event(); release=threading.Event(); events=[]
    def load(request): entered.set(); release.wait(3); return {}
    service=PreviewService(events.append,load)
    service.request("selected-device")
    assert entered.wait(3)
    service.invalidate()
    release.set()
    service.close()
    service._thread.join(3)
    assert not service._thread.is_alive()
    assert events==[]


def test_selection_preview_does_not_require_a_running_game_or_send_touches(monkeypatch):
    import numpy as np
    import momotalk_assistant.preview as preview
    from momotalk_assistant.adb import DisplayBinding
    calls=[]
    class Client:
        binding=None
        def __init__(self,path,serial): calls.append((path,serial))
        def display_targets(self): return [DisplayBinding(0,"111","com.android.launcher3")]
        def bind_display(self,logical_id,*,expected_package):
            self.binding=DisplayBinding(logical_id,"111",expected_package)
            calls.append(("bind",logical_id,expected_package))
        def screenshot(self):
            calls.append(("capture",self.binding.logical_id))
            return np.full((720,1280,3),100,np.uint8)
    monkeypatch.setattr(preview,"AdbClient",Client)
    service=PreviewService(lambda event:None)
    result=service._capture(PreviewRequest(1,"emulator-5554","custom-adb"))
    assert calls==[("custom-adb","emulator-5554"),("bind",0,"com.android.launcher3"),("capture",0)]
    assert result["resolution"]==(1280,720)
    assert result["target"].package=="com.android.launcher3"
    assert "选择支持的游戏" in result["message"]
    service.close()


@pytest.mark.parametrize("display_id,expected",[(None,0),(0,0),(3,3),(4,4)])
def test_device_preview_obeys_application_selection_including_desktop(monkeypatch,display_id,expected):
    import numpy as np
    import momotalk_assistant.preview as preview
    from momotalk_assistant.adb import DisplayBinding,select_display
    screens=[DisplayBinding(0,"111","com.android.launcher3"),DisplayBinding(3,"333","com.RoamingStar.BlueArchive"),DisplayBinding(4,"444","com.YostarJP.BlueArchive")]
    calls=[]
    class Client:
        binding=None
        def __init__(self,path,serial): pass
        def display_targets(self): return screens
        def bind_display(self,logical_id,*,expected_package):
            self.binding=select_display(screens,logical_id)
            calls.append(logical_id)
        def screenshot(self): return np.full((720,1280,3),self.binding.logical_id*30,np.uint8)
    monkeypatch.setattr(preview,"AdbClient",Client)
    service=PreviewService(lambda event:None)
    result=service._capture(PreviewRequest(1,"emulator-5554","",display_id))
    assert calls==[expected]
    assert result["target"].logical_id==expected
    assert result["image"][300,300,0]==expected*30
    service.close()


def test_switching_apps_within_same_device_discards_old_screen():
    entered=threading.Event(); release=threading.Event(); received=threading.Event(); events=[]
    def load(request):
        if request.display_id==3: entered.set(); assert release.wait(3)
        return {}
    def emit(event): events.append(event); received.set()
    service=PreviewService(emit,load)
    try:
        service.request("same-device","",3)
        assert entered.wait(3)
        service.request("same-device","",4)
        release.set(); assert received.wait(3)
        assert [event["requested_display"] for event in events]==[4]
    finally:
        release.set(); service.close()


@pytest.mark.parametrize("value",[0,-1,121,float("nan"),float("inf")])
def test_invalid_wait_values_preserve_the_active_setting(value):
    settings=RunOptions(8)
    with pytest.raises(ValueError): settings.set_idle_seconds(value)
    assert settings.idle_seconds==8
