from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

HTML = (
    ROOT
    / "frontend"
    / "index.html"
).read_text(
    encoding="utf-8"
)

APP = (
    ROOT
    / "frontend"
    / "app.js"
).read_text(
    encoding="utf-8"
)

CSS = (
    ROOT
    / "frontend"
    / "donate.css"
).read_text(
    encoding="utf-8"
)

AURORA_SYMBOLS = (
    ROOT
    / "frontend"
    / "aurora-symbols.js"
).read_text(
    encoding="utf-8"
)


FUNCTION_PATTERN = re.compile(
    r"^(?:async\s+)?function\s+"
    r"([A-Za-z0-9_$]+)\s*\(",
    re.M,
)


def function(name):
    matches = list(
        FUNCTION_PATTERN.finditer(
            APP
        )
    )

    found = []

    for index, match in enumerate(
        matches
    ):
        if match.group(1) != name:
            continue

        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(APP)
        )

        found.append(
            APP[
                match.start():
                end
            ]
        )

    assert len(found) == 1

    return found[0]


def donate_html():
    start = HTML.index(
        'id="tab-donate"'
    )

    end = HTML.index(
        'id="tab-wallet"',
        start,
    )

    return HTML[
        start:end
    ]


def test_donate_is_public_top_level_navigation():
    nav_id = HTML.index(
        'id="donateNavItem"'
    )

    nav_start = HTML.rfind(
        "<button",
        0,
        nav_id,
    )

    assert nav_start >= 0

    nav_end = HTML.index(
        "</button>",
        nav_id,
    )

    nav = HTML[
        nav_start:
        nav_end
    ]

    assert (
        'id="donateNavItem"'
        in nav
    )

    assert (
        'data-tab="donate"'
        in nav
    )

    assert (
        'class="nav-item"'
        in nav
    )

    assert (
        "hidden"
        not in nav
    )

    assert (
        'id="tab-donate"'
        in HTML
    )


def test_donate_explains_fixed_destination_and_wallet_boundary():
    page = donate_html()

    assert (
        "EQTY DAO Market Making"
        in page
    )

    assert (
        "Fixed by the server"
        in page
    )

    assert (
        "Donation, not Wallet credit"
        in page
    )

    assert (
        "not credited"
        in page
    )

    assert (
        "connected Wallet account"
        in page
    )


def test_donate_does_not_add_attribution_yet():
    page = donate_html().lower()

    # Descriptive copy may mention that attribution or the
    # Donation Ledger is planned for a later milestone.
    # What must not exist in C2A is an attribution control,
    # donor identity field, or donor-attribution data hook.
    for token in (
        "telegram handle",
        "x handle",
        "donor username",
        "donor nickname",
        'id="donatedonor',
        'name="donor_',
        'data-donate-donor',
        'data-donor-',
    ):
        assert token not in page

    assert (
        "donation ledger"
        in page
    )

    assert (
        "will be added in a later milestone"
        in page
    )


def test_public_donate_uses_only_public_api_helper():
    sources = "\n".join(
        function(name)
        for name in (
            "loadDonateCatalog",
            "selectDonateCurrency",
            "selectDonateNetwork",
        )
    )

    assert (
        "adminApi("
        not in sources
    )

    assert (
        "api("
        in sources
    )

    for verb in (
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    ):
        assert (
            f"method: '{verb}'"
            not in sources
        )

        assert (
            f'method: "{verb}"'
            not in sources
        )


def test_donate_frontend_uses_exact_public_backend_contract():
    catalog = function(
        "loadDonateCatalog"
    )

    networks = function(
        "selectDonateCurrency"
    )

    destination = function(
        "selectDonateNetwork"
    )

    assert (
        "/api/donate/currencies"
        in catalog
    )

    assert (
        "/api/donate/${"
        in networks
    )

    assert (
        "}/networks"
        in networks
    )

    assert (
        "/api/donate/${"
        in destination
    )

    assert (
        "chain:"
        in destination
    )

    assert (
        "/api/me/deposit"
        not in (
            catalog
            + networks
            + destination
        )
    )


