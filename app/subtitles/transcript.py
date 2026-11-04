"""Opt-in session TXT transcript, independent of the bounded display history."""
from __future__ import annotations
from app.i18n import tr as _tr
import asyncio
from dataclasses import asdict
from datetime import datetime
from itertools import combinations
import os
from pathlib import Path
import sqlite3
import uuid
from app.asr.clock import now_ns
from app.languages import LANGUAGE_LABELS, SOURCE_LANGUAGES

TRANSCRIPT_LANGUAGES = {'未识别语言', *(
    '+'.join(LANGUAGE_LABELS[code] for code in codes)
    for count in range(1, len(SOURCE_LANGUAGES) + 1)
    for codes in combinations(SOURCE_LANGUAGES, count))}


def language_label(hint:str,languages) -> str:
    if hint in LANGUAGE_LABELS:return LANGUAGE_LABELS[hint]
    values=set(languages)
    if not values or not values.issubset(SOURCE_LANGUAGES):return '未识别语言'
    return '+'.join(LANGUAGE_LABELS[code] for code in SOURCE_LANGUAGES if code in values)


def transcript_filename(started:datetime,language:str,minutes:int,index:int=1) -> str:
    if language not in TRANSCRIPT_LANGUAGES or type(minutes) is not int or minutes<0:
        raise ValueError('invalid transcript filename metadata')
    suffix='' if index==1 else f' ({index})'
    return f'{started:%Y-%m-%d}-{language}-{minutes}分钟{suffix}.txt'


def reserve_filename(directory:Path,started:datetime,language:str,minutes:int):
    for index in range(1,10001):
        path=directory/transcript_filename(started,language,minutes,index)
        try:
            with path.open('x',encoding='utf-8'):pass
            return path
        except FileExistsError:continue
    raise FileExistsError('too many transcripts with the same name')


