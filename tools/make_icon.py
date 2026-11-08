"""Render the application's own geometric speech-bubble mark."""
from pathlib import Path
from PIL import Image,ImageDraw


def make_icon(root: Path):
    directory=root/"assets"; directory.mkdir(exist_ok=True)
    image=Image.new("RGBA",(256,256),(0,0,0,0))
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((8,8,248,248),radius=52,fill="#A32C55")
    draw.rounded_rectangle((48,55,208,177),radius=30,fill="#FFFFFF")
    draw.polygon([(73,165),(73,207),(117,170)],fill="#FFFFFF")
    for x in [86,128,170]: draw.ellipse((x-9,107,x+9,125),fill="#A32C55")
    image.save(directory/"app.ico",sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    image.save(directory/"app.png")


if __name__=="__main__":
    make_icon(Path(__file__).resolve().parents[1])
