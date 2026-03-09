from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from logger import calendar_logger


UTC = timezone.utc


@dataclass(slots=True)
class ResearchSessionRef:
    chat_id: str
    session_id: str
    session_dir: Path


class ResearchContextStore:
    """File-based per-chat context cache for research follow-ups."""

    def __init__(
        self,
        base_dir: str | None = None,
        ttl_hours: int = 24,
        max_sessions_per_chat: int = 4,
    ) -> None:
        root = base_dir or os.getenv("RESEARCH_CONTEXT_DIR")
        if not root:
            root = os.path.join(os.getenv("TEMP", os.getenv("TMP", ".")), "selfhosted_assistant", "research")

        self.base_dir = Path(root).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.ttl = timedelta(hours=max(1, ttl_hours))
        self.max_sessions_per_chat = max(1, max_sessions_per_chat)

    def save_turn(self, chat_id: str, user_text: str, assistant_text: str) -> ResearchSessionRef:
        session = self.get_or_create_active_session(chat_id)
        turn_index = self._next_turn_index(session.session_dir)

        turns_dir = session.session_dir / "turns"
        turns_dir.mkdir(parents=True, exist_ok=True)

        user_file = turns_dir / f"{turn_index:03d}_user.txt"
        assistant_file = turns_dir / f"{turn_index:03d}_assistant.md"
        user_file.write_text(user_text or "", encoding="utf-8")
        assistant_file.write_text(assistant_text or "", encoding="utf-8")

        self._touch_meta(session.session_dir, status="active")
        return session

    def save_artifacts(self, chat_id: str, assistant_text: str) -> ResearchSessionRef:
        session = self.get_or_create_active_session(chat_id)
        brief = self._build_brief(assistant_text)
        findings = self._extract_findings(assistant_text)
        sources = self._extract_sources(assistant_text)

        (session.session_dir / "brief.md").write_text(brief, encoding="utf-8")
        (session.session_dir / "findings.json").write_text(
            json.dumps(findings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (session.session_dir / "sources.json").write_text(
            json.dumps(sources, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._touch_meta(session.session_dir, status="active")
        return session

    def get_active_context(self, chat_id: str) -> dict[str, Any] | None:
        session = self._find_latest_session(chat_id)
        if not session:
            return None

        meta = self._read_json(session / "meta.json", {})
        brief = self._safe_read_text(session / "brief.md")
        findings = self._read_json(session / "findings.json", [])
        sources = self._read_json(session / "sources.json", [])
        return {
            "meta": meta,
            "brief": brief,
            "findings": findings,
            "sources": sources,
            "session_dir": str(session),
        }

    def get_or_create_active_session(self, chat_id: str) -> ResearchSessionRef:
        self.cleanup_expired()
        session_dir = self._find_latest_session(chat_id)
        if session_dir is None:
            session_dir = self._create_session(chat_id)

        meta = self._read_json(session_dir / "meta.json", {})
        return ResearchSessionRef(
            chat_id=str(chat_id),
            session_id=str(meta.get("session_id", session_dir.name)),
            session_dir=session_dir,
        )

    def get_or_create_copilot_session_id(self, chat_id: str) -> str:
        session = self.get_or_create_active_session(chat_id)
        meta_path = session.session_dir / "meta.json"
        meta = self._read_json(meta_path, {})

        existing = str(meta.get("copilot_session_id", "")).strip()
        if existing:
            return existing

        raw_chat = re.sub(r"[^a-zA-Z0-9_-]", "-", str(chat_id))
        session_suffix = re.sub(r"[^a-zA-Z0-9_-]", "-", session.session_id)
        generated = f"tg-research-{raw_chat}-{session_suffix}"
        meta["copilot_session_id"] = generated
        meta["last_updated_at"] = datetime.now(tz=UTC).isoformat()
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return generated

    def reset_chat(self, chat_id: str) -> bool:
        """Reset only the active session, not the whole chat directory."""
        session_dir = self._find_active_session(chat_id)
        if not session_dir:
            return False
        shutil.rmtree(session_dir, ignore_errors=True)
        # Clear active_session_id so next call picks a remaining session or creates new
        state = self._read_chat_state(chat_id)
        state.pop("active_session_id", None)
        self._write_chat_state(chat_id, state)
        return True

    def reset_all_sessions(self, chat_id: str) -> bool:
        """Remove the entire chat directory with all sessions."""
        chat_dir = self.base_dir / str(chat_id)
        if not chat_dir.exists():
            return False
        shutil.rmtree(chat_dir, ignore_errors=True)
        return True

    def get_last_assistant_turn(self, chat_id: str) -> str:
        session = self._find_latest_session(chat_id)
        if not session:
            return ""

        turns_dir = session / "turns"
        if not turns_dir.exists() or not turns_dir.is_dir():
            return ""

        assistant_turns = sorted(turns_dir.glob("*_assistant.md"))
        if not assistant_turns:
            return ""
        return self._safe_read_text(assistant_turns[-1])

    def is_clarification_pending(self, chat_id: str) -> bool:
        text = self.get_last_assistant_turn(chat_id).lower()
        if not text:
            return False

        if "[confirmed]" in text or "[cancelled]" in text:
            return False

        clarification_hints = (
            "уточните",
            "уточни",
            "пожалуйста, уточните",
            "please clarify",
            "ответьте на эти вопросы",
            "нужны уточнения",
            "?",
        )
        return any(hint in text for hint in clarification_hints)

    def cancel_clarification(self, chat_id: str) -> bool:
        """Mark the current clarification as cancelled so input is no longer captured."""
        session = self._find_active_session(chat_id)
        if not session:
            return False
        turns_dir = session / "turns"
        if not turns_dir.exists():
            return False
        assistant_turns = sorted(turns_dir.glob("*_assistant.md"))
        if not assistant_turns:
            return False
        last = assistant_turns[-1]
        content = self._safe_read_text(last)
        if not content or "[cancelled]" in content.lower():
            return False
        last.write_text(content + "\n[cancelled]", encoding="utf-8")
        return True

    def list_sources(self, chat_id: str) -> list[str]:
        ctx = self.get_active_context(chat_id)
        if not ctx:
            return []

        urls: list[str] = []
        for source in ctx.get("sources", []):
            if isinstance(source, dict):
                url = str(source.get("url", "")).strip()
                if url:
                    urls.append(url)
        return urls

    def cleanup_expired(self) -> None:
        now = datetime.now(tz=UTC)

        for chat_dir in self.base_dir.iterdir():
            if not chat_dir.is_dir():
                continue

            sessions = [item for item in chat_dir.iterdir() if item.is_dir()]
            for session in sessions:
                meta = self._read_json(session / "meta.json", {})
                created_raw = str(meta.get("created_at", ""))
                created_at = self._parse_dt(created_raw)
                if created_at and now - created_at > self.ttl:
                    shutil.rmtree(session, ignore_errors=True)

            existing = sorted([item for item in chat_dir.iterdir() if item.is_dir()], key=lambda p: p.name)
            overflow = len(existing) - self.max_sessions_per_chat
            if overflow > 0:
                for old in existing[:overflow]:
                    shutil.rmtree(old, ignore_errors=True)

    def _create_session(self, chat_id: str) -> Path:
        chat_dir = self.base_dir / str(chat_id)
        chat_dir.mkdir(parents=True, exist_ok=True)

        session_id = f"session-{datetime.now(tz=UTC).strftime('%Y%m%d-%H%M%S')}"
        session_dir = chat_dir / session_id
        turns_dir = session_dir / "turns"
        turns_dir.mkdir(parents=True, exist_ok=True)

        now_iso = datetime.now(tz=UTC).isoformat()
        meta = {
            "chat_id": str(chat_id),
            "session_id": session_id,
            "created_at": now_iso,
            "last_updated_at": now_iso,
            "status": "active",
        }

        (session_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (session_dir / "brief.md").write_text("", encoding="utf-8")
        (session_dir / "findings.json").write_text("[]", encoding="utf-8")
        (session_dir / "sources.json").write_text("[]", encoding="utf-8")

        self.cleanup_expired()
        return session_dir

    def list_sessions(self, chat_id: str) -> list[ResearchSessionRef]:
        """Return all sessions for a chat, oldest first."""
        chat_dir = self.base_dir / str(chat_id)
        if not chat_dir.exists() or not chat_dir.is_dir():
            return []
        sessions = sorted([d for d in chat_dir.iterdir() if d.is_dir()], key=lambda p: p.name)
        refs: list[ResearchSessionRef] = []
        for s in sessions:
            meta = self._read_json(s / "meta.json", {})
            refs.append(ResearchSessionRef(
                chat_id=str(chat_id),
                session_id=str(meta.get("session_id", s.name)),
                session_dir=s,
            ))
        return refs

    def get_active_session_id(self, chat_id: str) -> str | None:
        state = self._read_chat_state(chat_id)
        return state.get("active_session_id")

    def set_active_session_id(self, chat_id: str, session_id: str) -> bool:
        """Switch the active session. Returns False if session doesn't exist."""
        sessions = self.list_sessions(chat_id)
        if not any(s.session_id == session_id for s in sessions):
            return False
        state = self._read_chat_state(chat_id)
        state["active_session_id"] = session_id
        self._write_chat_state(chat_id, state)
        return True

    def _find_active_session(self, chat_id: str) -> Path | None:
        """Return the explicitly-selected active session, falling back to the latest."""
        chat_dir = self.base_dir / str(chat_id)
        if not chat_dir.exists() or not chat_dir.is_dir():
            return None

        sessions = sorted([d for d in chat_dir.iterdir() if d.is_dir()], key=lambda p: p.name)
        if not sessions:
            return None

        active_id = self.get_active_session_id(chat_id)
        if active_id:
            for s in sessions:
                meta = self._read_json(s / "meta.json", {})
                if meta.get("session_id") == active_id:
                    return s

        return sessions[-1]

    def _find_latest_session(self, chat_id: str) -> Path | None:
        return self._find_active_session(chat_id)

    def _read_chat_state(self, chat_id: str) -> dict:
        chat_dir = self.base_dir / str(chat_id)
        return self._read_json(chat_dir / "chat_state.json", {})

    def _write_chat_state(self, chat_id: str, state: dict) -> None:
        chat_dir = self.base_dir / str(chat_id)
        chat_dir.mkdir(parents=True, exist_ok=True)
        (chat_dir / "chat_state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _next_turn_index(self, session_dir: Path) -> int:
        turns_dir = session_dir / "turns"
        if not turns_dir.exists():
            return 1

        max_idx = 0
        for item in turns_dir.iterdir():
            match = re.match(r"^(\d+)_", item.name)
            if match:
                max_idx = max(max_idx, int(match.group(1)))
        return max_idx + 1

    def _touch_meta(self, session_dir: Path, status: str) -> None:
        meta_path = session_dir / "meta.json"
        meta = self._read_json(meta_path, {})
        meta["last_updated_at"] = datetime.now(tz=UTC).isoformat()
        meta["status"] = status
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_brief(self, assistant_text: str) -> str:
        text = (assistant_text or "").strip()
        if not text:
            return ""

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines[:12])

    def _extract_findings(self, assistant_text: str) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for raw_line in (assistant_text or "").splitlines():
            line = raw_line.strip(" -*\t")
            if not line:
                continue

            if "[CONFIRMED]" in line:
                status = "CONFIRMED"
            elif "[UNCERTAIN]" in line:
                status = "UNCERTAIN"
            elif "[NOT_FOUND]" in line:
                status = "NOT_FOUND"
            else:
                continue

            claim = re.sub(r"\[(?:CONFIRMED|UNCERTAIN|NOT_FOUND)\]", "", line).strip(" :-")
            findings.append({"claim": claim, "status": status, "source_ids": []})

        return findings

    def _extract_sources(self, assistant_text: str) -> list[dict[str, Any]]:
        urls = re.findall(r"https?://[^\s)\]>]+", assistant_text or "")
        seen: set[str] = set()
        results: list[dict[str, Any]] = []

        for index, url in enumerate(urls, start=1):
            normalized = url.rstrip(".,;")
            if normalized in seen:
                continue
            seen.add(normalized)
            results.append(
                {
                    "id": f"src-{index}",
                    "url": normalized,
                    "title": "",
                    "source_type": "web",
                    "fetched_at": datetime.now(tz=UTC).isoformat(),
                }
            )

        return results

    def _read_json(self, path: Path, fallback: Any) -> Any:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            calendar_logger.log_error(exc, f"research_context_store._read_json({path})")
        return fallback

    def _safe_read_text(self, path: Path) -> str:
        try:
            if path.exists():
                return path.read_text(encoding="utf-8")
        except Exception as exc:
            calendar_logger.log_error(exc, f"research_context_store._safe_read_text({path})")
        return ""

    def _parse_dt(self, value: str) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except Exception:
            return None
