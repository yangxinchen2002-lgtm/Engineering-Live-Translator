"""Player-owned, bounded loopback access to one explicitly selected local file."""
from __future__ import annotations
from app.i18n import tr as _tr
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import threading
import time
from urllib.parse import urlsplit
from .media import Source,byte_range

ASSETS=Path(__file__).with_name('web')


@dataclass(frozen=True)
class Selection:
    source:Source
    token:str


class MediaServer(ThreadingHTTPServer):
    daemon_threads=True
    block_on_close=False

    def __init__(self,owner):
        self.owner=owner;self.slots=threading.BoundedSemaphore(8);self.connections=set();self.connection_lock=threading.Lock()
        super().__init__(('127.0.0.1',0),Handler)

    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):self.shutdown_request(request);return
        with self.connection_lock:self.connections.add(request)
        try:super().process_request(request,address)
        except BaseException:
            with self.connection_lock:self.connections.discard(request)
            self.slots.release();raise

    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:
            with self.connection_lock:self.connections.discard(request)
            self.slots.release()

    def abort_requests(self):
        with self.connection_lock:connections=list(self.connections)
        for connection in connections:
            try:connection.shutdown(socket.SHUT_RDWR)
            except OSError:pass


class LocalMediaHost:
    def __init__(self):
        self.lock=threading.Lock();self.selection=None;self.closed=threading.Event()
        self.server=MediaServer(self);self.origin=f'http://127.0.0.1:{self.server.server_port}'
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.1},daemon=True,name='ELT-Local-Video')
        self.thread.start()

    def select(self,value):
        source=Source.parse(value)
        if source.remote:raise ValueError(_tr('请选择本地视频文件'))
        if not source.local_identity[2]:raise ValueError(_tr('所选文件为空'))
        with self.lock:self.selection=Selection(source,secrets.token_urlsafe(32))
        self.server.abort_requests()
        return self.page_url

    @property
    def page_url(self):
        with self.lock:selected=self.selection
        return self.origin+'/p/'+selected.token+'/player.html' if selected else ''

    @property
    def name(self):
        with self.lock:selected=self.selection
        return Path(selected.source.value).name if selected else ''

    def is_page(self,value):return bool(self.page_url and value==self.page_url)

    def source_for(self,value):
        with self.lock:selected=self.selection
        if not selected or value!=self.origin+'/m/'+selected.token:raise ValueError(_tr('未授权的本地媒体'))
        try:selected.source.check_local(Path(selected.source.value).stat())
        except OSError:raise ValueError(_tr('本地媒体已无法读取，请重新打开文件')) from None
        return selected.source

    def close(self):
        if self.closed.is_set():return
        self.closed.set();self.server.shutdown();self.server.abort_requests();self.server.server_close();self.thread.join(2)
        with self.lock:self.selection=None


class Handler(BaseHTTPRequestHandler):
    def setup(self):super().setup();self.connection.settimeout(5);self.response_started=False
    def log_message(self,*args):pass  # No local paths or per-file capabilities in logs.

    def headers_for(self,status,mime,size,extra=()):
        self.response_started=True
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(size))
        self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Connection','close')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'")
        for key,value in extra:self.send_header(key,str(value))
        self.end_headers()

    def error(self,status,message,head=False):
        raw=json.dumps({'error':message},ensure_ascii=False).encode()
        self.headers_for(status,'application/json; charset=utf-8',len(raw))
        if not head:self.wfile.write(raw)

    def do_HEAD(self):self.get(True)
    def do_GET(self):self.get(False)
    def do_POST(self):self.error(405,'method not allowed')

    def get(self,head):
        try:self.respond(head)
        except (BrokenPipeError,ConnectionError,TimeoutError):pass
        except (OSError,ValueError):
            if self.response_started:self.close_connection=True;return
            try:self.error(409,_tr('本地视频已无法读取，请重新打开文件'),head)
            except (OSError,ValueError):pass

    def respond(self,head):
        owner=self.server.owner;url=urlsplit(self.path)
        if self.headers.get('Host')!=urlsplit(owner.origin).netloc or self.headers.get('Origin',owner.origin)!=owner.origin or url.query:
            self.error(403,'forbidden',head);return
        with owner.lock:selected=owner.selection
        if not selected or owner.closed.is_set():self.error(404,'no selected media',head);return
        prefix='/p/'+selected.token+'/'
        static={'player.html':('local-player.html','text/html; charset=utf-8'),
                'player.css':('local-player.css','text/css; charset=utf-8'),
                'player.js':('local-player.js','text/javascript; charset=utf-8')}
        if url.path.startswith(prefix):
            name=url.path[len(prefix):]
            if name=='info.json':raw=json.dumps({'name':Path(selected.source.value).name},ensure_ascii=False).encode();mime='application/json; charset=utf-8'
            elif name in static:
                file,mime=static[name];raw=(ASSETS/file).read_bytes()
            else:self.error(404,'not found',head);return
            self.headers_for(200,mime,len(raw))
            if not head:self.wfile.write(raw)
            return
        if url.path!='/m/'+selected.token:self.error(404,'not found',head);return
        # The path never comes from an HTTP request, only the native picker.
        with Path(selected.source.value).open('rb') as handle:
            stat=os.fstat(handle.fileno());selected.source.check_local(stat)
            try:start,end=byte_range(self.headers.get('Range'),stat.st_size)
            except ValueError:
                self.headers_for(416,'application/octet-stream',0,[('Content-Range',f'bytes */{stat.st_size}')]);return
            partial=self.headers.get('Range') is not None
            extra=[('Accept-Ranges','bytes')]
            if partial:extra.append(('Content-Range',f'bytes {start}-{end}/{stat.st_size}'))
            self.headers_for(206 if partial else 200,selected.source.mime,end-start+1,extra)
            if head:return
            self.connection.settimeout(None)  # Pausing the video may suspend a large Range read.
            handle.seek(start);remaining=end-start+1;checked=time.monotonic()
            while remaining and not owner.closed.is_set():
                with owner.lock:
                    if owner.selection is not selected:return
                if time.monotonic()-checked>1:
                    selected.source.check_local(os.fstat(handle.fileno()));checked=time.monotonic()
                data=handle.read(min(65536,remaining))
                if not data:return
                self.wfile.write(data);remaining-=len(data)
