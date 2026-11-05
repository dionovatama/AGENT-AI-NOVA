"""Worker-local relay session registry with Agent/owner/connection isolation."""
from __future__ import annotations
import time, uuid
from dataclasses import dataclass
from enum import Enum

class RelayState(str,Enum):
    REQUESTED="requested"; OPEN="open"; CLOSING="closing"; CLOSED="closed"; FAILED="failed"
class RelaySessionError(ValueError): pass
@dataclass
class RelaySession:
    session_id:uuid.UUID; request_id:uuid.UUID; agent_id:uuid.UUID; owner_id:uuid.UUID; connection_id:uuid.UUID; target_id:uuid.UUID; port:int; state:RelayState; created_at:float; last_activity:float; error_code:str|None=None

class RelaySessionRegistry:
    def __init__(self,*,max_per_agent:int=8,idle_timeout:float=60.0,clock=time.monotonic):
        if max_per_agent<1 or idle_timeout<=0: raise ValueError("invalid relay registry limits")
        self.max_per_agent=max_per_agent; self.idle_timeout=idle_timeout; self._clock=clock; self._sessions:dict[uuid.UUID,RelaySession]={}
    def create(self,*,agent_id,owner_id,connection_id,target_id,port,request_id=None,session_id=None):
        if isinstance(port,bool) or not isinstance(port,int) or not 1<=port<=65535: raise RelaySessionError("invalid target port")
        active=sum(s.agent_id==agent_id and s.state in {RelayState.REQUESTED,RelayState.OPEN,RelayState.CLOSING} for s in self._sessions.values())
        if active>=self.max_per_agent: raise RelaySessionError("agent relay session limit reached")
        self._prune_terminal(); sid=session_id or uuid.uuid4(); rid=request_id or uuid.uuid4()
        if sid in self._sessions or any(s.request_id==rid for s in self._sessions.values()): raise RelaySessionError("duplicate relay id")
        now=self._clock(); s=RelaySession(sid,rid,agent_id,owner_id,connection_id,target_id,port,RelayState.REQUESTED,now,now); self._sessions[sid]=s; return s
    def get(self,session_id,*,agent_id,owner_id,connection_id):
        s=self._sessions.get(session_id)
        if s is None or s.agent_id!=agent_id or s.owner_id!=owner_id or s.connection_id!=connection_id: raise RelaySessionError("relay session not found")
        return s
    def mark_open(self,session_id,**kw):
        s=self.get(session_id,**kw)
        if s.state is not RelayState.REQUESTED: raise RelaySessionError("invalid relay state transition")
        s.state=RelayState.OPEN; s.last_activity=self._clock(); return s
    def touch(self,session_id,**kw):
        s=self.get(session_id,**kw)
        if s.state is not RelayState.OPEN: raise RelaySessionError("relay session is not open")
        s.last_activity=self._clock(); return s
    def fail(self,session_id,*,code,**kw):
        s=self.get(session_id,**kw)
        if s.state not in {RelayState.REQUESTED,RelayState.OPEN,RelayState.CLOSING}: raise RelaySessionError("invalid relay state transition")
        s.state=RelayState.FAILED; s.error_code=code; return s
    def close(self,session_id,**kw):
        s=self.get(session_id,**kw)
        if s.state not in {RelayState.REQUESTED,RelayState.OPEN,RelayState.CLOSING}: raise RelaySessionError("invalid relay state transition")
        s.state=RelayState.CLOSED; return s
    def cleanup_connection(self,*,agent_id,connection_id):
        n=0
        for s in self._sessions.values():
            if s.agent_id==agent_id and s.connection_id==connection_id and s.state in {RelayState.REQUESTED,RelayState.OPEN,RelayState.CLOSING}: s.state=RelayState.CLOSED; n+=1
        return n
    def expire_idle(self):
        now=self._clock(); n=0
        for s in self._sessions.values():
            if s.state in {RelayState.REQUESTED,RelayState.OPEN,RelayState.CLOSING} and now-s.last_activity>=self.idle_timeout: s.state=RelayState.CLOSED; n+=1
        return n
    def _prune_terminal(self,retention_seconds=300.0):
        now=self._clock()
        for sid,s in list(self._sessions.items()):
            if s.state in {RelayState.CLOSED,RelayState.FAILED} and now-s.created_at>=retention_seconds: self._sessions.pop(sid,None)
    def __len__(self): return len(self._sessions)
