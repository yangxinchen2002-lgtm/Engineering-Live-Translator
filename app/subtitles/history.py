from __future__ import annotations
import asyncio
from dataclasses import asdict
import json
from pathlib import Path


class HistoryWriter:
    def __init__(self,path:Path|None,capacity:int,emit):
        self.path,self.capacity,self.emit=path,capacity,emit
        self.file=path.open('x',encoding='utf-8') if path else None
        self.queue=asyncio.Queue(maxsize=capacity)
        self.task=None;self.failed=False;self.written=0

    def start(self):
        if self.file:self.task=asyncio.create_task(self._run())

    def offer(self,record):
        if not self.file or self.failed:return
        try:self.queue.put_nowait(json.dumps(asdict(record),ensure_ascii=False))
        except asyncio.QueueFull:
            self.failed=True
            self.emit('history_error',reason='history_queue_full',history_complete=False)

    def _write(self,line):
        self.file.write(line+'\n');self.file.flush()

    async def _run(self):
        while True:
            line=await self.queue.get()
            try:
                if line is None:return
                if not self.failed:
                    try:
                        await asyncio.to_thread(self._write,line);self.written+=1
                    except (OSError,UnicodeError):
                        self.failed=True
                        self.emit('history_error',reason='history_write_failed',history_complete=False)
            finally:self.queue.task_done()

    async def close(self):
        if self.task:
            await self.queue.join()
            await self.queue.put(None)
            await self.task
        if self.file:
            try:await asyncio.to_thread(self.file.close)
            except OSError:
                self.failed=True;self.emit('history_error',reason='history_close_failed',history_complete=False)
        return {'history_enabled':self.path is not None,'history_complete':not self.failed,'history_written':self.written}
