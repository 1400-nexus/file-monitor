import math
from typing import List
from .models import BlockPlan,ShardAssignment
from .ids import SenderId

def calculate_block_count(file_size:int,block_size:int)->int:
    return math.ceil(file_size/block_size)

def compute_block_plans(file_size:int,block_size:int)->List[BlockPlan]:
    block_count=calculate_block_count(file_size,block_size)
    block_plans=[]
    for i in range(block_count):
        start_byte=i*block_size
        end_byte=min(start_byte+block_size,file_size)
        block_plans.append(BlockPlan(block_id=i,start_byte=start_byte,end_byte=end_byte))
    return block_plans

def derive_shard_assignments(total_blocks:int,active_senders:List[SenderId],base_port:int) ->List[ShardAssignment]:
    sender_count=len(active_senders)
    assignments=[]
    for i,sender_id in enumerate(active_senders):
        assigned_blocks=[j for j in range(total_blocks) if j%sender_count==i]
        target_port=base_port+i
        assignments.append(ShardAssignment(sender_id=sender_id,assigned_blocks=assigned_blocks,target_port=target_port))
    return assignments