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
        "v=20260823-wallet-card-depth-v1"
        in HTML
    )

    assert (
        "./deposit-history.css?"
        "v=20260823-wallet-summary-v1"
        in HTML
    )

    assert (
        './app.js?v=20260830-withdraw-destination-label-v1'
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

def test_wallet_hides_internal_quant_terminology():
    assert (
        "Gate quant account"
        not in HTML
    )

    assert (
        "quant-account value"
        not in HTML
    )

    assert (
        "Gate bot funds"
        in HTML
    )

    assert (
        "Funds allocated to Gate bots are shown "
        "separately and are not counted twice."
        in HTML
    )

    assert (
        "function formatPrivateAccountType(value)"
        in APP
    )

    start = APP.index(
        "function formatPrivateAccountType(value)"
    )

    end = APP.index(
        "\nfunction renderPrivateBalance()",
        start,
    )

    formatter = APP[start:end]

    assert (
        "=== 'quant'"
        in formatter
    )

    assert (
        "? 'bots'"
        in formatter
    )

    renderer_start = APP.index(
        "function renderPrivateBalance()"
    )

    renderer_end = APP.index(
        "\nasync function loadPrivateBalance",
        renderer_start,
    )

    renderer = APP[
        renderer_start:renderer_end
    ]

    assert (
        "formatPrivateAccountType("
        "item.account_type"
        ")"
        in renderer
    )


def test_wallet_internal_quant_contract_is_preserved():
    assert "data.quant_value" in APP
    assert "#privateQuantValue" in APP
    assert "#privateQuantNote" in APP

def test_wallet_balance_cards_have_restrained_depth():
    assert (
        "/* 3J17 Wallet balance card depth v1 */"
        in BALANCE_CSS
    )

    for token in (
        "box-shadow:",
        "var(--shadow-sm);",
        "transform:",
        "translateY(-1px);",
        "border-color .16s ease",
    ):
        assert token in BALANCE_CSS


def test_wallet_balance_cards_do_not_imply_clickability():
    depth_start = BALANCE_CSS.index(
        "/* 3J17 Wallet balance card depth v1 */"
    )

    depth_css = BALANCE_CSS[depth_start:]

    assert "cursor: pointer" not in depth_css


def test_wallet_total_card_remains_emphasized():
    depth_start = BALANCE_CSS.index(
        "/* 3J17 Wallet balance card depth v1 */"
    )

    depth_css = BALANCE_CSS[depth_start:]

    assert (
        ".private-balance-card:first-child"
        in depth_css
    )

    assert (
        "rgba(23, 211, 154, .34)"
        in depth_css
    )


def test_wallet_card_motion_respects_reduced_motion():
    assert (
        "@media (prefers-reduced-motion: reduce)"
        in BALANCE_CSS
    )

    assert "transition: none;" in BALANCE_CSS
