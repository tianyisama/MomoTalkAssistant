# 桃信助手

基于adb实现对模拟器的读取和控制，允许后台自动刷桃信~~(后备能源，启动！)~~。支持国服/B服/日服/国际服(繁体中文)，支持任意模拟器

[下载最新发行版](https://github.com/tianyisama/MomoTalkAssistant/releases/latest))

## 使用 EXE

1. 下载好后，双击运行 `MomoTalkAssistant.exe`。
2. 打开模拟器，确认模拟器已开启允许adb调试。打开游戏确保位于大厅且不处于待机状态。
3. 点击“查找模拟器”，选择模拟器，选择相应的画面。
4. 选择相应游戏画面后，点击“开始处理未读”。
5. 点击“停止”或在工具窗口内按 Esc 即可停止运行。


## 兼容范围

- 理论支持任意模拟器，已确认可在MuMu/雷电模拟器上运行。
- 支持国服/日服/国际服(繁体中文)。理论支持B服(没账号测试不了)。


## 区服与画面识别

本项目基于包名识别游戏类型

| 应用包名 | 区服 | 识别模板 |
|---|---|---|
| `com.YostarJP.BlueArchive` | 日服 | 日文 |
| `com.RoamingStar.BlueArchive` | 国服 | 简体中文 |
| `com.RoamingStar.BlueArchive.bilibili` | Bilibili 服 | 简体中文 |
| `com.nexon.bluearchive` | 国际服 | 繁体中文 |


## 从源码运行

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

开发测试与打包：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools\build_exe.py
```

离线识别：

```powershell
.\.venv\Scripts\python.exe main.py --probe "截图.png" --output "_analysis\probe"
.\.venv\Scripts\python.exe main.py --video "录屏.mp4" --output "_analysis\replay"
```

程序入口为 `main.py`，核心逻辑位于 `momotalk_assistant`。

实现参考：[Android ADB 文档](https://developer.android.com/tools/adb)、[OpenCV 模板匹配](https://docs.opencv.org/4.x/d4/dc6/tutorial_py_template_matching.html)、[PyInstaller 打包](https://pyinstaller.org/en/stable/usage.html)。
