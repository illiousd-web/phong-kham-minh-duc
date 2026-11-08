"""Rotate operational logs, without HTTP query strings or patient payloads."""
from .config import DATA
import os
from logging.handlers import RotatingFileHandler


class LockedRotatingFileHandler(RotatingFileHandler):
    """Keep one bounded log set safe when an administrator selects 2 workers."""
    def __init__(self,filename,**kwargs):
        super().__init__(filename,delay=True,**kwargs)
        self.process_lock=filename+".lock"

    def emit(self,record):
        try:
            with open(self.process_lock,"a+b") as guard:
                guard.seek(0,2)
                if guard.tell()==0:guard.write(b"0");guard.flush()
                guard.seek(0)
                if os.name=="nt":
                    import msvcrt
                    msvcrt.locking(guard.fileno(),msvcrt.LK_LOCK,1)
                else:
                    import fcntl
                    fcntl.flock(guard.fileno(),fcntl.LOCK_EX)
                try:
                    # Reopen under the lock so another worker rotating the file
                    # cannot leave this handler writing to an old renamed file.
                    if self.stream:self.stream.close();self.stream=None
                    super().emit(record)
                    if self.stream:self.stream.close();self.stream=None
                finally:
                    guard.seek(0)
                    if os.name=="nt":msvcrt.locking(guard.fileno(),msvcrt.LK_UNLCK,1)
                    else:fcntl.flock(guard.fileno(),fcntl.LOCK_UN)
        except Exception:self.handleError(record)



def server_logging():
    directory=DATA/'logs'
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    return {
        'version':1,'disable_existing_loggers':False,
        'formatters':{'plain':{'format':'%(asctime)s %(levelname)s %(name)s %(message)s'}},
        'handlers':{'clinic_file':{'class':'app.logging_config.LockedRotatingFileHandler',
            'filename':str(directory/'server.log'),'maxBytes':5*1024*1024,'backupCount':7,
            'encoding':'utf-8','formatter':'plain'}},
        'root':{'level':'WARNING','handlers':['clinic_file']},
        'loggers':{'uvicorn':{'level':'WARNING','handlers':['clinic_file'],'propagate':False},
                   'uvicorn.error':{'level':'WARNING','handlers':['clinic_file'],'propagate':False},
                   'uvicorn.access':{'level':'WARNING','handlers':[],'propagate':False}}
    }
