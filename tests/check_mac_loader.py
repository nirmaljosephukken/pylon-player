"""Exercise Mac loader control flow with simulated dynamic libraries on any OS."""
import ast,builtins,os,tempfile,types,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TREE=ast.parse((ROOT/'app/engine.py').read_text(encoding='utf-8'))
CODE=compile(ast.Module(body=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in ('_point_at','load_vlc')],type_ignores=[]),'<mac-loader>','exec')
class MacLoader(unittest.TestCase):
 def run_loader(self,fail=None,plugins=True):
  with tempfile.TemporaryDirectory() as d:
   folder=Path(d)/'VLC.app';lib=folder/'Contents/MacOS/lib';lib.mkdir(parents=True)
   (lib/'libvlc.dylib').touch();(lib/'libvlccore.dylib').touch()
   if plugins:(folder/'Contents/MacOS/plugins').mkdir()
   calls=[]
   def cdll(path,mode=0):
    calls.append(Path(path).name)
    if Path(path).name==fail:raise OSError('dlopen: incompatible architecture: expected arm64')
    return object()
   def importing(name,*args,**kwargs):
    if name=='vlc':
     self.assertEqual(calls,['libvlccore.dylib','libvlc.dylib'])
     return types.SimpleNamespace(dll=object())
    return builtins.__import__(name,*args,**kwargs)
   ns={'os':types.SimpleNamespace(path=os.path,environ={},pathsep=os.pathsep),
       'sys':types.SimpleNamespace(platform='darwin',modules={}),
       'ctypes':types.SimpleNamespace(CDLL=cdll,RTLD_GLOBAL=256),
       '_MAC_LIBS':[],'vlc':None,'VLC_ERROR':'','VLC_DIR':'',
       '__builtins__':dict(vars(builtins),__import__=importing)}
   exec(CODE,ns);ok=ns['load_vlc'](str(folder));return ok,ns['VLC_ERROR'],calls
 def test_core_before_engine(self):self.assertTrue(self.run_loader()[0])
 def test_original_core_error(self):
  ok,error,calls=self.run_loader('libvlccore.dylib');self.assertFalse(ok);self.assertIn('expected arm64',error);self.assertEqual(calls,['libvlccore.dylib'])
 def test_original_engine_error(self):
  ok,error,calls=self.run_loader('libvlc.dylib');self.assertFalse(ok);self.assertIn('incompatible architecture',error)
 def test_missing_plugins(self):
  ok,error,calls=self.run_loader(plugins=False);self.assertFalse(ok);self.assertIn('plugin folder does not exist',error)
if __name__=='__main__':unittest.main()
