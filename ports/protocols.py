from typing import Protocol,AsyncGenerator,List,Dict,Any
import time
from pathlib import Path
import asyncio
class Clock(Protocol):
    def now(self)->float:
        ...
    async def sleep(self,seconds:float)->None:
        ...

class FileEvents(Protocol):
    async def listen(self)->AsyncGenerator[Path,None]:
        ...

class Hasher(Protocol):
    async def compute_hash(self,path:Path)->str:
        ...

class IpcServer(Protocol):
    async def broadcast(self,message:any)->None:
        ...

