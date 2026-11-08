import threading

import numpy as np

from momotalk_assistant.adb import DisplayBinding
from momotalk_assistant.models import Observation
from momotalk_assistant.runner import Runner


class StopAfterWait(threading.Event):
    def wait(self,timeout=None):
        self.set()
        return True


def test_reused_game_display_pauses_instead_of_switching_to_another_package(monkeypatch,tmp_path):
    import momotalk_assistant.runner as runner_module
    monkeypatch.setattr(runner_module,"data_dir",lambda:tmp_path)
    class Client:
        binding=DisplayBinding(4,"444","com.YostarJP.BlueArchive")
        def foreground_package(self): return "com.RoamingStar.BlueArchive"
        def screenshot(self): raise AssertionError("Changed application must not be inspected for actions")
        def tap(self,point): raise AssertionError("Changed application must not receive input")
    events=[]
    Runner(Client(),events.append,StopAfterWait(),detector=object()).run()
    assert any(e["kind"]=="status" and "所选游戏" in e["message"] for e in events)
    assert events[-1]["outcome"]=="stopped"
    assert events[-1]["stats"]["touches"]==0


def test_continuous_desktop_preview_never_searches_for_a_game(monkeypatch,tmp_path):
    import momotalk_assistant.runner as runner_module
    monkeypatch.setattr(runner_module,"data_dir",lambda:tmp_path)
    class Client:
        binding=DisplayBinding(0,"111","com.android.launcher3")
        def foreground_package(self): raise AssertionError("Preview must not retarget a game")
        def screenshot(self): return np.full((720,1280,3),80,np.uint8)
        def tap(self,point): raise AssertionError("Preview must not send input")
    class Detector:
        def observe(self,frame): return Observation()
    events=[]
    Runner(Client(),events.append,StopAfterWait(),preview_only=True,detector=Detector()).run()
    assert any(e["kind"]=="frame" and "模拟器桌面" in e["status"] for e in events)
    assert events[-1]["stats"]["touches"]==0
