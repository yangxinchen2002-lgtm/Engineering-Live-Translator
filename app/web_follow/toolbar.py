"""Native course controls, styled to match the existing ELT desktop window."""
from app.i18n import tr as _tr
from urllib.parse import urlsplit


def create_toolbar(player,form,core):
    from System import Decimal
    from System.Globalization import CultureInfo
    from System.Drawing import Color,Font,FontStyle,Size,Region
    from System.Drawing.Drawing2D import GraphicsPath,SmoothingMode
    from System.Drawing import Pen
    from System.Windows.Forms import (Panel,TableLayoutPanel,ColumnStyle,RowStyle,SizeType,DockStyle,
        AnchorStyles,Padding,Label,TextBox,Button,CheckBox,ComboBox,ComboBoxStyle,NumericUpDown,
        TrackBar,TickStyle,FlatStyle,BorderStyle,ToolTip,Cursors,AutoSizeMode)

    scale=float(form.DeviceDpi)/96
    px=lambda value:max(1,round(value*scale))
    color=lambda hex:Color.FromArgb(int(hex[1:3],16),int(hex[3:5],16),int(hex[5:7],16))
    background=color('#F4F6FA');white=Color.White;text=color('#24364F');muted=color('#77849A')
    accent=color('#3B61E9');line=color('#DFE5EF');input_bg=color('#F7F9FD')
    font=Font('Microsoft YaHei UI',9.5);small=Font('Microsoft YaHei UI',8.5)
    tips=ToolTip();player.tooltips=tips

    def grid(columns):
        table=TableLayoutPanel();table.ColumnCount=len(columns);table.RowCount=1
        table.Dock=DockStyle.Fill;table.Margin=Padding(0);table.Padding=Padding(0)
        table.BackColor=Color.Transparent
        for width in columns:
            table.ColumnStyles.Add(ColumnStyle(SizeType.AutoSize) if width is None else
                ColumnStyle(SizeType.Percent,-width) if width<0 else ColumnStyle(SizeType.Absolute,px(width)))
        table.RowStyles.Add(RowStyle(SizeType.Percent,100))
        return table

    def path_for(control):
        path=GraphicsPath();diameter=px(14);w=max(diameter+1,control.Width-1);h=max(diameter+1,control.Height-1)
        path.AddArc(0,0,diameter,diameter,180,90);path.AddArc(w-diameter,0,diameter,diameter,270,90)
        path.AddArc(w-diameter,h-diameter,diameter,diameter,0,90);path.AddArc(0,h-diameter,diameter,diameter,90,90)
        path.CloseFigure();return path

    def rounded(control,border=line):
        def resize(sender,event):
            if control.Width<px(16) or control.Height<px(16):return
            shape=path_for(control)
            try:
                previous=control.Region;control.Region=Region(shape)
                if previous:previous.Dispose()
            finally:shape.Dispose()
        def paint(sender,event):
            if control.Width<px(16) or control.Height<px(16):return
            shape=path_for(control);pen=Pen(border,1)
            try:
                event.Graphics.SmoothingMode=SmoothingMode.AntiAlias;event.Graphics.DrawPath(pen,shape)
            finally:pen.Dispose();shape.Dispose()
        control.SizeChanged+=resize;control.Paint+=paint
        return control

    def label(value,quiet=False):
        item=Label();item.Text=_tr(value);item.AutoSize=True;item.Font=small if quiet else font
        item.ForeColor=muted if quiet else text;item.BackColor=Color.Transparent
        item.Anchor=AnchorStyles.Left;item.Margin=Padding(0,0,px(6),0)
        return item

    def button(value,action,primary=False,stop=False,quiet=False):
        item=Button();item.Text=_tr(value);item.Font=font
        item.FlatStyle=FlatStyle.Flat;item.FlatAppearance.BorderSize=0
        item.AutoSize=True;item.AutoSizeMode=AutoSizeMode.GrowAndShrink
        item.MinimumSize=Size(px(74),px(30));item.Padding=Padding(px(7),0,px(7),0)
        item.BackColor=accent if primary else color('#FFF4F5') if stop else white
        item.ForeColor=white if primary else color('#A34E60') if stop else text
        item.FlatAppearance.MouseOverBackColor=color('#2E52D2') if primary else color('#EAF0FF')
        item.FlatAppearance.MouseDownBackColor=color('#2547BD') if primary else color('#DFE8FB')
        item.Cursor=Cursors.Hand;item.Dock=DockStyle.Fill;item.Margin=Padding(px(6),px(2),0,px(2))
        item.Click+=lambda s,e:action();rounded(item,accent if primary else color('#F0DFE4') if stop else white if quiet else line)
        return item

    def field(control):
        shell=rounded(Panel());shell.BackColor=input_bg;shell.Dock=DockStyle.Fill;shell.Margin=Padding(0)
        shell.Padding=Padding(px(6),0,px(4),0)
        cell=grid([-100]);cell.BackColor=input_bg;shell.Controls.Add(cell)
        control.Font=font;control.ForeColor=text;control.BackColor=input_bg
        control.Anchor=AnchorStyles.Left|AnchorStyles.Right;control.Margin=Padding(0)
        cell.Controls.Add(control,0,0)
        return shell

    def card(header):
        shell=rounded(Panel());shell.BackColor=white;shell.Dock=DockStyle.Fill
        shell.Padding=Padding(px(12),px(8),px(12),px(10));shell.Margin=Padding(0,px(4),px(8),0)
        content=TableLayoutPanel();content.Dock=DockStyle.Fill;content.ColumnCount=1;content.RowCount=2
        content.Margin=Padding(0);content.ColumnStyles.Add(ColumnStyle(SizeType.Percent,100))
        content.RowStyles.Add(RowStyle(SizeType.Absolute,px(25)));content.RowStyles.Add(RowStyle(SizeType.Percent,100))
        content.Controls.Add(header,0,0);shell.Controls.Add(content)
        return shell,content

    def toggle(value):
        item=CheckBox();item.Text=_tr(value);item.AutoSize=True;item.FlatStyle=FlatStyle.Flat
        item.Font=font;item.ForeColor=accent;item.BackColor=white;item.Margin=Padding(0);item.Anchor=AnchorStyles.Left
        return item

    toolbar=Panel();toolbar.Name='eltCourseToolbar';toolbar.Dock=DockStyle.Top;toolbar.BackColor=background
    toolbar.Font=font;toolbar.Padding=Padding(px(14),px(9),px(14),px(10))
    outer=TableLayoutPanel();outer.Dock=DockStyle.Fill;outer.ColumnCount=1;outer.RowCount=3;outer.Margin=Padding(0)
    outer.ColumnStyles.Add(ColumnStyle(SizeType.Percent,100))
    outer.RowStyles.Add(RowStyle(SizeType.Absolute,px(41)));outer.RowStyles.Add(RowStyle(SizeType.Percent,100))
    outer.RowStyles.Add(RowStyle(SizeType.Absolute,px(40)))
    toolbar.Controls.Add(outer)

    nav=grid([None,-100,None,None,None,None,None]);nav.Margin=Padding(0,0,0,px(4));outer.Controls.Add(nav,0,0)
    nav.RowCount=2;nav.RowStyles[0].SizeType=SizeType.Absolute;nav.RowStyles[0].Height=px(37)
    nav.RowStyles.Add(RowStyle(SizeType.Absolute,0))
    brand=label('ELT');brand.Font=Font('Segoe UI',15,FontStyle.Bold);brand.ForeColor=accent;nav.Controls.Add(brand,0,0)
    location=rounded(Panel());location.BackColor=white;location.Dock=DockStyle.Fill
    location.Margin=Padding(0,px(2),0,px(2));location.Padding=Padding(px(3),px(2),px(4),px(2))
    address_row=grid([None,None,-100,None]);location.Controls.Add(address_row);nav.Controls.Add(location,1,0)
    back=button(_tr('返回'),lambda:core.GoBack() if core.CanGoBack else None,quiet=True)
    refresh=button(_tr('刷新'),lambda:core.Reload(),quiet=True)
    for control,hint,col in ((back,_tr('返回上一页'),0),(refresh,_tr('刷新课程页面'),1)):
        control.Margin=Padding(0);control.MinimumSize=Size(px(42),px(28));control.Padding=Padding(px(3),0,px(3),0)
        control.BackColor=white;control.ForeColor=muted;tips.SetToolTip(control,hint);address_row.Controls.Add(control,col,0)
    address=TextBox();address.BorderStyle=getattr(BorderStyle,'None');address.Font=font;address.ForeColor=text
    address.Anchor=AnchorStyles.Left|AnchorStyles.Right;address.Margin=Padding(px(7),0,px(6),0)
    address.AccessibleName=_tr('课程网址');address.Text='https://live.rbg.tum.de/w/950944516/77734';address_row.Controls.Add(address,2,0)
    def navigate():
        value=address.Text.strip();url=urlsplit(value)
        if url.scheme!='https' or not url.hostname or url.username or url.password:player.notice(_tr('请输入 HTTPS 课程网页地址'));return
        core.Navigate(value)
    def address_key(sender,event):
        from System.Windows.Forms import Keys
        if event.KeyCode==Keys.Enter:event.SuppressKeyPress=True;navigate()
    address.KeyDown+=address_key
    open_button=button(_tr('打开课程'),navigate);open_button.Margin=Padding(px(3),0,0,0);open_button.BackColor=color('#EEF2FD')
    address_row.Controls.Add(open_button,3,0)
    def platform(url):address.Text=url;navigate()
    tum=button('TUM-Live',lambda:platform('https://live.rbg.tum.de/w/950944516/77734'))
    moodle=button('Moodle',lambda:platform('https://www.moodle.tum.de/mod/lti/view.php?id=4002807'))
    local=button(_tr('本地视频'),player.open_local_file)
    start=button(_tr('开始字幕'),lambda:player.enqueue('FOLLOW'),primary=True)
    stop=button(_tr('停止字幕'),lambda:player.enqueue('STOP'),stop=True)
    for col,control in enumerate((tum,moodle,local,start,stop),2):nav.Controls.Add(control,col,0)

    settings=TableLayoutPanel();settings.Dock=DockStyle.Fill;settings.ColumnCount=12;settings.RowCount=2;settings.Margin=Padding(0)
    for _ in range(12):settings.ColumnStyles.Add(ColumnStyle(SizeType.Percent,100/12))
    settings.RowStyles.Add(RowStyle(SizeType.Absolute,px(88)));settings.RowStyles.Add(RowStyle(SizeType.Absolute,0))
    outer.Controls.Add(settings,0,1)

    check=toggle(_tr('中文朗读'));check.CheckedChanged+=lambda s,e:player.change_playback('narrate',bool(check.Checked))
    voices,voice_content=card(check);voice_row=grid([None,-35,None,-65]);voice_content.Controls.Add(voice_row,0,1)
    voice_row.Controls.Add(label(_tr('模型'),True),0,0)
    model=ComboBox();model.DropDownStyle=ComboBoxStyle.DropDownList;model.FlatStyle=FlatStyle.Flat;model.DropDownWidth=px(230)
    model.AccessibleName=_tr('朗读模型')
    for _,_,name in player.reading_models:model.Items.Add(_tr(name))
    voice_row.Controls.Add(field(model),1,0)
    voice_label=label(_tr('音色'),True);voice_label.Margin=Padding(px(8),0,px(6),0);voice_row.Controls.Add(voice_label,2,0)
    voice=ComboBox();voice.DropDownStyle=ComboBoxStyle.DropDownList;voice.FlatStyle=FlatStyle.Flat;voice.DropDownWidth=px(290)
    voice.AccessibleName=_tr('中文朗读音色');voice_row.Controls.Add(field(voice),3,0)
    def model_changed(s,e):
        if player.setting_controls or model.SelectedIndex<0:return
        engine,size,_=player.reading_models[model.SelectedIndex]
        player.change_playback('speech_engine',engine)
        if size:player.change_playback('tts_model',size)
        voice.Enabled=False
    def voice_changed(s,e):
        if player.setting_controls or not 0<=voice.SelectedIndex<len(player.voice_values):return
        player.change_playback('voice' if player.reading_models[model.SelectedIndex][0]=='system' else 'tts_voice',player.voice_values[voice.SelectedIndex][0])
    model.SelectedIndexChanged+=model_changed;voice.SelectedIndexChanged+=voice_changed

    play_header=grid([104,-100]);play_header.Controls.Add(label(_tr('基础语速')),0,0);play_header.Controls.Add(label(_tr('中文音量')),1,0)
    playback,play_content=card(play_header);play_row=grid([84,None,-100,None]);play_content.Controls.Add(play_row,0,1)
    speed=NumericUpDown();speed.Minimum=Decimal(1);speed.Maximum=Decimal(2);speed.DecimalPlaces=2
    speed.BorderStyle=getattr(BorderStyle,'None');speed.Increment=Decimal.Parse('0.05',CultureInfo.InvariantCulture);speed.AccessibleName=_tr('朗读基础语速')
    speed.ValueChanged+=lambda s,e:player.change_playback('base_speed',float(speed.Value.ToString(CultureInfo.InvariantCulture)))
    play_row.Controls.Add(field(speed),0,0);play_row.Controls.Add(label('×',True),1,0)
    volume=TrackBar();volume.Minimum=0;volume.Maximum=100;volume.TickStyle=getattr(TickStyle,'None');volume.AutoSize=False
    volume.Height=px(26);volume.Dock=DockStyle.Fill;volume.BackColor=white;volume.Margin=Padding(0,px(3),0,0);volume.AccessibleName=_tr('中文朗读音量')
    amount=label('80%',True);amount.Anchor=AnchorStyles.Right
    def volume_changed(s,e):amount.Text=str(volume.Value)+'%';player.change_playback('volume',int(volume.Value))
    volume.ValueChanged+=volume_changed;play_row.Controls.Add(volume,2,0);play_row.Controls.Add(amount,3,0)

    duck=toggle(_tr('朗读时降低原声'));duck.CheckedChanged+=lambda s,e:player.change_playback('duck_source',bool(duck.Checked))
    source,source_content=card(duck);source.Margin=Padding(0,px(4),0,0)
    source_row=grid([None,76,None,-100]);source_content.Controls.Add(source_row,0,1);source_row.Controls.Add(label(_tr('保留'),True),0,0)
    source_percent=NumericUpDown();source_percent.Minimum=Decimal(10);source_percent.Maximum=Decimal(100);source_percent.BorderStyle=getattr(BorderStyle,'None')
    source_percent.AccessibleName=_tr('朗读时原声保留比例')
    source_percent.ValueChanged+=lambda s,e:player.change_playback('source_percent',int(source_percent.Value.ToString(CultureInfo.InvariantCulture)))
    source_row.Controls.Add(field(source_percent),1,0);source_row.Controls.Add(label('%',True),2,0)
    restore_hint=label(_tr('读完恢复'),True);restore_hint.Anchor=AnchorStyles.Right;source_row.Controls.Add(restore_hint,3,0)
    tip=_tr('按原音量的比例保留，例如原音量 50%、保留 20%，朗读时原声为 10%；读完恢复。')
    tips.SetToolTip(duck,tip);tips.SetToolTip(source_percent,tip)
    tips.SetToolTip(speed,_tr('基础语速；原句时间不足时自动加快，能读完时保持基础速度。'))
    tips.SetToolTip(voice,_tr('选择中文音色；下拉列表会显示完整名称。'))
    caption_row=grid([None,None,75,None,None,75,None,None,65,None,-100]);caption_row.Margin=Padding(0,px(5),0,0)
    caption_row.Controls.Add(label(_tr('字幕'),True),0,0);player.caption_controls={}
    for key,title,low,high,default,unit,col in (
        ('caption_width',_tr('宽度'),30,100,92,'%',1),('caption_height',_tr('高度上限'),64,600,180,'px',4),('caption_font_size',_tr('字号'),8,48,18,'px',7)):
        caption_row.Controls.Add(label(title,True),col,0)
        number=NumericUpDown();number.Minimum=Decimal(low);number.Maximum=Decimal(high);number.Value=Decimal(default)
        number.BorderStyle=getattr(BorderStyle,'None');number.AccessibleName=_tr('字幕')+title
        number.ValueChanged+=lambda s,e,k=key,n=number:player.change_playback(k,int(n.Value.ToString(CultureInfo.InvariantCulture)))
        player.caption_controls[key]=number;caption_row.Controls.Add(field(number),col+1,0);caption_row.Controls.Add(label(unit,True),col+2,0)
    caption_row.Controls.Add(label(_tr('短句自动收紧'),True),10,0);outer.Controls.Add(caption_row,0,2)
    for control in (voices,playback,source):settings.Controls.Add(control)
    layout_mode=[None]
    def arrange(sender=None,event=None):
        narrow=toolbar.ClientSize.Width<px(1180)
        if narrow==layout_mode[0]:return
        layout_mode[0]=narrow;settings.SuspendLayout();nav.SuspendLayout();toolbar.SuspendLayout()
        try:
            rows=((voices,0,0,12),(playback,0,1,6),(source,6,1,6)) if narrow else ((voices,0,0,6),(playback,6,0,3),(source,9,0,3))
            for control,col,row,span in rows:
                settings.SetColumnSpan(control,1);settings.SetColumn(control,col);settings.SetRow(control,row);settings.SetColumnSpan(control,span)
            nav.SetColumnSpan(location,6 if narrow else 1)
            for control in (tum,moodle,local,start,stop):nav.SetRow(control,1 if narrow else 0)
            nav.RowStyles[1].Height=px(37) if narrow else 0
            outer.RowStyles[0].Height=px(78) if narrow else px(41)
            settings.RowStyles[1].Height=px(88) if narrow else 0
            toolbar.Height=px(188+125*int(narrow))
        finally:settings.ResumeLayout(True);nav.ResumeLayout(True);toolbar.ResumeLayout(True)
    toolbar.SizeChanged+=arrange;arrange()
    player.reading_controls=(check,speed,volume,amount,model,voice,duck,source_percent)
    player.toolbar=toolbar;player.toolbar_groups=(voices,playback,source)
    form.Controls.Add(toolbar);toolbar.BringToFront();arrange();player.update_reading_controls()
    return address
