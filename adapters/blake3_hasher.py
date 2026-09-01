import asyncio
import blake3
from pathlib import Path
from ports.protocols import Hasher

CHUNK_SIZE = 1048576 

class Blake3Hasher(Hasher):
    @staticmethod
    def _hash_file_sync(path:Path)->str:
        hasher=blake3.blake3()
        with open(path,"rb") as f:
            while True:
                chunk=f.read(CHUNK_SIZE)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()
    async def compute_hash(self,path:Path)->str:
        return await asyncio.to_thread(self._hash_file_sync,path)