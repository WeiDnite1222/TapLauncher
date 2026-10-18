from datetime import datetime, timezone

from manager.profile import ProfileSummary, sort_profile_summaries


def profile(
    profile_id: str,
    name: str,
    last_used: datetime | None = None,
) -> ProfileSummary:
    return ProfileSummary(
        display_name=name,
        id=profile_id,
        name=name,
        version_id="1.21.9",
        version_type="release",
        icon="",
        last_used=last_used,
    )


def test_sort_profiles_by_name() -> None:
    profiles = [profile("z", "Zulu"), profile("a", "alpha"), profile("b", "Beta")]

    ordered = sort_profile_summaries(profiles, "ByName")

    assert [item.id for item in ordered] == ["a", "b", "z"]


def test_sort_profiles_by_last_played() -> None:
    profiles = [
        profile("old", "Old", datetime(2025, 1, 1, tzinfo=timezone.utc)),
        profile("never", "Never"),
        profile("new", "New", datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ]

    ordered = sort_profile_summaries(profiles, "ByLastPlayed")

    assert [item.id for item in ordered] == ["new", "old", "never"]


def test_last_played_profile_id_is_first_when_timestamp_is_missing() -> None:
    profiles = [profile("first", "First"), profile("current", "Current")]

    ordered = sort_profile_summaries(profiles, "ByLastPlayed", "current")

    assert [item.id for item in ordered] == ["current", "first"]


def test_unknown_sorting_preserves_file_order() -> None:
    profiles = [profile("b", "Beta"), profile("a", "Alpha")]

    ordered = sort_profile_summaries(profiles, "FutureSortingMode")

    assert [item.id for item in ordered] == ["b", "a"]
