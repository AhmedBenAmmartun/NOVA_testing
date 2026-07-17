from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import uuid4


class TaskType(str, Enum):
    CONVERSATION = "conversation"
    DESKTOP = "desktop"
    CODING = "coding"
    ANALYSIS = "analysis"
    RESEARCH = "research"
    PRIVATE = "private"
    OFFLINE = "offline"


class TaskStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class NovaTask:
    request: str
    task_type: TaskType = TaskType.CONVERSATION
    preferred_model: str | None = None
    contains_private_data: bool = False

    task_id: str = field(
        default_factory=lambda: uuid4().hex
    )

    status: TaskStatus = TaskStatus.CREATED

    created_at: datetime = field(
        default_factory=datetime.now
    )

    result: str | None = None
    error: str | None = None