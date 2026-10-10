from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CSS = (
    ROOT
    / "frontend"
    / "aurora-transfer.css"
).read_text(
    encoding="utf-8"
)

HTML = (
    ROOT
    / "frontend"
    / "index.html"
).read_text(
    encoding="utf-8"
)


def c1_block():
    marker = (
        "/* M4.17C1 — INTERNAL DONATION TABLET POLISH */"
    )

    assert CSS.count(
        marker
    ) == 1

    return CSS[
        CSS.index(
            marker
        ):
    ]


def test_donation_checkbox_is_not_a_full_transfer_field():
    block = c1_block()

    assert (
        "label.treasury-user-transfer-donation-option"
        in block
    )

    assert (
        '> input[type="checkbox"]'
        in block
    )

    for token in (
        "width: 18px !important;",
        "min-width: 18px !important;",
        "height: 18px !important;",
        "min-height: 18px !important;",
        "padding: 0 !important;",
        "appearance: auto;",
        "accent-color: #52e8b7;",
    ):
        assert token in block


def test_tablet_primary_transfer_fields_are_three_equal_columns():
    block = c1_block()

    assert "(min-width: 721px)" in block
    assert "(max-width: 1320px)" in block

    assert (
        "repeat(\n"
        "        3,\n"
        "        minmax(0, 1fr)\n"
        "      )"
        in block
    )

    assert "height: 44px;" in block
    assert "min-height: 44px;" in block
    assert "max-height: 44px;" in block


def test_tablet_asset_symbol_is_centred_in_common_control_height():
    block = c1_block()

    assert (
        ".aurora-select-symbol-host"
        in block
    )

    assert "bottom: 13px;" in block

    assert (
        "--aurora-symbol-size: 18px;"
        in block
    )

    assert (
        "padding-left: 42px !important;"
        in block
    )


def test_tablet_amount_control_is_visually_reduced():
    block = c1_block()

    assert (
        "#treasuryUserTransferAmount"
        in block
    )

    assert "font-size: .92rem;" in block
    assert "font-weight: 650;" in block


def test_c1_is_presentation_only():
    block = c1_block()

    forbidden = (
        "fetch(",
        "adminApi(",
        "GateClient",
        "/api/",
        "localStorage",
        "sessionStorage",
        "zolnode",
    )

    for token in forbidden:
        assert token not in block


def test_aurora_transfer_css_has_c1_cache_buster():
    assert (
        "./aurora-transfer.css?"
        "v=20260906-aurora-a7c94-v1"
        "&amp;m417c1="
        "20261010-internal-donation-tablet-polish-v1"
        in HTML
    )
