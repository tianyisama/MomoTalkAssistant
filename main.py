"""Desktop entry point; headless commands also work in the frozen executable."""
from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys


def main():
    parser=argparse.ArgumentParser(description="桃信助手：通过 ADB 后台处理日服、国服和国际服繁中未读桃信")
    parser.add_argument("--smoke-test",metavar="REPORT",help="检查随附资源并写入 JSON 后退出")
    parser.add_argument("--probe",metavar="IMAGE",help="仅识别一张本地截图")
    parser.add_argument("--video",metavar="VIDEO",help="分析本地录屏，不发送触控")
    parser.add_argument("--output",default="_analysis/validation",help="离线报告目录")
    parser.add_argument("--preview-file",default="",help="打开 GUI 并预览本地截图或录屏")
    args=parser.parse_args()
    if args.smoke_test:
        import tkinter
        import cv2
        from momotalk_assistant.vision import TemplateBank
        from momotalk_assistant.paths import resource_dir
        from momotalk_assistant.adb import resolve_adb
        from momotalk_assistant import __version__
        bank=TemplateBank()
        cn_bank=TemplateBank(resource_dir()/"assets/templates_cn")
        tw_bank=TemplateBank(resource_dir()/"assets/templates_tw")
        home_icons=TemplateBank(resource_dir()/"assets/home_icons")
        root=tkinter.Tk()
        root.withdraw()
        root.update_idletasks()
        patchlevel=str(root.tk.call("info","patchlevel"))
        root.destroy()
        report={"version":__version__,"templates":len(bank.templates),"opencv":cv2.__version__,
                "tk":patchlevel,"adb":resolve_adb(),"frozen":bool(getattr(sys,"frozen",False))}
        report["template_profiles"]={"jp":len(bank.templates),"cn":len(cn_bank.templates),"tw":len(tw_bank.templates)}
        report["home_icon_variants"]=len(home_icons.templates)
        path=Path(args.smoke_test); path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        return
    if args.probe:
        from momotalk_assistant.diagnostics import inspect_image
        from momotalk_assistant.vision import annotate,write_image
        frame,obs=inspect_image(Path(args.probe)); output=Path(args.output)
        output.mkdir(parents=True,exist_ok=True)
        write_image(output/"probe.png",annotate(frame,obs))
        result={"scene":str(obs.scene),"targets":{k:{"box":v.box.as_list(),"confidence":v.confidence}
                                                 for k,v in obs.targets.items()},"meta":obs.meta}
        (output/"probe.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        if sys.stdout: print(json.dumps(result,ensure_ascii=False))
        return
    if args.video:
        from momotalk_assistant.diagnostics import analyze_video
        result=analyze_video(Path(args.video),Path(args.output))
        if sys.stdout: print(json.dumps({k:v for k,v in result.items() if k!="frames"},ensure_ascii=False))
        return
    from momotalk_assistant.gui import Application
    Application(args.preview_file).run()


if __name__=="__main__":
    main()
