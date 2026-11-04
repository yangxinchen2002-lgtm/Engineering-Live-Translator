"""Per-session relative attenuation with identity checks and reversible leases.

Core Audio COM objects stay inside a dedicated volume guardian process. No master
device volume or mute state is ever written here.
"""
from dataclasses import dataclass
import ctypes as ct
import math
from .processes import ProcessInfo,ProcessSelector,process_source


def process_tree(target,selector):
    try:current=selector.inspect(target.pid)
    except OSError:raise ProcessLookupError('source ended or became inaccessible') from None
    if current!=target:raise ProcessLookupError('source identity changed')
    members={target.pid:target};rows=selector.snapshot()
    changed=True
    while changed:
        changed=False
        for pid,parent,_ in rows:
            if pid in members or parent not in members:continue
            try:child=selector.inspect(pid)
            except OSError:continue
            if child.created<members[parent].created:continue
            members[pid]=child;changed=True
    try:current=selector.inspect(target.pid)
    except OSError:raise ProcessLookupError('source ended or became inaccessible') from None
    if current!=target:raise ProcessLookupError('source identity changed')
    return members


@dataclass
class VolumeLease:
    session:object
    original:float
    applied:float
    overridden:bool=False


class SourceAttenuator:
    def __init__(self,target,backend,selector=None):
        process_source(target)
        self.target=target;self.backend=backend;self.selector=selector or ProcessSelector();self.leases={}

    def update(self,percent):
        if type(percent) is not int or not 0<=percent<=100:raise ValueError('invalid source volume percentage')
        members=process_tree(self.target,self.selector);applied=0
        for session in self.backend.sessions():
            identity=members.get(session.pid)
            if identity is None:continue
            try:
                if self.selector.inspect(session.pid)!=identity:continue
                key=(session.key,identity.created)
                lease=self.leases.get(key)
                current=session.get_volume()
                if not math.isfinite(current) or not 0<=current<=1:raise ValueError('invalid session volume')
                if lease is None:
                    if len(self.leases)>=256:raise RuntimeError('too many audio sessions')
                    lease=VolumeLease(session,current,current);self.leases[key]=lease
                elif lease.overridden:continue
                elif abs(current-lease.applied)>1e-4:
                    # Respect an external/manual mixer adjustment instead of fighting it.
                    lease.overridden=True;continue
                lease.session=session
                volume=lease.original*percent/100
                if abs(current-volume)>1e-5:session.set_volume(volume)
                lease.applied=volume;applied+=1
            except OSError:continue  # A session/device can disappear between enumeration and use.
        return applied

    def restore(self):
        failed=0
        for lease in self.leases.values():
            try:
                if not lease.overridden and abs(lease.session.get_volume()-lease.applied)<=1e-4:
                    lease.session.set_volume(lease.original)
            except Exception:failed+=1
        self.leases.clear();return failed


class CoreAudioSession:
    def __init__(self,key,pid,control,volume,*,state=0,display_name=''):
        self.key=key;self.pid=pid;self.control=control;self.volume=volume
        self.state=state;self.display_name=display_name

    def get_volume(self):
        try:return float(self.volume.GetMasterVolume())
        except Exception:raise OSError('audio session unavailable') from None

    def set_volume(self,value):
        try:self.volume.SetMasterVolume(float(value),None)
        except Exception:raise OSError('audio session unavailable') from None


class CoreAudioBackend:
    def __init__(self):
        from pycaw.utils import AudioUtilities
        self.enumerator=AudioUtilities.GetDeviceEnumerator()
        self.errors=[]

    def sessions(self):
        import comtypes
        from pycaw.api.audiopolicy import IAudioSessionManager2,IAudioSessionControl2
        from pycaw.api.audioclient import ISimpleAudioVolume
        devices=self.enumerator.EnumAudioEndpoints(0,1)  # Active rendering endpoints only.
        result=[];self.errors=[]
        for index in range(devices.GetCount()):
            device=devices.Item(index)
            try:
                manager=device.Activate(IAudioSessionManager2._iid_,comtypes.CLSCTX_ALL,None).QueryInterface(IAudioSessionManager2)
                sessions=manager.GetSessionEnumerator()
                for slot in range(sessions.GetCount()):
                    try:
                        control=sessions.GetSession(slot).QueryInterface(IAudioSessionControl2)
                        state=control.GetState()
                        if state==2:continue
                        pid=ct.c_ulong()
                        # The raw HRESULT distinguishes cross-process shared sessions
                        # (AUDCLNT_S_NO_SINGLE_PROCESS), which we must never attenuate.
                        hr=control._IAudioSessionControl2__com_GetProcessId(ct.byref(pid))
                        if hr!=0 or not pid.value:continue
                        key=(device.GetId(),control.GetSessionIdentifier())
                        try:name=control.GetDisplayName() or ''
                        except (OSError,comtypes.COMError):name=''
                        if len(result)>=256:raise BufferError('audio session enumeration exceeds 256 sessions')
                        result.append(CoreAudioSession(key,pid.value,control,control.QueryInterface(ISimpleAudioVolume),
                                                       state=state,display_name=name))
                    except (OSError,comtypes.COMError) as error:
                        if len(self.errors)<64:self.errors.append({'error':'audio_session_unavailable','device_index':index,
                            'hresult':getattr(error,'hresult',None)})
            except (OSError,comtypes.COMError) as error:
                if len(self.errors)<64:self.errors.append({'error':'audio_device_sessions_unavailable','device_index':index,
                    'hresult':getattr(error,'hresult',None)})
        return result
