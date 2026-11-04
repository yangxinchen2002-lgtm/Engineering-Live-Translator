from app.i18n import tr as _tr
from dataclasses import replace
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor,QFont
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QFontComboBox,QPushButton,QColorDialog,
    QSpinBox,QDialogButtonBox,QLabel,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QCheckBox)
from .usage import usage_text


class AppearanceDialog(QDialog):
    def __init__(self,settings,parent):
        super().__init__(parent);self.setWindowTitle(_tr('悬浮字幕外观'));self.setMinimumWidth(480)
        self.initial=settings;self.colors={name:getattr(settings,name) for name in ('source_color','translation_color','background_color')}
        box=QVBoxLayout(self);box.setContentsMargins(26,24,26,22);box.setSpacing(20)
        title=QLabel(_tr('让字幕适合你的屏幕'));title.setObjectName('sectionTitle');box.addWidget(title)
        form=QFormLayout();form.setVerticalSpacing(12);form.setHorizontalSpacing(24);box.addLayout(form)
        self.family=QFontComboBox();self.family.setCurrentFont(QFont(settings.font_family));form.addRow(_tr('字体'),self.family)
        self.size=QSpinBox();self.size.setRange(6,72);self.size.setValue(settings.font_size);form.addRow(_tr('字号'),self.size)
        self.opacity=QSpinBox();self.opacity.setRange(35,95);self.opacity.setSuffix(' %');self.opacity.setValue(settings.opacity)
        form.addRow(_tr('背景不透明度'),self.opacity)
        geometry=settings.overlay_geometry or (0,0,settings.overlay_width,settings.overlay_height)
        self.width_value=QSpinBox();self.width_value.setRange(280,8000);self.width_value.setValue(geometry[2]);form.addRow(_tr('悬浮窗宽度'),self.width_value)
        self.height_value=QSpinBox();self.height_value.setRange(120,8000);self.height_value.setValue(geometry[3]);form.addRow(_tr('悬浮窗高度'),self.height_value)
        self.lines=QSpinBox();self.lines.setRange(1,12);self.lines.setValue(settings.visible_segments);form.addRow(_tr('最近字幕条数'),self.lines)
        self.focus=QCheckBox(_tr('在所选焦点显示，旧句向上推进'));self.focus.setChecked(settings.focus_mode);form.addRow(_tr('焦点显示'),self.focus)
        for name,title in (('source_color',_tr('原文颜色')),('translation_color',_tr('译文颜色')),('background_color',_tr('背景颜色'))):
            button=QPushButton(self.colors[name]);button.clicked.connect(lambda checked=False,n=name,b=button:self.choose(n,b))
            form.addRow(title,button)
        hint=QLabel(_tr('颜色用于悬浮字幕窗。鼠标穿透关闭后可移动、缩放和滚动长字幕。'));hint.setWordWrap(True);box.addWidget(hint)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel|QDialogButtonBox.RestoreDefaults)
        buttons.button(QDialogButtonBox.Ok).setText(_tr('应用'));buttons.button(QDialogButtonBox.Cancel).setText(_tr('取消'))
        buttons.button(QDialogButtonBox.Ok).setObjectName('primary')
        buttons.button(QDialogButtonBox.RestoreDefaults).setText(_tr('默认外观'))
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject)
        def defaults():
            from .preferences import UISettings
            self.initial=replace(settings,visible_segments=4,focus_mode=False,focus_x=.5,focus_y=.5,overlay_width=900,overlay_height=360,
                overlay_geometry=(geometry[0],geometry[1],900,360) if settings.overlay_geometry else None,
                **{k:getattr(UISettings(),k) for k in ('font_family','font_size','opacity','source_color','translation_color','background_color')})
            self.done(2)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(defaults);box.addWidget(buttons)

    def choose(self,name,button):
        color=QColorDialog.getColor(QColor(self.colors[name]),self,_tr('选择字幕颜色'))
        if color.isValid():self.colors[name]=color.name();button.setText(color.name())

    def value(self):
        if self.result()==2:return self.initial
        geometry=self.initial.overlay_geometry
        return replace(self.initial,font_family=self.family.currentFont().family(),font_size=self.size.value(),
            opacity=self.opacity.value(),visible_segments=self.lines.value(),
            focus_mode=self.focus.isChecked(),
            overlay_width=self.width_value.value(),overlay_height=self.height_value.value(),
            overlay_geometry=(geometry[0],geometry[1],self.width_value.value(),self.height_value.value()) if geometry else None,**self.colors).validate()


