from __future__ import annotations
from dataclasses import replace
import json
from pathlib import Path
from datetime import datetime
import time
from PySide6.QtCore import Qt,QTimer,Signal,QUrl,QFileInfo,QSignalBlocker
from PySide6.QtGui import QColor,QPainter,QFont,QCloseEvent,QIcon,QDesktopServices
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QFrame,QLabel,QVBoxLayout,QHBoxLayout,QGridLayout,
    QPushButton,QComboBox,QCheckBox,QSlider,QPlainTextEdit,QScrollArea,QDialog,QLineEdit,QDialogButtonBox,
    QFileDialog,QSizePolicy,QLayout,QSpinBox,QDoubleSpinBox,QTabWidget,QFileIconProvider)
from app.asr.config import ROOT
from app.languages import LANGUAGE_LABELS
from app.i18n import set_language,get_language,tr as _tr
from .controller import BackendController
from .overlay import Overlay,CaptionLabel,source_html,translation_caption
from .preferences import UISettings,place_window
from .appearance import AppearanceDialog,PerformanceDialog
from .hotkeys import GlobalHotkeys
from .theme import STYLE
from .usage import usage_text
from app.translation.glossary import Glossary
from app.speech.config import VOICES,MODEL_SIZES,SpeechConfig,LECTURE_VOICE
from .speech import SpeechController
from .web_player import WebPlayer
from .notes import NotesController
from .source_volume import SourceVolumeController
from app.translation.providers import PROVIDERS,provider_info,validate_model


def label(text='',name=None,size=None,bold=False):
    result=QLabel(_tr(text));result.setWordWrap(True)
    result.setTextFormat(Qt.PlainText)
    if name:result.setObjectName(name)
    if size:
        font=result.font();font.setPointSize(size);font.setBold(bold);result.setFont(font)
    return result


def card(name='card'):
    frame=QFrame();frame.setObjectName(name);return frame


def settings_page():
    scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setStyleSheet('QScrollArea, QScrollArea > QWidget > QWidget { background:transparent; border:0; }')
    settings=QWidget();controls=QVBoxLayout(settings);controls.setContentsMargins(2,6,10,8);controls.setSpacing(9)
    controls.setSizeConstraint(QLayout.SetMinimumSize);scroll.setWidget(settings)
    return scroll,controls


class ScrollablePage(QWidget):
    def heightForWidth(self,width):
        # Wrapped subtitles/settings have their own scrolling areas. Let the
        # outer page shrink to layout minima instead of its full text size hint.
        return self.minimumSizeHint().height()


class KeyDialog(QDialog):
    def __init__(self,controller,status,parent):
        super().__init__(parent);self.controller=controller;self.setWindowTitle(_tr('翻译 API 密钥'));self.saving_provider=None
        self.setMinimumWidth(470)
        box=QVBoxLayout(self);box.setContentsMargins(26,24,26,24);box.setSpacing(16)
        box.addWidget(label(_tr('连接翻译服务'),size=18,bold=True))
        box.addWidget(label(_tr('密钥只保存在本机 Windows 用户凭据中，不写入项目文件或日志。'),'muted'))
        self.provider=QComboBox();self.provider.setAccessibleName(_tr('密钥来源'))
        for code,info in PROVIDERS.items():self.provider.addItem(info.label,code)
        selected=getattr(parent,'translation_provider',None)
        current=selected.currentData() if selected is not None else controller.translation_provider
        self.provider.setCurrentIndex(self.provider.findData(current));box.addWidget(self.provider)
        self.key=QLineEdit();self.key.setEchoMode(QLineEdit.Password);self.key.setMaxLength(512)
        self.key.setPlaceholderText(_tr('输入或粘贴所选服务的 API 密钥'));self.key.setMinimumHeight(38)
        self.key.setAccessibleName(_tr('API 密钥，隐藏输入'));box.addWidget(self.key)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.message=label(_tr('保存后，在主界面勾选“启用翻译”并选择目标语言。'),'muted');box.addWidget(self.message)
        if status.get('source')=='environment':box.addWidget(label(_tr('当前环境变量中的密钥具有优先级。保存到凭据库不会修改该环境变量。'),'muted'))
        row=QHBoxLayout();row.addStretch();cancel=QPushButton(_tr('取消'));cancel.clicked.connect(self.reject)
        self.save=QPushButton(_tr('保存密钥'));self.save.setObjectName('primary');self.save.clicked.connect(self._save)
        row.addWidget(cancel);row.addWidget(self.save);box.addLayout(row)
        self.controller.credential_saved_for.connect(self._saved)

    def _provider_changed(self):
        self.key.clear();self.message.setText(_tr('请粘贴所选服务的密钥；不会覆盖其他来源的密钥。'))

    def _save(self):
        if not self.key.text().strip():self.message.setText(_tr('请先输入密钥。'));return
        self.save.setEnabled(False);self.provider.setEnabled(False);self.message.setText(_tr('正在保存…'))
        self.saving_provider=self.provider.currentData()
        value=self.key.text();self.key.clear();self.controller.save_credential(value,self.saving_provider)

    def _saved(self,provider,success,message):
        if provider!=self.saving_provider:return
        self.saving_provider=None
        self.save.setEnabled(True);self.provider.setEnabled(True);self.message.setText(message)
        if success:self.accept()

    def done(self,result):
        self.key.clear()
        try:self.controller.credential_saved_for.disconnect(self._saved)
        except RuntimeError:pass
        super().done(result)


