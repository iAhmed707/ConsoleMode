"""Scheduled Task scanner.

Tasks are enumerated read-only through the official Task Scheduler API's
PowerShell cmdlet ``Get-ScheduledTask`` (one process, JSON output).  Each
action's executable is extracted and the task is treated as component metadata
that can attach to its owning program by executable path.
"""

from __future__ import annotations

from typing import List

from ..commandline import split_executable
from ..models import Component, RawDiscoveryItem, SOURCE_SCHEDULED_TASK
from ..powershell import run_json
from .base import BaseScanner, make_id

_QUERY = r"""
$ErrorActionPreference = 'SilentlyContinue'
Get-ScheduledTask | ForEach-Object {
    $t = $_
    foreach ($a in $t.Actions) {
        if ($a.Execute) {
            [pscustomobject]@{
                TaskName = [string]$t.TaskName
                TaskPath = [string]$t.TaskPath
                State = [string]$t.State
                Author = [string]$t.Author
                Execute = [string]$a.Execute
                Arguments = [string]$a.Arguments
            }
        }
    }
} | ConvertTo-Json -Depth 3 -Compress
"""


class ScheduledTaskScanner(BaseScanner):
    name = "ScheduledTask"

    def scan(self) -> List[RawDiscoveryItem]:
        result = run_json(_QUERY, timeout=30.0)
        if result is None:
            return []
        if isinstance(result, dict):
            result = [result]

        items: List[RawDiscoveryItem] = []
        for task in result:
            if not isinstance(task, dict):
                continue
            item = self._item(task)
            if item is not None:
                items.append(item)
        return items

    def _item(self, task) -> RawDiscoveryItem:
        task_name = (task.get("TaskName") or "").strip()
        execute = (task.get("Execute") or "").strip()
        arguments = (task.get("Arguments") or "").strip()
        if not execute:
            return None

        exe = execute
        if exe.lower().endswith(".exe") and arguments:
            # Keep the arguments for matching but store the plain exe as the
            # component path.
            pass
        details = {
            "task_path": (task.get("TaskPath") or "").strip(),
            "state": (task.get("State") or "").strip(),
            "author": (task.get("Author") or "").strip(),
            "arguments": arguments,
        }

        item = RawDiscoveryItem(
            id=make_id("scheduled-task", (task.get("TaskPath") or "") + task_name),
            name=task_name,
            executable_path=exe if _exists(exe) else "",
            source=SOURCE_SCHEDULED_TASK,
            components=[Component(kind="scheduled_task", name=task_name, path=exe,
                                  details=details)],
        )
        item.extra.update(details)
        return item


def _exists(path: str) -> bool:
    import os
    try:
        return bool(path) and os.path.isfile(path)
    except OSError:
        return False
