from lmu_ep_client.registration_display import (
    private_registration_column,
    private_registration_marker,
)


def test_private_registration_falls_back_without_owner() -> None:
    reg = {"isPrivate": True, "ownerLmuDriverName": None}

    assert private_registration_marker(reg) == " [private]"
    assert private_registration_column(reg) == "yes"


def test_private_registration_treats_whitespace_owner_as_missing() -> None:
    reg = {"isPrivate": True, "ownerLmuDriverName": "   "}

    assert private_registration_marker(reg) == " [private]"
    assert private_registration_column(reg) == "yes"
