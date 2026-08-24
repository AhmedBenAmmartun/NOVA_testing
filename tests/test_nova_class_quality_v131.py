from __future__ import annotations

from pathlib import Path

from nova_capture.terminology import TerminologyInterpreter
from nova_core.configuration import ProviderConfiguration, ProviderName
from nova_core.provider_registry import create_provider_registry
from nova_school.context import CourseContextLibrary
from nova_school.registry import CourseProfile
from nova_school.vocabulary import course_stt_keyterms
from providers.groq_provider import GroqProvider


def test_groq_provider_is_registered(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "unit-test-key-not-secret")
    registry = create_provider_registry()
    assert registry.is_registered(ProviderName.GROQ)


def test_retired_groq_model_is_migrated(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "unit-test-key-not-secret")
    config = ProviderConfiguration(
        name=ProviderName.GROQ,
        model="llama-3.3-70b-versatile",
        enabled=True,
        api_key_environment_variable="GROQ_API_KEY",
        base_url="https://api.groq.com/openai/v1",
    )
    provider = GroqProvider(config)
    assert provider.model == "openai/gpt-oss-120b"
    assert provider.model_was_migrated is True


def test_cen4065_domain_terms_cover_real_stt_failures():
    course = CourseProfile(
        code="CEN4065",
        name="Software Architecture and Design",
        aliases=[],
        keywords=[],
        term="Fall 2026",
    )
    terms = course_stt_keyterms(course)
    lowered = {term.casefold() for term in terms}
    assert "cohesion" in lowered
    assert "coupling" in lowered
    assert "aggregation" in lowered
    assert "composition" in lowered
    assert len(terms) <= 100


def test_material_context_expands_keyterms(tmp_path: Path, monkeypatch):
    material = tmp_path / "architecture-notes.txt"
    material.write_text(
        "Repository pattern Repository pattern Dependency Injection Dependency Injection "
        "Domain Driven Design Domain Driven Design",
        encoding="utf-8",
    )
    library = CourseContextLibrary("CEN4065", session_path=tmp_path)
    monkeypatch.setattr(
        library,
        "_candidate_files",
        lambda: [(material, "course_material")],
    )
    terms = library.build_stt_keyterms(["cohesion", "coupling"], limit=100)
    lowered = {term.casefold() for term in terms}
    assert "repository" in lowered
    assert "dependency" in lowered
    assert len(terms) <= 100


def test_terminology_interpreter_repairs_observed_question_errors():
    interpreter = TerminologyInterpreter(
        ["aggregation", "composition", "cohesion", "coupling"]
    )
    result = interpreter.interpret(
        "what is the difference between aggression and compulsion?"
    )
    assert result.interpreted == (
        "what is the difference between aggregation and composition?"
    )
    assert result.changed is True
