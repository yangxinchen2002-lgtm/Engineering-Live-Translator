"""Real Qt history/return interaction check with labelled fixtures; no ASR/API."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def record(index,*,live=False):
    return dict(session_id='history-layout-fixtures-only',segment_id=index,revision=1,candidate_revision=0,
        source_text=f'Layout test {index}: The matrix has two eigenvalues.',candidate_text='Still being recognized.' if live else '',
        translated_text='' if live else f'排版测试 {index}：矩阵有两个特征值。',translated_revision=1,
        state='preview' if live else 'final',source_closed=not live,translation_status='streaming' if live else 'ready')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    from PySide6.QtCore import Qt,QPoint,QPointF
    from PySide6.QtGui import QFontDatabase,QWheelEvent
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from app.ui.overlay import Overlay
    app=QApplication([]);app.setStyle('Fusion')
    if 'Microsoft YaHei UI' not in QFontDatabase.families():QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    if 'Segoe UI Symbol' not in QFontDatabase.families():QFontDatabase.addApplicationFont('C:/Windows/Fonts/seguisym.ttf')
    window=Overlay();window.resize(900,460)
    window.apply_appearance(replace(window.appearance,focus_mode=True,visible_segments=1,font_size=14,focus_x=.62,focus_y=.4))
    window.show();view=window.focus;checks={};result={'test_text_only':True,'api_requests':0,'models_loaded':False}
    def process():
        for _ in range(4):app.processEvents()
    def scroll():
        event=QWheelEvent(QPointF(40,40),QPointF(view.mapToGlobal(QPoint(40,40))),QPoint(),QPoint(0,120),
                          Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
        QApplication.sendEvent(view,event);process()
    def capture(name):
        if not window.grab().save(str(args.output/name)):raise OSError('could not save layout evidence')
    try:
        rows=[record(i) for i in range(1,16)]+[record(16,live=True)]
        window.present_many(rows,True);process();capture('live-before.png')
        checks['return_hidden_by_default']=not view.return_button.isVisible()
        scroll();bar=view.history_scroll.verticalScrollBar();bar.setValue(view.history_rows[4].y()+7)
        checks['history_available_beyond_recent_one']=view.browsing and len(view.history_rows)==16 and 1 in view.history_rows
        checks['return_button_visible']=view.return_button.isVisible()
        capture('history.png');offset=bar.value()-view.history_rows[4].y();settled=[];view.settled.connect(settled.append)
        newer=[record(i) for i in range(1,17)]+[record(17,live=True)]
        newer[1]={**newer[1],'translated_text':'排版测试：补齐一段较长的中文，核对回看位置保持。'*12}
        window.present_many(newer,True);process()
        checks['late_translation_preserves_reading_position']=abs(bar.value()-view.history_rows[4].y()-offset)<=1
        checks['incoming_text_does_not_add_or_replace_history_rows']=len(view.history_rows)==16 and 17 not in view.history_rows
        checks['no_live_focus_paint_while_browsing']=not settled
        checks['late_translation_updated']=view.history_rows[2].translation.text()==newer[1]['translated_text']
        capture('history-after-new-text.png')
        QTest.mouseClick(view.return_button,Qt.LeftButton);process();capture('returned-live.png')
        checks['returned_to_current_without_replay']=not view.browsing and view.current==16 and not view.transitioning and not view.pending
        checks['preview_is_live']=view.preview_record is not None and view.preview_record['segment_id']==17 and view.preview_clip.isVisible()
        card=view.cards[16].widget
        checks['custom_focus_preserved']=abs(card.x()+card.width()/2-view._center_x())<=.51 and abs(card.y()+card.height()/2-view._center_y())<=.51
        checks['button_hidden_after_return']=not view.return_button.isVisible()
        window.resize(280,120);process();scroll();capture('small-window.png')
        checks['small_window_button_fits']=view.rect().contains(view.return_button.geometry())
        result.update(checks=checks,verified=all(checks.values()),platform=app.platformName(),history_capacity=view.HISTORY_CAPACITY)
    except Exception as error:result.update(verified=False,error=str(error),checks=checks)
    finally:window.close();process()
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False));return 0 if result['verified'] else 1


if __name__=='__main__':raise SystemExit(main())
