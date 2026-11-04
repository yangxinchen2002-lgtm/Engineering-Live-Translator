import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
pytest.importorskip('PySide6',reason='install ui extra to run desktop component tests')
from PySide6.QtWidgets import QApplication,QLineEdit
from app.ui.window import MainWindow,KeyDialog,STYLE,source_html


@pytest.fixture(scope='module')
def app():
    instance=QApplication.instance() or QApplication([])
    instance.setStyle('Fusion');instance.setStyleSheet(STYLE)
    return instance


def test_window_has_real_controls_and_readable_fonts_without_auto_capture(app):
    window=MainWindow();window.show();app.processEvents()
    assert not window.controller.running and not window.stop_button.isEnabled()
    assert not window.translate_check.isChecked()
    assert window.source.font().pointSize()==21
    assert window.minimumSizeHint().height()<750
    assert window.start_button.text()=='开始字幕' and window.history_button.text()=='最近字幕'
    assert not window.overlay.isVisible()
    window.close();app.processEvents()


def test_password_entry_hidden_and_html_escaped(app):
    window=MainWindow()
    dialog=KeyDialog(window.controller,{'available':False},window)
    assert dialog.key.echoMode()==QLineEdit.Password
    assert dialog.key.maxLength()==512
    dialog.reject()
    value=source_html({'source_text':'x < 0 <img src="secret">','candidate_text':'& lambda'})
    assert '<img' not in value and '&lt;' in value and '&amp;' in value
    window.close();app.processEvents()


def test_japanese_selector_and_live_original_rendering(app, tmp_path):
    from dataclasses import replace
    from PySide6.QtGui import QTextDocument
    from app.ui.preferences import PreferencesStore, UISettings
    store=PreferencesStore(tmp_path/'settings.json')
    store.save(replace(UISettings(),language='ja'))
    window=MainWindow(preferences=store)
    try:
        assert window.language.currentData()=='ja' and window.language.currentText()=='日语'
        document=QTextDocument()
        document.setHtml(source_html({'source_language':'ja','source_text':'この行列は','candidate_text':'正則です。'}))
        assert document.toPlainText()=='この行列は正則です。'
        assert not window.controller.running
    finally:window.close();app.processEvents()


def test_overlay_font_and_background_controls_change_actual_widget(app):
    window=MainWindow();window.font_slider.setValue(26);window.opacity_slider.setValue(50)
    assert window.source.font().pointSize()==26 and window.overlay.source.font().pointSize()==26
    assert window.overlay.alpha==128
    window.close();app.processEvents()


@pytest.mark.parametrize('ui_points',[9,10,12])
def test_numeric_controls_have_room_for_full_digits_and_chinese_suffix(app,ui_points):
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QStyle,QStyleOptionFrame
    window=MainWindow();window.show();app.processEvents()
    try:
        for spin,values in ((window.font_value,(6,10,72)),(window.sentence_spin,(1,5,12))):
            font=QFont(spin.font());font.setPointSize(ui_points);spin.setFont(font)
            for value in values:
                spin.setValue(value);app.processEvents()
                edit=spin.findChild(QLineEdit);option=QStyleOptionFrame();edit.initStyleOption(option)
                contents=edit.style().subElementRect(QStyle.SE_LineEditContents,option,edit)
                margins=edit.textMargins()
                available=contents.width()-margins.left()-margins.right()-4
                assert edit.fontMetrics().horizontalAdvance(spin.text())<=available
                assert edit.text()==spin.text()
    finally:window.close();app.processEvents()


def test_multiple_vlc_instances_need_selection_and_restart_does_not_rebind(app):
    from app.audio.processes import ProcessInfo
    window=MainWindow()
    first=ProcessInfo(10,'vlc.exe','C:/vlc.exe',100)
    second=ProcessInfo(20,'vlc.exe','C:/vlc.exe',200)
    window.processes_ready([first,second],[])
    assert window.target is None and not window.start_button.isEnabled()
    window.process_combo.setCurrentIndex(1)
    assert window.target is first
    window.processes_ready([ProcessInfo(10,'vlc.exe','C:/vlc.exe',300),second],[])
    assert window.target is None  # changed creation time must be selected again
    window.close();app.processEvents()


def test_backend_readiness_requires_audio_connection_and_exposes_failures(app):
    from app.audio.processes import ProcessInfo
    window=MainWindow()
    window.processes_ready([ProcessInfo(10,'vlc.exe','C:/vlc.exe',100,display_name='VLC')],[])
    window.backend_event({'event':'asr_model_ready','device':'cuda'})
    assert '连接 VLC' in window.notice.text()
    window.backend_event({'event':'audio_source_ready'})
    assert '继续播放' in window.notice.text()
    window.backend_event({'event':'translation_error','code':'insufficient_balance'})
    assert '余额不足' in window.notice.text()
    window.backend_event({'event':'bilingual_source_error','message':'target_exited'})
    assert 'VLC 已退出' in window.notice.text()
    window.overlay.present({'state':'preview','source_text':'Matrix.','candidate_text':'',
                            'translated_text':'矩阵','revision':2,'translated_revision':1},True)
    assert '对应前段' in window.overlay.title.text()
    window.close();app.processEvents()
