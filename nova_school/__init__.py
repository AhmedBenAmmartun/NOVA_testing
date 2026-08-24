"""NOVA school/course intelligence.

This package owns course awareness and academic material organization.
It does NOT own microphone capture or lecture session lifecycle.
"""

from .organizer import Classification, OrganizeResult, SchoolMaterialOrganizer, classify_file
from .registry import CourseProfile, CourseRegistry, Meeting
from .resolver import resolve_current_course, resolve_course_override
from .vocabulary import course_stt_keyterms

__all__ = [
    "Classification",
    "CourseProfile",
    "CourseRegistry",
    "Meeting",
    "OrganizeResult",
    "SchoolMaterialOrganizer",
    "classify_file",
    "course_stt_keyterms",
    "resolve_course_override",
    "resolve_current_course",
]
