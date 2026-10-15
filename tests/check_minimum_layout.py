"""Run with python tests/check_minimum_layout.py; opens temporary Qt windows."""
import os,sys,tempfile
os.environ['PYLON_NO_UPDATE_CHECK']='1'
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from app import engine
engine.vlc=None
from app.window import MainWindow,PAGE_VIDEO
from app.store import Store
app=QApplication([])
with tempfile.TemporaryDirectory() as d:
 s=Store(d+'/data.json');s.set_setting('onboarded',True)
 w=MainWindow(s);w._vlc_missing=lambda:None;w.show();app.processEvents();w._ui_timer.stop();w._time_timer.stop()
 w.stage.setCurrentIndex(PAGE_VIDEO)
 for library,settings in ((False,False),(True,False),(False,True),(True,True)):
  w.toggle_library(library);w.toggle_sidebar(settings);w.resize(640,400);app.processEvents()
  w._place_overlays();w._set_bars(True);app.processEvents();w._place_overlays()
  rect=w.centralWidget().rect()
  for panel in (w.library,w.stage,w.sidebar):
   if panel.isVisible():assert rect.contains(panel.geometry()),(library,settings,rect,panel.geometry())
  assert w.stage.width()>=240
  for bar in (w.top,w.bottom):
   assert bar.x()+bar.mask().boundingRect().right()<=w.stage.mapToGlobal(w.stage.rect().topRight()).x()
  assert w.bottom.btn_tune.geometry().right()<w.stage.width()
  print('PASS minimum layout:',library,settings,w.width(),w.stage.width(),flush=True)
 w.toggle_sidebar(False);w.toggle_library(False);w.resize(640,400);app.processEvents();assert w.width()==640
 s._save_timer.stop();w.hide();w.top.hide();w.bottom.hide()


