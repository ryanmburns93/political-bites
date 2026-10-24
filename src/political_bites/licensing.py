"""License tiers, release modes, review states, and the release gate.

The gate is the single place that decides whether a clip's audio may leave the
private database. Keep it strict and well tested.
"""

from __future__ import annotations

from enum import StrEnum


class LicenseTier(StrEnum):
    A = "A"  # House/Senate floor proceedings (public domain)
    A_MINUS = "A-"  # other official federal sources; verify per source
    B = "B"  # C-SPAN-produced; non-commercial with attribution
    C = "C"  # network/cable/social; copyrighted, metadata + links only


class ReleaseMode(StrEnum):
    PRIVATE = "private"
    PUBLIC_UNMONETIZED = "public_unmonetized"
    MONETIZED = "monetized"  # out of scope; requires legal review


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# Tiers whose *audio* may be hosted publicly, per release mode.
_HOSTABLE: dict[ReleaseMode, frozenset[LicenseTier]] = {
    ReleaseMode.PRIVATE: frozenset(LicenseTier),
    ReleaseMode.PUBLIC_UNMONETIZED: frozenset({LicenseTier.A, LicenseTier.A_MINUS, LicenseTier.B}),
    ReleaseMode.MONETIZED: frozenset({LicenseTier.A}),
}


def can_release_audio(
    tier: LicenseTier,
    review_status: ReviewStatus,
    mode: ReleaseMode,
    *,
    verified_a_minus: bool = False,
) -> bool:
    """Return True only if a clip's audio may be exported/hosted in ``mode``.

    - Nothing is released without a human approval.
    - Tier C never leaves the private database as audio.
    - Tier A- must have been verified per source before public release.
    """
    if review_status is not ReviewStatus.APPROVED:
        return False
    if mode is ReleaseMode.PRIVATE:
        return True
    if tier not in _HOSTABLE[mode]:
        return False
    if tier is LicenseTier.A_MINUS and not verified_a_minus:
        return False
    return True
