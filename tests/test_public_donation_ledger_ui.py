from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

HTML = (
    ROOT / "frontend" / "index.html"
).read_text(
    encoding="utf-8"
)

APP = (
    ROOT / "frontend" / "app.js"
).read_text(
    encoding="utf-8"
)

DONATE_CSS = (
    ROOT / "frontend" / "donate.css"
).read_text(
    encoding="utf-8"
)

AURORA_CSS = (
    ROOT / "frontend" / "aurora-donate.css"
).read_text(
    encoding="utf-8"
)

SYMBOLS = (
    ROOT / "frontend" / "aurora-symbols.js"
).read_text(
    encoding="utf-8"
)


FUNCTION_PATTERN = re.compile(
    r"^\s*(?:async\s+)?function\s+"
    r"([A-Za-z0-9_$]+)\s*\(",
    re.M,
)


def function(
    source,
    name,
):
    matches = list(
        FUNCTION_PATTERN.finditer(
            source
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
            else len(source)
        )

        found.append(
            source[
                match.start():
                end
            ]
        )

    assert len(found) == 1

    return found[0]


def test_public_donation_ledger_surface_exists():
    for identifier in (
        "donateLedgerTitle",
        "donateLedgerRefresh",
        "donateLedgerCount",
        "donateLedgerTotals",
        "donateLedgerStatus",
        "donateLedgerList",
    ):
        assert (
            f'id="{identifier}"'
            in HTML
        )

    normalized = " ".join(
        HTML.lower().split()
    )

    assert "donation ledger" in normalized
    assert "confirmed donations" in normalized
    assert "confirmed totals" in normalized
    assert "self-declared" in normalized


def test_public_ledger_loader_is_anonymous_read_only_api():
    loader = function(
        APP,
        "loadDonateLedger",
    )

    assert (
        "'/api/donate/ledger?limit=50&offset=0'"
        in loader
    )

    assert "api(" in loader
    assert "adminApi(" not in loader

    for forbidden in (
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "GateClient",
        "claim_token",
    ):
        assert forbidden not in loader


def test_public_ledger_renderer_uses_public_projection_only():
    renderer = function(
        APP,
        "renderDonateLedger",
    )

    for token in (
        "real_event_count",
        "real_totals_by_currency",
        "payload?.items",
        "donationLedgerSourceLabel(",
        "occurred_at",
        "item?.attribution",
        "data-donation-event-id",
    ):
        assert token in renderer

    for private_field in (
        "request_id",
        "source_key",
        "source_account_id",
        "destination_account_id",
        "username",
        "gate_transfer_id",
        "updated_by",
    ):
        assert private_field not in renderer


def test_public_ledger_supports_all_attribution_modes():
    attribution = function(
        APP,
        "donationLedgerAttributionMarkup",
    )

    for mode in (
        "nickname",
        "telegram",
        "x",
        "telegram_x",
        "Anonymous",
    ):
        assert mode in attribution

    social = function(
        APP,
        "donationLedgerSocialLink",
    )

    assert "https://t.me/" in social
    assert "https://x.com/" in social
    assert 'rel="noopener noreferrer"' in social
    assert 'target="_blank"' in social


def test_public_ledger_labels_internal_and_onchain_sources():
    source = function(
        APP,
        "donationLedgerSourceLabel",
    )

    assert "item?.source_type" in source
    assert "item?.chain" in source

    assert (
        "sourceType === 'internal_transfer'"
        in source
    )

    assert "Internal donation" in source

    assert (
        "sourceType === 'external_deposit'"
        in source
    )

    assert "On-chain" in source


def test_donate_tab_and_refresh_load_public_ledger():
    assert (
        "void loadDonateLedger();"
        in APP
    )

    assert (
        "$('#donateLedgerRefresh')?.addEventListener("
        in APP
    )

    assert (
        "force: true"
        in APP
    )


def test_public_ledger_has_shared_and_aurora_responsive_styles():
    for token in (
        "M4.17E1 — PUBLIC DONATION LEDGER",
        ".donate-ledger-panel",
        ".donate-ledger-summary",
        ".donate-ledger-entry",
        ".donate-ledger-social",
        "@media (max-width: 720px)",
    ):
        assert token in DONATE_CSS

    for token in (
        "M4.17E1 — AURORA PUBLIC DONATION LEDGER",
        ".donate-ledger-panel",
        ".donate-ledger-entry",
        ".donate-ledger-social",
        "@media (max-width: 900px)",
        "@media (max-width: 700px)",
    ):
        assert token in AURORA_CSS


def test_aurora_symbols_decorate_public_ledger_assets():
    decorator = function(
        SYMBOLS,
        "decorateDonateLedger",
    )

    assert (
        "data-donate-ledger-asset"
        in decorator
    )

    assert "replaceMark(" in decorator
    assert "'asset'" in decorator

    assert (
        "decorateDonateLedger();"
        in SYMBOLS
    )


def test_m417e1_assets_are_cache_busted():
    marker = (
        "m417e1=20261010-public-ledger-ui-v1"
    )

    assert HTML.count(marker) == 4

    for asset in (
        "./donate.css?",
        "./aurora-donate.css?",
        "./aurora-symbols.js?",
        "./app.js?",
    ):
        assert asset in HTML
