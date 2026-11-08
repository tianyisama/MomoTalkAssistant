"""Extract international Traditional-Chinese controls from local captures."""
from pathlib import Path
import json
import shutil
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"assets/templates_tw"
SAMPLES=ROOT/"_analysis/global"
SPECS=[
    ("people_label","02_people",(347,248,416,285),.83),
    ("empty_chat","02_people",(1281,561,1467,598),.83),
    ("filter_latest","03_chat",(770,248,828,282),.84),
    ("filter_unread","06_unread_chat",(770,248,828,282),.84),
    ("sort_title","04_sort_latest",(354,333,421,369),.84),
    ("sort_unread_idle","04_sort_latest",(802,428,870,464),.83),
    ("sort_unread_active","05_sort_unread",(802,428,870,464),.83),
    ("sort_ok","04_sort_latest",(641,697,707,731),.84),
    ("reply_label","07_reply",(1189,637,1255,673),.84),
    ("bond_label","08_bond",(1188,797,1315,832),.84),
    ("story_start","09_story_info",(1235,819,1524,874),.84),
    ("menu_light","10_story_menu",(1748,40,1869,82),.84),
    ("menu_dark","11_expanded_menu",(1748,40,1869,82),.84),
    ("skip_question","12_skip_confirm",(810,646,1111,684),.84),
    ("skip_ok","12_skip_confirm",(1101,754,1198,809),.84),
    ("reward_title","13_reward",(749,194,1180,291),.83),
    ("reward_touch","13_reward",(742,928,1178,967),.84),
]


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    base=ROOT/"assets/templates"
    manifest=json.loads((base/"manifest.json").read_text(encoding="utf-8"))
    for item in manifest.values(): shutil.copy2(base/item["file"],OUT/item["file"])
    for name,sample,box,threshold in SPECS:
        im=Image.open(SAMPLES/(sample+".png")).crop(box)
        im=im.resize((max(2,round(im.width*2/3)),max(2,round(im.height*2/3))),Image.Resampling.LANCZOS)
        im.save(OUT/(name+".png"))
        manifest[name]={"file":name+".png","threshold":threshold,"source":sample+".png","source_crop":list(box)}
    (OUT/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(f"Traditional-Chinese templates: {len(manifest)}, overrides: {len(SPECS)}")


if __name__=="__main__": main()