def test_donate_tab_is_not_auth_gated():
    switch = function(
        "switchTab"
    )

    assert (
        "donate: ['Donate'"
        in switch
    )

    assert (
        "target === 'donate'"
        in switch
    )

    auth_guard_match = re.search(
        r"\[\s*'wallet',\s*"
        r"'trading',\s*"
        r"'security'\s*\]"
        r"\.includes\(target\)",
        switch,
    )

    assert auth_guard_match

    assert (
        "'wallet', 'trading', "
        "'security', 'donate'"
        not in switch
    )


def test_global_account_selector_is_hidden_on_donate():
    switch = function(
        "switchTab"
    )

    visibility = switch[
        switch.index(
            "const globalAccountVisible"
        ):
        switch.index(
            "$$('.nav-item')",
        )
    ]

    assert "'donate'" in visibility


def test_donate_network_display_prefers_human_name():
    render = function(
        "renderDonateNetworks"
    )

    assert (
        "network.name"
        in render
    )

    assert (
        "network.name\n"
        "          || network.chain"
        in render
    )

    assert (
        "data-donate-chain"
        in render
    )

    # Provider chain ID is used internally for selection,
    # not deliberately printed as a user-facing subtitle.
    assert (
        "Gate deposit network"
        in render
    )


def test_donate_supports_address_qr_and_required_memo():
    page = donate_html()
    render = function(
        "renderDonateDetails"
    )

    for marker in (
        'id="donateQr"',
        'id="donateAddress"',
        'id="donateMemoBlock"',
        'id="donateContract"',
        'id="donateMinimum"',
        'id="donateConfirmations"',
    ):
        assert marker in page

    assert (
        "network.qr_svg_data_uri"
        in render
    )

    assert (
        "network.payment_id"
        in render
    )

    assert (
        "network.payment_name"
        in render
    )


def test_donate_uses_existing_deposit_visual_primitives():
    page = donate_html()

    for token in (
        "deposit-step",
        "deposit-option-list",
        "deposit-qr-card",
        "deposit-address-fields",
        "deposit-definition-list",
    ):
        assert token in page

    assert (
        ".donate-tab-panel"
        in CSS
    )

    assert (
        ".donate-wallet-warning"
        in CSS
    )


def test_aurora_symbols_cover_donate_assets_and_networks():
    for token in (
        "decorateDonateOptions",
        "decorateDonateFavorites",
        "decorateDonateResult",
        "#donateCurrencyList ",
        "[data-donate-currency]",
        "#donateNetworkList ",
        "[data-donate-chain]",
        "#donateSelectedAsset",
        "#donateSelectedNetwork",
    ):
        assert token in AURORA_SYMBOLS

    decorate_start = (
        AURORA_SYMBOLS.index(
            "function decorate()"
        )
    )

    decorate_end = (
        AURORA_SYMBOLS.index(
            "let scheduled",
            decorate_start,
        )
    )

    decorate = AURORA_SYMBOLS[
        decorate_start:
        decorate_end
    ]

    for call in (
        "decorateDonateOptions();",
        "decorateDonateFavorites();",
        "decorateDonateResult();",
    ):
        assert call in decorate


def test_donate_assets_are_cache_busted():
    assert (
        './donate.css?'
        'v=20261003-m414c2g-mobile-title-flex-v1'
        in HTML
    )

    assert (
        "m414c2a=20261003-donate-v1"
        in HTML
    )


def test_donate_mobile_visual_acceptance_contract():
    for token in (
        "body:has(#tab-donate.active) .topbar",
        "grid-template-columns:",
        "repeat(2, minmax(0, 1fr))",
        "flex: 0 0 auto !important",
        "align-self: stretch",
        ".topbar > div:first-child",
        "min-width: 0 !important",
        ".donate-workflow-header .mode-badge",
        "white-space: nowrap",
        "#donateNetworkList",
        "text-overflow: ellipsis",
        ".deposit-qr-card",
        ".button.secondary",
        "background: #effff8",
    ):
        assert token in CSS
