"""Bounded live-focus cards and detached scrollable history. No backend work."""
from app.i18n import tr as _tr
from collections import OrderedDict,deque
from dataclasses import dataclass
from typing import Callable
import math
import time
from PySide6.QtCore import Qt,Signal,QTimer,QVariantAnimation,QEasingCurve,QPointF
from PySide6.QtGui import QPainter,QColor,QPen
from PySide6.QtWidgets import QWidget,QLabel,QScrollArea,QVBoxLayout,QPushButton
from .captions import final_translation,translation_failed,translation_caption,translation_pending,reading_hold_ms


def completed_for_focus(record:dict,translation_enabled:bool) -> bool:
    if not record.get('source_text','').strip() or not record.get('source_closed'):return False
    if translation_enabled:
        return final_translation(record) or translation_failed(record)
    return not record.get('candidate_text','').strip()


@dataclass
class FocusCard:
    record:dict
    widget:QWidget
    y:float=0.


class FocusHandle(QWidget):
    """A movable crosshair; global deltas remain stable while the handle moves."""
    def __init__(self,view):
        super().__init__(view);self.view=view;self.origin=None;self.setFixedSize(22,22)
        self.setCursor(Qt.SizeAllCursor);self.setAccessibleName(_tr('拖动调整字幕焦点'))
        self.setToolTip(_tr('拖动调整焦点位置；双击回到中央。可用上方「定位」隐藏标识。'))

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor('#78d9ff'),2));p.setBrush(Qt.NoBrush);p.drawEllipse(5,5,12,12)
        p.drawLine(11,0,11,5);p.drawLine(11,17,11,22);p.drawLine(0,11,5,11);p.drawLine(17,11,22,11)

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            self.origin=(event.globalPosition(),QPointF(self.view._center_x(),self.view._center_y()));event.accept()

    def mouseMoveEvent(self,event):
        if self.origin and event.buttons()&Qt.LeftButton:
            point=self.origin[1]+event.globalPosition()-self.origin[0]
            self.view.set_focus_position(point.x()/max(1,self.view.width()),point.y()/max(1,self.view.height()),notify=True)
            event.accept()

    def mouseReleaseEvent(self,event):self.origin=None;event.accept()
    def mouseDoubleClickEvent(self,event):self.view.set_focus_position(.5,.5,notify=True);event.accept()


def wheel_distance(event):
    return event.pixelDelta().y() or event.angleDelta().y()/3


class HistoryScroll(QScrollArea):
    def __init__(self,view):super().__init__(view);self.view=view

    def wheelEvent(self,event):
        if self.view.history_anchor is not None:
            # Coalesce trackpad input while a text reflow is pending, rather
            # than letting the restoration undo the user's next wheel step.
            self.view.history_wheel-=wheel_distance(event);event.accept()
        else:super().wheelEvent(event)


