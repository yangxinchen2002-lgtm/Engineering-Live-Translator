"""Short native input/render QA, using labelled test text; no ASR/API/audio.

Click the underlying counter while the actual Overlay is input-transparent, then
restore edit mode. This is a UI fixture, never called by the production app.
"""
import argparse
import ctypes as ct
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QTimer
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QPushButton,QLabel,QCheckBox
from app.ui.overlay import Overlay
from app.ui.hotkeys import GlobalHotkeys


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    app=QApplication([]);app.setFont(QFont('Microsoft YaHei UI',10));app.setQuitOnLastWindowClosed(False)
    window=QWidget();window.setWindowTitle('ELT · M3 原生悬浮窗验收');window.resize(900,610)
    layout=QVBoxLayout(window);layout.addWidget(QLabel('界面验收：以下是排版测试文字，不是语音识别或翻译结果。'))
    mode=QCheckBox('开启鼠标穿透');layout.addWidget(mode)
    recover=QPushButton('恢复可编辑（Ctrl+Alt+E）');layout.addWidget(recover)
    counter=QPushButton('穿透点击计数：0');counter.setMinimumHeight(320);layout.addWidget(counter)
    close=QPushButton('结束验收');layout.addWidget(close)
    overlay=Overlay();overlay.setWindowTitle('ELT · M3 测试字幕')
    overlay.apply_appearance(replace(overlay.appearance,font_size=12,visible_segments=4))
    phrases=[('The matrix has two eigenvalues.','矩阵有两个特征值。'),('The system is not stable.','系统不稳定。'),
             ('The control input is bounded.','控制输入有界。'),('The sampling rate is fixed.','采样率保持不变。')]
    overlay.present_many([dict(session_id='style-test',segment_id=i+1,revision=1,translated_revision=1,
        source_text=source,candidate_text='',translated_text=target,state='final') for i,(source,target) in enumerate(phrases)],True)
    result={'input_count':0,'changes':[],'test_text_only':True}
    api=ct.WinDLL('user32',use_last_error=True)
    api.GetWindowLongPtrW.argtypes=[ct.c_void_p,ct.c_int];api.GetWindowLongPtrW.restype=ct.c_ssize_t
    def save():
        result.update(click_through=overlay.click_through,visible_rows=len(overlay.rows),
            font_size=overlay.source.font().pointSize(),geometry=list(overlay.geometry().getRect()),
            qt_input_flag=bool(overlay.windowFlags()&Qt.WindowTransparentForInput),
            qwindow_input_flag=bool(overlay.windowHandle().flags()&Qt.WindowTransparentForInput),
            mouse_attribute=overlay.testAttribute(Qt.WA_TransparentForMouseEvents),
            extended_style=int(api.GetWindowLongPtrW(int(overlay.winId()),-20)))
        (args.output/'state.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    def changed(value):result['changes'].append(bool(value));save()
    overlay.input_changed.connect(changed)
    def clicked():result['input_count']+=1;counter.setText(f"穿透点击计数：{result['input_count']}");save()
    counter.clicked.connect(clicked);mode.toggled.connect(overlay.set_click_through)
    def edit():mode.setChecked(False);overlay.set_click_through(False);overlay.show();save()
    recover.clicked.connect(edit);close.clicked.connect(app.quit)
    window.show();app.processEvents()
    point=counter.mapToGlobal(counter.rect().center())
    overlay.setGeometry(point.x()-360,point.y()-130,720,260);overlay.show()
    keys=GlobalHotkeys(app,window.winId(),lambda action:edit() if action=='edit' else overlay.setVisible(not overlay.isVisible()))
    result['shortcuts_registered']=sorted(keys.registered);result['shortcut_errors']=keys.errors;save()
    timer=QTimer();timer.setInterval(100)
    timer.timeout.connect(lambda:app.quit() if (args.output/'stop.request').exists() else save());timer.start()
    QTimer.singleShot(120000,app.quit)
    try:app.exec()
    finally:
        save();keys.close();overlay.close();window.close()
        (args.output/'stopped.json').write_text(json.dumps({'closed':True}),encoding='utf-8')
    return 0


if __name__=='__main__':raise SystemExit(main())
