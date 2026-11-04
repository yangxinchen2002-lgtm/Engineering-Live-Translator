"""Bounded full-session RAM transcript, independent of the 128-row display history."""
from collections import OrderedDict


class CourseTranscript:
    def __init__(self,limit=32*1024*1024,capacity=50000):
        self.limit=limit;self.capacity=capacity;self.reset()

    def reset(self):
        self.records=OrderedDict();self.session=None;self.bytes=0;self.incomplete=False

    def offer(self,record):
        if not record.get('source_text','').strip():return
        session=record.get('session_id')
        if self.session is None:self.session=session
        if session!=self.session:return
        key=record['segment_id'];old=self.records.get(key)
        if old and (old['final'] or old['revision']>record['revision']):return
        final=bool(record.get('source_closed') and record.get('state')=='final' and record.get('translated_text','').strip()
                   and record.get('translated_revision')==record['revision'])
        row={'id':key,'revision':record['revision'],'source':record['source_text'],
             'translated':record.get('translated_text','') if final else '', 'final':final,
             'closed':bool(record.get('source_closed')),'language':record.get('source_language','')}
        size=len((row['source']+row['translated']).encode('utf-8'))
        previous=len((old['source']+old['translated']).encode('utf-8')) if old else 0
        if self.bytes-previous+size>self.limit or (old is None and len(self.records)>=self.capacity):
            self.incomplete=True;return
        self.records[key]=row;self.bytes+=size-previous

    def snapshot(self):
        rows=[dict(row) for _,row in sorted(self.records.items()) if row['closed'] or row['final']]
        return {'session':self.session,'records':rows,'incomplete':self.incomplete,
                'untranslated':sum(not row['final'] for row in rows)}

    @property
    def available(self):return any(row['closed'] or row['final'] for row in self.records.values())
