from dataclasses import FrozenInstanceError

import pytest

from astrbot_plugin_bangumi.src.app import AppImages, AppResponse, AppText


def test_app_text_is_immutable_response_payload() -> None:
    response: AppResponse = AppText(text="hello")

    assert response == AppText(text="hello")
    with pytest.raises(FrozenInstanceError):
        response.text = "changed"


def test_app_images_normalizes_iterables_to_tuple() -> None:
    response: AppResponse = AppImages.from_iterable(["a", "b"])

    assert response == AppImages(base64_images=("a", "b"))
    assert AppImages.single("only") == AppImages(base64_images=("only",))
