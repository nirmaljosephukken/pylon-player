"""Repack unchanged 1.3.2 runtimes with the repository's 1.3.3 application.
Run after preparing build/tools and linux-old.tar (see BUILD.md).
"""
import copy,hashlib,io,shutil,subprocess,tarfile,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'build'
OUT=ROOT.parent/'Pylon-1.3.3/Downloads'
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
 with zipfile.ZipFile(BASE/'Pylon-1.3.2-macOS.zip') as old,zipfile.ZipFile(OUT/'Pylon-1.3.3-macOS.zip','w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as new:
  for info in old.infolist():
   if '__pycache__/' in info.filename or info.filename.endswith('.pyc'):continue
   data=replacements.pop(info.filename,None)
   if data is None:data=old.read(info)
   new.writestr(info,data)
  assert not replacements, sorted(replacements)
 print('macOS package written',flush=True)

def linux():
 replacements={f'usr/share/pylon/{n}':b for n,b in sources().items()}
 # Linux payload has no Windows diagnostics/ICO in the baseline; add only existing files.
 replacements.pop('usr/share/pylon/diag.bat');replacements.pop('usr/share/pylon/pylon.ico');replacements.pop('usr/share/pylon/pylon.png')
 replacements['usr/share/metainfo/io.github.nirmaljosephukken.pylon.appdata.xml']=(ROOT/'packaging/linux/io.github.nirmaljosephukken.pylon.appdata.xml').read_bytes()
 with tarfile.open(BUILD/'linux-old.tar') as old,tarfile.open(BUILD/'linux-new.tar','w',format=tarfile.PAX_FORMAT) as new:
  for info in old:
   if '__pycache__/' in info.name or info.name.endswith('.pyc'):continue
   data=replacements.pop(info.name,None)
   if data is not None:
    info=copy.copy(info);info.size=len(data);new.addfile(info,io.BytesIO(data))
   else:new.addfile(info,old.extractfile(info) if info.isfile() else None)
  assert not replacements,sorted(replacements)
 tool=BUILD/'tools/squashfs/squashfs-tools-ng-1.3.2-mingw64/bin/tar2sqfs.exe'
 with (BUILD/'linux-new.tar').open('rb') as src:
  subprocess.run([str(tool),'-f','-q','-c','xz','-j','4',str(BUILD/'linux-new.sqfs')],stdin=src,check=True)
 with (OUT/'Pylon-1.3.3-x86_64.AppImage').open('wb') as dest:
  for p in (BUILD/'linux-runtime',BUILD/'linux-new.sqfs'):
   with p.open('rb') as src:shutil.copyfileobj(src,dest)
 print('Linux package written',flush=True)

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

