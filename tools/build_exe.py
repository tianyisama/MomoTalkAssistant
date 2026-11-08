"""Build a portable Windows executable without changing system Python."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description="Build a portable MomoTalk Assistant executable")
    parser.add_argument("--output-dir",default=str(ROOT/"dist"),help="Directory for the executable and usage guide")
    args=parser.parse_args()
    output=Path(args.output_dir).resolve()
    output.mkdir(parents=True,exist_ok=True)
    from momotalk_assistant.adb import resolve_adb
    from make_icon import make_icon
    make_icon(ROOT)
    adb=Path(resolve_adb())
    bundled=ROOT/"assets/adb"
    bundled.mkdir(parents=True,exist_ok=True)
    for name in ["adb.exe","AdbWinApi.dll","AdbWinUsbApi.dll","NOTICE.txt"]:
        source=adb.parent/name
        destination=bundled/name
        if source.is_file() and source.resolve()!=destination.resolve():
            shutil.copy2(source,destination)
    if not (bundled/"adb.exe").is_file(): raise RuntimeError("ADB 未能加入发行包")
    build=ROOT/"_build"
    temporary=build/"tmp"; temporary.mkdir(parents=True,exist_ok=True)
    environment=os.environ.copy()
    environment.update({"TEMP":str(temporary),"TMP":str(temporary),
                        "PYINSTALLER_CONFIG_DIR":str(build/"pyinstaller-cache"),
                        "PYTHONIOENCODING":"utf-8"})
    command=[sys.executable,"-m","PyInstaller","--noconfirm","--onefile","--windowed",
             "--name","MomoTalkAssistant","--icon",str(ROOT/"assets/app.ico"),
             "--distpath",str(output),"--workpath",str(build/"pyinstaller"),
             "--specpath",str(build),"--add-data",f"{ROOT/'assets/templates'}:assets/templates",
             "--add-data",f"{ROOT/'assets/templates_cn'}:assets/templates_cn",
             "--add-data",f"{ROOT/'assets/templates_tw'}:assets/templates_tw",
             "--add-data",f"{ROOT/'assets/home_icons'}:assets/home_icons",
             "--add-data",f"{ROOT/'assets/app.ico'}:assets", "--add-data",f"{ROOT/'assets/app.png'}:assets"]
    command += ["--add-data",f"{ROOT/'assets/github-mark.png'}:assets"]
    for name in ["adb.exe","AdbWinApi.dll","AdbWinUsbApi.dll"]:
        path=bundled/name
        if path.is_file(): command += ["--add-binary",f"{path}:assets/adb"]
    notice=bundled/"NOTICE.txt"
    if notice.is_file(): command += ["--add-data",f"{notice}:assets/adb"]
    command.append(str(ROOT/"main.py"))
    subprocess.run(command,cwd=ROOT,env=environment,check=True)
    shutil.copy2(ROOT/"README.md",output/"使用说明.md")
    print(f"Built: {output/'MomoTalkAssistant.exe'}")


if __name__=="__main__": main()
