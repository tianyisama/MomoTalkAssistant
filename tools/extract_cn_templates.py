"""Extract CN control samples, reusing language-independent JP icon assets."""
from pathlib import Path
import json
import shutil
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"assets/templates_cn"
SAMPLES=ROOT/"_analysis/cn"
SPECS=[
    ("home_phone","01_home",(198,188,245,238),.77),
    ("home_notice","01_home",(50,176,113,235),.75),
    ("momo_logo","03_people",(217,157,351,200),.84),
    ("people_label","03_people",(346,248,417,284),.83),
    ("empty_chat","03_people",(1280,561,1455,598),.83),
    ("filter_latest","07_latest_chat",(737,248,796,282),.84),
    ("filter_unread","04_chat_ready",(737,248,796,282),.84),
    ("sort_title","05_sort_ready",(353,331,420,369),.84),
    ("sort_unread_active","05_sort_ready",(802,428,868,462),.83),
    ("sort_unread_idle","06_sort_latest",(802,428,868,462),.83),
    ("sort_ok","05_sort_ready",(638,693,708,728),.84),
    ("reply_label","08_reply",(1189,762,1253,795),.84),
    ("bond_label","09_bond",(1189,796,1314,830),.84),
    ("story_start","10_story_info",(1235,819,1523,874),.84),
    ("menu_light","11_story_menu",(1761,40,1848,82),.84),
    ("menu_dark","12_expanded_menu",(1761,40,1848,82),.84),
    ("skip_question","13_skip_confirm",(812,647,1096,684),.84),
    ("skip_ok","13_skip_confirm",(1101,754,1198,808),.84),
    ("reward_title","14_reward",(740,191,1185,294),.84),
    ("reward_touch","14_reward",(879,924,1046,972),.84),
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
    (OUT/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"CN templates: {len(manifest)}, language-specific overrides: {len(SPECS)}")


if __name__=="__main__": main()
