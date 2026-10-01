from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

APP = (
    ROOT
    / "frontend"
    / "app.js"
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


def _function(
    name: str,
    next_name: str,
) -> str:
    start = APP.index(
        f"function {name}("
    )

    end = APP.index(
        f"\n\nfunction {next_name}(",
        start,
    )

    return APP[
        start:end
    ]


def test_apr_has_seven_day_minimum_runtime():
    assert (
        "const ANNUALIZED_APR_MIN_RUNTIME_SECONDS"
        in APP
    )

    assert (
        "7 * 24 * 60 * 60"
        in APP
    )


def test_apr_helper_rejects_short_runtime():
    block = _function(
        "annualizedAprPct",
        "fmtDate",
    )

    assert (
        "seconds < ANNUALIZED_APR_MIN_RUNTIME_SECONDS"
        in block
    )

    assert (
        "365 * 24 * 60 * 60 / seconds"
        in block
    )


def test_short_runtime_has_clear_user_message():
    assert (
        "const annualizedAprDisplay"
        in APP
    )

    assert (
        "'After 7d'"
        in APP
    )

    assert (
        "'Annualized APR'"
        in APP
    )


def test_apr_card_uses_guarded_display_value():
    annualized_card = (
        "    [\n"
        "      'Annualized APR',\n"
        "      annualizedAprDisplay,\n"
        "      annualizedApr,\n"
        "    ],"
    )

    assert annualized_card in APP


def test_roi_remains_independent_of_apr_window():
    roi_card = (
        "    [\n"
        "      'ROI',\n"
        "      fmtRatioPct(rate),\n"
        "      rate,\n"
        "    ],"
    )

    assert roi_card in APP


def test_apr_is_not_artificially_capped():
    block = _function(
        "annualizedAprPct",
        "fmtDate",
    )

    assert "Math.min" not in block
    assert "Math.max" not in block
    assert "clamp" not in block.lower()


def test_missing_runtime_does_not_claim_seven_day_wait():
    assert (
        "annualizedAprRuntimeSeconds !== null"
        in APP
    )

    assert (
        "annualizedAprRuntimeSeconds > 0"
        in APP
    )


def test_m48_cache_bust_is_scoped_to_app_script():
    marker = (
        "m48a="
        "20261001-apr-min-window-v1"
    )

    assert HTML.count(
        marker
    ) == 1

    app_tag_start = HTML.index(
        'src="./app.js?'
    )

    app_tag_end = HTML.index(
        '"',
        app_tag_start + len(
            'src="'
        ),
    )

    app_src = HTML[
        app_tag_start:
        app_tag_end
    ]

    assert marker in app_src