class MainWindow(QMainWindow):
    def __init__(self,controller=None,preferences=None,enable_global_shortcuts=False):
        super().__init__()
        self.settings=preferences.load() if preferences else UISettings();set_language(self.settings.ui_language)
        self.setWindowTitle(_tr('Engineering Live Translator · 工科实时字幕'))
        self.setWindowIcon(QIcon(str(Path(__file__).with_name('assets')/'elt.ico')))
        self.resize(1240 if get_language()=='en' else 1180,860)
        self.setMinimumSize(1040 if get_language()=='en' else 860,620 if get_language()=='en' else 560)
        self.controller=controller or BackendController(self)
        self.speech=SpeechController(self);self.notes=NotesController(self)
        self.web_player=WebPlayer(self);self.web_player.problem.connect(self.web_player_failed)
        self.web_player.follow_requested.connect(self.web_start_requested)
        self._auto_summary_session=False;self._summary_started=False;self.course_name=_tr('课程翻译稿')
        self.source_volume=SourceVolumeController(self)
        self.preferences_store=preferences
        self._saved_settings=self.settings;self._loading_preferences=True;self._settings_dirty=False;self._save_failed=False
        self._overlay_positioned=False;self.glossary_path=None;self.hotkeys=None;self.performance_dialog=None
        self.transcript_directory=None;self.last_transcript_path=None;self.transcript_failed=False;self._save_session=False
        self.credential_status={'available':False,'source':'unavailable'}
        self.provider_credentials={};self.provider_models={};self._provider_code='deepseek'
        self.target=None;self.closing=False;self.started_at=None;self.history_signature=None
        self.web_connect_url=''
        self.web_captions={k:getattr(self.settings,'web_'+k) for k in ('caption_width','caption_height','caption_font_size')}
        self._last_qwen_model=self.settings.speech_model_size
        self.file_icons=QFileIconProvider()
        self.overlay=Overlay();self.overlay.hidden.connect(lambda:self.overlay_check.setChecked(False))
        central=ScrollablePage();outer=QScrollArea();outer.setWidgetResizable(True);outer.setFrameShape(QFrame.NoFrame)
        outer.setStyleSheet('QScrollArea, QScrollArea > QWidget > QWidget { background:#f4f6fa; border:0; }')
        outer.setWidget(central);self.setCentralWidget(outer)
        layout=QVBoxLayout(central);layout.setContentsMargins(26,22,26,16);layout.setSpacing(16)
        header=QHBoxLayout();header.setSpacing(14)
        mark=label('','brandMark');mark.setFixedSize(54,54);mark.setAlignment(Qt.AlignCenter)
        mark.setPixmap(self.windowIcon().pixmap(54,54));mark.setAccessibleName(_tr('ELT 双语声波图标'));header.addWidget(mark)
        titles=QVBoxLayout();titles.setSpacing(3)
        brand=label('ENGINEERING LIVE TRANSLATOR','eyebrow');brand.setWordWrap(False);titles.addWidget(brand)
        heading=label(_tr('工程实时字幕'),size=20,bold=True);heading.setWordWrap(False);titles.addWidget(heading)
        header.addLayout(titles,1)
        self.mode_badge=label(_tr('本地原文模式'),'badge')
        self.ui_language=QComboBox();self.ui_language.addItem(_tr('简体中文'),'zh');self.ui_language.addItem('English','en')
        self.ui_language.setAccessibleName(_tr('界面语言'));self.ui_language.setToolTip(_tr('界面语言，下次打开 ELT 时生效。'))
        self.ui_language.setFixedWidth(112);header.addWidget(self.ui_language)
        header.addWidget(self.mode_badge,alignment=Qt.AlignVCenter);layout.addLayout(header)
        self.guide=label(_tr('① 在目标应用播放一下声音　　② 选择应用和语言后开始　　③ 音频就绪后继续播放'),'guide')
        layout.addWidget(self.guide)
        content=QHBoxLayout();content.setSpacing(18);layout.addLayout(content,1)
        left=card('sidebar');left.setFixedWidth(386 if get_language()=='en' else 300);leftbox=QVBoxLayout(left);leftbox.setContentsMargins(18,18,18,16);leftbox.setSpacing(10)
        leftbox.addWidget(label(_tr('工作台'),'sectionTitle'))
        self.settings_tabs=QTabWidget();self.settings_tabs.setDocumentMode(True);self.settings_tabs.setAccessibleName(_tr('课程、翻译、朗读与存稿设置'))
        self.settings_tabs.tabBar().setDrawBase(False)
        if get_language()=='en':self.settings_tabs.setStyleSheet('QTabBar::tab { padding:9px 10px; }')
        self.course_scroll,controls=settings_page();self.settings_tabs.addTab(self.course_scroll,_tr('课程'))
        controls.addWidget(label(_tr('字幕方式'),'muted'))
        self.capture_mode=QComboBox();self.capture_mode.setAccessibleName(_tr('字幕方式'))
        self.capture_mode.addItem(_tr('应用音频实时字幕'),'audio');self.capture_mode.addItem(_tr('视频预读（网页 / 本地）'),'web')
        controls.addWidget(self.capture_mode)
        self.web_player_panel=QWidget();playerbox=QVBoxLayout(self.web_player_panel)
        playerbox.setContentsMargins(0,0,0,0);playerbox.setSpacing(8)
        playerbox.addWidget(label(_tr('课程播放方式'),'muted'));self.web_player_choice=QComboBox()
        self.web_player_choice.setAccessibleName(_tr('课程播放方式'))
        self.web_player_choice.addItem(_tr('ELT 内置窗口（网页 / 本地）'),'internal');self.web_player_choice.addItem(_tr('Edge 网页扩展（兼容）'),'edge')
        playerbox.addWidget(self.web_player_choice);controls.addWidget(self.web_player_panel);self.web_player_panel.hide()
        self.web_panel=QWidget();webbox=QVBoxLayout(self.web_panel);webbox.setContentsMargins(0,0,0,0);webbox.setSpacing(8)
        webbox.addWidget(label(_tr('支持本地视频与 TUM-Live / Moodle 课程，字幕和朗读跟随播放进度。'),'muted'))
        self.web_speech_engine=QComboBox(self);self.web_speech_engine.hide()
        self.web_speech_engine.addItem(_tr('本地 Qwen TTS · 使用朗读页设置'),'qwen');self.web_speech_engine.addItem(_tr('Windows 系统音色'),'system')
        for combo in (self.web_player_choice,self.web_speech_engine):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon);combo.setMinimumContentsLength(8)
            combo.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed)
        webbox.addWidget(label(_tr('预读秒数'),'muted'));self.web_lookahead=QSpinBox();self.web_lookahead.setRange(5,30)
        self.web_lookahead.setValue(15);self.web_lookahead.setSuffix(_tr(' 秒'));webbox.addWidget(self.web_lookahead)
        self.web_voice_label=label(_tr('Windows 系统音色'),'muted');self.web_voice_label.hide()
        self.web_voice=QComboBox();self.web_voice.setAccessibleName(_tr('Windows 系统音色'));self.web_voice.addItem(_tr('正在读取系统音色…'),None)
        self.web_voice.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon);self.web_voice.setMinimumContentsLength(8)
        self.web_voice.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed)
        speedrow=QHBoxLayout();speedrow.addWidget(label(_tr('基础语速'),'muted'));self.web_base_speed=QDoubleSpinBox()
        self.web_base_speed.setRange(1,2);self.web_base_speed.setSingleStep(.05);self.web_base_speed.setDecimals(2)
        self.web_base_speed.setSuffix(_tr(' 倍'));speedrow.addWidget(self.web_base_speed);webbox.addLayout(speedrow)
        webbox.addWidget(label(_tr('正常速度能读完就不减速，来不及才加快。Qwen 的模型、音色和设备在“朗读”页选择；停止字幕不暂停视频。'),'muted'))
        self.web_connect_button=QPushButton(_tr('启动并连接网页'));webbox.addWidget(self.web_connect_button)
        self.web_local_button=QPushButton(_tr('打开本地视频'));webbox.addWidget(self.web_local_button)
        self.web_extension_button=QPushButton(_tr('打开扩展文件夹'));webbox.addWidget(self.web_extension_button)
        self.web_status=label(_tr('启动后在连接页完成配对，再回课程页点击扩展开始。'),'muted');webbox.addWidget(self.web_status)
        webbox.removeWidget(self.web_connect_button);webbox.removeWidget(self.web_local_button);webbox.removeWidget(self.web_extension_button)
        webbox.insertWidget(1,self.web_connect_button);webbox.insertWidget(2,self.web_local_button);webbox.insertWidget(3,self.web_extension_button)
        self.web_panel.hide()
        self.source_caption=label(_tr('音频来源'),'muted');controls.addWidget(self.source_caption)
        self.process_combo=QComboBox();self.process_combo.setAccessibleName(_tr('音频来源应用'))
        self.process_combo.addItem(_tr('正在读取应用音频…'),None)
        self.process_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.process_combo.setMinimumContentsLength(12);controls.addWidget(self.process_combo)
        self.source_hint=label(_tr('从 Windows 音量合成器读取；捕获所选应用的声音，可能包含多个窗口或标签页。'),'muted');controls.addWidget(self.source_hint)
        self.refresh_button=QPushButton(_tr('刷新列表'));controls.addWidget(self.refresh_button)
        course_options=QHBoxLayout();course_options.setSpacing(10)
        language_column=QVBoxLayout();language_column.setSpacing(8);language_column.addWidget(label(_tr('原始语言'),'muted'))
        self.language=QComboBox();self.language.setAccessibleName(_tr('课程原始语言'))
        self.language.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon);self.language.setMinimumContentsLength(4)
        for value,title in LANGUAGE_LABELS.items():self.language.addItem(_tr(title),value)
        self.language.addItem(_tr('自动识别'),'auto')
        language_column.addWidget(self.language);course_options.addLayout(language_column,1)
        duration_column=QVBoxLayout();duration_column.setSpacing(8);duration_column.addWidget(label(_tr('运行时长'),'muted'))
        self.duration=QComboBox()
        self.duration.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon);self.duration.setMinimumContentsLength(2)
        for title,value in [(_tr('30 分钟'),1800),(_tr('1 小时'),3600),(_tr('2 小时'),7200),(_tr('手动停止'),28800)]:self.duration.addItem(title,value)
        self.duration.setItemData(3,_tr('手动停止，单次最长 8 小时'),Qt.ToolTipRole)
        self.duration.setToolTip(_tr('单次最长 8 小时，也可随时点击停止。'))
        self.duration.setCurrentIndex(1);duration_column.addWidget(self.duration);course_options.addLayout(duration_column,1)
        controls.addLayout(course_options)
        controls.addWidget(self.web_panel)
        controls.addStretch(1)
        self.translation_scroll,controls=settings_page();self.settings_tabs.addTab(self.translation_scroll,_tr('翻译'))
        translation_controls=controls
        controls.addWidget(label(_tr('翻译服务'),'sectionTitle'))
        self.translate_check=QCheckBox(_tr('启用翻译'));self.translate_check.setEnabled(False)
        controls.addWidget(label(_tr('翻译 API 来源'),'muted'));self.translation_provider=QComboBox()
        self.translation_provider.setAccessibleName(_tr('翻译 API 来源'))
        for code,info in PROVIDERS.items():self.translation_provider.addItem(info.label,code)
        controls.addWidget(self.translation_provider)
        self.translation_model=QComboBox();self.translation_model.setEditable(True)
        self.translation_model.setAccessibleName(_tr('翻译模型'));self.translation_model.lineEdit().setMaxLength(128)
        self.translation_model.addItems(PROVIDERS['deepseek'].models)
        self.translation_model.setToolTip(_tr('选择模型，或填写该服务支持的文本模型ID；停止会话后可切换。'))
        controls.addWidget(label(_tr('翻译模型'),'muted'));controls.addWidget(self.translation_model)
        self.key_status=label(_tr('正在检查密钥状态…'),'muted');controls.addWidget(self.key_status)
        self.key_button=QPushButton(_tr('设置翻译密钥'));controls.addWidget(self.key_button)
        note=label(_tr('仅发送已确认的文字及有限上下文。原始音频始终留在本机。'),'muted');controls.addWidget(note)
        controls.addWidget(label(_tr('翻译术语表'),'muted'))
        self.glossary_label=label(_tr('配置中的工科术语表'),'muted');controls.addWidget(self.glossary_label)
        self.glossary_button=QPushButton(_tr('选择术语表'));self.glossary_button.clicked.connect(self.choose_glossary);controls.addWidget(self.glossary_button)
        controls.addStretch(1)
        self.speech_scroll,controls=settings_page();self.settings_tabs.addTab(self.speech_scroll,_tr('朗读'))
        self.speech_check=QCheckBox(_tr('自动朗读已确认的译文'));controls.addWidget(self.speech_check)
        self.speech_check.setToolTip(_tr('语音完全在本机生成，只朗读最终确认的译文。'))
        model_row=QHBoxLayout();model_title=label(_tr('模型'),'muted');model_title.setWordWrap(False)
        model_row.addWidget(model_title);self.speech_model=QComboBox()
        self.speech_model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.speech_model.setMinimumContentsLength(10);self.speech_model.setAccessibleName(_tr('朗读模型大小与讲课模式'))
        for value,title in MODEL_SIZES:self.speech_model.addItem(_tr(title),value)
        self.speech_model.addItem(_tr('Windows 系统音色'),'system')
        self.speech_model.setToolTip(_tr('1.7B 使用平稳讲解语气，建议 GPU；Windows 系统音色使用已安装的对应语言声音，不加载 Qwen。切换后重新准备朗读，字幕继续。'))
        model_row.addWidget(self.speech_model,1);controls.addLayout(model_row)
        voice_row=QHBoxLayout();voice_title=label(_tr('音色'),'muted');voice_title.setWordWrap(False)
        voice_row.addWidget(voice_title);self.speech_voice=QComboBox()
        self.speech_voice.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.speech_voice.setMinimumContentsLength(10)
        self.speech_voice.setAccessibleName(_tr('朗读预设音色'))
        for value,title in VOICES:self.speech_voice.addItem(_tr(title),value)
        self.speech_voice.setItemData(self.speech_voice.findData(LECTURE_VOICE),
            _tr('Aiden 男声的讲课试用预设：压缩过长的近静音停顿，保留字音声调。请先试听；不同句子的语气仍会有变化。'),Qt.ToolTipRole)
        voice_row.addWidget(self.speech_voice,1);voice_row.addWidget(self.web_voice,1);self.web_voice.hide();controls.addLayout(voice_row)
        device_row=QHBoxLayout();self.speech_device_label=label(_tr('设备'),'muted');device_row.addWidget(self.speech_device_label);self.speech_device=QComboBox()
        self.speech_device.setAccessibleName(_tr('朗读模型运行设备'))
        self.speech_device.addItem(_tr('GPU · 速度优先'),'cuda');self.speech_device.addItem(_tr('CPU · 节省显存，较慢'),'cpu')
        device_row.addWidget(self.speech_device,1);controls.addLayout(device_row)
        self.speech_device.setToolTip(_tr('运行中也可切换；切换模型或设备会重新加载并清空待播，字幕继续。1.7B 实时朗读建议 GPU。'))
        volume_row=QHBoxLayout();volume_row.addWidget(label(_tr('音量'),'muted'))
        self.speech_volume=QSlider(Qt.Horizontal);self.speech_volume.setRange(0,100);self.speech_volume.setValue(80)
        self.speech_volume.setAccessibleName(_tr('朗读音量'));volume_row.addWidget(self.speech_volume,1);controls.addLayout(volume_row)
        speed_row=QHBoxLayout();speed_row.addWidget(label(_tr('基础语速'),'muted'));self.speech_speed=QDoubleSpinBox()
        self.speech_speed.setRange(.8,2.);self.speech_speed.setSingleStep(.05);self.speech_speed.setDecimals(2)
        self.speech_speed.setSuffix(_tr(' 倍'));self.speech_speed.setValue(1.25);self.speech_speed.setAccessibleName(_tr('朗读基础语速'))
        speed_row.addWidget(self.speech_speed,1);controls.addLayout(speed_row)
        self.speech_catch_up=QCheckBox(_tr('积压时自动加速'));self.speech_catch_up.setChecked(True)
        self.speech_catch_up.setToolTip(_tr('待播字数持续达到门槛后平缓提速，最多为基础语速的1.5倍；积压减少后逐渐恢复。'))
        controls.addWidget(self.speech_catch_up)
        catch_row=QHBoxLayout();catch_row.addWidget(label(_tr('加速门槛'),'muted'))
        self.speech_catch_chars=QSpinBox();self.speech_catch_chars.setRange(20,1000)
        self.speech_catch_chars.setSingleStep(20);self.speech_catch_chars.setSuffix(_tr(' 字'));self.speech_catch_chars.setValue(80)
        self.speech_catch_chars.setAccessibleName(_tr('自动加速待播字数门槛'));catch_row.addWidget(self.speech_catch_chars,1)
        controls.addLayout(catch_row)
        grace_row=QHBoxLayout();grace_row.addWidget(label(_tr('积压缓冲'),'muted'))
        self.speech_catch_grace=QSpinBox();self.speech_catch_grace.setRange(1,30)
        self.speech_catch_grace.setSuffix(_tr(' 秒'));self.speech_catch_grace.setValue(5)
        self.speech_catch_grace.setAccessibleName(_tr('积压持续多久后开始加速'));grace_row.addWidget(self.speech_catch_grace,1)
        controls.addLayout(grace_row)
        controls.addWidget(label(_tr('从首次播放开始观察待播内容；达到门槛并持续缓冲时间后才提速。最高基础语速×1.5，字数不含正在朗读的句子。'),'muted'))
        speech_actions=QHBoxLayout();self.speech_preview_button=QPushButton(_tr('试听音色'));speech_actions.addWidget(self.speech_preview_button)
        self.speech_clear_button=QPushButton(_tr('清空 / 恢复'));speech_actions.addWidget(self.speech_clear_button);controls.addLayout(speech_actions)
        self.speech_status=label(_tr('朗读未启动'),'muted');controls.addWidget(self.speech_status)
        duck_row=QHBoxLayout();self.source_duck_check=QCheckBox(_tr('朗读时降低原声'));self.source_duck_check.setChecked(True)
        self.source_duck_check.setToolTip(_tr('只调整所选音源进程树；浏览器可能包含同一进程树的其他页面。停止朗读后恢复原音量。'))
        duck_row.addWidget(self.source_duck_check,1);self.source_duck_percent=QSpinBox()
        self.source_duck_percent.setRange(10,100);self.source_duck_percent.setSuffix('%');self.source_duck_percent.setValue(20)
        self.source_duck_percent.setAccessibleName(_tr('朗读时原声音量保留比例'))
        self.source_duck_percent.setToolTip(_tr('按原音量的比例保留，例如原音量为50%，选择20%后实际为10%。'))
        duck_row.addWidget(self.source_duck_percent);controls.addLayout(duck_row)
        self.source_duck_status=label(_tr('原声保留比例；停止朗读后自动恢复'),'muted');controls.addWidget(self.source_duck_status)
        controls.removeItem(duck_row);controls.insertLayout(6,duck_row)
        controls.addWidget(label(_tr('无语音 API 费用。1.7B 可控制讲课语气，实时建议 GPU。切换模型或设备会清空待播，字幕继续。'),'muted'))
        controls.addWidget(label(_tr('逐条朗读并提前准备后续语音，保留防卡顿缓冲；积压减少时平缓回到基础语速。'),'muted'))
        controls.addStretch(1)
        self.settings_scroll,controls=settings_page();self.settings_tabs.addTab(self.settings_scroll,_tr('存稿'))
        controls.addWidget(label(_tr('保存本次与之后的翻译'),'sectionTitle'))
        controls.addWidget(label(_tr('首次选择文件夹，之后每次停止字幕时自动整理成双语 TXT。'),'muted'))
        self.save_transcripts_check=QCheckBox(_tr('自动保存每次翻译稿'));controls.addWidget(self.save_transcripts_check)
        self.save_transcripts_check.setToolTip(_tr('保存双语 TXT，未完成的翻译会标注。首次启用请选择文件夹，之后每次会话自动保存。'))
        self.transcript_folder_label=label(_tr('尚未选择保存文件夹'),'muted');controls.addWidget(self.transcript_folder_label)
        self.transcript_folder_button=QPushButton(_tr('选择保存文件夹'));controls.addWidget(self.transcript_folder_button)
        self.transcript_status=label(_tr('未启用保存'),'muted');controls.addWidget(self.transcript_status)
        controls.addWidget(label(_tr('文件名：日期-语言-分钟数\n重名自动编号，不覆盖已有稿件。'),'muted'))
        controls.addWidget(label(_tr('AI 课程梳理与总结'),'sectionTitle'))
        self.auto_summary_check=QCheckBox(_tr('结束翻译后自动生成详细 AI 稿'));controls.addWidget(self.auto_summary_check)
        controls.addWidget(label(_tr('使用已配置的 DeepSeek，分段整理完整课程稿，另计 Token 用量。AI 稿保存在所选文件夹。'),'muted'))
        self.summary_button=QPushButton(_tr('生成本次 AI 稿'));self.summary_button.setEnabled(False);controls.addWidget(self.summary_button)
        self.summary_file_button=QPushButton(_tr('选择已有翻译稿整理'));controls.addWidget(self.summary_file_button)
        self.summary_open_button=QPushButton(_tr('打开已生成的 AI 稿'));self.summary_open_button.setEnabled(False);controls.addWidget(self.summary_open_button)
        self.summary_cancel_button=QPushButton(_tr('取消 AI 整理'));self.summary_cancel_button.setEnabled(False);controls.addWidget(self.summary_cancel_button)
        self.summary_status=label(_tr('尚未生成 AI 稿'),'muted');controls.addWidget(self.summary_status)
        controls.addWidget(label(_tr('未保存原始翻译稿时，本次完整内容仅在内存中保留至下次开始或关闭。'),'muted'))
        controls.addStretch(1)
        leftbox.addWidget(self.settings_tabs,1)
        line=QFrame();line.setFrameShape(QFrame.HLine);line.setStyleSheet('color:#e6ebf3;');leftbox.addWidget(line)
        targetrow=QHBoxLayout();targetrow.setSpacing(8);targetrow.addWidget(self.translate_check,1)
        self.target_language=QComboBox();self.target_language.addItem(_tr('中文'),'zh');self.target_language.addItem('English','en')
        self.target_language.setAccessibleName(_tr('翻译目标语言'));self.target_language.setToolTip(_tr('译文与朗读的目标语言。开始字幕前选择。'))
        self.target_language.setMinimumContentsLength(5);self.target_language.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        targetrow.addWidget(self.target_language);leftbox.addLayout(targetrow)
        self.translation_mode=QComboBox();self.translation_mode.setAccessibleName(_tr('翻译方式'))
        self.translation_mode.setToolTip(_tr('翻译方式：整句后翻译，或实时预览翻译。'))
        self.translation_mode.addItem(_tr('整句后翻译（节省用量）'),'sentence')
        self.translation_mode.addItem(_tr('实时预览翻译'),'preview');leftbox.addWidget(self.translation_mode)
        self.translation_mode_hint=label(_tr('原文实时显示，等句末或停顿后翻译；极长内容会安全分段。'),'muted')
        translation_controls.insertWidget(1,self.translation_mode_hint)
        self.start_button=QPushButton(_tr('开始字幕'));self.start_button.setObjectName('primary');self.start_button.setMinimumHeight(44)
        self.stop_button=QPushButton(_tr('停止'));self.stop_button.setObjectName('stop');self.stop_button.setEnabled(False);self.stop_button.setMinimumHeight(44)
        self.pause_button=QPushButton(_tr('暂停'));self.pause_button.setEnabled(False);self.pause_button.setMinimumHeight(44)
        self.pause_button.setToolTip(_tr('暂停收音和朗读，保留字幕与模型。请同时手动暂停视频；暂停期间的音频不会转写。'))
        actions=QHBoxLayout();actions.setSpacing(8);actions.addWidget(self.start_button,1);actions.addWidget(self.pause_button);actions.addWidget(self.stop_button)
        leftbox.addLayout(actions)
        self.elapsed=label(_tr('尚未启动'),'timer');self.elapsed.setAlignment(Qt.AlignCenter);leftbox.addWidget(self.elapsed)
        content.addWidget(left)
        right=QVBoxLayout();right.setSpacing(14);content.addLayout(right,1)
        status=card();statusbox=QHBoxLayout(status);statusbox.setContentsMargins(20,16,20,16);statusbox.setSpacing(16)
        self.audio_status=label(_tr('等待选择应用'));self.asr_status=label(_tr('识别未启动'));self.translation_status=label(_tr('仅原文'))
        for index,(title,value) in enumerate([(_tr('音频来源'),self.audio_status),(_tr('本地识别'),self.asr_status),(_tr('翻译'),self.translation_status)]):
            if index:
                divider=QFrame();divider.setFrameShape(QFrame.VLine);divider.setStyleSheet('color:#e8edf5;');statusbox.addWidget(divider)
            column=QVBoxLayout();column.setSpacing(7);column.addWidget(label(title,'muted'));column.addWidget(value);statusbox.addLayout(column,1)
        right.addWidget(status)
        self.subtitle_card=card('subtitleCard');subtitle=QVBoxLayout(self.subtitle_card);subtitle.setContentsMargins(24,18,24,16);subtitle.setSpacing(12)
        subhead=QHBoxLayout();subhead.addWidget(label(_tr('实时字幕'),size=14,bold=True));subhead.addStretch()
        self.subtitle_state=label(_tr('等待语音'),'state');subhead.addWidget(self.subtitle_state);subtitle.addLayout(subhead)
        self.source=CaptionLabel(_tr('启动后会在这里显示原文'));self.source.setTextFormat(Qt.RichText)
        self.source.setTextInteractionFlags(Qt.TextSelectableByMouse);self.source.setMinimumHeight(48)
        self.source.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        self.translation=CaptionLabel(_tr('当前为本地原文模式'));self.translation.setStyleSheet('color:#456d94; background:transparent;')
        self.translation.setTextInteractionFlags(Qt.TextSelectableByMouse);self.translation.setMinimumHeight(48)
        self.translation.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        caption_scroll=QScrollArea();caption_scroll.setWidgetResizable(True);caption_scroll.setFrameShape(QFrame.NoFrame)
        caption_scroll.setStyleSheet('QScrollArea, QScrollArea > QWidget > QWidget { background:white; border:0; }')
        caption_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content_text=QWidget();text_layout=QVBoxLayout(content_text);text_layout.setContentsMargins(0,0,4,0);text_layout.setSpacing(12)
        text_layout.addWidget(label(_tr('原文  /  ORIGINAL'),'captionLabel'));text_layout.addWidget(self.source)
        translation_panel=card('translationPanel');translation_box=QVBoxLayout(translation_panel)
        translation_box.setContentsMargins(16,14,16,16);translation_box.setSpacing(10)
        translation_box.addWidget(label(_tr('译文  /  TRANSLATION'),'translationLabel'));translation_box.addWidget(self.translation)
        text_layout.addWidget(translation_panel);text_layout.addStretch()
        caption_scroll.setWidget(content_text);subtitle.addWidget(caption_scroll,1)
        self.caption_note=label(_tr('原文中的浅色部分仍可能修订。'),'muted');subtitle.addWidget(self.caption_note)
        self.subtitle_card.setMinimumHeight(200);right.addWidget(self.subtitle_card,1)
        tools=card('toolCard');toolsbox=QGridLayout(tools);toolsbox.setContentsMargins(18,14,18,14);toolsbox.setHorizontalSpacing(14);toolsbox.setVerticalSpacing(12)
        self.overlay_check=QCheckBox(_tr('置顶字幕窗'));toolsbox.addWidget(self.overlay_check,0,0)
        self.focus_check=QCheckBox(_tr('焦点显示'));self.focus_check.setToolTip(_tr('下一句滑入焦点，旧句上移；滚动回看历史，点击底部箭头返回实时。「定位」可调整焦点位置。'))
        toolsbox.addWidget(self.focus_check,0,1)
        self.mouse_check=QCheckBox(_tr('鼠标穿透'));self.mouse_check.setToolTip(_tr('开启后鼠标可直接操作下方视频；可在此取消或用恢复按钮。'));toolsbox.addWidget(self.mouse_check,0,2)
        fontrow=QHBoxLayout();fontrow.setSpacing(8);fontrow.addWidget(label(_tr('字号'),'muted'));self.font_slider=QSlider(Qt.Horizontal)
        self.font_slider.setRange(6,72);self.font_slider.setValue(21);self.font_slider.setMinimumWidth(40);fontrow.addWidget(self.font_slider,1)
        # Qt's size hint includes styled arrows and suffixes; fixed pixel widths clip text.
        self.font_value=QSpinBox();self.font_value.setRange(6,72);self.font_value.setValue(21)
        self.font_value.setSizePolicy(QSizePolicy.Fixed,QSizePolicy.Fixed);fontrow.addWidget(self.font_value)
        toolsbox.addLayout(fontrow,1,0,1,2)
        opacityrow=QHBoxLayout();opacityrow.setSpacing(8);opacityrow.addWidget(label(_tr('背景'),'muted'));self.opacity_slider=QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(35,95);self.opacity_slider.setValue(86);self.opacity_slider.setMinimumWidth(40);opacityrow.addWidget(self.opacity_slider,1)
        toolsbox.addLayout(opacityrow,1,2)
        options=QHBoxLayout();options.setSpacing(8);options.addWidget(label(_tr('最近'),'muted'))
        self.sentence_spin=QSpinBox();self.sentence_spin.setRange(1,12);self.sentence_spin.setValue(4);self.sentence_spin.setSuffix(_tr(' 条'))
        self.sentence_spin.setSizePolicy(QSizePolicy.Fixed,QSizePolicy.Fixed);options.addWidget(self.sentence_spin)
        self.appearance_button=QPushButton(_tr('外观 / 长宽'));options.addWidget(self.appearance_button)
        options.addStretch();self.recover_button=QPushButton(_tr('恢复可编辑'));options.addWidget(self.recover_button)
        toolsbox.addLayout(options,2,0,1,3)
        toolsbox.setColumnStretch(0,1);toolsbox.setColumnStretch(1,1);toolsbox.setColumnStretch(2,1)
        right.addWidget(tools)
        self.history_dialog=QDialog(self);self.history_dialog.setWindowTitle(_tr('最近字幕'));self.history_dialog.resize(740,460)
        historylayout=QVBoxLayout(self.history_dialog);historylayout.setContentsMargins(18,14,18,14)
        historylayout.addWidget(label(_tr('最近字幕 · 仅保留在本次内存中'),'muted'))
        self.history=QPlainTextEdit();self.history.setReadOnly(True);self.history.document().setMaximumBlockCount(180)
        self.history.setMinimumHeight(85);historylayout.addWidget(self.history)
        self.notice=label(_tr('请先选择要翻译的应用，然后点击“开始字幕”。'),'notice');layout.addWidget(self.notice)
        row=QHBoxLayout();self.metrics=label(_tr('识别处理 —　·　GPU 显存 —'),'muted')
        self.metrics.setWordWrap(True);self.metrics.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        meterbox=QVBoxLayout();meterbox.setSpacing(3);meterbox.addWidget(self.metrics)
        self.usage_summary=label(_tr('Token — · 累计预计 — USD'),'muted')
        self.usage_summary.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);meterbox.addWidget(self.usage_summary)
        row.addLayout(meterbox,1)
        self.history_button=QPushButton(_tr('最近字幕'));self.history_button.setMaximumHeight(34);row.addWidget(self.history_button)
        self.transcript_settings_button=QPushButton(_tr('翻译稿设置'));self.transcript_settings_button.setMaximumHeight(34);row.addWidget(self.transcript_settings_button)
        self.transcript_settings_button.clicked.connect(self.show_transcript_settings)
        self.details_button=QPushButton(_tr('诊断详情'));self.details_button.setMaximumHeight(34);row.addWidget(self.details_button);layout.addLayout(row)
        self.performance_button=QPushButton(_tr('性能统计'));self.performance_button.setMaximumHeight(34);row.addWidget(self.performance_button)
        for button in (self.history_button,self.transcript_settings_button,self.details_button,self.performance_button):button.setObjectName('quiet')
        self.refresh_button.clicked.connect(self.controller.refresh_processes)
        self.start_button.clicked.connect(self.start_capture);self.stop_button.clicked.connect(self.controller.stop)
        self.pause_button.clicked.connect(self.controller.toggle_pause)
        self.controller.pause_changed.connect(self.pause_changed)
        self.key_button.clicked.connect(self.configure_key);self.translate_check.toggled.connect(self.mode_changed)
        self.translation_mode.currentIndexChanged.connect(self.translation_mode_changed)
        self.translation_provider.currentIndexChanged.connect(self.translation_provider_changed)
        self.ui_language.currentIndexChanged.connect(self.interface_language_changed)
        self.target_language.currentIndexChanged.connect(self.target_language_changed)
        self.translation_model.currentTextChanged.connect(self.translation_model_changed)
        self.save_transcripts_check.toggled.connect(self.transcript_saving_changed)
        self.transcript_folder_button.clicked.connect(self.choose_transcript_directory)
        self.process_combo.currentIndexChanged.connect(self.selection_changed)
        self.capture_mode.currentIndexChanged.connect(self.capture_mode_changed)
        self.web_connect_button.clicked.connect(self.open_web_connect)
        self.web_local_button.clicked.connect(self.open_local_video)
        self.web_extension_button.clicked.connect(self.open_web_extension)
        self.web_player_choice.currentIndexChanged.connect(self.web_options_changed)
        self.web_speech_engine.currentIndexChanged.connect(self.web_options_changed)
        self.controller.web_ready.connect(self.web_ready)
        self.controller.web_voices_ready.connect(self.web_voices_ready)
        self.overlay_check.toggled.connect(self.toggle_overlay);self.font_slider.valueChanged.connect(self.set_font)
        self.opacity_slider.valueChanged.connect(self.set_opacity);self.details_button.clicked.connect(self.show_diagnostics)
        self.font_value.valueChanged.connect(self.font_slider.setValue);self.sentence_spin.valueChanged.connect(self.set_visible_segments)
        self.focus_check.toggled.connect(self.set_focus_mode)
        self.appearance_button.clicked.connect(self.show_appearance);self.mouse_check.toggled.connect(self.toggle_mouse)
        self.recover_button.clicked.connect(self.recover_overlay);self.performance_button.clicked.connect(self.show_performance)
        self.overlay.input_changed.connect(self.mouse_check.setChecked)
        self.overlay.text_painted.connect(lambda part,token,when:self.controller.painted('overlay',part,token,when))
        self.overlay.focus_text_painted.connect(lambda part,token,when:self.controller.painted('focus',part,token,when))
        self.overlay.focus_settled.connect(self.focus_settled)
        self.overlay.focus_position_changed.connect(self.settings_changed)
        self.overlay.base_speed_changed.connect(self.speech_speed.setValue)
        self.overlay.presentation_waiting.connect(lambda event:self.controller.diagnostics.append(event))
        self.overlay.focus_coalesced.connect(lambda count:self.controller.diagnostics.append(
            {'event':'focus_transitions_coalesced','count':count,'reason':'bounded_animation_queue','subtitle_records_unchanged':True}))
        self.source.painted.connect(lambda token,when:self.controller.painted('main','source',token,when))
        self.translation.painted.connect(lambda token,when:self.controller.painted('main','translation',token,when))
        self.history_button.clicked.connect(self.show_history)
        self.controller.processes_ready.connect(self.processes_ready);self.controller.credentials_ready.connect(self.credentials_ready)
        self.controller.event_received.connect(self.backend_event);self.controller.view_changed.connect(self.render)
        self.controller.subtitle_received.connect(lambda record:self.speech.offer(record) if not self.controller.web_mode else None)
        self.controller.running_changed.connect(self.running_changed);self.controller.finished.connect(self.capture_finished)
        self.controller.problem.connect(self.show_problem)
        self.controller.preferences_saved.connect(self.preferences_saved)
        self.speech.status_changed.connect(lambda value:self.speech_status.setText(value) if not self.is_web_mode() else None);self.speech.problem.connect(self.show_problem)
        self.speech.status_changed.connect(lambda _:self.sync_source_volume())
        self.source_volume.status_changed.connect(self.source_duck_status.setText)
        self.source_volume.diagnostic.connect(lambda row:self.controller.diagnostics.append(row))
        self.speech.diagnostic.connect(lambda event:self.controller.diagnostics.append(event))
        self.speech_preview_button.clicked.connect(self.speech.preview)
        self.speech_clear_button.clicked.connect(lambda:self.speech.clear())
        self.stop_button.clicked.connect(self.speech.stop)
        self.speech_model.currentIndexChanged.connect(self.speech_model_changed)
        self.web_voice.currentIndexChanged.connect(self.speech_settings_changed)
        for widget in (self.speech_voice,self.speech_device):widget.currentIndexChanged.connect(self.speech_settings_changed)
        self.speech_check.toggled.connect(self.speech_settings_changed);self.speech_volume.valueChanged.connect(self.speech_settings_changed)
        self.speech_speed.valueChanged.connect(self.speech_settings_changed);self.speech_catch_up.toggled.connect(self.speech_settings_changed)
        self.speech_catch_chars.valueChanged.connect(self.speech_settings_changed)
        self.speech_catch_grace.valueChanged.connect(self.speech_settings_changed)
        self.source_duck_check.toggled.connect(self.source_volume_settings_changed)
        self.source_duck_percent.valueChanged.connect(self.source_volume_settings_changed)
        self.auto_summary_check.toggled.connect(self.auto_summary_changed)
        self.summary_button.clicked.connect(self.generate_current_notes);self.summary_file_button.clicked.connect(self.generate_file_notes)
        self.summary_open_button.clicked.connect(self.open_notes);self.summary_cancel_button.clicked.connect(self.cancel_notes)
        self.notes.status_changed.connect(self.summary_status.setText);self.notes.problem.connect(self.show_problem)
        self.notes.saved.connect(self.notes_saved);self.notes.busy_changed.connect(self.notes_busy_changed)
        self.scan_timer=QTimer(self);self.scan_timer.setInterval(2500);self.scan_timer.timeout.connect(self.controller.refresh_processes);self.scan_timer.start()
        self.time_timer=QTimer(self);self.time_timer.setInterval(1000);self.time_timer.timeout.connect(self.update_time);self.time_timer.start()
        self.save_timer=QTimer(self);self.save_timer.setSingleShot(True);self.save_timer.setInterval(700)
        self.save_timer.timeout.connect(self.save_preferences)
        self.overlay.geometry_changed.connect(self.settings_changed)
        for widget in (self.language,self.duration,self.translation_mode,self.capture_mode,self.web_voice):widget.currentIndexChanged.connect(self.settings_changed)
        self.web_lookahead.valueChanged.connect(self.settings_changed);self.web_base_speed.valueChanged.connect(self.settings_changed)
        self.apply_settings(self.settings,restore_main=True);self.start_button.setEnabled(self.is_web_mode())
        if enable_global_shortcuts:
            self.hotkeys=GlobalHotkeys(QApplication.instance(),self.winId(),self.shortcut)
            if self.hotkeys.errors:self.recover_button.setToolTip(_tr('部分全局快捷键被占用；可以用此按钮恢复编辑。'))
            else:self.recover_button.setToolTip(_tr('Ctrl+Alt+E 恢复编辑；Ctrl+Alt+S 显示/隐藏字幕。'))
        QApplication.instance().screenAdded.connect(self.screens_changed)
        QApplication.instance().screenRemoved.connect(self.screens_changed)
        self._screen_connections=True
        QTimer.singleShot(0,self.finish_loading_preferences)
        QTimer.singleShot(0,self.controller.refresh_processes);QTimer.singleShot(0,self.controller.refresh_credentials)
        if self.controller.translation_provider!='deepseek':QTimer.singleShot(0,lambda:self.controller.refresh_credentials('deepseek'))

    def finish_loading_preferences(self):
        if self.controller.closed:return
        self._loading_preferences=False
        self.update_speech_controls()
        self.speech.configure(self.speech_config())
        if self.web_speech_engine.currentData()=='system':self.refresh_system_voices()
        if self.preferences_store and self.preferences_store.error:self.show_problem(self.preferences_store.error)

    @staticmethod
    def rectangle(rect):return (rect.x(),rect.y(),rect.width(),rect.height())

    def screens(self):
        screens=QApplication.screens();current=self.screen()
        if current in screens:screens=[current]+[screen for screen in screens if screen!=current]
        return [self.rectangle(screen.availableGeometry()) for screen in screens]

    def apply_settings(self,settings,restore_main=False):
        # Legacy application filters remain readable, but the desktop picker
        # always lists the Windows mixer sources. Keep all other preferences.
        settings=replace(settings.validate(),source='sessions')
        self.settings=settings;self._loading_preferences=True
        try:
            self.font_slider.setValue(settings.font_size);self.font_value.setValue(settings.font_size)
            self.opacity_slider.setValue(settings.opacity);self.sentence_spin.setValue(settings.visible_segments)
            self.focus_check.setChecked(settings.focus_mode)
            self.overlay.apply_appearance(settings);self.set_font(settings.font_size)
            self.overlay.resize(settings.overlay_width,settings.overlay_height)
            if settings.overlay_geometry:
                self.overlay.setGeometry(*place_window(settings.overlay_geometry,self.screens()));self._overlay_positioned=True
            if restore_main:
                self.ui_language.setCurrentIndex(self.ui_language.findData(settings.ui_language))
                self.target_language.setCurrentIndex(self.target_language.findData(settings.target_language))
                if settings.main_geometry:self.setGeometry(*place_window(settings.main_geometry,self.screens(),(720,480)))
                self.web_lookahead.setValue(settings.web_lookahead);self.web_base_speed.setValue(settings.web_base_speed)
                self.web_player_choice.setCurrentIndex(self.web_player_choice.findData(settings.web_player))
                self.web_speech_engine.setCurrentIndex(self.web_speech_engine.findData(settings.web_speech_engine))
                self.capture_mode.setCurrentIndex(self.capture_mode.findData('web' if settings.web_follow else 'audio'))
                self.language.setCurrentIndex(self.language.findData(settings.language));self.duration.setCurrentIndex(self.duration.findData(settings.duration))
                self.translation_mode.setCurrentIndex(self.translation_mode.findData(settings.translation_mode))
                self.provider_models=dict(settings.translation_models)
                self.translation_provider.setCurrentIndex(self.translation_provider.findData(settings.translation_provider))
                self._populate_translation_model(settings.translation_provider)
                self.transcript_directory=Path(settings.transcript_directory) if settings.transcript_directory else None
                self.transcript_folder_label.setText(str(self.transcript_directory) if self.transcript_directory else _tr('尚未选择保存文件夹'))
                self.save_transcripts_check.setChecked(settings.save_transcripts)
                self.speech_check.setChecked(settings.speech_enabled)
                self.speech_device.setCurrentIndex(self.speech_device.findData(settings.speech_device))
                self._last_qwen_model=settings.speech_model_size
                with QSignalBlocker(self.speech_model):self.speech_model.setCurrentIndex(self.speech_model.findData(settings.speech_model_size))
                self.speech_voice.setCurrentIndex(self.speech_voice.findData(settings.speech_voice))
                self.speech_volume.setValue(settings.speech_volume)
                self.speech_speed.setValue(settings.speech_speed);self.speech_catch_up.setChecked(settings.speech_auto_catch_up)
                self.speech_catch_chars.setValue(settings.speech_catch_up_start_chars)
                self.speech_catch_grace.setValue(settings.speech_catch_up_grace_seconds)
                self.source_duck_check.setChecked(settings.speech_duck_source);self.source_duck_percent.setValue(settings.speech_source_percent)
                self.auto_summary_check.setChecked(settings.auto_summary)
                self.transcript_status.setText(_tr('已启用，下次开始时自动保存') if settings.save_transcripts else _tr('未启用保存'))
                if settings.glossary:
                    try:Glossary.load(Path(settings.glossary));self.glossary_path=Path(settings.glossary)
                    except (OSError,ValueError):
                        self.glossary_path=None
                        if self.preferences_store:self.preferences_store.error=_tr('上次选择的翻译术语表不可用，已恢复配置中的术语表。')
                    self.glossary_label.setText(self.glossary_path.name if self.glossary_path else _tr('配置中的工科术语表'))
        finally:
            if not restore_main:self._loading_preferences=False
        self.refresh_overlay();self.update_speech_controls()

    def settings_snapshot(self):
        main=self.normalGeometry()
        if not main.isValid():main=self.geometry()
        return replace(self.overlay.appearance,source='sessions',language=self.language.currentData(),
            ui_language=self.ui_language.currentData(),target_language=self.target_language.currentData(),
            web_follow=self.is_web_mode(),web_lookahead=self.web_lookahead.value(),
            web_voice=self.web_voice.currentData() if self.web_voice.currentData() is not None else -1,
            web_base_speed=self.web_base_speed.value(),
            web_player=self.web_player_choice.currentData(),web_speech_engine=self.web_speech_engine.currentData(),
            **{'web_'+k:v for k,v in self.web_captions.items()},
            duration=self.duration.currentData(),glossary=str(self.glossary_path) if self.glossary_path else '',
            translation_mode=self.translation_mode.currentData(),
            translation_provider=self.translation_provider.currentData(),translation_models=self._model_preferences(),
            save_transcripts=self.save_transcripts_check.isChecked(),
            transcript_directory=str(self.transcript_directory) if self.transcript_directory else '',
            speech_enabled=self.speech_check.isChecked(),speech_device=self.speech_device.currentData(),
            speech_model_size=self._last_qwen_model if self.speech_model.currentData()=='system' else self.speech_model.currentData(),
            speech_voice=self.speech_voice.currentData(),speech_volume=self.speech_volume.value(),
            speech_speed=self.speech_speed.value(),speech_auto_catch_up=self.speech_catch_up.isChecked(),
            speech_catch_up_start_chars=self.speech_catch_chars.value(),speech_catch_up_grace_seconds=self.speech_catch_grace.value(),
            speech_duck_source=self.source_duck_check.isChecked(),speech_source_percent=self.source_duck_percent.value(),
            auto_summary=self.auto_summary_check.isChecked(),
            font_size=self.font_slider.value(),opacity=self.opacity_slider.value(),visible_segments=self.sentence_spin.value(),
            focus_mode=self.focus_check.isChecked(),
            main_geometry=self.rectangle(main),overlay_width=self.overlay.width(),overlay_height=self.overlay.height(),
            overlay_geometry=self.rectangle(self.overlay.geometry()) if self._overlay_positioned else None).validate()

    def settings_changed(self,*args):
        if self._loading_preferences or not self.preferences_store:return
        self._settings_dirty=True;self._save_failed=False;self.save_timer.start()

    def save_preferences(self):
        if not self.preferences_store or not self._settings_dirty:return
        if 'preferences' in self.controller.operations:self.save_timer.start();return
        snapshot=self.settings_snapshot()
        if snapshot==self._saved_settings:self._settings_dirty=False;return
        self.controller.save_preferences(self.preferences_store,snapshot)

    def preferences_saved(self,settings,success):
        if success:
            self._saved_settings=settings;self._settings_dirty=self.settings_snapshot()!=settings
        else:
            self._save_failed=True;self.show_problem(_tr('外观设置未保存，仍可继续使用。'))
        if self.closing:QTimer.singleShot(0,self.close)
        elif self._settings_dirty and not self._save_failed:self.save_timer.start()

    def show_appearance(self):
        dialog=AppearanceDialog(self.settings_snapshot(),self)
        if dialog.exec():self.apply_settings(dialog.value());self.settings_changed()

    def choose_glossary(self):
        filename,_=QFileDialog.getOpenFileName(self,_tr('选择翻译术语表'),str(ROOT/'terminology'),_tr('JSON 术语表 (*.json)'))
        if not filename:return
        try:Glossary.load(Path(filename))
        except (OSError,ValueError):self.show_problem(_tr('术语表无效或无法读取，请选择符合工程术语格式的 JSON 文件。'));return
        self.glossary_path=Path(filename).resolve();self.glossary_label.setText(self.glossary_path.name);self.settings_changed()

    def show_transcript_settings(self):
        self.settings_tabs.setCurrentWidget(self.settings_scroll)
        self.settings_scroll.ensureWidgetVisible(self.transcript_status)

    def choose_transcript_directory(self):
        directory=QFileDialog.getExistingDirectory(self,_tr('选择翻译稿保存文件夹'),str(self.transcript_directory or ROOT))
        if not directory:return False
        self.transcript_directory=Path(directory).resolve()
        self.transcript_folder_label.setText(str(self.transcript_directory));self.settings_changed();return True

    def transcript_saving_changed(self,enabled):
        if self._loading_preferences:return
        if enabled and self.transcript_directory is None and not self.choose_transcript_directory():
            self.save_transcripts_check.setChecked(False);return
        self.transcript_status.setText(_tr('已启用，下次开始时自动保存') if enabled else _tr('未启用保存'))
        self.settings_changed()

    def speech_config(self):
        system=self.web_speech_engine.currentData()=='system'
        return SpeechConfig(self.speech_check.isChecked(),'cpu' if system else self.speech_device.currentData(),
                            self.speech_voice.currentData(),self.speech_volume.value(),self.speech_speed.value(),
                            self.speech_catch_up.isChecked(),self._last_qwen_model if system else self.speech_model.currentData(),
                            self.speech_catch_chars.value(),self.speech_catch_grace.value(),
                            engine='system' if system else 'qwen',system_voice=self.web_voice.currentData() if self.web_voice.currentData() is not None else -1,
                            language=self.target_language.currentData()).validate()

    def interface_language_changed(self):
        if self._loading_preferences:return
        self.settings_changed()
        self.notice.setText('Interface language will apply after restarting ELT.' if self.ui_language.currentData()=='en' else _tr('界面语言将在下次打开 ELT 时生效。'))

    def target_language_changed(self):
        if self._loading_preferences:return
        if self.controller.running:
            with QSignalBlocker(self.target_language):self.target_language.setCurrentIndex(self.target_language.findData(self.speech.config.language))
            return
        with QSignalBlocker(self.web_voice):self.web_voice.clear();self.web_voice.addItem(_tr('正在读取系统朗读音色…'),None)
        if self.target_language.currentData()=='en' and self.speech_voice.currentData() not in ('aiden','ryan','lecture_male'):
            self.speech_voice.setCurrentIndex(self.speech_voice.findData('aiden'))
        if self.web_speech_engine.currentData()=='system':self.refresh_system_voices()
        self.speech_settings_changed();self.mode_changed();self.settings_changed()

    def refresh_system_voices(self):
        language=self.target_language.currentData()
        self.controller.refresh_web_voices() if language=='zh' else self.controller.refresh_web_voices(language)

    def update_speech_controls(self):
        system=self.web_speech_engine.currentData()=='system';web=self.is_web_mode();running=self.controller.running
        wanted='system' if system else self._last_qwen_model if self.speech_model.currentData()=='system' else self.speech_model.currentData()
        if self.speech_model.currentData()!=wanted:
            with QSignalBlocker(self.speech_model):self.speech_model.setCurrentIndex(self.speech_model.findData(wanted))
        self.speech_voice.setVisible(not system);self.web_voice.setVisible(system);self.web_voice_label.hide()
        self.speech_model.setEnabled(not web or not running)
        self.speech_voice.setEnabled(not system and (not web or not running))
        self.speech_device.setEnabled(not system and (not web or not running))
        self.speech_device.setVisible(not system);self.speech_device_label.setVisible(not system)
        self.web_voice.setEnabled(system and (not web or not running))

    def speech_model_changed(self):
        if self._loading_preferences:return
        selected=self.speech_model.currentData();system=selected=='system'
        if not system:self._last_qwen_model=selected
        with QSignalBlocker(self.web_speech_engine):self.web_speech_engine.setCurrentIndex(self.web_speech_engine.findData('system' if system else 'qwen'))
        self.update_speech_controls()
        if system and self.web_voice.currentData() is None:self.refresh_system_voices()
        self.speech_settings_changed()

    def speech_settings_changed(self,*args):
        if self._loading_preferences:return
        if self.is_web_mode():self.settings_changed();return
        self.overlay.set_base_speed(self.speech_speed.value())
        self.speech.configure(self.speech_config())
        if self.controller.running and self.translate_check.isChecked() and self.speech_check.isChecked() and not self.speech.active:
            self.speech.start()
        if self.controller.paused or self.controller.pause_pending:self.speech.pause_playback(True)
        self.settings_changed()

    def sync_source_volume(self):
        if self._loading_preferences:return
        reading=(self.controller.running and self.speech.active) or (self.speech.finishing and self.speech.current is not None)
        enabled=(reading and self.speech.config.enabled and not self.speech.paused and not self.speech.user_paused and self.translate_check.isChecked()
                 and self.source_duck_check.isChecked())
        target=getattr(self.controller,'capture_target',None) if enabled else None
        self.source_volume.set_target(target,self.source_duck_percent.value())

    def source_volume_settings_changed(self,*args):
        if self._loading_preferences:return
        self.sync_source_volume();self.settings_changed()

    def auto_summary_changed(self,enabled):
        if self._loading_preferences:return
        if enabled and self.transcript_directory is None and not self.choose_transcript_directory():
            self.auto_summary_check.setChecked(False);return
        self.summary_status.setText(_tr('下次翻译结束后自动生成 AI 稿。') if enabled else _tr('可在每次翻译结束后手动生成 AI 稿。'))
        self.settings_changed()

    def generate_current_notes(self):
        if self.controller.running:self.show_problem(_tr('请先停止本次翻译，再生成 AI 稿。'));return False
        if not self.notes_key_ready():
            self.show_problem(_tr('请先在翻译页配置 DeepSeek 密钥，再生成 AI 稿。'));return False
        payload=self.controller.course.snapshot()
        if not payload['records']:self.show_problem(_tr('本次尚未取得可整理的完整原文片段。'));return False
        if self.transcript_directory is None and not self.choose_transcript_directory():return False
        payload['name']=self.last_transcript_path.stem if self.last_transcript_path else self.course_name
        payload['incomplete']|=self.transcript_failed or self.controller.forced
        try:self.notes.generate(payload,self.transcript_directory)
        except (ValueError,OSError) as error:self.show_problem(str(error));return False
        return True

    def generate_file_notes(self):
        if self.controller.running:return
        if not self.notes_key_ready():
            self.show_problem(_tr('请先在翻译页配置 DeepSeek 密钥，再生成 AI 稿。'));return
        filename,_=QFileDialog.getOpenFileName(self,_tr('选择已有课程翻译稿'),str(self.transcript_directory or ROOT),_tr('翻译稿 (*.txt)'))
        if not filename:return
        try:
            with Path(filename).open('rb') as source:raw=source.read(32*1024*1024+1)
            if len(raw)>32*1024*1024:raise ValueError(_tr('翻译稿超过 32 MiB，请选择较短的课程稿。'))
            text=raw.decode('utf-8-sig')
            if not text.strip():raise ValueError(_tr('所选翻译稿没有内容。'))
            payload={'name':Path(filename).stem,'records':[{'id':i//6000+1,'source':text[i:i+6000],'translated':''}
                      for i in range(0,len(text),6000)],'incomplete':False,'untranslated':0}
            self.notes.generate(payload,self.transcript_directory or Path(filename).parent)
        except (OSError,ValueError,UnicodeError) as error:self.show_problem(str(error))

    def notes_busy_changed(self,busy):
        self.summary_button.setEnabled(not busy and not self.controller.running and self.controller.course.available)
        self.summary_file_button.setEnabled(not busy and not self.controller.running)
        self.summary_cancel_button.setEnabled(busy)
        if not busy and self.closing and self.isVisible():QTimer.singleShot(0,self.close)

    def notes_saved(self,value):
        self.summary_open_button.setEnabled(True)
        self.summary_open_button.setToolTip(value['path'])
        suffix=_tr(' · 用量未完整') if value.get('unknown_usage_attempts') else ''
        self.summary_status.setText(f"{_tr('AI 稿已保存 · 已报告 ')}{value.get('total_tokens', 0):,} Token"+suffix)

    def open_notes(self):
        if self.notes.last_path and self.notes.last_path.is_file():QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.notes.last_path)))

    def cancel_notes(self):
        self.notes.close();self.summary_status.setText(_tr('AI 整理已取消，原始翻译稿保留，可重新生成。'))

    def show_performance(self):
        if self.performance_dialog is None:self.performance_dialog=PerformanceDialog(self.controller,self)
        self.performance_dialog.timer.start();self.performance_dialog.refresh();self.performance_dialog.show();self.performance_dialog.raise_()

    def screens_changed(self,*args):
        if self.overlay.isVisible():self.overlay.setGeometry(*place_window(self.rectangle(self.overlay.geometry()),self.screens()))
        self.setGeometry(*place_window(self.rectangle(self.geometry()),self.screens(),(720,480)))

    def shortcut(self,action):
        if action=='toggle':self.overlay_check.setChecked(not self.overlay.isVisible())
        elif action=='edit':self.recover_overlay()

    def toggle_mouse(self,enabled):
        if enabled:self.overlay_check.setChecked(True)
        try:self.overlay.set_click_through(enabled)
        except OSError:
            self.overlay.hide();self.mouse_check.blockSignals(True);self.mouse_check.setChecked(False);self.mouse_check.blockSignals(False)
            self.show_problem(_tr('鼠标穿透切换失败，已隐藏悬浮窗；请用恢复按钮重试。'))

    def recover_overlay(self):
        self.mouse_check.setChecked(False);self.overlay.set_click_through(False)
        self.overlay.setGeometry(*place_window(self.rectangle(self.overlay.geometry()),self.screens()))
        self.overlay_check.setChecked(True);self.overlay.raise_()

    def refresh_overlay(self,token=None):
        recent=self.controller.model.recent()
        if recent:self.overlay.present_many(list(reversed(recent)),self.translate_check.isChecked(),token)

    def set_focus_mode(self,enabled):
        self.overlay.apply_appearance(replace(self.overlay.appearance,focus_mode=enabled))
        self.refresh_overlay();self.settings_changed()

    def focus_settled(self,record):
        if not self.focus_check.isChecked() or not self.overlay.isVisible():return
        from .captions import final_translation
        parts=('source','translation') if final_translation(record) else ('source',)
        token=self.controller.begin_paint('focus',record,parts)
        self.overlay.focus.mark_paint(token)

    def set_visible_segments(self,value):
        self.overlay.appearance=replace(self.overlay.appearance,visible_segments=value).validate();self.refresh_overlay();self.settings_changed()

    def set_opacity(self,value):self.overlay.set_opacity(value);self.settings_changed()

    def processes_ready(self,processes,errors):
        if self.is_web_mode():return
        previous=self.process_combo.currentData()
        selected=(previous.pid,previous.created) if previous else None
        self.process_combo.blockSignals(True);self.process_combo.clear()
        self.process_combo.addItem(_tr('请选择要翻译的应用') if processes else _tr('暂未找到有声音的应用'),None)
        for process in processes:
            caption=f'{process.display_name or process.name} · PID {process.pid} · '+(_tr('活动') if process.audio_state=='active' else _tr('空闲'))
            self.process_combo.addItem(self.file_icons.icon(QFileInfo(process.path)),caption,process)
            self.process_combo.setItemData(self.process_combo.count()-1,process.path,Qt.ToolTipRole)
        index=next((i for i in range(1,self.process_combo.count())
                    if (self.process_combo.itemData(i).pid,self.process_combo.itemData(i).created)==selected),None)
        if index is not None:self.process_combo.setCurrentIndex(index)
        elif len(processes)==1 and not self.controller.running:self.process_combo.setCurrentIndex(1)
        self.process_combo.blockSignals(False);self.selection_changed()
        if not processes and not self.controller.running:
            self.notice.setText(_tr('部分应用音频会话无法读取，请在普通 Windows 桌面启动 ELT 后重试。') if errors else
                _tr('暂未找到可选应用。请先在目标应用播放一下声音，再刷新；列表不包含系统声音和本窗口的朗读。'))

    def is_web_mode(self):return self.capture_mode.currentData()=='web'

    def web_player_failed(self,message):
        self.show_problem(message)
        if self.controller.running and self.controller.web_mode and self.web_player_choice.currentData()=='internal':self.controller.stop()

    def web_options_changed(self,*args):
        web=self.is_web_mode();running=self.controller.running
        internal=self.web_player_choice.currentData()=='internal';qwen=self.web_speech_engine.currentData()=='qwen'
        self.web_local_button.setVisible(internal)
        self.web_extension_button.setVisible(not internal);self.web_voice_label.hide()
        self.web_connect_button.setText(_tr('打开课程窗口') if internal else _tr('打开网页连接页') if self.web_connect_url else _tr('启动并连接网页'))
        self.update_speech_controls()
        if not qwen and not self._loading_preferences and self.web_voice.currentData() is None:self.refresh_system_voices()
        if web and internal:
            self.guide.setText(_tr('① 选择语言和朗读　　② 打开本地视频或课程网页　　③ 开始字幕，按视频进度显示'))
            if not running:self.web_status.setText(_tr('同一个 ELT 管理课程、翻译、TTS 和存稿；无需扩展配对。'))
        elif web:self.guide.setText(_tr('① 选择语言、翻译和朗读　　② 启动并连接网页扩展　　③ 回原网页点击扩展开始跟随'))
        if not self._loading_preferences:self.settings_changed()

    def capture_mode_changed(self):
        web=self.is_web_mode()
        if self.controller.running:
            with QSignalBlocker(self.capture_mode):self.capture_mode.setCurrentIndex(self.capture_mode.findData('web' if self.controller.web_mode else 'audio'))
            return
        self.controller.web_mode=web
        self.web_panel.setVisible(web)
        self.web_player_panel.setVisible(web)
        for widget in (self.source_caption,self.source_hint,self.process_combo,self.refresh_button):widget.setVisible(not web)
        self.start_button.setText(_tr('启动视频预读') if web else _tr('开始字幕'))
        self.web_connect_button.setText(_tr('启动并连接网页'))
        for widget in (self.speech_model,self.speech_voice,self.speech_device,self.speech_speed,self.speech_catch_up,
                       self.speech_catch_chars,self.speech_catch_grace,self.speech_preview_button,self.speech_clear_button,
                       self.source_duck_check,self.source_duck_percent,self.translation_mode,
                       self.overlay_check,self.focus_check,self.mouse_check,self.recover_button):widget.setEnabled(not web)
        self.speech_check.setEnabled(True);self.speech_volume.setEnabled(True)
        if web:
            self.speech.stop();self.source_volume.set_target(None,self.source_duck_percent.value())
            self.overlay_check.setChecked(False);self.overlay.hide();self.scan_timer.stop()
            self.target=None;self.start_button.setEnabled(True)
            self.guide.setText(_tr('① 选择语言、翻译和朗读　　② 启动并连接网页扩展　　③ 回原网页点击扩展开始跟随'))
            self.notice.setText(_tr('可打开本地视频，或连接 TUM-Live / Moodle 课程。字幕和朗读按视频进度显示。'))
            self.audio_status.setText(_tr('等待视频连接'));self.speech_status.setText(_tr('视频朗读：可选本地 Qwen TTS 或系统音色'))
        else:
            self.scan_timer.start();self.controller.refresh_processes();self.selection_changed()
            self.guide.setText(_tr('① 在目标应用播放一下声音　　② 选择应用和语言后开始　　③ 音频就绪后继续播放'))
            self.speech_status.setText(_tr('朗读未启动'))
            self.pause_button.setToolTip(_tr('暂停收音和朗读，保留字幕与模型。请同时手动暂停视频。'))
        self.web_options_changed()
        self.settings_changed()

    def web_voices_ready(self,voices):
        selected=self.web_voice.currentData()
        if selected is None:selected=self.settings.web_voice
        with QSignalBlocker(self.web_voice):
            self.web_voice.clear()
            for voice in voices:self.web_voice.addItem(voice['label'],voice['id'])
            index=self.web_voice.findData(selected)
            if index>=0:self.web_voice.setCurrentIndex(index)
        if not voices:self.web_voice.addItem(_tr('未找到对应语言的系统音色'),None)
        self.web_voice.setToolTip(self.web_voice.currentText())
        self.update_speech_controls()
        if self.web_speech_engine.currentData()=='system' and not self._loading_preferences:self.speech_settings_changed()

    def open_web_extension(self):
        path=ROOT/'app/web_follow/extension'
        legacy=ROOT/'experiments/lookahead/extension'
        if (legacy/'manifest.json').is_file() and (legacy/'manifest.json').read_bytes()==(path/'manifest.json').read_bytes():path=legacy
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):self.show_problem(_tr('无法打开扩展目录，请在软件文件夹的 app/web_follow/extension 中查看。'))

    def web_ready(self,url):
        from urllib.parse import urlsplit
        parsed=urlsplit(url)
        if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or not parsed.port or len(parsed.fragment)<20:
            self.show_problem(_tr('网页连接地址无效，已停止本次会话。'));self.controller.stop();return
        self.web_connect_url=url;self.web_connect_button.setEnabled(True);self.web_connect_button.setText(_tr('打开网页连接页'))
        self.web_status.setText(_tr('预读服务已就绪，等待本地文件或课程视频。') if self.web_player_choice.currentData()=='internal' else _tr('服务已就绪，请在连接页配对，再回课程页点扩展开始。'))
        self.web_options_changed()
        self.open_web_connect()

    def open_web_connect(self):
        if self.web_player_choice.currentData()=='internal':
            self.web_player.open(self.web_connect_url);return
        if not self.controller.running:
            self.start_capture();return
        if not self.web_connect_url:return
        if not QDesktopServices.openUrl(QUrl('microsoft-edge:'+self.web_connect_url)):
            self.show_problem(_tr('无法打开 Edge，请检查浏览器安装；本机服务仍在运行。'))

    def open_local_video(self):
        if self.controller.running and self.web_player_choice.currentData()!='internal':
            self.show_problem(_tr('请先停止当前字幕，再切换到本地视频。'));return
        if not self.is_web_mode():self.capture_mode.setCurrentIndex(self.capture_mode.findData('web'))
        self.web_player_choice.setCurrentIndex(self.web_player_choice.findData('internal'))
        self.web_player.open_file(self.web_connect_url)

    def web_start_requested(self):
        if self.closing or self.controller.running:return
        self.capture_mode.setCurrentIndex(self.capture_mode.findData('web'))
        self.web_player_choice.setCurrentIndex(self.web_player_choice.findData('internal'))
        self.start_capture()

    def start_web_capture(self):
        if (self.save_transcripts_check.isChecked() or self.auto_summary_check.isChecked()) and self.transcript_directory is None:
            if not self.choose_transcript_directory():return
        try:
            translate=self.translate_check.isChecked();narrate=translate and self.speech_check.isChecked()
            if translate and not self.credential_status.get('available'):raise ValueError(_tr('请先为所选服务保存密钥。'))
            voice=self.web_voice.currentData()
            if narrate and self.web_speech_engine.currentData()=='system' and voice is None:
                raise ValueError(_tr('未找到对应语言的 Windows 音色，请选择本地 Qwen TTS 或安装相应系统语音。'))
            if narrate and self.web_speech_engine.currentData()=='qwen':
                from app.speech.config import PYTHON
                if not PYTHON.is_file() or not (self.speech_config().model_path/'model.safetensors').is_file():
                    raise ValueError(_tr('所选 Qwen TTS 模型或朗读运行环境尚未准备好，请选择已有模型或系统音色。'))
            options=dict(language=self.language.currentData(),provider=self.translation_provider.currentData(),
                model=validate_model(self.translation_provider.currentData(),self.translation_model.currentText().strip()) if translate else PROVIDERS[self.translation_provider.currentData()].models[0],
                translate=translate,narrate=narrate,voice=voice if voice is not None else 0,
                lookahead=self.web_lookahead.value(),base_speed=self.web_base_speed.value(),volume=self.speech_volume.value(),
                duck_source=self.source_duck_check.isChecked(),source_percent=self.source_duck_percent.value(),
                glossary=str(self.glossary_path) if self.glossary_path else '')
            options.update(speech_engine=self.web_speech_engine.currentData(),tts_device=self.speech_config().device,
                           tts_model=self.speech_config().model_size,tts_voice=self.speech_voice.currentData())
            options.update(self.web_captions)
            options.update(target_language=self.target_language.currentData(),ui_language=get_language())
            self.web_connect_url='';self.speech.stop()
            self.controller.start_web(options,self.duration.currentData(),self.transcript_directory if self.save_transcripts_check.isChecked() else None)
        except Exception as error:self.show_problem(str(error))

    def source_title(self):
        if self.is_web_mode():return _tr('视频播放器')
        target=getattr(self.controller,'capture_target',None) if self.controller.running else self.target
        return (target.display_name or target.name) if target else _tr('Windows 应用音频')

    def selection_changed(self):
        if self.is_web_mode():
            self.target=None;self.start_button.setEnabled(not self.controller.running);return
        self.target=self.process_combo.currentData()
        if not self.controller.running:
            title=self.source_title()
            self.audio_status.setText(f'{title} · {self.target.pid}' if self.target else f"{_tr('等待选择 ')}{title}")
            self.start_button.setEnabled(self.target is not None)

    def credentials_ready(self,status):
        provider=status.get('provider',self.translation_provider.currentData())
        if provider not in PROVIDERS:return
        self.provider_credentials[provider]=dict(status)
        index=self.translation_provider.findData(provider)
        self.translation_provider.setItemText(index,PROVIDERS[provider].label+(_tr(' · 已配置') if status.get('available') else ''))
        if provider!=self.translation_provider.currentData():return
        self.credential_status=status
        ready=status.get('available',False)
        self.key_status.setText(_tr('密钥已配置，开始后才能验证连接。') if ready else _tr('未配置密钥，可直接使用本地原文。'))
        if status.get('source')=='read_error':self.key_status.setText(status.get('error') or _tr('暂时无法读取凭据，可先使用本地原文。'))
        self.translate_check.setEnabled(ready and not self.controller.running)
        if not ready:self.translate_check.setChecked(False)

    def _populate_translation_model(self,provider):
        info=provider_info(provider);self._provider_code=provider;self.controller.translation_provider=provider
        with QSignalBlocker(self.translation_model):
            self.translation_model.clear();self.translation_model.addItems(info.models)
            self.translation_model.setCurrentText(self.provider_models.get(provider,info.models[0]))

    def _model_preferences(self):
        values=dict(self.provider_models);provider=self.translation_provider.currentData()
        try:values[provider]=validate_model(provider,self.translation_model.currentText().strip())
        except ValueError:pass  # incomplete typing is never persisted as a model ID
        return values

    def translation_provider_changed(self,*args):
        provider=self.translation_provider.currentData()
        if not self._loading_preferences:
            try:self.provider_models[self._provider_code]=validate_model(self._provider_code,self.translation_model.currentText().strip())
            except ValueError:pass
        self._populate_translation_model(provider)
        if self._loading_preferences:return
        self.credential_status=self.provider_credentials.get(provider,{'available':False,'source':'unavailable'})
        self.translate_check.setEnabled(False);self.key_status.setText(_tr('正在检查所选服务的密钥…'))
        self.controller.refresh_credentials(provider);self.settings_changed()

    def translation_model_changed(self,*args):
        if not self._loading_preferences:self.provider_models=self._model_preferences();self.settings_changed()

    def notes_key_ready(self):
        return (self.credential_status if self.translation_provider.currentData()=='deepseek' else
                self.provider_credentials.get('deepseek',{})).get('available',False)

    def mode_changed(self,checked):
        self.mode_badge.setText((_tr('原文 + 中文翻译') if self.target_language.currentData()=='zh' else _tr('原文 + 英文翻译')) if checked else _tr('本地原文模式'))
        self.translation_status.setText(_tr('待连接') if checked else _tr('仅原文'))
        if not self.controller.running:
            self.translation.setText((_tr('原文实时显示，等整句结束后翻译。') if self.translation_mode.currentData()=='sentence'
                                      else _tr('开始后将流式显示译文。')) if checked else _tr('当前为本地原文模式'))

    def translation_mode_changed(self):
        sentence=self.translation_mode.currentData()=='sentence'
        self.translation_mode_hint.setText(_tr('原文实时显示，等句末或停顿后翻译；极长内容会安全分段。') if sentence else
                                          _tr('稳定短语先翻译，句末再确认；同一片段可能多次请求。'))
        self.mode_changed(self.translate_check.isChecked())

    def start_capture(self):
        if self.is_web_mode():self.start_web_capture();return
        target=self.process_combo.currentData()
        if target is None:self.show_problem(_tr('请先选择一个音频来源进程。'));return
        if (self.save_transcripts_check.isChecked() or self.auto_summary_check.isChecked()) and self.transcript_directory is None:
            if not self.choose_transcript_directory():return
        try:
            if self.translate_check.isChecked() and not self.credential_status.get('available'):
                raise ValueError(_tr('请先为所选翻译服务保存密钥，并等待密钥状态读取完成。'))
            model=validate_model(self.translation_provider.currentData(),self.translation_model.currentText().strip()) if self.translate_check.isChecked() else None
            self.controller.start(target,self.language.currentData(),self.translate_check.isChecked(),self.duration.currentData(),
                                  glossary=self.glossary_path,translation_mode=self.translation_mode.currentData(),
                                  transcript_directory=self.transcript_directory if self.save_transcripts_check.isChecked() else None,
                                  translation_model=model,target_language=self.target_language.currentData())
        except Exception as error:self.show_problem(str(error))

    def pause_changed(self):
        if self.controller.web_mode:
            self.pause_button.setEnabled(False);self.pause_button.setToolTip(_tr('网页模式请使用原播放器暂停、继续和跳转。'));return
        controller=self.controller
        pending=controller.pause_pending
        self.pause_button.setEnabled(controller.running and controller.audio_ready and not controller.stopping and not pending)
        self.pause_button.setText((_tr('恢复中…') if controller.paused else _tr('暂停中…')) if pending else (_tr('继续') if controller.paused else _tr('暂停')))
        if controller.running:
            self.speech.pause_playback(controller.paused or pending)
            if controller.paused and not pending:
                self.audio_status.setText(_tr('已暂停收音'));self.notice.setText(_tr('已暂停收音和朗读；暂停前的尾句仍可补齐。请手动暂停视频，暂停期间的新声音不会转写。'))
            elif not pending and controller.audio_ready:self.audio_status.setText(f"{_tr('已连接 ')}{self.source_title()}")
        self.sync_source_volume()

    def running_changed(self,running):
        self.pause_button.setEnabled(False)
        if running:self.refresh_usage()
        for item in (self.process_combo,self.language,self.target_language,self.duration,self.key_button,
                     self.glossary_button,self.translation_mode,self.save_transcripts_check,self.transcript_folder_button,
                     self.auto_summary_check,self.translation_provider,self.translation_model):item.setEnabled(not running)
        self.speech_preview_button.setEnabled(not running)
        self.notes_busy_changed(self.notes.busy)
        self.translate_check.setEnabled(not running and self.credential_status.get('available',False))
        self.capture_mode.setEnabled(not running)
        self.start_button.setEnabled(not running and (self.is_web_mode() or self.target is not None));self.stop_button.setEnabled(running)
        self.web_connect_button.setEnabled(not running or bool(self.web_connect_url))
        for widget in (self.web_lookahead,self.web_voice,self.web_base_speed,self.web_player_choice,self.web_speech_engine):widget.setEnabled(not running)
        if self.is_web_mode():
            for widget in (self.translation_mode,self.speech_model,self.speech_voice,self.speech_device,self.speech_speed,
                           self.speech_catch_up,self.speech_catch_chars,self.speech_catch_grace,self.speech_preview_button,
                           self.speech_clear_button,self.source_duck_check,self.source_duck_percent):widget.setEnabled(False)
            self.speech_check.setEnabled(not running);self.speech_volume.setEnabled(not running)
            self.web_options_changed()
        if running:
            self._auto_summary_session=self.auto_summary_check.isChecked();self._summary_started=False
            self.course_name=datetime.now().astimezone().strftime('%Y-%m-%d-%H%M')+_tr('-课程')
            self.speech.configure(self.speech_config())
            if not self.controller.web_mode and self.speech_check.isChecked() and self.translate_check.isChecked():self.speech.start()
            self.last_transcript_path=None;self.transcript_failed=False;self._save_session=self.save_transcripts_check.isChecked()
            self.transcript_status.setText(_tr('准备保存翻译稿…') if self._save_session else _tr('未启用保存'))
            self.started_at=time.monotonic();self.asr_status.setText(_tr('准备模型中…'))
            self.source.setText(_tr('正在准备本地识别模型…'));self.translation.setText(_tr('等待原文…') if self.translate_check.isChecked() else _tr('当前为本地原文模式'))
            self.history.clear();self.history_signature=None;self.subtitle_state.setText(_tr('准备中'))
            self.overlay.clear(_tr('正在准备本地识别模型…'))
            title=self.source_title()
            self.notice.setText(f"{_tr('正在准备本地模型，请暂时保持 ')}{title}{_tr(' 视频暂停；音频连接就绪后再继续播放。')}")
            self.notice.setProperty('severity','info');self.notice.style().unpolish(self.notice);self.notice.style().polish(self.notice)
            if self.controller.web_mode:
                internal=self.web_player_choice.currentData()=='internal'
                self.asr_status.setText(_tr('等待视频开始'));self.audio_status.setText(_tr('正在启动视频预读服务'))
                self.source.set_caption(_tr('等待本地文件或网页视频…') if internal else _tr('等待连接网页播放器…'));self.subtitle_state.setText(_tr('视频预读'))
                self.notice.setText(_tr('正在连接内置播放器；可打开本地视频或课程网页。') if internal else _tr('正在打开网页连接页；配对后回课程页点击 ELT 扩展开始。视频保持原有播放状态。'))
                self.speech_status.setText(_tr('网页朗读按原视频时间驱动 · ')+(_tr('本地 Qwen TTS') if self.web_speech_engine.currentData()=='qwen' else _tr('Windows 系统音色')))

    def backend_event(self,event):
        name=event['event']
        if name in ('translation_usage','translation_submitted','bilingual_summary'):self.refresh_usage()
        if self.controller.web_mode:
            if name=='gui_backend_error':self.show_problem(event.get('message') or _tr('网页服务启动失败，请查看诊断。'));return
            if name=='web_clock':
                playback=event.get('playback_options',{});changed=False
                for key in self.web_captions:
                    if key in playback and self.web_captions[key]!=playback[key]:
                        self.web_captions[key]=playback[key];changed=True
                if playback.get('tts_model') in ('0.6B','1.7B'):self._last_qwen_model=playback['tts_model']
                for key,widget in (('narrate',self.speech_check),('volume',self.speech_volume),('base_speed',self.web_base_speed),
                                   ('duck_source',self.source_duck_check),('source_percent',self.source_duck_percent)):
                    if key not in playback:continue
                    value=playback[key];toggle=key in ('narrate','duck_source');old=widget.isChecked() if toggle else widget.value()
                    if value!=old:
                        with QSignalBlocker(widget):
                            if toggle:widget.setChecked(value)
                            else:widget.setValue(value)
                        changed=True
                for key,widget in (('speech_engine',self.web_speech_engine),('tts_model',self.speech_model),('tts_voice',self.speech_voice),('voice',self.web_voice)):
                    if key in playback and widget.currentData()!=playback[key]:
                        index=widget.findData(playback[key])
                        if index>=0:
                            with QSignalBlocker(widget):widget.setCurrentIndex(index)
                            changed=True
                if changed:self.web_options_changed()
                internal=self.web_player_choice.currentData()=='internal'
                local=event.get('source_kind')=='local_file'
                self.web_status.setText(_tr('已连接本地视频') if local and event['has_source'] else _tr('已连接课程页') if event['has_source'] else _tr('自动等待课程窗口中的视频') if internal else _tr('已配对，请回课程页点扩展开始') if event['paired'] else _tr('等待连接网页扩展'))
                self.audio_status.setText((_tr('本地视频已连接') if local else _tr('网页播放器已连接')) if event['has_source'] else _tr('等待视频开始'))
                device='GPU' if event.get('device')=='cuda' else 'CPU' if event.get('device')=='cpu' else _tr('识别')
                self.asr_status.setText(_tr('预读已停止，请查看错误') if event['status']=='error' else device+_tr('预读就绪') if event['status']=='ready' else _tr('预读准备中') if event['has_source'] else _tr('等待课程开始'))
                ahead=max(0,event['prepared_until']-event['position'])
                self.metrics.setText(f"{_tr('原文预读 ')}{ahead:.1f}{_tr(' 秒 · 译文预读 ')}{event.get('translation_ahead_seconds', 0):.1f}{_tr(' 秒 · 翻译排队 ')}{event.get('translation_queue', 0)}{_tr(' · 跳过窗口 ')}{event['skipped_windows']}")
                if event.get('error'):self.notice.setText(event['error'])
                elif event['has_source']:
                    offset=event.get('clock_offset_seconds',0)
                    timing=(f"{_tr('已对时：字幕')}{(_tr('提前') if offset >= 0 else _tr('延后'))} {abs(offset):.2f}{_tr(' 秒。 ')}" if event.get('clock_calibrated') else
                            _tr('正在校准声音时间；首次请保持原声开启、1 倍速播放。 ') if event.get('audio_alignment',{}).get('status')=='sampling' else
                            _tr('尚未完成声音对时；请在原声开启、1 倍速时重新开始字幕。 ') if event.get('audio_alignment',{}).get('status')=='inconclusive' else '')
                    self.notice.setText((_tr('本地文件预读；') if local else timing)+_tr('字幕按视频时间显示。播放、暂停、跳转和倍速由你控制。'))
                else:self.notice.setText(_tr('请打开课程窗口并播放视频，字幕和译文朗读会自动跟随。') if internal else _tr('等待网页视频连接；请在课程页启动 ELT 跟随。'))
                tts=event.get('tts',{})
                if not event['has_source']:self.speech_status.setText(_tr('网页朗读等待课程视频'))
                elif tts:self.speech_status.setText(_tr('本地 Qwen TTS · ')+{'loading':_tr('模型准备中'),'ready':_tr('已就绪'),'skipped':_tr('已跳过过期语音'),'error':_tr('朗读暂不可用，字幕继续')}.get(tts.get('status'),_tr('等待译文')))
                self.pause_button.setEnabled(False);return
            if name in ('asr_model_ready','audio_source_ready'):return
        title=self.source_title()
        if name=='asr_model_ready':
            self.asr_status.setText(_tr('GPU 已就绪') if event.get('device')=='cuda' else _tr('CPU 已就绪'));self.subtitle_state.setText(_tr('等待语音'))
            self.source.setText(_tr('等待课程语音…'));self.notice.setText(f"{_tr('模型已就绪，正在连接 ')}{title}{_tr(' 音频…')}")
        elif name=='audio_source_ready':
            self.audio_status.setText(f"{_tr('已连接 ')}{title}");self.notice.setText(f"{_tr('音频连接已就绪，现在可以继续播放 ')}{title}。")
        elif name=='audio_capture_resumed':
            self.notice.setText(f"{_tr('已恢复收音和朗读，可以继续播放 ')}{title}。")
        elif name=='asr_result':self.metrics.setText(f"{_tr('单次识别处理 ')}{event['inference_seconds']:.2f}{_tr(' 秒\u3000·\u3000显卡总占用 ')}{getattr(self, 'gpu_memory', '—')}")
        elif name=='gpu':
            self.gpu_memory=f"{event['total_device_memory_mib']} MiB"  # entire device, not model-only
        elif name=='translation_status':self.translation_status.setText(_tr('等待整句') if event.get('mode')=='sentence' else _tr('等待首次请求'))
        elif name=='translation_submitted':self.translation_status.setText(_tr('翻译请求中…'))
        elif name=='translation_completed' and event.get('applied'):self.translation_status.setText(_tr('已收到译文'))
        elif name=='transcript_started':self.transcript_status.setText(_tr('正在自动保存；停止后生成正式文件名'))
        elif name=='transcript_error':
            self.transcript_failed=True;self.transcript_status.setText(_tr('保存出现错误，稿件可能不完整'))
            self.show_problem(_tr('翻译稿保存出现错误，翻译仍可继续。请停止后检查保存文件夹。'))
        elif name=='transcript_saved':
            self.last_transcript_path=Path(event['transcript_path'])
            self.transcript_failed|=not event.get('transcript_complete',False)
            suffix=f"；{event['transcript_untranslated']}{_tr(' 条翻译未完成')}" if event.get('transcript_untranslated') else ''
            if event.get('transcript_records')==0:suffix+=_tr('；未取得已确认原文')
            self.transcript_status.setText((_tr('已保存部分稿件：') if self.transcript_failed else _tr('已保存：'))+self.last_transcript_path.name+suffix)
            self.transcript_status.setToolTip(str(self.last_transcript_path))
        elif name=='translation_unavailable':
            reason=event.get('reason')
            self.translation_status.setText(_tr('仅原文') if reason=='translation_disabled_by_user' else _tr('翻译不可用'))
        elif name=='translation_error':
            api_label=PROVIDERS[self.translation_provider.currentData()].label
            messages={'authentication_failed':_tr('密钥验证失败，请停止后检查密钥。'),'insufficient_balance':f"{api_label}{_tr(' 余额不足，原文继续显示。')}",
                      'invalid_request_or_model':_tr('所选模型不可用或参数不兼容，请停止后检查模型名称和账号权限。'),
                      'rate_limited':_tr('翻译服务暂时限流，正在有限重试。'),'network_timeout':_tr('翻译连接超时，原文继续显示。'),
                      'request_deadline':_tr('翻译请求超时，原文继续显示。'),
                      'translation_finish_length':_tr('这句译文超过输出长度限制，未作为完整译文显示；原文已保留。')}
            self.notice.setText(messages.get(event.get('code'),_tr('翻译暂时不可用，原文继续显示。')))
        elif name in ('translation_backlog_drop','translation_expired'):
            self.notice.setText(_tr('翻译任务积压或等待过久，部分片段未完成翻译；原文已保留，可在最近字幕或翻译稿中核查。'))
        elif name=='gui_stopping':self.notice.setText(_tr('正在停止并释放音频、模型和网络资源…'));self.stop_button.setEnabled(False)
        elif name in ('bilingual_source_error','bilingual_error','asr_error','gui_backend_error'):
            message=event.get('message','')
            self.show_problem(f"{title}{_tr(' 已退出，请刷新列表后重新选择。')}" if 'target_exited' in message else _tr('本次运行出现异常，请查看诊断详情。'))

    def capture_finished(self,code,requested):
        if self.controller.web_mode:self.web_player.disconnect()
        self.web_connect_url=''
        self.refresh_usage()
        self.asr_status.setText(_tr('已停止'));self.started_at=None
        self.elapsed.setText(_tr('本次会话已结束'))
        if requested:self.notice.setText((_tr('视频预读已停止，播放器仍可继续播放。') if self.controller.web_mode else _tr('已停止。后台音频捕获和识别进程已清理。')) if not self.controller.forced else _tr('已强制停止。本次未完成的字幕已取消。'))
        elif code in (0,3):self.notice.setText(_tr('本次会话已结束。') if code==0 else _tr('本地原文会话已结束；翻译未启用或未完成。'))
        if self._save_session:
            if self.transcript_failed:self.show_problem(_tr('本次会话已结束，但翻译稿保存出现错误；请查看保存状态，进行中文件可能保留。'))
            elif self.last_transcript_path:self.notice.setText(self.notice.text()+_tr('\n翻译稿已保存：')+str(self.last_transcript_path))
            else:
                self.transcript_status.setText(_tr('未收到保存完成状态，请检查进行中文件'))
                self.show_problem(_tr('本次会话已结束，未确认翻译稿保存完成；请检查保存文件夹中的进行中文件。'))
        if requested or self.speech.user_paused:self.speech.stop()
        else:self.speech.finish_input()
        self.notes_busy_changed(self.notes.busy)
        if self._auto_summary_session and not self._summary_started and self.controller.course.available:
            self._summary_started=self.generate_current_notes()
        elif self._auto_summary_session and not self.controller.course.available:
            self.summary_status.setText(_tr('本次没有完整课程内容，未生成 AI 稿。'))
        if self.closing:QTimer.singleShot(0,self.close)

    def render(self):
        record=self.controller.model.current
        if self.controller.web_mode and not record:
            preview=self.controller.web_clock.get('preview_source','')
            self.source.set_caption(source_html({'source_text':'','candidate_text':preview}) if preview else _tr('等待当前播放位置的字幕…'))
            self.translation.set_caption('');self.subtitle_state.setText(_tr('原文预览') if preview else _tr('等待下一句'))
        if record:
            token=self.controller.begin_paint('main',record) if self.isVisible() and not self.isMinimized() else None
            self.source.set_caption(source_html(record),token)
            text=record.get('translated_text','')
            self.translation.set_caption(translation_caption(record) if self.translate_check.isChecked() or text else _tr('当前为本地原文模式'),token)
            self.subtitle_state.setText(_tr('已确认') if record['state']=='final' else _tr('预览 · 可修订'))
            old_prefix=bool(text) and record.get('translated_revision')!=record['revision']
            self.caption_note.setText(_tr('译文对应前段原文，正在等待补全。') if old_prefix else _tr('原文中的浅色部分仍可能修订。'))
            parts=('source','translation') if self.translate_check.isChecked() or text else ('source',)
            token=self.controller.begin_paint('overlay',record,parts) if self.overlay.isVisible() and not self.focus_check.isChecked() else None
            if not self.controller.web_mode:self.refresh_overlay(token)
        recent=self.controller.model.recent()[:16]
        signature=tuple((r['segment_id'],r['revision'],r.get('translated_text',''),r['state']) for r in recent)
        if signature!=self.history_signature:
            self.history_signature=signature
            text=[]
            for r in recent:
                if not r['source_text']:continue
                text.append(r['source_text'])
                if r.get('translated_text'):text.append(r['translated_text'])
                text.append('')
            self.history.setPlainText('\n'.join(text))

    def configure_key(self):
        dialog=KeyDialog(self.controller,self.credential_status,self);dialog.exec()

    def set_font(self,size):
        for item in (self.source,self.translation):
            font=item.font();font.setPointSize(size);item.setFont(font)
        self.overlay.set_font(size)
        self.font_value.setValue(size);self.settings_changed()

    def toggle_overlay(self,enabled):
        if self.is_web_mode() and enabled:
            with QSignalBlocker(self.overlay_check):self.overlay_check.setChecked(False)
            return
        if enabled:
            if not self.overlay.isVisible():
                if not self._overlay_positioned:
                    screen=self.screen().availableGeometry()
                    self.overlay.move(screen.x()+(screen.width()-self.overlay.width())//2,
                                      screen.y()+screen.height()-self.overlay.height()-65)
                    self._overlay_positioned=True
                self.overlay.setGeometry(*place_window(self.rectangle(self.overlay.geometry()),self.screens()))
                self.refresh_overlay()
                self.overlay.show()
        else:self.overlay.hide()

    def update_time(self):
        self.refresh_usage()
        if self.started_at is not None:
            seconds=int(time.monotonic()-self.started_at)
            self.elapsed.setText(f"{_tr('已运行 ')}{seconds // 60:02d}:{seconds % 60:02d}")

    def refresh_usage(self):
        short,detail=usage_text(self.controller.telemetry.snapshot())
        self.usage_summary.setText(short);self.usage_summary.setToolTip(detail+_tr('\n完整明细见“性能统计”。输入包括提示词、术语与上下文。'))

    def show_problem(self,message):
        self.notice.setText(message);self.notice.setProperty('severity','error')
        self.notice.style().unpolish(self.notice);self.notice.style().polish(self.notice)

    def show_diagnostics(self):
        dialog=QDialog(self);dialog.setWindowTitle(_tr('运行诊断'));dialog.resize(760,500)
        box=QVBoxLayout(dialog);box.addWidget(label(_tr('仅本次内存数据；导出时保存到你指定的新文件。'),'muted'))
        text=QPlainTextEdit();text.setReadOnly(True);text.document().setMaximumBlockCount(500)
        value={'events':list(self.controller.diagnostics),'stderr_tail':self.controller.stderr_tail,
               'backend_running':self.controller.running,'backend_pid':self.controller.backend_pid,
               'performance':self.controller.telemetry.snapshot(),
               'shortcuts':self.hotkeys.errors if self.hotkeys else {'active':False}}
        text.setPlainText(json.dumps(value,ensure_ascii=False,indent=2));box.addWidget(text)
        row=QHBoxLayout();row.addStretch();export=QPushButton(_tr('导出诊断'));close=QPushButton(_tr('关闭'));close.clicked.connect(dialog.accept)
        def save():
            filename,_=QFileDialog.getSaveFileName(dialog,_tr('保存诊断到新文件'),'',_tr('JSON 文件 (*.json)'))
            if not filename:return
            try:
                with Path(filename).open('x',encoding='utf-8') as output:json.dump(value,output,ensure_ascii=False,indent=2)
            except OSError:self.show_problem(_tr('诊断未保存：请选择尚不存在的新文件。'))
        export.clicked.connect(save);row.addWidget(export);row.addWidget(close);box.addLayout(row);dialog.exec()

    def show_history(self):
        self.history_dialog.show();self.history_dialog.raise_();self.history_dialog.activateWindow()

    def closeEvent(self,event:QCloseEvent):
        self.speech.stop()
        if self.controller.running:
            self.closing=True;self.controller.stop();event.ignore();return
        if self.notes.busy:
            self.closing=True;self.settings_tabs.setCurrentWidget(self.settings_scroll)
            self.settings_scroll.ensureWidgetVisible(self.summary_cancel_button)
            self.notice.setText(_tr('正在完成 AI 稿，完成后自动退出；也可在存稿页取消 AI 整理后退出。'))
            event.ignore();return
        if self.preferences_store and self._settings_dirty and not self._save_failed:
            self.closing=True;self.save_timer.stop()
            if 'preferences' in self.controller.operations:event.ignore();return
            self.save_preferences()
            if 'preferences' in self.controller.operations:event.ignore();return
        self.scan_timer.stop();self.time_timer.stop();self.overlay.hide();self.overlay.close()
        self.save_timer.stop()
        if self.hotkeys:self.hotkeys.close()
        if self._screen_connections:
            QApplication.instance().screenAdded.disconnect(self.screens_changed)
            QApplication.instance().screenRemoved.disconnect(self.screens_changed);self._screen_connections=False
        if self.performance_dialog:self.performance_dialog.close()
        self.history_dialog.close()
        self.web_player.close();self.speech.close();self.source_volume.close();self.notes.close();self.controller.cleanup_idle();event.accept()

    def moveEvent(self,event):
        super().moveEvent(event)
        if hasattr(self,'save_timer'):self.settings_changed()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'save_timer'):self.settings_changed()
