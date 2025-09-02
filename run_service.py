"""
Windows Service wrapper untuk FastAPI
Install dengan: pip install pywin32
"""
import sys
import os
import servicemanager
import socket
import win32event
import win32service
import win32serviceutil
import subprocess

class FastAPIService(win32serviceutil.ServiceFramework):
    _svc_name_ = "FastAPIConverter"
    _svc_display_name_ = "FastAPI DOCX to PDF Converter"
    _svc_description_ = "Service untuk konversi DOCX ke PDF"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        socket.setdefaulttimeout(60)
        self.process = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        if self.process:
            self.process.terminate()

    def SvcDoRun(self):
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                            servicemanager.PYS_SERVICE_STARTED,
                            (self._svc_name_, ''))
        self.main()

    def main(self):
        # Path ke project directory
        project_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Jalankan uvicorn
        cmd = [
            sys.executable, "-m", "uvicorn", 
            "app:app", 
            "--host", "0.0.0.0", 
            "--port", "80",
            "--workers", "1"
        ]
        
        self.process = subprocess.Popen(cmd, cwd=project_dir)
        
        # Wait for stop signal
        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)

if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(FastAPIService)
