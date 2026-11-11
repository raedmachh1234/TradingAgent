"""Kill switch. Anyone and anything may engage it; only a signed operator command releases it.

When a path is given, the switch is a file: creating that file by hand engages it even if the program
is unresponsive, and it stays engaged across restarts.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class KillSwitch:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else None
        self._memory: dict | None = None

    @property
    def engaged(self) -> bool:
        return self._memory is not None or (self.path is not None and self.path.exists())

    def engage(self, reason: str, by: str, now: datetime) -> None:
        info = {"reason": reason, "by": by, "at": now.isoformat()}
        self._memory = info
        if self.path is not None and not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(info) + "\n", encoding="utf-8")

    def reason(self) -> str:
        if self._memory:
            return str(self._memory.get("reason", ""))
        if self.path is not None and self.path.exists():
            try:
                return str(json.loads(self.path.read_text(encoding="utf-8")).get("reason", "engaged by file"))
            except (ValueError, OSError):
                return "engaged by file"
        return ""

    def release(self, command, verifier, now: datetime) -> tuple[bool, str]:
        """Release needs an operator command that verifies against the operator public key."""
        ok, why = verifier.verify(command, "release_kill_switch", now)
        if not ok:
            return False, why
        self._memory = None
        if self.path is not None and self.path.exists():
            self.path.unlink()
        return True, "released"
