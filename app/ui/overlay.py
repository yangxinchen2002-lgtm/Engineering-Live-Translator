"""Rendering and native input behavior only; no capture/model/network access."""
from app.i18n import tr as _tr
from dataclasses import replace
from collections import OrderedDict
import ctypes as ct
import html
import os
import time
from pathlib import Path
from PySide6.QtCore import Qt,Signal,QTimer,QSignalBlocker
from PySide6.QtGui import QColor,QPainter,QFont
from PySide6.QtWidgets import QApplication,QWidget,QLabel,QVBoxLayout,QHBoxLayout,QPushButton,QSizeGrip,QScrollArea,QSizePolicy,QDoubleSpinBox
from app.asr.clock import now_ns
from app.languages import NO_SPACE_LANGUAGES
from .preferences import UISettings
from .focus import FocusViewport
from .captions import translation_caption,final_translation,translation_pending,reading_hold_ms


def source_html(record,candidate_color='#8c9ab1'):
    stable=html.escape(record.get('source_text',''));candidate=html.escape(record.get('candidate_text',''))
    separator='' if record.get('source_language') in NO_SPACE_LANGUAGES else ' '
    return f'<span>{stable}</span>{separator}<span style="color:{candidate_color}">{candidate}</span>'


class CaptionLabel(QLabel):
    painted=Signal(object,object)
    def __init__(self,text=''):
        super().__init__(text);self.setWordWrap(True);self.setTextFormat(Qt.PlainText);self.pending_token=None

    def set_caption(self,text,token=None):
        self.pending_token=token;self.setText(text);self.update()

    def paintEvent(self,event):
        super().paintEvent(event)
        if self.pending_token is not None:
            token=self.pending_token;self.pending_token=None;self.painted.emit(token,now_ns())


