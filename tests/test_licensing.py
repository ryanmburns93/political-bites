import itertools

import pytest

from political_bites.licensing import (
    LicenseTier,
    ReleaseMode,
    ReviewStatus,
    can_release_audio,
)


@pytest.mark.parametrize("tier", list(LicenseTier))
@pytest.mark.parametrize("mode", list(ReleaseMode))
@pytest.mark.parametrize("status", [ReviewStatus.PENDING, ReviewStatus.REJECTED])
def test_nothing_unapproved_is_ever_released(tier, mode, status):
    assert not can_release_audio(tier, status, mode, verified_a_minus=True)


@pytest.mark.parametrize("mode", [ReleaseMode.PUBLIC_UNMONETIZED, ReleaseMode.MONETIZED])
def test_tier_c_never_public(mode):
    assert not can_release_audio(LicenseTier.C, ReviewStatus.APPROVED, mode, verified_a_minus=True)


def test_tier_c_allowed_privately_when_approved():
    assert can_release_audio(LicenseTier.C, ReviewStatus.APPROVED, ReleaseMode.PRIVATE)


def test_tier_a_public_unmonetized_and_monetized():
    for mode in (ReleaseMode.PUBLIC_UNMONETIZED, ReleaseMode.MONETIZED):
        assert can_release_audio(LicenseTier.A, ReviewStatus.APPROVED, mode)


def test_tier_b_only_unmonetized():
    assert can_release_audio(LicenseTier.B, ReviewStatus.APPROVED, ReleaseMode.PUBLIC_UNMONETIZED)
    assert not can_release_audio(LicenseTier.B, ReviewStatus.APPROVED, ReleaseMode.MONETIZED)


def test_a_minus_requires_verification():
    args = (LicenseTier.A_MINUS, ReviewStatus.APPROVED, ReleaseMode.PUBLIC_UNMONETIZED)
    assert not can_release_audio(*args)
    assert can_release_audio(*args, verified_a_minus=True)


def test_full_matrix_is_deterministic():
    combos = itertools.product(LicenseTier, ReviewStatus, ReleaseMode)
    assert all(isinstance(can_release_audio(t, s, m), bool) for t, s, m in combos)
