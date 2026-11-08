import tkinter as tk
from tkinter import ttk

import pytest

from momotalk_assistant.gui import Application


@pytest.fixture
def app(monkeypatch,tmp_path):
    import momotalk_assistant.gui as gui
    monkeypatch.setattr(gui,"data_dir",lambda:tmp_path)
    try:
        instance=Application()
    except tk.TclError as error:
        pytest.skip(f"Desktop display unavailable: {error}")
    instance.root.withdraw()
    yield instance
    instance.close()


def test_usage_popup_body_is_exactly_the_requested_text(app):
    expected="使用方法：1.请先打开模拟器，确认设置里允许ADB调试已打开。2.启动游戏，确认位于大厅且不处于待机状态。3.点击查找模拟器，选择正确的模拟器。4.选择对应的画面，然后点击开始处理未读即可自动运行。Tips：1.如果模拟器有其他应用要操作，请将其拖出模拟器独立于碧蓝档案运行。2.后台运行期间，不影响模拟器以外的其他程序，电脑可以自由操作。"
    app.show_usage()
    app.usage_window.withdraw()
    assert "".join(label.cget("text") for label in app.usage_text_widgets)==expected
    assert len(app.usage_body_labels)==6
    assert app.github_button.winfo_toplevel()!=app.usage_window
    original=app.usage_window
    app.show_usage()
    assert app.usage_window is original


def test_repository_button_belongs_to_main_window_and_opens_exact_repository(app,monkeypatch):
    import momotalk_assistant.gui as gui
    opened=[]
    monkeypatch.setattr(gui.webbrowser,"open",lambda url,**kwargs:opened.append(url))
    assert app.github_button.winfo_toplevel()==app.root
    assert app.github_button.master==app.main_footer
    assert app.github_button.cget("image")
    app.github_button.invoke()
    assert opened==["https://github.com/tianyisama/MomoTalkAssistant"]


def test_main_controls_remain_inside_the_sidebar_after_adding_help(app):
    app.root.geometry("1120x840")
    app.root.update_idletasks()
    sidebar=app.usage_button.master
    buttons=[child for child in sidebar.winfo_children() if isinstance(child,ttk.Button)]
    assert buttons
    for button in buttons:
        assert button.winfo_y()+button.winfo_height()<=sidebar.winfo_height()


def test_usage_and_connection_popups_are_centered_on_main_window(app):
    app.root.geometry("1120x840+240+140")
    app.root.deiconify()
    app.root.update_idletasks()
    app.show_usage()
    app.connection_settings()
    app.root.update_idletasks()
    center_x=app.root.winfo_x()+app.root.winfo_width()/2
    center_y=app.root.winfo_y()+app.root.winfo_height()/2
    for window in (app.usage_window,app.settings_window):
        assert abs(window.winfo_x()+window.winfo_width()/2-center_x)<12
        assert abs(window.winfo_y()+window.winfo_height()/2-center_y)<12
        window.withdraw()
