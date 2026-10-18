"""Repack unchanged 1.3.2 runtimes with the repository's current application.
Run after preparing build/tools and linux-old.tar (see BUILD.md).
"""
import copy,hashlib,io,re,shutil,struct,subprocess,tarfile,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'build'
VERSION=re.search(r'APP_VERSION = "([^"]+)"', (ROOT/'app/__init__.py').read_text()).group(1)
OUT=ROOT.parent/f'Pylon-{VERSION}/Downloads'
BASE=ROOT.parent/'Pylon-1.3.2/Downloads'

def sources():
 files={f'app/{p.name}':p.read_bytes() for p in (ROOT/'app').glob('*.py')}
 for name in ('main.py','LICENSE','THIRD_PARTY_NOTICES.md','pylon.ico','pylon.png','diag.py','diag.bat'):
  files[name]=(ROOT/name).read_bytes()
 return files

def macos():
 replacements={f'Pylon.app/Contents/Resources/pylon/{n}':b for n,b in sources().items()}
 replacements.pop('Pylon.app/Contents/Resources/pylon/diag.bat')
 replacements.pop('Pylon.app/Contents/Resources/pylon/pylon.ico')
 replacements['Pylon.app/Contents/Info.plist']=(ROOT/'packaging/macos/Info.plist').read_bytes()
 replacements['Pylon.app/Contents/MacOS/Pylon']=(ROOT/'packaging/macos/Pylon-launcher.sh').read_bytes()
 with zipfile.ZipFile(BASE/'Pylon-1.3.2-macOS.zip') as old,zipfile.ZipFile(OUT/f'Pylon-{VERSION}-macOS.zip','w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as new:
  for info in old.infolist():
   if '__pycache__/' in info.filename or info.filename.endswith('.pyc'):continue
   data=replacements.pop(info.filename,None)
   if data is None:data=old.read(info)
   new.writestr(info,data)
  for name in list(replacements):
   if name.startswith('Pylon.app/Contents/Resources/pylon/app/') and name.endswith('.py'):
    info=zipfile.ZipInfo(name);info.create_system=3;info.external_attr=0o100644<<16
    info.compress_type=zipfile.ZIP_DEFLATED
    new.writestr(info,replacements.pop(name))
  assert not replacements, sorted(replacements)
 print('macOS package written',flush=True)

def linux():
 replacements={f'usr/share/pylon/{n}':b for n,b in sources().items()}
 # Linux payload has no Windows diagnostics/ICO in the baseline; add only existing files.
 replacements.pop('usr/share/pylon/diag.bat');replacements.pop('usr/share/pylon/pylon.ico');replacements.pop('usr/share/pylon/pylon.png')
 replacements['usr/share/metainfo/io.github.nirmaljosephukken.pylon.appdata.xml']=(ROOT/'packaging/linux/io.github.nirmaljosephukken.pylon.appdata.xml').read_bytes()
 replacements['AppRun']=(ROOT/'packaging/linux/AppRun').read_bytes().replace(b'\r\n',b'\n')
 # #28: a bundled libxkbcommon-x11 paired with a newer system libxkbcommon crashes Qt.
 # Ship it only as a fallback, together with the libxkbcommon it was built against.
 moves={'usr/lib/libxkbcommon-x11.so.0':'usr/lib/fallback/libxkbcommon-x11.so.0'}
 fallback=ROOT/'packaging/linux/fallback'
 additions={'usr/lib/fallback/libxkbcommon.so.0':(fallback/'libxkbcommon.so.0').read_bytes(),
            'usr/share/pylon/licenses/libxkbcommon0-copyright.txt':(fallback/'libxkbcommon0-copyright.txt').read_bytes()}
 with tarfile.open(BUILD/'linux-old.tar') as old,tarfile.open(BUILD/'linux-new.tar','w',format=tarfile.PAX_FORMAT) as new:
  for info in old:
   if '__pycache__/' in info.name or info.name.endswith('.pyc'):continue
   if info.name=='usr/lib/fallback' or info.name.startswith('usr/lib/fallback/'):continue
   if info.name in moves:
    if info.name=='usr/lib/libxkbcommon-x11.so.0':
     d=tarfile.TarInfo('usr/lib/fallback');d.type=tarfile.DIRTYPE;d.mode=0o755;d.mtime=info.mtime;new.addfile(d)
    moved=copy.copy(info);moved.name=moves.pop(info.name)
    new.addfile(moved,old.extractfile(info));continue
   data=replacements.pop(info.name,None)
   if data is not None:
    info=copy.copy(info);info.size=len(data);new.addfile(info,io.BytesIO(data))
   else:new.addfile(info,old.extractfile(info) if info.isfile() else None)
  for name in list(replacements):
   if name.startswith('usr/share/pylon/app/') and name.endswith('.py'):
    data=replacements.pop(name);info=tarfile.TarInfo(name);info.mode=0o644;info.size=len(data)
    new.addfile(info,io.BytesIO(data))
  for name,data in additions.items():
   info=tarfile.TarInfo(name);info.mode=0o644;info.size=len(data);new.addfile(info,io.BytesIO(data))
  assert not replacements,sorted(replacements)
  assert not moves,sorted(moves)
 tool=BUILD/'tools/squashfs/squashfs-tools-ng-1.3.2-mingw64/bin/tar2sqfs.exe'
 if not tool.exists():tool=Path(shutil.which('tar2sqfs') or tool)
 with (BUILD/'linux-new.tar').open('rb') as src:
  subprocess.run([str(tool),'-f','-q','-c','zstd','-j','4',str(BUILD/'linux-new.sqfs')],stdin=src,check=True)
 validate_squashfs(BUILD/'linux-new.sqfs')
 with (OUT/f'Pylon-{VERSION}-x86_64.AppImage').open('wb') as dest:
  for p in (BUILD/'linux-runtime',BUILD/'linux-new.sqfs'):
   with p.open('rb') as src:shutil.copyfileobj(src,dest)
 print('Linux package written',flush=True)

def validate_squashfs(path):
 # The bundled AppImage runtime supports zlib and zstd, but NOT xz.
 # Check the actual superblock before assembling a distributable.
 with path.open('rb') as src:header=src.read(96)
 if len(header)!=96 or header[:4]!=b'hsqs':
  raise ValueError('Invalid SquashFS header')
 compressor=struct.unpack_from('<H',header,20)[0]
 if compressor not in (1,6):
  raise ValueError(f'Compressor {compressor} is unsupported by the bundled AppImage runtime; use gzip or zstd')

def windows_stage():
 stage=BUILD/'windows/Pylon';stage.mkdir(parents=True,exist_ok=True)
 installed=ROOT.parent/'Pylon-1.1/Pylon'
 for name in ('Python','licenses'):
  shutil.copytree(installed/name,stage/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
 for name,data in sources().items():
  p=stage/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 shutil.copy2(ROOT/'Pylon.exe',stage/'Pylon.exe')
 print('Windows payload staged',flush=True)

if __name__=='__main__':
 import sys
 OUT.mkdir(parents=True,exist_ok=True)
 for line in (BASE/'SHA256SUMS.txt').read_text().splitlines():
  expected,name=line.split(maxsplit=1)
  with (BASE/name).open('rb') as src:
   assert hashlib.file_digest(src,'sha256').hexdigest()==expected,name
 {'macos':macos,'linux':linux,'windows':windows_stage}[sys.argv[1]]()

