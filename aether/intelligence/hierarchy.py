"""Hierarchical Orchestration — multi-level coordination for cluster-scale deployment.

Phase 8 §18: supervisor-subordinate device hierarchy with automatic promotion.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class HierarchyRole(str, Enum):
    SUPER = "super"
    PRIMARY = "primary"
    SECONDARY = "secondary"
    WORKER = "worker"
    STANDBY = "standby"


@dataclass
class HierarchyNode:
    node_id: str
    role: HierarchyRole
    parent_id: str = ""
    children: list[str] = field(default_factory=list)
    max_children: int = 4
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HierarchyEvent:
    event_id: str
    event_type: str
    node_id: str
    old_role: HierarchyRole
    new_role: HierarchyRole
    timestamp: float
    reason: str = ""


class Hierarchy:
    def __init__(self, super_node_id: str = "controller") -> None:
        self._lock = threading.RLock()
        self._super_node = super_node_id
        self._nodes: dict[str, HierarchyNode] = {}
        self._events: list[HierarchyEvent] = []

    def register_node(self, node_id: str, role: HierarchyRole = HierarchyRole.WORKER,
                      parent_id: str = "") -> HierarchyNode:
        with self._lock:
            parent = parent_id or self._super_node
            node = HierarchyNode(node_id=node_id, role=role, parent_id=parent)
            self._nodes[node_id] = node
            if parent in self._nodes:
                self._nodes[parent].children.append(node_id)
            elif parent == self._super_node:
                pass
            logger.info("Registered node %s as %s (parent: %s)", node_id, role.value, parent)
            return node

    def get_node(self, node_id: str) -> HierarchyNode | None:
        with self._lock:
            return self._nodes.get(node_id)

    def promote_node(self, node_id: str, new_role: HierarchyRole,
                     reason: str = "") -> HierarchyNode | None:
        with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                return None
            old_role = node.role
            node.role = new_role
            event = HierarchyEvent(
                event_id="evt_" + node_id + "_" + str(len(self._events)),
                event_type="promotion",
                node_id=node_id,
                old_role=old_role,
                new_role=new_role,
                timestamp=0.0,
                reason=reason,
            )
            import time
            event.timestamp = time.time()
            self._events.append(event)
            logger.info("Promoted %s from %s to %s: %s", node_id, old_role.value,
                        new_role.value, reason)
            return node

    def reassign_parent(self, node_id: str, new_parent_id: str) -> bool:
        with self._lock:
            node = self._nodes.get(node_id)
            if not node or new_parent_id not in self._nodes:
                return False
            if node.parent_id and node.parent_id in self._nodes:
                try:
                    self._nodes[node.parent_id].children.remove(node_id)
                except ValueError:
                    pass
            node.parent_id = new_parent_id
            self._nodes[new_parent_id].children.append(node_id)
            return True

    def get_children(self, node_id: str) -> list[str]:
        with self._lock:
            node = self._nodes.get(node_id)
            return list(node.children) if node else []

    def get_descendants(self, node_id: str) -> list[str]:
        with self._lock:
            descendants = []
            stack = list(self.get_children(node_id))
            while stack:
                child = stack.pop()
                descendants.append(child)
                stack.extend(self.get_children(child))
            return descendants

    def get_role_summary(self) -> dict[str, int]:
        with self._lock:
            summary = {}
            for node in self._nodes.values():
                summary[node.role.value] = summary.get(node.role.value, 0) + 1
            return summary

    def list_nodes(self) -> list[str]:
        with self._lock:
            return list(self._nodes.keys())
