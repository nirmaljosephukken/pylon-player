"""Regression checks for collaboration browsing and playlist destinations."""
import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication,QInputDialog,QMessageBox
from app import engine
engine.vlc=None
from app.music import MusicLibrary,credit_artists
from app.store import Store
from app.window import MainWindow
app=QApplication.instance() or QApplication([])

class MusicAndPlaylists(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.store=Store(str(self.root/'data.json'))
  self.win=MainWindow(self.store);self.lib=self.win.library
  self.win._ui_timer.stop();self.win._time_timer.stop()
 def tearDown(self):
  self.store._save_timer.stop();self.win.deleteLater();app.processEvents();self.temp.cleanup()
 def test_credits(self):
  self.assertEqual(credit_artists('Shing02, Shing02, JO-JAY'),['Shing02','JO-JAY'])
  self.assertEqual(credit_artists('SPIN MASTER A-1 & SHING02',{'Shing02'}),['SPIN MASTER A-1','SHING02'])
  self.assertEqual(credit_artists('Earth, Wind & Fire'),['Earth, Wind & Fire'])
  self.assertEqual(credit_artists('AC/DC'),['AC/DC'])
  self.assertEqual(credit_artists('Simon & Garfunkel'),['Simon & Garfunkel'])
  self.assertEqual(credit_artists('A feat. B; b'),['A','B'])
  self.assertEqual(credit_artists('Unknown Person, Other Person'),['Unknown Person, Other Person'])
 def test_artist_membership_and_album_stability(self):
  music=self.lib.music;music.songs={}
  for name,credit,track in [('solo','Shing02',1),('collab','Shing02, Shing02, JO-JAY',2),('other','Another Artist',3)]:
   path=str(self.root/(name+'.mp3'));Path(path).touch()
   music.songs[path]={'artist':credit,'album_artist':'Various Artists','album':'Compilation','track':track}
  self.assertEqual(len(music.albums()),1)
  artists=dict(music.artists());self.assertEqual(set(artists),{'Shing02','JO-JAY','Another Artist'})
  self.assertEqual(len(artists['Shing02'][0]['tracks']),2)
  self.assertEqual(len(artists['JO-JAY'][0]['tracks']),1)
  self.assertEqual(len(music.all_songs()),3)
  self.lib.music_trail=[('artist','JO-JAY')]
  self.assertEqual(len(self.lib._artist_tracks('JO-JAY')),1)
  self.assertEqual(len(self.lib._album_by_key(music.albums()[0]['key'])['tracks']),1)
  self.lib.refresh_music()
 def test_append_and_destination(self):
  a=str(self.root/'a.mp3');b=str(self.root/'b.mp3')
  self.store.data['playlists']={'Favourites':[a]}
  with patch.object(QInputDialog,'getItem',return_value=('Add to: Favourites',True)):
   self.lib.save_to_playlist([a,b,b])
  self.assertEqual(self.store.data['playlists']['Favourites'],[a,b])
  with patch.object(QInputDialog,'getItem',return_value=('',False)):
   self.lib.save_to_playlist(['cancelled.mp3'])
  self.assertEqual(self.store.data['playlists']['Favourites'],[a,b])
  with patch.object(QInputDialog,'getItem',return_value=('Create a new playlist…',True)),patch.object(QInputDialog,'getText',return_value=('New',True)):
   self.lib.save_to_playlist([b])
  self.assertEqual(self.store.data['playlists']['New'],[b])
 def test_existing_name_does_not_overwrite(self):
  self.store.data['playlists']={'Existing':['old.mp3']}
  with patch.object(QInputDialog,'getText',return_value=('Existing',True)),patch.object(QMessageBox,'question',return_value=QMessageBox.No):
   self.lib.new_playlist(['new.mp3'])
  self.assertEqual(self.store.data['playlists']['Existing'],['old.mp3'])
  with patch.object(QInputDialog,'getText',return_value=('Existing',True)),patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):
   self.lib.new_playlist(['new.mp3'])
  self.assertEqual(self.store.data['playlists']['Existing'],['old.mp3','new.mp3'])

if __name__=='__main__':unittest.main()
