"""Short real Qt-rendering check with labelled layout fixtures; no audio/ASR/API."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont,QFontDatabase
from PySide6.QtWidgets import QApplication
from app.ui.overlay import Overlay


def record(index,source,target):
    return dict(session_id='layout-test-only',segment_id=index,revision=1,candidate_revision=0,
        source_text=source,translated_text=target,candidate_text='',source_closed=True,
        translated_revision=1,state='final',translation_status='ready')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--focus-x',type=float,default=.5);parser.add_argument('--focus-y',type=float,default=.5)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    app=QApplication([]);app.setStyle('Fusion');app.setFont(QFont('Microsoft YaHei UI',10))
    if 'Microsoft YaHei UI' not in QFontDatabase.families():
        font=Path('C:/Windows/Fonts/msyh.ttc')
        if font.is_file():QFontDatabase.addApplicationFont(str(font))
    overlay=Overlay();overlay.resize(900,420)
    overlay.apply_appearance(replace(overlay.appearance,focus_mode=True,font_size=16,visible_segments=6,
                                     focus_x=args.focus_x,focus_y=args.focus_y))
    first=record(1,'Layout test: The matrix has two eigenvalues.','排版测试：矩阵有两个特征值。')
    second=record(2,'Layout test: The system is not stable.','排版测试：系统不稳定。')
    live_second=dict(second,state='preview',source_closed=False,translated_text='',
        source_text='Layout test: The system',candidate_text='is not stable.')
    live_third=dict(record(3,'Layout test: The control input',''),state='preview',source_closed=False,
        candidate_text='remains bounded.')
    overlay.show();app.processEvents();overlay.present_many([first,live_second],True)
    overlay.title.setText('ELT · 焦点排版测试（非语音识别 / 翻译结果）')
    results={'test_text_only':True,'platform':app.platformName(),'easing':'OutCubic','duration_ms':overlay.focus.DURATION_MS,
             'frames':[],'errors':[]};started=[None]
    def frame():
        view=overlay.focus
        results['frames'].append({'elapsed_ms':None if started[0] is None else (time.perf_counter()-started[0])*1000,
            'animation_ms':view.animation.currentTime(),'current':view.current,'target':view.target,
            'live_preview':{'segment':view.preview_record['segment_id'] if view.preview_record else None,
                'visible':view.preview_clip.isVisible(),'y':view.preview_clip.y(),'height':view.preview_clip.height()},
            'cards':{str(key):{'y':card.widget.y(),'height':card.widget.height(),
                'effect':card.widget.graphicsEffect() is not None} for key,card in view.cards.items()}})
    timer=QTimer();timer.setInterval(16);timer.timeout.connect(frame)
    def start():
        overlay.grab().save(str(args.output/'before.png'))
        started[0]=time.perf_counter();overlay.present_many([first,second,live_third],True);timer.start();frame()
    def mid():overlay.grab().save(str(args.output/'during.png'))
    def done():
        timer.stop();frame();view=overlay.focus
        overlay.grab().save(str(args.output/'after.png'))
        if view.current!=2 or view.transitioning:results['errors'].append('new caption did not settle')
        if not view.preview_record or view.preview_record['segment_id']!=3 or not view.preview_clip.isVisible():
            results['errors'].append('live source below focus missing')
        if 1 not in view.cards or 2 not in view.cards:results['errors'].append('old or new caption missing')
        else:
            old=view.cards[1].widget;new=view.cards[2].widget
            if not old.y()<new.y():results['errors'].append('old caption was not pushed upward')
            # Compare the geometric midpoint (not QRect's rounded pixel index)
            # to a fractional anchor. Rounding the widget position costs <= .5px.
            if abs(new.y()+new.height()/2-view._center_y())>.51:results['errors'].append('caption missed selected focus')
            if abs(new.x()+new.width()/2-view._center_x())>.51:results['errors'].append('caption missed horizontal focus')
            if old.graphicsEffect() or new.graphicsEffect():results['errors'].append('unexpected graphics effect')
        moving=[row for row in results['frames'] if row['target']==2]
        if len({row['cards']['2']['y'] for row in moving})<4:results['errors'].append('insufficient actual animation frames')
        failed=dict(live_third,source_closed=True,translation_status='request_deadline',candidate_text='')
        live_fourth=dict(record(4,'Layout test: New source remains visible.',''),source_closed=False,state='preview',candidate_text='next words')
        overlay.present_many([first,second,failed,live_fourth],True)
        view.animation.setCurrentTime(view.DURATION_MS);app.processEvents()
        overlay.title.setText('ELT · 翻译超时排版测试（测试文字）')
        overlay.grab().save(str(args.output/'fallback.png'))
        fallback=view.cards.get(3);results['fallback_original_visible']=bool(fallback and fallback.widget.source.text()==failed['source_text'])
        results['live_source_visible']=view.preview_clip.isVisible()
        final=record(3,failed['source_text'],'排版测试：迟到的中文补回原句。')
        overlay.present_many([first,second,final,live_fourth],True);app.processEvents()
        results['late_translation_same_card']=bool(fallback and view.cards[3] is fallback and fallback.widget.translation.text()==final['translated_text'])
        overlay.grab().save(str(args.output/'late-translation.png'))
        results['focus_position']=[view.focus_x,view.focus_y]
        for key in ('fallback_original_visible','live_source_visible','late_translation_same_card'):
            if not results[key]:results['errors'].append(key)
        results['verified']=not results['errors']
        (args.output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        overlay.close();app.quit()
    QTimer.singleShot(150,start);QTimer.singleShot(400,mid);QTimer.singleShot(1100,done)
    try:app.exec()
    finally:timer.stop();overlay.close()
    return 0 if results.get('verified') else 2


if __name__=='__main__':raise SystemExit(main())
