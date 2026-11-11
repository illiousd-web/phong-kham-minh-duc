"""Offline input contract: adapters return identifiers, values, times; never approve."""
from typing import Protocol
from copy import deepcopy
from .m5 import ResultInput

class LabResultSource(Protocol):
    def receive(self, *, order_id:int) -> ResultInput: ...

class FakeLabResultSource:
    def __init__(self,results:dict[int,ResultInput]):self.results=deepcopy(results)
    def receive(self, *, order_id:int) -> ResultInput:
        return self.results[order_id].model_copy(deep=True)