class FocusViewport(QWidget):
    """One shared eased displacement pushes every card; Qt clips the upper edge."""
    settled=Signal(object)
    transitions_coalesced=Signal(int)
    position_changed=Signal(float,float)
    order_waiting=Signal(int,int)
    display_issue=Signal(str,int)
    browsing_changed=Signal(bool)
    DURATION_MS=520
    QUEUE_CAPACITY=8
    GAP=24
    HISTORY_CAPACITY=128

    def __init__(self,row_factory:Callable[[],QWidget],parent=None,*,preview_renderer:Callable[[dict],str]):
        super().__init__(parent);self.row_factory=row_factory;self.preview_renderer=preview_renderer
        self.setMinimumSize(0,0);self.setStyleSheet('background:transparent;')
        self.placeholder=QLabel(_tr('等待完整的双语字幕…'),self)
        self.placeholder.setAlignment(Qt.AlignCenter);self.placeholder.setWordWrap(True)
        self.placeholder.setStyleSheet('color:#a7b6d0; background:transparent;')
        self.card_clip=QWidget(self)
        self.preview_clip=QWidget(self);self.preview=self.row_factory();self.preview.setParent(self.preview_clip)
        self.preview.source.setTextFormat(Qt.RichText);self.preview.source.setAlignment(Qt.AlignCenter)
        self.preview.source.setAccessibleName(_tr('正在识别的实时原文'));self.preview.translation.hide()
        self.preview.setToolTip(_tr('实时原文预览，浅色部分仍可能修订。'))
        self.preview_record=None;self.preview_clip.hide();self.preview.show()
        self.cards:OrderedDict[int,FocusCard]=OrderedDict();self.pending=deque()
        self.session=None;self.highest_segment=-1;self.current=None;self.target=None
        self.history_limit=4;self.starts={};self.ends={};self.scroll_offset=0.
        self.focus_x=self.focus_y=.5;self.translation_enabled=False
        self.latest_records={};self.handle=FocusHandle(self)
        self.waited_segments=set();self.read_until=0.;self.wait_signature=None;self.read_key=None
        self.ordered_recovery=False
        self.browsing=False;self.history_snapshot=OrderedDict();self.history_rows=OrderedDict()
        self.history_anchor=None;self.history_wheel=0.
        self.history_scroll=HistoryScroll(self);self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setFrameShape(QScrollArea.NoFrame)
        self.history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history_scroll.setStyleSheet('QScrollArea,QScrollArea > QWidget > QWidget {background:transparent;border:0;}'
            'QScrollBar:vertical {background:transparent;width:6px;margin:2px 0;}'
            'QScrollBar::handle:vertical {background:#52657e;min-height:24px;border-radius:3px;}'
            'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}'
            'QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:transparent;}')
        self.history_scroll.viewport().setStyleSheet('background:transparent;')
        self.history_content=QWidget();self.history_box=QVBoxLayout(self.history_content)
        self.history_box.setContentsMargins(8,12,12,60);self.history_box.setSpacing(self.GAP);self.history_box.addStretch(1)
        self.history_scroll.setWidget(self.history_content);self.history_scroll.hide()
        self.history_scroll.verticalScrollBar().sliderPressed.connect(self._cancel_history_anchor)
        self.history_layout_timer=QTimer(self);self.history_layout_timer.setSingleShot(True)
        self.history_layout_timer.timeout.connect(self._restore_history_anchor)
        self.return_button=QPushButton('⬇',self);self._size_return_button(42)
        self.return_button.setAccessibleName(_tr('返回实时焦点'));self.return_button.setToolTip(_tr('返回实时字幕和已设定的焦点位置'))
        self.return_button.setCursor(Qt.PointingHandCursor)
        self.return_button.clicked.connect(self.return_to_focus);self.return_button.hide()
        self.animation=QVariantAnimation(self);self.animation.setDuration(self.DURATION_MS)
        self.animation.setStartValue(0.);self.animation.setEndValue(1.)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.valueChanged.connect(self._advance);self.animation.finished.connect(self._finish)
        self.next_timer=QTimer(self);self.next_timer.setSingleShot(True);self.next_timer.timeout.connect(self._pump)

    def anchor(self):return QPointF(self.width()*self.focus_x,self.height()*self.focus_y)

    def set_focus_position(self,x,y,*,notify=False):
        self.focus_x=max(0.,min(1.,x));self.focus_y=max(0.,min(1.,y));self.relayout()
        if notify:self.position_changed.emit(self.focus_x,self.focus_y)

    def _center_x(self):
        half=min(120.,max(0.,(self.width()-16)/2))
        return max(half+8,min(self.width()-half-8,self.width()*self.focus_x))

    def _center_y(self):
        # Reserve a band for ongoing recognition even when the focused text is tall.
        return max(0.,min(float(self.card_clip.height()),self.height()*self.focus_y))

    def _layout_regions(self):
        reserve=min(self.height(),max(32,min(100,round(self.height()*.25)))) if self.preview_record else 0
        self.card_clip.setGeometry(0,0,self.width(),max(0,self.height()-reserve-(8 if reserve else 0)))
        self.handle.move(round(self._center_x())-11,round(self._center_y())-11);self.handle.raise_()
        diameter=max(18,min(42,self.width(),self.height()-8))
        if self.return_button.width()!=diameter:self._size_return_button(diameter)
        self.return_button.move(max(0,(self.width()-self.return_button.width())//2),max(0,self.height()-self.return_button.height()-8))
        history_height=self.height()-diameter-16 if self.height()>=100 else self.height()
        self.history_scroll.setGeometry(0,0,self.width(),max(0,history_height))
        if self.browsing:self.return_button.raise_()

    @property
    def transitioning(self):return self.target is not None

    @property
    def live_visible(self):return self.isVisible() and not self.browsing

    def clear(self,text=None,*,preserve_history=False):
        if text is None:text=_tr('等待完整的双语字幕…')
        if not preserve_history:self._clear_history()
        self.animation.stop();self.next_timer.stop();self.pending.clear();self.target=None
        for card in self.cards.values():card.widget.hide();card.widget.deleteLater()
        self.cards.clear();self.current=None;self.session=None;self.highest_segment=-1
        self.starts.clear();self.ends.clear();self.scroll_offset=0.
        self.latest_records.clear()
        self.waited_segments.clear();self.read_until=0.;self.wait_signature=None;self.read_key=None
        self.ordered_recovery=False
        self.preview_record=None;self.preview.source.set_caption('');self.preview_clip.hide()
        self.placeholder.setText(text);self.placeholder.setVisible(not self.browsing)

    def set_history_limit(self,value:int):
        self.history_limit=max(1,min(12,value));self._trim()

    def _card(self,record:dict) -> FocusCard:
        row=self.row_factory();row.setParent(self.card_clip)
        for label in (row.source,row.translation):label.setAlignment(Qt.AlignCenter)
        row.source.setTextFormat(Qt.PlainText)
        card=FocusCard(dict(record),row);self.cards[record['segment_id']]=card
        self._render_card(card);self._measure(card);row.show();return card

    def _render_card(self,card):
        row=card.widget;record=card.record
        row.source.set_caption(record['source_text'])
        text=record.get('translated_text','') if final_translation(record) else ''
        row.translation.set_caption(text or translation_caption({**record,'translated_text':''}))
        row.translation.setVisible(self.translation_enabled or bool(text))

    def _refresh_cards(self):
        for card in self.cards.values():self._render_card(card);self._measure(card)

    def _measure(self,card:FocusCard):
        self._measure_row(card.widget)

    def _measure_row(self,row):
        width=max(1,round(2*min(self._center_x(),self.width()-self._center_x())-16))
        row.setFixedWidth(width)
        height=row.layout().heightForWidth(width)
        row.resize(width,max(24,height if height>=0 else row.sizeHint().height()))
        row.layout().activate()

    def _move(self,card:FocusCard):card.widget.move(round(self._center_x()-card.widget.width()/2),round(card.y+self.scroll_offset))

    def _position(self):
        self._layout_regions()
        if self.current not in self.cards:self._layout_preview();return
        self.scroll_offset=0.;current=self.cards[self.current]
        current.y=self._center_y()-current.widget.height()/2;self._move(current)
        previous_y=current.y
        for key,card in reversed(self.cards.items()):
            if key==self.current:continue
            card.y=previous_y-self.GAP-card.widget.height();self._move(card);previous_y=card.y
        self._layout_preview()

    def _set_preview(self,record):
        self.preview_record=dict(record) if record else None
        self._layout_regions()
        if not record:self.preview.source.set_caption('');self.preview_clip.hide();return
        text=self.preview_renderer(record)
        if self.preview.source.text()!=text:self.preview.source.set_caption(text)
        self._measure_row(self.preview);self._layout_preview()

    def _layout_preview(self):
        if self.browsing:self.preview_clip.hide();self.return_button.raise_();return
        if self.preview_record is None:self.preview_clip.hide();return
        bottom=max((card.widget.y()+card.widget.height() for card in self.cards.values()),default=self.height()//2)
        top=max(0,min(bottom+self.GAP,self.card_clip.height()+8));available=max(0,self.height()-top)
        height=min(self.preview.height(),available)
        self.preview_clip.setGeometry(round(self._center_x()-self.preview.width()/2),top,self.preview.width(),height)
        # Keep the newest words visible without truncating the stored text or
        # allowing a tall preview to overlap the centered completed sentence.
        self.preview.move(0,min(0,height-self.preview.height()))
        self.preview_clip.setVisible(height>0);self.preview_clip.raise_();self.handle.raise_()

    def _trim(self):
        limit=self.history_limit+(1 if self.transitioning else 0)
        while len(self.cards)>limit:
            key=next(iter(self.cards))
            if key in (self.current,self.target):break
            card=self.cards.pop(key);card.widget.hide();card.widget.deleteLater()

    def present(self,records:list[dict],translation_enabled:bool):
        if not records:return
        session=records[-1].get('session_id','')
        if session!=self.session:
            self.clear();self.session=session
        translation_changed=self.translation_enabled!=translation_enabled
        self.translation_enabled=translation_enabled
        self.latest_records={row['segment_id']:dict(row) for row in records[-128:] if row.get('session_id','')==session}
        if self.browsing:
            self._update_history()
            if translation_changed:self._capture_history_anchor();self._render_history();self._queue_history_layout()
        self.waited_segments.intersection_update(self.latest_records)
        ordered=sorted(self.latest_records.values(),key=lambda row:row['segment_id'])
        floor=self.current if self.current is not None else -1
        blocker=next((row for row in ordered if row['segment_id']>=floor and translation_enabled and translation_pending(row)),None)
        blocked_id=blocker['segment_id'] if blocker else None
        waiting=sum(final_translation(row) for row in ordered if blocked_id is not None and row['segment_id']>blocked_id)
        signature=(blocked_id,waiting)
        if signature!=self.wait_signature:
            self.wait_signature=signature;self.order_waiting.emit(blocked_id if blocked_id is not None else -1,waiting)
        if blocker and ordered[-1]['segment_id']>blocked_id:
            self.waited_segments.add(blocked_id);self.ordered_recovery=True
        changed=translation_changed and bool(self.cards)
        for key,card in self.cards.items():
            if key in self.latest_records and card.record!=self.latest_records[key]:
                card.record=self.latest_records[key];changed=True
            elif key not in self.latest_records and translation_pending(card.record):
                card.record={**card.record,'translation_status':'translation_history_expired','translation_retry_pending':False}
                changed=True;self.display_issue.emit('translation_history_expired',key)
        latest=max((row for row in records if row.get('session_id','')==session),key=lambda row:row['segment_id'])
        live=latest if latest['segment_id'] not in self.cards and (not completed_for_focus(latest,translation_enabled)
            or (blocked_id is not None and latest['segment_id']>blocked_id)
            or (self.ordered_recovery and self.current is not None and latest['segment_id']>self.current)) and (
            latest.get('source_text','').strip() or latest.get('candidate_text','').strip()) else None
        self._set_preview(live)
        if changed and not self.transitioning:
            self._refresh_cards();self._position();self._hold_late_translation()
            if self.live_visible:self.settled.emit(dict(self.cards[self.current].record))
        completed=sorted((dict(row) for row in records if row.get('session_id','')==session
                          and (blocked_id is None or row['segment_id']<=blocked_id)
                          and (completed_for_focus(row,translation_enabled) or
                               (row['segment_id']<latest['segment_id'] and row.get('source_closed') and row.get('source_text','').strip()))),
                         key=lambda row:row['segment_id'])
        if not completed:
            if not self.cards:self.placeholder.setText(_tr('等待完整的双语字幕…') if translation_enabled else _tr('等待原文片段结束…'))
            return
        if not self.cards:
            self._seed(completed);return
        if not self.live_visible:
            if self.current is None or completed[-1]['segment_id']>self.current:self._seed(completed)
            return
        for record in completed:
            if record['segment_id']<=self.highest_segment:continue
            if len(self.pending)>=self.QUEUE_CAPACITY:
                # During out-of-order recovery, refill this bounded FIFO in
                # batches instead of coalescing away a late translated sentence.
                if self.ordered_recovery:break
                self.pending.popleft();self.transitions_coalesced.emit(1)
            self.highest_segment=record['segment_id']
            self.pending.append(record)
        if not self.transitioning and not self.next_timer.isActive():self._start_next()

    def _seed(self,completed):
        session=self.session;preview=self.preview_record;latest=dict(self.latest_records);waited=self.waited_segments.copy();signature=self.wait_signature;recovery=self.ordered_recovery
        self.clear(preserve_history=True);self.session=session;self.latest_records=latest;self.waited_segments=waited;self.wait_signature=signature
        self.ordered_recovery=recovery
        for record in completed[-self.history_limit:]:self._card(record)
        self.current=self.highest_segment=completed[-1]['segment_id'];self.placeholder.hide()
        self._set_preview(preview)
        self._position()
        self._hold_late_translation()
        if self.live_visible:self.settled.emit(dict(self.cards[self.current].record))

    def _pump(self):
        if not self.pending and self.ordered_recovery and self.latest_records:
            self.present(list(self.latest_records.values()),self.translation_enabled)
        else:self._start_next()

    def _start_next(self):
        if self.transitioning or not self.pending:return
        if not self.live_visible:self._collapse();return
        if self.translation_enabled and translation_pending(self.cards[self.current].record):return
        remaining=self.read_until-time.monotonic()
        if remaining>0:self.next_timer.start(math.ceil(remaining*1000));return
        if self.scroll_offset:
            for card in self.cards.values():card.y+=self.scroll_offset
            self.scroll_offset=0.
        record=self.pending.popleft();record=self.latest_records.get(record['segment_id'],record);previous=self.cards[self.current]
        incoming=self._card(record);self.target=record['segment_id']
        if self.preview_record and self.preview_record['segment_id']==self.target:self._set_preview(None)
        incoming.y=previous.y+previous.widget.height()+self.GAP
        distance=incoming.y-(self._center_y()-incoming.widget.height()/2)
        self.starts={key:card.y for key,card in self.cards.items()}
        self.ends={key:card.y-distance for key,card in self.cards.items()}
        for card in self.cards.values():self._move(card)
        self._layout_preview()
        self.animation.start()

    def _hold_late_translation(self):
        if (self.current in self.waited_segments or self.ordered_recovery) and self.current in self.cards:
            record=self.cards[self.current].record
            key=(self.current,record.get('revision'),record.get('translation_status'),record.get('translated_text'))
            if record.get('source_closed') and not translation_pending(record) and self.read_key!=key:
                self.waited_segments.discard(self.current)
                self.read_key=key
                self.read_until=time.monotonic()+reading_hold_ms(record)/1000

    def _advance(self,progress):
        if not self.transitioning:return
        for key,card in self.cards.items():
            if key in self.starts:card.y=self.starts[key]+(self.ends[key]-self.starts[key])*float(progress);self._move(card)
        self._layout_preview()

    def _finish(self):
        if not self.transitioning:return
        self._advance(1.);self.current=self.target;self.target=None;self.starts.clear();self.ends.clear();self._trim()
        self._refresh_cards();self._position()
        self._hold_late_translation()
        if self.live_visible:self.settled.emit(dict(self.cards[self.current].record))
        more=self.ordered_recovery and any(key>self.highest_segment for key in self.latest_records)
        if self.pending or more:self.next_timer.start(0)
        elif not translation_pending(self.cards[self.current].record):self.ordered_recovery=False

    def relayout(self):
        if self.browsing:self._capture_history_anchor();self._queue_history_layout()
        if self.transitioning:
            self.animation.stop();self.current=self.target;self.target=None;self.starts.clear();self.ends.clear()
        self._refresh_cards()
        self._measure_row(self.preview)
        self._trim();self._position()
        self._hold_late_translation()
        if self.current in self.cards and self.live_visible:self.settled.emit(dict(self.cards[self.current].record))
        if self.pending and self.live_visible:self.next_timer.start(0)

    def _collapse(self):
        records=[card.record for card in self.cards.values()]+list(self.pending)
        if records:self._seed(sorted(records,key=lambda row:row['segment_id']))
        else:self.animation.stop();self.next_timer.stop()

    def mark_paint(self,token):
        if self.browsing or self.current not in self.cards:return
        row=self.cards[self.current].widget;record=self.cards[self.current].record
        row.source.set_caption(record['source_text'],token)
        if final_translation(record):row.translation.set_caption(record['translated_text'],token)

    def resizeEvent(self,event):
        super().resizeEvent(event);self.placeholder.setGeometry(self.rect());self.relayout()

    def showEvent(self,event):super().showEvent(event);self.relayout()

    def hideEvent(self,event):
        super().hideEvent(event);self._collapse()

    def wheelEvent(self,event):
        distance=wheel_distance(event)
        if not distance or not self.latest_records:return super().wheelEvent(event)
        if not self.browsing:self._begin_history()
        if self.history_anchor is not None:self.history_wheel-=distance
        else:
            bar=self.history_scroll.verticalScrollBar();bar.setValue(round(bar.value()-distance))
        event.accept()

    def _begin_history(self):
        self.browsing=True
        if self.transitioning:self.animation.stop();self._finish()
        self.next_timer.stop()
        self.history_snapshot=OrderedDict((key,dict(row)) for key,row in sorted(self.latest_records.items())[-self.HISTORY_CAPACITY:])
        self.card_clip.hide();self.preview_clip.hide();self.placeholder.hide();self.handle.hide()
        for card in self.cards.values():
            card.widget.source.pending_token=None;card.widget.translation.pending_token=None
        self._layout_regions();self.history_scroll.show()
        self._render_history()
        key=self.current if self.current in self.history_snapshot else next(reversed(self.history_snapshot))
        live_y=self.cards[key].widget.y() if key in self.cards else self._center_y()
        self.history_anchor=(key,-live_y);self.history_wheel=0.
        self._queue_history_layout();self.return_button.show();self.return_button.raise_()
        self.browsing_changed.emit(True)

    def _render_history(self):
        for index,(key,record) in enumerate(self.history_snapshot.items()):
            if key not in self.history_rows:
                row=self.row_factory();self.history_rows[key]=row
                for label in (row.source,row.translation):label.setAlignment(Qt.AlignCenter)
                row.source.setTextFormat(Qt.RichText);row.source.setAccessibleName(f"{_tr('历史原文 ')}{key}")
                self.history_box.insertWidget(index,row)
            row=self.history_rows[key];source=self.preview_renderer(record);translation=translation_caption(record)
            if (record.get('translated_text') and not translation_failed(record)
                    and record.get('translated_revision')!=record.get('revision')):
                translation+=_tr('\n（译文对应前段原文，等待补全）')
            if row.source.text()!=source:row.source.set_caption(source)
            if row.translation.text()!=translation:row.translation.set_caption(translation)
            row.translation.setVisible(self.translation_enabled or bool(record.get('translated_text')))

    def _update_history(self):
        changed=False
        for key,record in self.history_snapshot.items():
            latest=self.latest_records.get(key)
            if latest is not None and latest!=record:
                if not changed:self._capture_history_anchor()
                self.history_snapshot[key]=dict(latest);changed=True
            elif latest is None and translation_pending(record):
                if not changed:self._capture_history_anchor()
                self.history_snapshot[key]={**record,'translation_status':'translation_history_expired','translation_retry_pending':False}
                changed=True
        if changed:self._render_history();self._queue_history_layout()

    def _capture_history_anchor(self):
        if self.history_anchor is not None:return
        position=self.history_scroll.verticalScrollBar().value()
        for key,row in self.history_rows.items():
            if row.y()+row.height()>position:
                self.history_anchor=(key,position-row.y());return

    def _cancel_history_anchor(self):
        self.history_anchor=None;self.history_wheel=0.;self.history_layout_timer.stop()

    def _queue_history_layout(self):self.history_layout_timer.start(0)

    def _restore_history_anchor(self):
        if not self.browsing:return
        bottom=max(60,round(self.height()-self._center_y()))
        self.history_box.setContentsMargins(8,12,12,bottom)
        # A vertical scrollbar can change the available wrapping width. Measure
        # again after it appears before restoring the same sentence and offset.
        for _ in range(2):
            width=max(1,self.history_scroll.viewport().width())
            height=self.history_box.heightForWidth(width)
            self.history_content.setMinimumHeight(max(1,height));self.history_box.activate()
        if self.history_anchor is not None:
            key,offset=self.history_anchor;row=self.history_rows.get(key)
            if row is not None:self.history_scroll.verticalScrollBar().setValue(round(row.y()+offset+self.history_wheel))
        self.history_anchor=None;self.history_wheel=0.;self.return_button.raise_()

    def _clear_history(self):
        self.history_layout_timer.stop();self.history_scroll.hide();self.return_button.hide()
        for row in self.history_rows.values():self.history_box.removeWidget(row);row.hide();row.deleteLater()
        self.history_rows.clear();self.history_snapshot.clear();self.history_anchor=None;self.history_wheel=0.
        self.history_content.setMinimumHeight(0)
        was_browsing=self.browsing;self.browsing=False;self.card_clip.show()
        if was_browsing:self.browsing_changed.emit(False)

    def _size_return_button(self,size):
        self.return_button.setFixedSize(size,size)
        self.return_button.setStyleSheet(f'QPushButton {{color:#eaf8ff;background:#234967;border:1px solid #75c9eb;'
            f'border-radius:{size//2}px;font-family:"Segoe UI Symbol";font-size:{max(9,round(size*18/42))}pt;padding:0;}}'
            'QPushButton:hover {background:#32658a;} QPushButton:pressed {background:#19384f;}')

    def return_to_focus(self):
        if not self.browsing:return
        # Catch up without replaying animations from the time spent reading.
        # The normal earlier-sentence/translation checks still determine focus.
        if self.latest_records:self.present(list(self.latest_records.values()),self.translation_enabled)
        self._clear_history();self.placeholder.setVisible(not self.cards);self.relayout()
