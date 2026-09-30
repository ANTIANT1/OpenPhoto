# PyInstaller directory build. Models are local; no first-run downloads.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
datas = [(str(root / 'frontend/dist'), 'frontend/dist'),
         (str(root / 'models'), 'models'),
         (str(root / 'tools/vendor/rawtherapee'), 'tools/vendor/rawtherapee'),
         (str(root / 'tools/vendor/exiftool'), 'tools/vendor/exiftool'),
         (str(root / 'LICENSE'), '.'),
         (str(root / 'README.md'), '.'),
         (str(root / 'LIMITATIONS.md'), '.'),
         (str(root / 'SECURITY.md'), '.'),
         (str(root / 'docs'), 'docs'),
         (str(root / 'licenses'), 'licenses'),
         (str(root / 'tools/engines.lock.json'), 'tools'),
         (str(root / 'THIRD_PARTY_NOTICES.md'), '.')]
hidden = ['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto',
          'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on', 'webview.platforms.edgechromium',
          'sklearn.utils._cython_blas', 'sklearn.utils._weight_vector', 'sklearn.neighbors._typedefs',
          'scipy.special._ufuncs_cxx']
binaries = []
for package in ('openphoto', 'open_clip', 'mediapipe', 'rawpy', 'imagecodecs', 'tifffile', 'webview', 'alembic', 'psd_tools'):
    datas += collect_data_files(package, include_py_files=(package == 'openphoto'))
    binaries += collect_dynamic_libs(package)
for package in ('open_clip', 'mediapipe', 'webview', 'imagecodecs'):
    hidden += collect_submodules(package)
for package in ('openphoto', 'torch', 'torchvision', 'open-clip-torch', 'mediapipe', 'rawpy', 'imagecodecs', 'tifffile', 'numpy', 'scipy', 'opencv-contrib-python', 'psd-tools'):
    datas += copy_metadata(package)
datas = [(source, target) for source, target in datas if not str(source).endswith('direct_url.json')]
a = Analysis([str(root / 'packaging/entry.py')], pathex=[str(root / 'src')],
             binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=['IPython', 'notebook', 'jupyter', 'pytest', 'tkinter', 'PyQt5', 'PySide6'], noarchive=False)
# copy_metadata can add a whole directory; remove machine-local provenance after expansion.
a.datas = [entry for entry in a.datas if not str(entry[0]).endswith('direct_url.json')]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='OpenPhoto',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          icon=str(root / 'packaging/OpenPhoto.ico'), version=str(root / 'packaging/version-info.txt'))
diagnostic = EXE(pyz, a.scripts, [], exclude_binaries=True, name='OpenPhoto-Diagnostics',
                 debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True,
                 icon=str(root / 'packaging/OpenPhoto.ico'), version=str(root / 'packaging/version-info.txt'))
coll = COLLECT(exe, diagnostic, a.binaries, a.datas, strip=False, upx=False, name='OpenPhoto')
