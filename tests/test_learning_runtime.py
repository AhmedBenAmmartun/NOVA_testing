from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time

from nova_learning.runtime import LearningSessionRecorder
from nova_learning.store import NDJSONExperienceStore


class FakeSession:
    def __init__(self) -> None:
        self.handlers: dict[str, list] = {}

    def on(self, name: str):
        def decorate(fn):
            self.handlers.setdefault(name, []).append(fn)
            return fn
        return decorate

    def emit(self, name: str, event) -> None:
        for fn in self.handlers.get(name, []):
            fn(event)


@dataclass
class Event:
    item: object | None = None
    transcript: str = ""
    is_final: bool = False
    function_calls: list | None = None
    function_call_outputs: list | None = None
    error: object | None = None
    type: str = "test"


@dataclass
class Item:
    role: str
    text_content: str


@dataclass
class Call:
    name: str
    arguments: object
    call_id: str = "1"


@dataclass
class Output:
    is_error: bool = False
    call_id: str = "1"
    name: str = ""
    output: str = ""


def _wait_for_line(path: Path, timeout: float = 2.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size:
            lines = path.read_text(encoding="utf-8").splitlines()
            if lines:
                return json.loads(lines[-1])
        time.sleep(0.01)
    raise AssertionError(f"learning record was not written: {path}")


def test_disabled_recorder_attaches_nothing(tmp_path: Path) -> None:
    session = FakeSession()
    recorder = LearningSessionRecorder(
        enabled=False,
        store=NDJSONExperienceStore(tmp_path),
    )
    assert recorder.attach(session) is False
    assert session.handlers == {}


def test_records_voice_turn_tools_without_raw_utterance_or_outputs(tmp_path: Path) -> None:
    session = FakeSession()
    store = NDJSONExperienceStore(tmp_path)
    recorder = LearningSessionRecorder(
        enabled=True,
        store_utterances=False,
        store=store,
        route="gemini_realtime",
        model="test-model",
        strategy_versions={"learning_runtime": "v1"},
    )
    assert recorder.attach(session) is True

    secret_utterance = "my private lecture question should not be stored"
    session.emit("user_input_transcribed", Event(transcript=secret_utterance, is_final=True))
    session.emit("conversation_item_added", Event(item=Item("user", secret_utterance)))
    session.emit(
        "function_tools_executed",
        Event(
            function_calls=[
                Call(
                    "get_recent_class_context",
                    json.dumps(
                        {
                            "max_lines": 30,
                            "transcript": "PRIVATE CLASS TRANSCRIPT",
                            "api_key": "SECRET",
                            "path": r"C:\\Users\\ahmed\\private\\thing.txt",
                        }
                    ),
                )
            ],
            function_call_outputs=[Output(is_error=False, output="PRIVATE TOOL OUTPUT")],
        ),
    )
    session.emit("conversation_item_added", Event(item=Item("assistant", "answer")))

    record = _wait_for_line(store._daily_path())
    exp = record["experience"]
    serialized = json.dumps(record)

    assert exp["modality"] == "voice"
    assert exp["utterance_redacted"].startswith("<not stored; chars=")
    assert exp["route"] == "gemini_realtime"
    assert exp["model"] == "test-model"
    assert exp["outcome"] == "unknown"
    assert exp["outcome_source"] == "assistant_response"
    assert exp["tools"][0]["name"] == "get_recent_class_context"
    assert exp["tools"][0]["args"]["transcript"] == "<transcript redacted>"
    assert exp["tools"][0]["args"]["api_key"] == "<redacted>"
    assert exp["tools"][0]["args"]["path"] == "file:thing.txt"
    assert secret_utterance not in serialized
    assert "PRIVATE CLASS TRANSCRIPT" not in serialized
    assert "PRIVATE TOOL OUTPUT" not in serialized
    assert "SECRET" not in serialized


def test_verified_tool_error_marks_turn_failure(tmp_path: Path) -> None:
    session = FakeSession()
    store = NDJSONExperienceStore(tmp_path)
    recorder = LearningSessionRecorder(enabled=True, store=store)
    recorder.attach(session)

    session.emit("conversation_item_added", Event(item=Item("user", "open it")))
    session.emit(
        "function_tools_executed",
        Event(
            function_calls=[Call("open_app", '{"app":"Example"}')],
            function_call_outputs=[Output(is_error=True)],
        ),
    )
    session.emit("conversation_item_added", Event(item=Item("assistant", "I could not open it")))

    record = _wait_for_line(store._daily_path())
    exp = record["experience"]
    assert exp["outcome"] == "failure"
    assert exp["outcome_source"] == "verified_tool_error"
    assert exp["outcome_score"] == 1.0
    assert exp["tools"][0]["ok"] is False
    assert exp["tools"][0]["error"] == "tool_error"


def test_new_user_turn_preserves_superseded_turn_as_partial(tmp_path: Path) -> None:
    session = FakeSession()
    store = NDJSONExperienceStore(tmp_path)
    recorder = LearningSessionRecorder(enabled=True, store=store)
    recorder.attach(session)

    session.emit("conversation_item_added", Event(item=Item("user", "first")))
    session.emit("conversation_item_added", Event(item=Item("user", "second")))

    record = _wait_for_line(store._daily_path())
    exp = record["experience"]
    assert exp["outcome"] == "partial"
    assert exp["outcome_source"] == "superseded_by_user_turn"


class ExplodingStore:
    root = "exploding"

    def append_experience(self, _experience):
        raise OSError("disk unavailable")


def test_store_failure_is_fail_open() -> None:
    session = FakeSession()
    recorder = LearningSessionRecorder(enabled=True, store=ExplodingStore())  # type: ignore[arg-type]
    recorder.attach(session)

    session.emit("conversation_item_added", Event(item=Item("user", "hello")))
    # No exception may escape to the LiveKit session event emitter.
    session.emit("conversation_item_added", Event(item=Item("assistant", "hi")))
    time.sleep(0.05)


def test_path_redaction_is_idempotent() -> None:
    from nova_learning.redaction import redact

    once = redact({"path": r"C:\\Users\\ahmed\\private\\thing.txt"})
    twice = redact(once)
    assert once == {"path": "file:thing.txt"}
    assert twice == once


def test_disabled_default_store_does_not_create_data_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    session = FakeSession()
    recorder = LearningSessionRecorder(enabled=False)
    assert recorder.attach(session) is False
    assert not (tmp_path / "NOVA" / "learning" / "experience").exists()


def _wait_for_records(path: Path, count: int, timeout: float = 2.0) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size:
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if len(lines) >= count:
                return [json.loads(line) for line in lines]
        time.sleep(0.01)
    raise AssertionError(f"expected {count} learning records in {path}")


def test_verified_get_time_result_marks_success_and_infers_intent(tmp_path: Path) -> None:
    session = FakeSession()
    store = NDJSONExperienceStore(tmp_path)
    recorder = LearningSessionRecorder(enabled=True, store=store)
    recorder.attach(session)

    session.emit("conversation_item_added", Event(item=Item("user", "<noise>")))
    session.emit(
        "function_tools_executed",
        Event(
            function_calls=[Call("get_time", "{}")],
            function_call_outputs=[Output(is_error=False, output="The current time is 11:34 AM.")],
        ),
    )
    session.emit("conversation_item_added", Event(item=Item("assistant", "It's 11:34 AM.")))

    record = _wait_for_line(store._daily_path())
    exp = record["experience"]
    assert exp["outcome"] == "success"
    assert exp["outcome_source"] == "verified_tool_result:get_time"
    assert exp["outcome_score"] == 0.98
    assert exp["intent"] == "tool:get_time"
    assert exp["strategy_versions"]["outcome_evaluator"] == "v1"
    assert "The current time is 11:34 AM." not in json.dumps(record)


def test_class_start_needing_course_is_partial_not_success(tmp_path: Path) -> None:
    session = FakeSession()
    store = NDJSONExperienceStore(tmp_path)
    recorder = LearningSessionRecorder(enabled=True, store=store)
    recorder.attach(session)

    session.emit("conversation_item_added", Event(item=Item("user", "record class")))
    session.emit(
        "function_tools_executed",
        Event(
            function_calls=[Call("start_class_capture", "{}")],
            function_call_outputs=[Output(is_error=False, output="I can record class at any time. There isn't one scheduled right now, so tell me which class this is.")],
        ),
    )
    session.emit("conversation_item_added", Event(item=Item("assistant", "Which class is it?")))

    record = _wait_for_line(store._daily_path())
    exp = record["experience"]
    assert exp["tools"][0]["ok"] is True
    assert exp["outcome"] == "partial"
    assert exp["outcome_source"] == "verified_tool_result:needs_user_input"
    assert exp["intent"] == "tool:start_class_capture"


def test_class_start_active_is_verified_success(tmp_path: Path) -> None:
    session = FakeSession()
    store = NDJSONExperienceStore(tmp_path)
    recorder = LearningSessionRecorder(enabled=True, store=store)
    recorder.attach(session)

    session.emit("conversation_item_added", Event(item=Item("user", "start CEN4065")))
    session.emit(
        "function_tools_executed",
        Event(
            function_calls=[Call("start_class_capture", '{"course":"CEN4065"}')],
            function_call_outputs=[Output(is_error=False, output="Class recording is active for CEN4065 (explicit user request). Session: abc.")],
        ),
    )
    session.emit("conversation_item_added", Event(item=Item("assistant", "Recording started.")))

    record = _wait_for_line(store._daily_path())
    exp = record["experience"]
    assert exp["outcome"] == "success"
    assert exp["outcome_source"] == "verified_tool_result:class_active"
    assert exp["outcome_score"] == 1.0


def test_class_status_no_active_is_successful_status_query(tmp_path: Path) -> None:
    session = FakeSession()
    store = NDJSONExperienceStore(tmp_path)
    recorder = LearningSessionRecorder(enabled=True, store=store)
    recorder.attach(session)

    session.emit("conversation_item_added", Event(item=Item("user", "are you recording?")))
    session.emit(
        "function_tools_executed",
        Event(
            function_calls=[Call("get_class_capture_status", "{}")],
            function_call_outputs=[Output(is_error=False, output="No class recording is active.")],
        ),
    )
    session.emit("conversation_item_added", Event(item=Item("assistant", "No.")))

    record = _wait_for_line(store._daily_path())
    exp = record["experience"]
    assert exp["outcome"] == "success"
    assert exp["outcome_source"] == "verified_tool_result:class_status"


def test_strong_user_correction_appends_private_patch(tmp_path: Path) -> None:
    session = FakeSession()
    store = NDJSONExperienceStore(tmp_path)
    recorder = LearningSessionRecorder(enabled=True, store_utterances=False, store=store)
    recorder.attach(session)

    session.emit("conversation_item_added", Event(item=Item("user", "first request")))
    session.emit("conversation_item_added", Event(item=Item("assistant", "first answer")))
    first = _wait_for_line(store._daily_path())
    first_id = first["experience"]["id"]

    correction = "That's wrong, I said open Spotify"
    session.emit("conversation_item_added", Event(item=Item("user", correction)))
    session.emit("conversation_item_added", Event(item=Item("assistant", "Okay.")))

    records = _wait_for_records(store._daily_path(), 3)
    patches = [record for record in records if record["record_type"] == "patch"]
    assert patches
    patch = patches[0]
    assert patch["experience_id"] == first_id
    assert patch["changes"]["outcome"] == "failure"
    assert patch["changes"]["outcome_source"] == "user_correction"
    assert patch["changes"]["user_correction"] == "explicit_user_correction"
    assert correction not in json.dumps(records)
