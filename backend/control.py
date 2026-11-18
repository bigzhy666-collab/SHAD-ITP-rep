"""Process-local shutdown authorization; tokens never appear in runtime responses."""
import os
import re
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class DesktopControl:
    instance_id: str
    token: str = field(repr=False)
    on_stop: Callable[[], None]

    def __post_init__(self):
        if not re.fullmatch('[a-f0-9]{32}', self.instance_id) or not re.fullmatch('[a-f0-9]{64}', self.token):
            raise ValueError('本机启动凭据格式不正确。')

    def identity(self):
        return {'managed': True, 'instanceId': self.instance_id, 'pid': os.getpid()}
