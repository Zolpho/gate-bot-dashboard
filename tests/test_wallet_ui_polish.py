from pathlib import Path


HTML = Path(
    "frontend/index.html"
).read_text(
    encoding="utf-8"
)

APP = Path(
    "frontend/app.js"
).read_text(
    encoding="utf-8"
)

BALANCE_CSS = Path(
    "frontend/private-balance.css"
).read_text(
    encoding="utf-8"
)

DEPOSIT_CSS = Path(
    "frontend/deposit-history.css"
).read_text(
    encoding="utf-8"
)


def test_wallet_balance_assets_are_versioned():
    assert (
        "./private-balance.css?"
        "v=20260823-wallet-summary-v1"
        in HTML
    )

    assert (
        "./deposit-history.css?"
        "v=20260823-wallet-summary-v1"
        in HTML
    )

    assert (
        "./app.js?"
        "v=20260823-wallet-summary-v1"
        in HTML
    )


def test_wallet_balance_panel_is_compact():
    assert (
        "/* 3J17 Wallet balance polish v1 */"
        in BALANCE_CSS
    )

    for token in (
        "min-height: 88px;",
        "padding: 10px 11px;",
        "font-variant-numeric:",
        "tabular-nums;",
    ):
        assert token in BALANCE_CSS


def test_wallet_disclosure_has_custom_focus_state():
    assert (
        ".private-assets-details summary:focus-visible"
        in BALANCE_CSS
    )

    assert "outline: none;" in BALANCE_CSS

    assert (
        "rgba(23, 211, 154, .30)"
        in BALANCE_CSS
    )


def test_wallet_deposit_amount_uses_asset_formatter():
    start = APP.index(
        "function renderDepositHistory(payload)"
    )

    end = APP.index(
        "\nasync function loadDepositHistory",
        start,
    )

    renderer = APP[start:end]

    assert (
        "fmtAssetQuantity(item.amount)"
        in renderer
    )

    assert (
        renderer.count(
            "fmtAssetQuantity(item.amount)"
        )
        == 1
    )


def test_wallet_deposit_history_is_compact():
    assert (
        "/* 3J17 Wallet deposit history polish v1 */"
        in DEPOSIT_CSS
    )

    for token in (
        "min-height: 30px;",
        "font-size: .75rem;",
        "font-variant-numeric:",
        "max-width: 165px;",
    ):
        assert token in DEPOSIT_CSS


def test_wallet_mobile_layout_is_preserved():
    assert (
        "@media (max-width: 560px)"
        in BALANCE_CSS
    )

    assert (
        "grid-template-columns: 1fr;"
        in BALANCE_CSS
    )

    assert (
        "@media (max-width: 760px)"
        in DEPOSIT_CSS
    )
