"""
Segment data model for Aether memory management.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ResidencyState(Enum):
    LOCAL          = "local"
    REMOTE_RESIDENT = "remote_resident"
    IN_TRANSFER     = "in_transfer"
    EXECUTING       = "executing"
    EVICTABLE       = "evictable"
    INVALID         = "invalid"


class SegmentType(Enum):
    MODEL_WEIGHTS = "model_weights"
    ACTIVATION    = "activation"
    GRADIENT      = "gradient"
    MISC          = "misc"


class SegmentPriority(Enum):
    HIGH   = 1
    MEDIUM = 2
    LOW    = 3


@dataclass
class Segment:
    name: str = ""
    size_bytes: int = 0
    segment_id: str = field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    seg_type: SegmentType = SegmentType.MISC
    residency: ResidencyState = ResidencyState.LOCAL
    priority: SegmentPriority = SegmentPriority.MEDIUM
    pinned: bool = False
    owner_device: Optional[str] = None
    tensor_id: Optional[str] = None
    created_at: float = field(default_factory=__import__("time").time)

    def __post_init__(self):
        if not self.name:
            self.name = f"seg_{self.segment_id[:6]}"

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)

    @property
    def is_remote(self) -> bool:
        return self.residency in (
            ResidencyState.REMOTE_RESIDENT,
            ResidencyState.IN_TRANSFER,
            ResidencyState.EXECUTING,
        )

    def to_dict(self) -> dict:
        return {
            "segment_id": self.segment_id,
            "name": self.name,
            "size_bytes": self.size_bytes,
            "size_mb": self.size_mb,
            "seg_type": self.seg_type.value,
            "residency": self.residency.value,
            "priority": self.priority.value,
            "pinned": self.pinned,
            "owner_device": self.owner_device,
            "tensor_id": self.tensor_id,
            "is_remote": self.is_remote,
        }