class PerformanceDialog(QDialog):
    NAMES={'source_first_available':'原文首次可用（识别核心）','source_stable':'稳定原文（识别核心）',
        'inference':'单次识别推理','asr_queue_wait':'识别任务等待','translation_first_available':'译文首次可用（字幕核心）',
        'translation_queue_wait':'翻译队列等待','translation_request':'翻译请求全程',
        'ui_delivery_main':'主窗口接收至文字绘制','ui_delivery_overlay':'悬浮窗接收至文字绘制',
        'translation_first_paint_main':'译文首次绘制（主窗口）','translation_first_paint_overlay':'译文首次绘制（悬浮窗）',
        'ui_delivery_focus':'接收至焦点就位绘制（含动画）','translation_first_paint_focus':'译文焦点就位绘制（含动画）'}

    def __init__(self,controller,parent):
        super().__init__(parent);self.controller=controller;self.setWindowTitle(_tr('性能统计'));self.resize(860,760)
        box=QVBoxLayout(self);box.setContentsMargins(24,22,24,22);box.setSpacing(16)
        title=QLabel(_tr('会话运行表现'));title.setObjectName('sectionTitle');box.addWidget(title)
        self.usage_info=QLabel();self.usage_info.setWordWrap(True);self.usage_info.setTextFormat(Qt.PlainText)
        self.usage_info.setTextInteractionFlags(Qt.TextSelectableByMouse);self.usage_info.setObjectName('usagePanel');box.addWidget(self.usage_info)
        note=QLabel(_tr('每项最多保留最近 512 个样本；核心文本可用、网络请求和界面绘制分别统计。未取得的数据显示“—”。'))
        note.setWordWrap(True);box.addWidget(note)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels([_tr('指标'),_tr('样本'),'P50','P95'])
        self.table.verticalHeader().hide();self.table.setAlternatingRowColors(True);self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
        box.addWidget(self.table);self.details=QLabel();self.details.setWordWrap(True);box.addWidget(self.details)
        footer=QLabel(_tr('时间单位：秒。文字绘制为 Qt 完成绘制，不等于显示器刷新；首条中文只统计版本可对齐的样本。'))
        footer.setWordWrap(True);box.addWidget(footer)
        from PySide6.QtCore import QTimer
        self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self.refresh);self.timer.start();self.refresh()

    def refresh(self):
        snapshot=self.controller.telemetry.snapshot();values=snapshot['metrics_seconds']
        self.usage_info.setText(usage_text(snapshot)[1])
        self.table.setRowCount(len(self.NAMES))
        for row,(key,title) in enumerate(self.NAMES.items()):
            data=values.get(key,{});items=[title,str(data.get('count',0))]
            items += ['—' if data.get(field) is None else f'{data[field]:.3f}' for field in ('p50','p95')]
            for column,text in enumerate(items):self.table.setItem(row,column,QTableWidgetItem(_tr(text)))
        latest=snapshot['latest'];asr=latest.get('asr_queues',{});translation=latest.get('translation_queue',{});gpu=latest.get('gpu',{})
        counts=snapshot['events']
        self.details.setText(f"{_tr('显卡总占用：')}{gpu.get('total_device_memory_mib', '—')}{_tr(' MiB\u3000利用率：')}{gpu.get('utilization_percent', '—')}{_tr('%\n识别待处理：最终 ')}{asr.get('pending_required', '—')}{_tr(' / 预览 ')}{asr.get('pending_preview', '—')}{_tr('，最长等待 ')}{asr.get('oldest_wait_seconds', '—')}{_tr(' 秒\n翻译待处理：')}{translation.get('pending', '—')}{_tr('，运行中 ')}{translation.get('active', '—')}{_tr('，最长等待 ')}{translation.get('oldest_wait_seconds', '—')}{_tr(' 秒\n跳过的预览窗口：')}{asr.get('preview_windows_skipped', '—')}{_tr('\u3000过期翻译：')}{counts.get('translation_expired', 0)}{_tr('\u3000翻译错误：')}{counts.get('translation_error', 0)}{_tr('\u3000无效计时：')}{snapshot['invalid_measurements']}")

    def closeEvent(self,event):self.timer.stop();super().closeEvent(event)