class TranscriptWriter:
    def __init__(self,directory:Path|None,session_id:str,language:str,emit,*,capacity=64,clock=now_ns,started=None,target_language='zh'):
        if target_language not in ('zh','en'):raise ValueError('invalid transcript target language')
        self.translation_label=_tr('中文') if target_language=='zh' else _tr('英文')
        if not 1<=capacity<=256:raise ValueError('invalid transcript queue capacity')
        self.directory=Path(directory) if directory is not None else None
        self.session_id,self.language,self.emit,self.clock=session_id,language,emit,clock
        self.started=started or datetime.now().astimezone();self.audio_start=None;self.audio_end=None
        self.queue=asyncio.Queue(maxsize=capacity);self.task=None;self.failed=self.storage_failed=False
        self.connection=None;self.file=None;self.progress_path=self.database_path=self.ready_path=None
        self.result=None;self.dropped=0;self.errors=set()
        self.pause_count=0;self.pause_started=None;self.paused_ns=0

    def start(self):
        if self.directory is not None:self.task=asyncio.create_task(self._run())

    def source_started(self):
        if self.audio_start is None:self.audio_start=self.clock()

    def source_ended(self):
        self.capture_pause(False)
        if self.audio_end is None:self.audio_end=self.clock()

    def capture_pause(self,paused):
        if paused and self.pause_started is None:self.pause_started=self.clock();self.pause_count+=1
        elif not paused and self.pause_started is not None:
            self.paused_ns+=max(0,self.clock()-self.pause_started);self.pause_started=None

    def _fail(self,reason,storage=False):
        self.failed=True;self.storage_failed|=storage
        if reason not in self.errors:
            self.errors.add(reason);self.emit('transcript_error',reason=reason,transcript_complete=False)

    def offer(self,record):
        if self.directory is None or self.storage_failed:return
        value=dict(record) if isinstance(record,dict) else asdict(record)
        source=value.get('source_text','')
        if not source:return
        if (value.get('session_id')!=self.session_id or value.get('source_language') not in SOURCE_LANGUAGES
            or not isinstance(source,str) or len(source)>16384
            or type(value.get('segment_id')) is not int or value['segment_id']<0
            or type(value.get('revision')) is not int or value['revision']<0
            or type(value.get('start_sample')) is not int or value['start_sample']<0):
            self._fail('invalid_transcript_record');return
        translated=value.get('translated_text','')
        if not isinstance(translated,str) or len(translated)>16384:self._fail('invalid_transcript_record');return
        final=bool(value.get('source_closed') and value.get('state')=='final' and translated.strip()
                   and value.get('translated_revision')==value['revision'])
        row=(value['segment_id'],value['revision'],value['source_language'],value['start_sample'],source,
             translated if final else '',int(final))
        try:self.queue.put_nowait(row)
        except asyncio.QueueFull:self.dropped+=1;self._fail('transcript_queue_full')

    def _open(self):
        if not self.directory.is_dir():raise OSError('selected transcript directory is unavailable')
        identifier=uuid.uuid4().hex
        self.progress_path=self.directory/f"{self.started:%Y-%m-%d}{_tr('-翻译稿-进行中-')}{identifier}.txt"
        self.database_path=self.directory/f'.elt-transcript-{identifier}.sqlite3'
        self.ready_path=self.directory/f'.elt-transcript-{identifier}.ready'
        self.connection=sqlite3.connect(self.database_path,check_same_thread=False)
        self.connection.execute('CREATE TABLE segments (id INTEGER PRIMARY KEY, revision INTEGER, language TEXT, start INTEGER, source TEXT, translated TEXT, final INTEGER)')
        self.connection.commit()
        self.file=self.progress_path.open('x',encoding='utf-8')
        self.file.write(_tr('ELT 翻译稿（进行中）\n停止后将按原文顺序整理并生成正式文件名。\n\n'));self.file.flush()

    def _write(self,row):
        old=self.connection.execute('SELECT revision, final FROM segments WHERE id=?',(row[0],)).fetchone()
        if old and (old[1] or old[0]>row[1]):return
        self.connection.execute('INSERT INTO segments VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, language=excluded.language, start=excluded.start, source=excluded.source, translated=excluded.translated, final=excluded.final',row)
        self.connection.commit()
        if row[-1]:
            self.file.write(f"{_tr('原文：')}{row[4]}\n{self.translation_label}：{row[5]}\n\n");self.file.flush();os.fsync(self.file.fileno())

    async def _run(self):
        try:
            await asyncio.to_thread(self._open)
            self.emit('transcript_started',path=str(self.progress_path),transcript_complete=False)
        except (OSError,sqlite3.Error,UnicodeError):self._fail('transcript_open_failed',storage=True)
        while True:
            row=await self.queue.get()
            try:
                if row is None:return
                if not self.storage_failed:
                    try:await asyncio.to_thread(self._write,row)
                    except (OSError,sqlite3.Error,UnicodeError):self._fail('transcript_write_failed',storage=True)
            finally:self.queue.task_done()

    def _close_handles(self):
        try:
            if self.file:self.file.close();self.file=None
        finally:
            if self.connection:self.connection.close();self.connection=None

    def _finalize(self,source_complete):
        count,translated=self.connection.execute('SELECT COUNT(*), COALESCE(SUM(final),0) FROM segments').fetchone()
        language=language_label(self.language,[row[0] for row in self.connection.execute('SELECT DISTINCT language FROM segments')])
        minutes=max(0,(self.audio_end-self.audio_start)//60_000_000_000) if self.audio_start is not None else 0
        with self.ready_path.open('x',encoding='utf-8') as output:
            readable_language='+'.join(_tr(part) for part in language.split('+'))
            output.write(f"{_tr('Engineering Live Translator — 翻译稿\n日期：')}{self.started:%Y-%m-%d}{_tr('\n语言：')}{readable_language}{_tr('\n翻译时长：')}{minutes}{_tr('分钟\n')}")
            output.write(f"{_tr('原文片段：')}{count}{_tr('；已完成')}{self.translation_label}：{translated}{_tr('；未完成')}{self.translation_label}：{count - translated}\n")
            if self.pause_count:
                output.write(f"{_tr('手动暂停：')}{self.pause_count}{_tr('次，约')}{self.paused_ns / 1000000000.0:.0f}{_tr('秒；暂停期间的新音频未处理。时长包含暂停时间，片段采样时间仅计算已收音部分。\n')}")
            if not source_complete:output.write(_tr('本次会话已停止或中断，可能缺少停止时尚未识别的末尾内容。\n'))
            if self.failed:output.write(f"{_tr('保存过程中发生错误，此稿可能不完整；未入队记录数：')}{self.dropped}。\n")
            output.write('\n')
            for index,row in enumerate(self.connection.execute('SELECT source, translated, final FROM segments ORDER BY start, id'),1):
                output.write(f"{index}{_tr('.\n原文：')}{row[0]}\n{self.translation_label}：{(row[1] if row[2] else _tr('[未完成翻译，仅保存已确认原文]'))}\n\n")
            if not count:output.write(_tr('本次未取得可保存的已确认原文。\n'))
            output.flush();os.fsync(output.fileno())
        self._close_handles()
        destination=reserve_filename(self.directory,self.started,language,int(minutes))
        try:os.replace(self.ready_path,destination)
        except OSError:
            # Only this call's exclusively created empty reservation is removed.
            destination.unlink(missing_ok=True);raise
        cleanup_warning=False
        for path in (self.progress_path,self.database_path):
            try:path.unlink(missing_ok=True)
            except OSError:cleanup_warning=True
        return {'transcript_path':str(destination),'transcript_records':count,'transcript_translated':translated,
                'transcript_untranslated':count-translated,'transcript_minutes':int(minutes),
                'transcript_cleanup_warning':cleanup_warning}

    async def close(self,*,source_complete=False):
        self.source_ended()
        if self.task:
            await self.queue.join();await self.queue.put(None);await self.task
            if not self.storage_failed:
                try:self.result=await asyncio.to_thread(self._finalize,source_complete)
                except (OSError,sqlite3.Error,UnicodeError):self._fail('transcript_finalize_failed',storage=True)
            try:await asyncio.to_thread(self._close_handles)
            except (OSError,sqlite3.Error):self._fail('transcript_close_failed',storage=True)
        if self.result:
            self.emit('transcript_saved',**self.result,transcript_complete=not self.failed,source_complete=source_complete)
        return {'transcript_enabled':self.directory is not None,
                'transcript_complete':not self.failed and (self.directory is None or self.result is not None),
                'transcript_dropped':self.dropped,**(self.result or {})}
