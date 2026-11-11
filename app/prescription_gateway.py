"""Internal contract only. No HTTP client, credentials or national integration."""
from typing import Protocol


class PrescriptionGateway(Protocol):
    def submit(self, payload: dict) -> dict: ...


class FakePrescriptionGateway:
    def __init__(self):
        self.received = []

    def submit(self, payload):
        import copy
        self.received.append(copy.deepcopy(payload))
        return {'status': 'fake_accepted', 'national_code': None}
