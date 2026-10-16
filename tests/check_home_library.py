"""Regression checks for privacy, queue display, view sorting and home actions."""
import os,sys,tempfile,copy,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication,QLabel,QInputDialog,QPushButton
from app import engine
engine.vlc=None
from app.window import MainWindow
from app.store import Store
from app.dialogs import PreferencesDialog
from app.util import pretty_title
app=QApplication.instance() or QApplication([])
class HomeLibrary(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.path=str(self.root/'Show.Name.S02E03.1080p.WEB-DL.mkv');Path(self.path).touch()
  self.store=Store(str(self.root/'data.json'));self.store.set_setting('onboarded',True)
  self.other=str(self.root/'Other.mp4');Path(self.other).touch()
  self.store.data['recent']=[{'path':self.path,'t':1},{'path':self.other,'t':2}]
  self.store.data['positions'][self.path]={'pos':30000,'len':120000,'t':1,'watched':False}
  self.win=MainWindow(self.store);self.lib=self.win.library
  self.win._ui_timer.stop();self.win._time_timer.stop()
 def tearDown(self):
  self.store._save_timer.stop();self.win.deleteLater();app.processEvents();self.temp.cleanup()
 def test_home_visibility_preserves_data(self):
  original=copy.deepcopy(self.store.data)
  dlg=PreferencesDialog(self.win)
  for cont,recent in ((False,False),(True,False),(False,True),(True,True)):
   dlg._set_home_section('home_continue',cont);dlg._set_home_section('home_recent',recent)
   labels=[w.text() for w in self.win.home.widget().findChildren(QLabel)]
   self.assertEqual('Continue watching' in labels,cont)
   self.assertEqual('Recently played' in labels,recent)
   self.assertEqual(self.store.data['positions'],original['positions'])
   self.assertEqual(self.store.data['recent'],original['recent'])
  self.store.save_now();loaded=Store(self.store.path);self.assertTrue(loaded.setting('home_continue'));loaded._save_timer.stop()
  dlg.deleteLater()
 def test_queue_and_suggestion(self):
  self.win.queue=[{'path':self.path,'title':'Original filename'}];self.lib.refresh_queue()
  self.assertEqual(self.lib.queue.item(0).text(),'Original filename')
  dlg=PreferencesDialog(self.win);dlg._set_simple_queue(True)
  self.assertEqual(self.lib.queue.item(0).text(),pretty_title(self.path))
  self.assertEqual(self.lib.queue.item(0).toolTip(),self.path)
  self.assertEqual(self.win.queue[0]['title'],'Original filename')
  with patch.object(QInputDialog,'getText',return_value=('Chosen name',True)) as ask:
   self.lib.save_to_playlist([self.path],'Suggested folder')
   self.assertEqual(ask.call_args.kwargs['text'],'Suggested folder')
  self.assertEqual(self.store.data['playlists']['Chosen name'],[self.path]);dlg.deleteLater()
 def test_sort_counts_and_music(self):
  self.store.data['playlists']={'Zulu':[self.path],'Alpha':[self.path,self.path]}
  self.lib.refresh_playlists();self.assertEqual(self.lib.playlists_count.text(),'2 playlists')
  self.lib.playlists_sort.setCurrentIndex(self.lib.playlists_sort.findData('count'))
  self.assertTrue(self.lib.pl_list.item(0).text().startswith('Alpha'))
  self.lib.playlists_sort.setCurrentIndex(self.lib.playlists_sort.findData('reverse'))
  self.assertTrue(self.lib.pl_list.item(0).text().startswith('Zulu'))
  self.lib.pl_search.setText('none');self.assertEqual(self.lib.playlists_count.text(),'0 playlists')
  self.store.data['streams']=[{'name':'Zulu','url':'https://example.com/z'},{'name':'Alpha','url':'https://example.com/a'}]
  self.lib.streams_sort.setCurrentIndex(self.lib.streams_sort.findData('name'))
  self.assertEqual(self.lib.st_list.item(0).text(),'Alpha');self.assertEqual(self.lib.streams_count.text(),'2 streams')
  music=self.lib.music;music.songs={self.path:{'artist':'Test','album':'Album','title':'Track'}}
  for mode in ('artists','albums','songs'):
   self.lib._music_mode(mode);self.assertEqual(self.lib.music_count.text(),'1 '+mode)
   self.lib.music_search.setText('no matching entry');self.assertEqual(self.lib.music_count.text(),'0 '+mode)
   self.lib.music_search.clear()
 def test_context_actions_and_swatch(self):
  actions=dict(self.win.home._card_actions('media',self.path))
  actions['Mark as watched']();self.assertTrue(self.store.position(self.path)['watched'])
  actions['Remove from history (including resume position)']()
  self.assertEqual(self.store.data['recent'],[{'path':self.other,'t':2}]);self.assertNotIn(self.path,self.store.data['positions']);self.assertTrue(Path(self.path).exists())
  dlg=PreferencesDialog(self.win)
  b=dlg._colour_button('Test',['#00ffff','#ff00ff'],False,lambda:None)
  self.assertEqual(b.iconSize().width(),24)
  im=b.icon().pixmap(24,20).toImage();self.assertGreater(im.pixelColor(20,10).alpha(),0)
  b.deleteLater();dlg.deleteLater()
if __name__=='__main__':unittest.main()
