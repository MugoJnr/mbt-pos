"""Find which PIDs lock a file via Restart Manager."""
from __future__ import annotations

import ctypes
import subprocess
from ctypes import wintypes

path = r"C:\Users\mugoj\AppData\Local\Google\Chrome\User Data\Profile 2\Network\Cookies"

rstrtmgr = ctypes.WinDLL("rstrtmgr")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ULONG = ctypes.c_ulong
DWORD = wintypes.DWORD


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", DWORD), ("dwHighDateTime", DWORD)]


class RM_UNIQUE_PROCESS(ctypes.Structure):
    _fields_ = [("dwProcessId", DWORD), ("ProcessStartTime", FILETIME)]


class RM_PROCESS_INFO(ctypes.Structure):
    _fields_ = [
        ("Process", RM_UNIQUE_PROCESS),
        ("strAppName", ctypes.c_wchar * 256),
        ("strServiceShortName", ctypes.c_wchar * 64),
        ("ApplicationType", ctypes.c_uint32),
        ("AppStatus", ULONG),
        ("TSSessionId", DWORD),
        ("bRestartable", wintypes.BOOL),
    ]


RmStartSession = rstrtmgr.RmStartSession
RmStartSession.argtypes = [ctypes.POINTER(DWORD), DWORD, ctypes.c_wchar_p]
RmEndSession = rstrtmgr.RmEndSession
RmEndSession.argtypes = [DWORD]
RmRegisterResources = rstrtmgr.RmRegisterResources
RmRegisterResources.argtypes = [
    DWORD,
    ULONG,
    ctypes.POINTER(ctypes.c_wchar_p),
    ULONG,
    ctypes.c_void_p,
    ULONG,
    ctypes.c_void_p,
]
RmGetList = rstrtmgr.RmGetList
RmGetList.argtypes = [
    DWORD,
    ctypes.POINTER(ULONG),
    ctypes.POINTER(ULONG),
    ctypes.POINTER(RM_PROCESS_INFO),
    ctypes.POINTER(ULONG),
]

session = DWORD()
key = ctypes.c_wchar_p("mbtjunior")
rc = RmStartSession(ctypes.byref(session), 0, key)
print("start", rc, session.value)
files = (ctypes.c_wchar_p * 1)(path)
rc = RmRegisterResources(session, 1, files, 0, None, 0, None)
print("reg", rc)
needed = ULONG(0)
count = ULONG(0)
reboot = ULONG(0)
rc = RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reboot))
print("list1", rc, "needed", needed.value)
if needed.value:
    arr = (RM_PROCESS_INFO * needed.value)()
    count = ULONG(needed.value)
    rc = RmGetList(session, ctypes.byref(needed), ctypes.byref(count), arr, ctypes.byref(reboot))
    print("list2", rc, "count", count.value)
    for i in range(count.value):
        pid = arr[i].Process.dwProcessId
        print("LOCKER", pid, arr[i].strAppName)
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
                text=True,
                timeout=10,
            )
            print(" CL", (out or "").strip()[:250])
        except Exception as e:
            print(" CL err", e)
RmEndSession(session)
