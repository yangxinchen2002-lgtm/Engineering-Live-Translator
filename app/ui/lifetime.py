"""GUI owns a Windows Job; backend joins itself before creating any workers."""
from __future__ import annotations
import os
import uuid

JOB_ENV='ELT_GUI_OWNER_JOB'


class OwnerJob:
    def __init__(self):
        if os.name!='nt':raise OSError('desktop capture requires Windows')
        import win32job
        self.name='Local\\ELT.Gui.'+uuid.uuid4().hex
        self.handle=win32job.CreateJobObject(None,self.name)
        try:
            info=win32job.QueryInformationJobObject(self.handle,win32job.JobObjectExtendedLimitInformation)
            info['BasicLimitInformation']['LimitFlags']|=win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(self.handle,win32job.JobObjectExtendedLimitInformation,info)
        except BaseException:
            self.handle.Close();raise

    def close(self):
        if self.handle is not None:
            self.handle.Close();self.handle=None


def join_owner_job(name:str):
    import win32api,win32job
    if not name.startswith('Local\\ELT.Gui.'):raise ValueError('invalid GUI owner job')
    handle=win32job.OpenJobObject(win32job.JOB_OBJECT_ASSIGN_PROCESS,False,name)
    try:win32job.AssignProcessToJobObject(handle,win32api.GetCurrentProcess())
    finally:handle.Close()  # only the GUI may keep the last job handle alive
