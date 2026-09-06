from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Mapping


class VerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class VerificationResult:
    contract: str
    status: VerificationStatus
    observation: str

    @property
    def ok(self) -> bool:
        return self.status is VerificationStatus.VERIFIED

    def render(self) -> str:
        return f"Verification: {self.status.value} — {self.contract}: {self.observation}"


def verified(contract: str, observation: str) -> VerificationResult:
    return VerificationResult(str(contract), VerificationStatus.VERIFIED, str(observation))


def failed(contract: str, observation: str) -> VerificationResult:
    return VerificationResult(str(contract), VerificationStatus.FAILED, str(observation))


def unknown(contract: str, observation: str) -> VerificationResult:
    return VerificationResult(str(contract), VerificationStatus.UNKNOWN, str(observation))


def verify_fields(
    contract: str,
    *,
    expected: Mapping[str, object],
    observed: Mapping[str, object] | None,
) -> VerificationResult:
    if observed is None:
        return unknown(contract, "post-condition could not be observed")

    mismatches: list[str] = []
    for key, expected_value in expected.items():
        observed_value = observed.get(key)
        if observed_value != expected_value:
            mismatches.append(
                f"{key} expected={expected_value!r} observed={observed_value!r}"
            )

    if mismatches:
        return failed(contract, "; ".join(mismatches)[:700])

    summary = ", ".join(f"{key}={observed.get(key)!r}" for key in expected)
    return verified(contract, summary[:700])


def verify_text_write(path: Path | str, expected_text: str) -> VerificationResult:
    target = Path(path)
    expected_bytes = str(expected_text).encode("utf-8")
    expected_hash = sha256(expected_bytes).hexdigest()

    try:
        if not target.exists():
            return failed("safe_text_write", f"path missing: {target}")
        if not target.is_file():
            return failed("safe_text_write", f"path is not a file: {target}")
        actual_bytes = target.read_bytes()
    except OSError as exc:
        return unknown(
            "safe_text_write",
            f"could not read post-write state: {type(exc).__name__}",
        )

    actual_hash = sha256(actual_bytes).hexdigest()
    if actual_bytes != expected_bytes:
        return failed(
            "safe_text_write",
            (
                f"path={target}; expected_bytes={len(expected_bytes)}; "
                f"observed_bytes={len(actual_bytes)}; "
                f"expected_sha256={expected_hash}; observed_sha256={actual_hash}"
            ),
        )

    return verified(
        "safe_text_write",
        f"path={target}; bytes={len(actual_bytes)}; sha256={actual_hash}",
    )