class Overlay(QWidget):
    hidden=Signal()
    input_changed=Signal(bool)
    geometry_changed=Signal()
    text_painted=Signal(str,object,object)
    focus_text_painted=Signal(str,object,object)
    focus_settled=Signal(object)
    focus_coalesced=Signal(int)
    focus_position_changed=Signal()
    base_speed_changed=Signal(float)
    presentation_waiting=Signal(object)
    def __init__(self,parent=None):
        super().__init__(None,Qt.Window|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint)
        self.setWindowTitle(_tr('ELT · 悬浮字幕'));self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.appearance=UISettings();self.alpha=round(86*255/100);self.click_through=False;self._changing_flags=False
        self.record=None;self.records=[];self.rows=OrderedDict();self.translation_enabled=False;self._drag_offset=None
        self.list_session=None;self.list_frontier=-1;self.list_blocked=None;self.list_hold=None;self.list_read_until=0.;self.list_signature=None
        self.list_timer=QTimer(self);self.list_timer.setSingleShot(True)
        self.list_timer.timeout.connect(lambda:self.present_many(self.records,self.translation_enabled))
        self.setMinimumSize(280,120);self.setMaximumSize(8000,8000);self.resize(900,360)
        box=QVBoxLayout(self);box.setContentsMargins(20,12,18,10);box.setSpacing(8)
        row=QHBoxLayout();self.title=QLabel(_tr('ELT · 等待语音'))
        self.title.setStyleSheet('color:#a7b6d0; font-size:9pt; background:transparent;')
        self.title.setAttribute(Qt.WA_TransparentForMouseEvents);row.addWidget(self.title,1)
        self.title.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        self.locate=QPushButton(_tr('定位'));self.locate.setCheckable(True);self.locate.setChecked(True)
        self.locate.setToolTip(_tr('显示或隐藏可拖动的焦点标识；双击标识复位。'))
        self.base_speed=QDoubleSpinBox();self.base_speed.setRange(.8,2.);self.base_speed.setSingleStep(.05)
        self.base_speed.setDecimals(2);self.base_speed.setPrefix(_tr('基础 '));self.base_speed.setSuffix('×')
        self.base_speed.setFixedWidth(112);self.base_speed.setAccessibleName(_tr('朗读基础速度'))
        self.base_speed.setToolTip(_tr('朗读基础速度；自动追赶仍最多为此速度的 1.5 倍。'))
        self.base_speed.valueChanged.connect(self.base_speed_changed.emit)
        for item in (self.locate,self.base_speed):
            item.setStyleSheet('color:#c9d8ef;background:#1b2b43;border:1px solid #3d5475;border-radius:5px;padding:3px;font-size:9pt;')
            row.addWidget(item)
        assets=(Path(__file__).parent/'assets').as_posix()
        self.base_speed.setStyleSheet(f'''
            QDoubleSpinBox {{color:#c9d8ef;background:#1b2b43;border:1px solid #3d5475;
                border-radius:5px;padding:3px 20px 3px 6px;font-size:9pt;}}
            QDoubleSpinBox::up-button {{subcontrol-origin:border;subcontrol-position:top right;width:18px;border-left:1px solid #3d5475;}}
            QDoubleSpinBox::down-button {{subcontrol-origin:border;subcontrol-position:bottom right;width:18px;border-left:1px solid #3d5475;}}
            QDoubleSpinBox::up-button:hover,QDoubleSpinBox::down-button:hover {{background:#304a6c;}}
            QDoubleSpinBox::up-arrow {{image:url("{assets}/chevron-up.svg");width:10px;height:10px;}}
            QDoubleSpinBox::down-arrow {{image:url("{assets}/chevron-down.svg");width:10px;height:10px;}}
        ''')
        close=QPushButton('×');close.setFixedSize(28,26)
        close.setStyleSheet('color:#cad5e8; background:transparent; border:0; padding:0; font-size:16pt;')
        close.clicked.connect(self.hide);row.addWidget(close);box.addLayout(row)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet('QScrollArea, QScrollArea > QWidget > QWidget { background:transparent; border:0; }')
        self.scroll.viewport().setStyleSheet('background:transparent;')
        content=QWidget();self.captions=QVBoxLayout(content);self.captions.setContentsMargins(0,0,4,0);self.captions.setSpacing(14)
        self.placeholder=self.make_row();self.captions.addWidget(self.placeholder);self.captions.addStretch(1)
        self.source=self.placeholder.source;self.translation=self.placeholder.translation
        self.source.setText(_tr('等待课程语音'));self.translation.setText(_tr('本地原文模式'))
        self.scroll.setWidget(content);box.addWidget(self.scroll,1)
        self.focus=FocusViewport(lambda:self.make_row(focus=True),self,
            preview_renderer=lambda record:source_html(record,self.candidate_color()))
        self.focus.hide();box.addWidget(self.focus,1)
        self.focus.settled.connect(self._focus_settled);self.focus.transitions_coalesced.connect(self.focus_coalesced.emit)
        self.focus.position_changed.connect(self._focus_position)
        self.focus.order_waiting.connect(self._focus_order_waiting)
        self.focus.browsing_changed.connect(self._focus_browsing_changed)
        self.focus.display_issue.connect(lambda code,segment:self.presentation_waiting.emit(
            {'event':'subtitle_presentation_issue','view':'focus','code':code,'segment_id':segment}))
        self.locate.toggled.connect(self._show_handle)
        self.input_changed.connect(self._show_handle)
        self.follow_timer=QTimer(self);self.follow_timer.setSingleShot(True)
        self.follow_timer.timeout.connect(lambda:self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))
        grip=QSizeGrip(self);grip.setFixedSize(18,18);box.addWidget(grip,alignment=Qt.AlignRight)
        self.apply_appearance(self.appearance)

    def apply_appearance(self,settings):
        changed_mode=self.appearance.focus_mode!=settings.focus_mode
        self.appearance=settings.validate();self.set_font(settings.font_size);self.set_opacity(settings.opacity)
        for row in [self.placeholder,*self.rows.values()]:self.style_row(row)
        if changed_mode:self.focus.clear();self._reset_list_order()
        self.scroll.setVisible(not settings.focus_mode);self.focus.setVisible(settings.focus_mode)
        self.focus.set_history_limit(settings.visible_segments)
        self.focus.set_focus_position(settings.focus_x,settings.focus_y)
        self.locate.setVisible(settings.focus_mode);self._show_handle()
        self.set_base_speed(settings.speech_speed)
        if self.records:self.present_many(self.records,self.translation_enabled)

    def _focus_position(self,x,y):
        self.appearance=replace(self.appearance,focus_x=x,focus_y=y).validate();self.focus_position_changed.emit()

    def _show_handle(self,*args):
        self.focus.handle.setVisible(self.appearance.focus_mode and self.locate.isChecked()
                                     and not self.click_through and not self.focus.browsing)

    def set_base_speed(self,speed):
        with QSignalBlocker(self.base_speed):self.base_speed.setValue(speed)
        self.appearance=replace(self.appearance,speech_speed=speed).validate()

    def make_row(self,focus=False):
        row=QWidget();layout=QVBoxLayout(row);layout.setContentsMargins(0,0,0,0);layout.setSpacing(4)
        row.source=CaptionLabel();row.source.setTextFormat(Qt.RichText);row.translation=CaptionLabel()
        for name,item in (('source',row.source),('translation',row.translation)):
            item.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
            signal=self.focus_text_painted if focus else self.text_painted
            item.painted.connect(lambda token,when,part=name,target=signal:target.emit(part,token,when));layout.addWidget(item)
        self.style_row(row);return row

    def style_row(self,row):
        for name,color in (('source',self.appearance.source_color),('translation',self.appearance.translation_color)):
            item=getattr(row,name);item.setFont(QFont(self.appearance.font_family,self.appearance.font_size))
            item.setStyleSheet(f'color:{color}; background:transparent;')

    def set_font(self,size):
        self.appearance=replace(self.appearance,font_size=size).validate()
        for row in [self.placeholder,*self.rows.values()]:self.style_row(row)
        if hasattr(self,'focus'):
            for card in self.focus.cards.values():self.style_row(card.widget)
            for row in self.focus.history_rows.values():self.style_row(row)
            self.style_row(self.focus.preview)
            self.focus.relayout()

    def candidate_color(self):
        foreground=QColor(self.appearance.source_color);background=QColor(self.appearance.background_color)
        return QColor(*(round(a*.55+b*.45) for a,b in zip(foreground.getRgb()[:3],background.getRgb()[:3]))).name()

    def set_opacity(self,value):
        self.appearance=replace(self.appearance,opacity=value).validate();self.alpha=round(value*255/100);self.update()

    def set_click_through(self,enabled):
        enabled=bool(enabled)
        if enabled==self.click_through:return
        self._drag_offset=None
        if os.name=='nt' and QApplication.platformName()=='windows':
            previous=self.click_through;self.click_through=enabled
            try:self.sync_native_input()
            except OSError:self.click_through=previous;raise
            self.input_changed.emit(enabled);return
        visible=self.isVisible();geometry=self.geometry();self._changing_flags=True
        try:
            self.setWindowFlag(Qt.WindowTransparentForInput,enabled)
            self.setWindowFlag(Qt.WindowDoesNotAcceptFocus,enabled)
            self.setAttribute(Qt.WA_TransparentForMouseEvents,enabled)
            self.click_through=enabled;self.setGeometry(geometry)
            if visible:self.show()
            self.sync_native_input()
        finally:self._changing_flags=False
        self.input_changed.emit(enabled)

    def sync_native_input(self):
        # Use the documented layered-window mouse input bit on Windows. Keeping
        # Qt's WindowTransparentForInput clear avoids a stale native QWindow flag
        # being reapplied during later repaints after the user restores editing.
        if os.name!='nt' or QApplication.platformName()!='windows' or not self.windowHandle():return
        api=ct.WinDLL('user32',use_last_error=True)
        api.GetWindowLongPtrW.argtypes=[ct.c_void_p,ct.c_int];api.GetWindowLongPtrW.restype=ct.c_ssize_t
        api.SetWindowLongPtrW.argtypes=[ct.c_void_p,ct.c_int,ct.c_ssize_t];api.SetWindowLongPtrW.restype=ct.c_ssize_t
        handle=int(self.winId());style=api.GetWindowLongPtrW(handle,-20)
        desired=style|0x20 if self.click_through else style&~0x20
        if desired!=style:
            ct.set_last_error(0);previous=api.SetWindowLongPtrW(handle,-20,desired)
            if not previous and ct.get_last_error():raise ct.WinError(ct.get_last_error())

    def showEvent(self,event):
        super().showEvent(event);self.sync_native_input()
        if self.record and not self._changing_flags:self.follow_timer.start(0)

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing)
        color=QColor(self.appearance.background_color);color.setAlpha(self.alpha)
        painter.setPen(Qt.NoPen);painter.setBrush(color);painter.drawRoundedRect(self.rect(),13,13)

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and event.position().y()<45 and not self.click_through:
            self._drag_offset=event.globalPosition().toPoint()-self.frameGeometry().topLeft();event.accept()
        else:super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self._drag_offset is not None and event.buttons()&Qt.LeftButton:
            self.move(event.globalPosition().toPoint()-self._drag_offset);event.accept()
        else:super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        self._drag_offset=None;super().mouseReleaseEvent(event)

    def resizeEvent(self,event):super().resizeEvent(event);self.geometry_changed.emit()
    def moveEvent(self,event):super().moveEvent(event);self.geometry_changed.emit()

    def hideEvent(self,event):
        self._drag_offset=None
        if not self._changing_flags:
            self.set_click_through(False);self.hidden.emit()
        super().hideEvent(event)

    def present(self,record,translation_enabled,token=None):
        self.present_many([record],translation_enabled,token)

    def clear(self,text=None):
        if text is None:text=_tr('等待课程语音')
        self._reset_list_order()
        self.focus.clear(text)
        for row in self.rows.values():self.captions.removeWidget(row);row.deleteLater()
        self.rows.clear();self.records=[];self.record=None;self.placeholder.show()
        self.source=self.placeholder.source;self.translation=self.placeholder.translation
        self.source.set_caption(text);self.translation.set_caption('');self.translation.hide();self.title.setText(_tr('ELT · 等待语音'))

    def present_many(self,records,translation_enabled,token=None):
        records=[record for record in records if record.get('source_text') or record.get('candidate_text')][-128:]
        # Keep the simple single-record rendering API used by diagnostics; real
        # backend events always provide their own session/segment identity.
        records=[record if 'segment_id' in record else {**record,'segment_id':0} for record in records]
        if not records:self.clear();return
        self.records=list(records);self.translation_enabled=translation_enabled
        if self.appearance.focus_mode:
            self.focus.set_history_limit(self.appearance.visible_segments);self.focus.present(records,translation_enabled)
            if not self.focus.cards:self.title.setText(_tr('ELT · 焦点 · 等待完成'))
            return
        records=self._ordered_list(records,translation_enabled);self.record=record=records[-1]
        bar=self.scroll.verticalScrollBar();follow=bar.value()>=bar.maximum()-8
        self.placeholder.hide()
        keys={(item.get('session_id',''),item.get('segment_id',0)) for item in records}
        for key in list(self.rows):
            if key not in keys:
                row=self.rows.pop(key);self.captions.removeWidget(row);row.deleteLater()
        dim=self.candidate_color()
        for index,item in enumerate(records):
            key=(item.get('session_id',''),item.get('segment_id',0))
            if key not in self.rows:self.rows[key]=self.make_row()
            row=self.rows[key];self.captions.insertWidget(index,row)
            current_token=token if item is record and not item.get('_translation_withheld') else None
            source=source_html(item,dim);text=item.get('translated_text','')
            if row.source.text()!=source or current_token is not None:row.source.set_caption(source,current_token)
            translation=translation_caption(item)
            row.translation.setVisible(translation_enabled or bool(text))
            if row.translation.text()!=translation or current_token is not None:row.translation.set_caption(translation,current_token)
        latest_key=(record.get('session_id',''),record.get('segment_id',0));latest=self.rows[latest_key]
        self.source=latest.source;self.translation=latest.translation
        self.title.setText(_tr('ELT · 已确认') if record.get('state')=='final' else _tr('ELT · 原文预览'))
        text=record.get('translated_text','')
        if text and record.get('translated_revision')!=record['revision']:self.title.setText(_tr('ELT · 译文对应前段原文，等待补全'))
        if self.list_signature and self.list_signature[1]>0:
            self.title.setText(f"{_tr('ELT · 按原句顺序显示 · 后续 ')}{self.list_signature[1]}{_tr(' 句已译')}")
        if follow:self.follow_timer.start(0)

    def _reset_list_order(self):
        self.list_timer.stop();self.list_session=None;self.list_frontier=-1;self.list_blocked=None
        self.list_hold=None;self.list_read_until=0.;self.list_signature=None

    def _ordered_list(self,records,enabled):
        ordered=sorted(records,key=lambda row:row['segment_id']);latest=ordered[-1]
        session=latest.get('session_id','')
        if session!=self.list_session:
            self._reset_list_order();self.list_session=session
        if not enabled:return ordered[-self.appearance.visible_segments:]
        by_id={row['segment_id']:row for row in ordered};now=time.monotonic()
        blocker=next((row for row in ordered if row['segment_id']>=self.list_frontier and translation_pending(row)),None)
        previous=by_id.get(self.list_blocked)
        if previous and previous.get('source_closed') and not translation_pending(previous):
            self.list_hold=previous['segment_id'];self.list_read_until=now+reading_hold_ms(previous)/1000
        self.list_blocked=blocker['segment_id'] if blocker else None
        if self.list_hold not in by_id:self.list_hold=None;self.list_read_until=0.
        if self.list_hold is not None and now>=self.list_read_until:
            next_ready=next((row for row in ordered if row['segment_id']>self.list_hold
                and row.get('source_closed') and not translation_pending(row)),None)
            if next_ready and (blocker is None or next_ready['segment_id']<blocker['segment_id']):
                self.list_hold=next_ready['segment_id'];self.list_read_until=now+reading_hold_ms(next_ready)/1000
            else:self.list_hold=None
        cutoff=self.list_hold if self.list_hold is not None else self.list_blocked
        if cutoff is None:cutoff=latest['segment_id']
        self.list_frontier=max(self.list_frontier,cutoff)
        visible=[row for row in ordered if row['segment_id']<=cutoff][-self.appearance.visible_segments:]
        if latest['segment_id']>cutoff:
            # Separate live source row: later Chinese is buffered, never paired
            # with the earlier source or measured as a completed Chinese paint.
            visible.append({**latest,'translated_text':'','state':'preview','translation_status':'waiting_previous',
                            '_translation_withheld':True})
        if self.list_hold is not None:
            self.list_timer.start(max(1,round((self.list_read_until-now)*1000)))
        waiting=sum(final_translation(row) for row in ordered if row['segment_id']>cutoff)
        signature=(cutoff,waiting,self.list_hold is not None)
        if signature!=self.list_signature:
            self.list_signature=signature
            self.presentation_waiting.emit({'event':'subtitle_presentation_waiting','view':'list',
                'segment_id':cutoff,'later_completed':waiting,'reading_hold':self.list_hold is not None})
        return visible

    def _focus_settled(self,record):
        if self.focus.browsing:return
        self.record=record;card=self.focus.cards[self.focus.current]
        self.source=card.widget.source;self.translation=card.widget.translation
        self._focus_title(record)
        self.focus_settled.emit(record)

    def _focus_title(self,record):
        if self.focus.browsing:self.title.setText(_tr('ELT · 历史字幕 · 点击底部按钮返回实时焦点'));return
        waiting=(self.focus.wait_signature or (None,0))[1]
        self.title.setText(f"{_tr('ELT · 等待前句翻译 · 后续 ')}{waiting}{_tr(' 句已译')}" if waiting else
                          _tr('ELT · 焦点 · 已完成') if final_translation(record) else _tr('ELT · 焦点 · 原文'))

    def _focus_order_waiting(self,segment,count):
        self.presentation_waiting.emit({'event':'subtitle_presentation_waiting','view':'focus',
                                       'segment_id':segment,'later_completed':count})
        if self.focus.current in self.focus.cards:self._focus_title(self.focus.cards[self.focus.current].record)

    def _focus_browsing_changed(self,enabled):
        self._show_handle()
        if enabled:self.title.setText(_tr('ELT · 历史字幕 · 点击底部按钮返回实时焦点'))
        elif self.focus.current in self.focus.cards:self._focus_title(self.focus.cards[self.focus.current].record)
        self.presentation_waiting.emit({'event':'subtitle_history_browsing','view':'focus','active':enabled})
