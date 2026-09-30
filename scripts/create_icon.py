"""Rasterize the existing Lucide aperture mark for Windows (Lucide ISC license)."""
from pathlib import Path
import tomllib
from PIL import Image, ImageDraw
from PyInstaller.utils.win32.versioninfo import FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo

root = Path(__file__).resolve().parents[1]
image = Image.new("RGBA", (1024, 1024))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((16, 16, 1008, 1008), radius=230, fill="#182119")
scale, inset = 32, 128
def points(items):
    return [(inset+x*scale, inset+y*scale) for x,y in items]

color = "#c3d9a9"
draw.ellipse([points([(2,2)])[0], points([(22,22)])[0]], outline=color, width=43)
for start,end in [((14.31,8),(20.05,17.94)),((9.69,8),(21.17,8)),((7.38,12),(13.12,2.06)),
                  ((9.69,16),(3.95,6.06)),((14.31,16),(2.83,16)),((16.62,12),(10.88,21.94))]:
    draw.line(points([start,end]),fill=color,width=38)
image.save(root/'packaging/OpenPhoto.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])

version = tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
parts = tuple(int(p) for p in version.split('.')) + (0,)
metadata = VSVersionInfo(ffi=FixedFileInfo(filevers=parts,prodvers=parts,fileType=1),kids=[
    StringFileInfo([StringTable('040904B0', [StringStruct(k,v) for k,v in {
        'CompanyName':'OpenPhoto contributors','FileDescription':'OpenPhoto local photo laboratory',
        'FileVersion':version,'ProductVersion':version,'ProductName':'OpenPhoto',
        'LegalCopyright':'OpenPhoto contributors. GPL-3.0-or-later.'}.items()])]),
    VarFileInfo([VarStruct('Translation',[1033,1200])])])
(root/'packaging/version-info.txt').write_text(str(metadata),encoding='utf-8')
