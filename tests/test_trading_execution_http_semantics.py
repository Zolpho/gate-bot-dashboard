from types import SimpleNamespace

import pytest

import app.trading_execution as execution


@pytest.mark.parametrize(
    "status_code",
    [
        408,
        409,
        425,
        429,
    ],
)
def test_ambiguous_gate_write_status_is_not_definitive(
    status_code,
):
    exc = SimpleNamespace(
        status_code=status_code,
    )

    assert (
        execution
        ._definitive_gate_rejection(exc)
        is False
    )


@pytest.mark.parametrize(
    "status_code",
    [
        400,
        401,
        403,
        404,
        422,
    ],
)
def test_normal_4xx_gate_rejection_is_definitive(
    status_code,
):
    exc = SimpleNamespace(
        status_code=status_code,
    )

    assert (
        execution
        ._definitive_gate_rejection(exc)
        is True
    )


def test_missing_gate_status_is_not_definitive():
    exc = SimpleNamespace(
        status_code=None,
    )

    assert (
        execution
        ._definitive_gate_rejection(exc)
        is False
    )


def test_required_ambiguous_status_set_is_complete():
    expected = {
        408,
        409,
        425,
        429,
    }

    actual = set(
        execution
        ._AMBIGUOUS_HTTP_STATUS_CODES
    )

    assert expected <= actual
