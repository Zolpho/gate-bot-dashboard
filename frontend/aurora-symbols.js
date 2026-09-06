(() => {
  'use strict';

  if (
    document.documentElement.dataset.dashboardUi
    !== 'aurora'
  ) {
    return;
  }

(() => {
  'use strict';

  const ASSET_ICONS = {
    BTC: 'bitcoin.svg',
    ETH: 'ethereum.svg',
    WETH: 'ethereum.svg',
    USDT: 'tether.svg',
    USDC: 'usdc.svg',
    SOL: 'solana.svg',
    BNB: 'bnbchain.svg',
    MATIC: 'polygon.svg',
    POL: 'polygon.svg',
    AVAX: 'avalanche.svg',
    TRX: 'tron.svg',
    TON: 'ton.svg',
    APT: 'aptos.svg',
    ARB: 'arbitrum.svg',
    OP: 'optimism.svg',
    EQTY: 'eqty.svg',
    XPL: 'plasma.svg',
    // A7C45 — exact-address verified Tier-A token artwork.
    ACN1: 'tokens/acn1.png',
    AIGENSYN: 'tokens/aigensyn.png',
    ATEAM: 'tokens/ateam.jpg',
    BABYSHARK: 'tokens/babyshark.jpg',
    BEEFI: 'tokens/beefi.png',
    BIFIF: 'tokens/bifif.png',
    BIGPUMP: 'tokens/bigpump.jpg',
    BITBOARD: 'tokens/bitboard.png',
    CROSS: 'tokens/cross.png',
    CYRUS: 'tokens/cyrus.png',
    DOGNFT: 'tokens/dognft.png',
    EDGEX: 'tokens/edgex.jpg',
    ENERGYWEB: 'tokens/energyweb.png',
    HOLDSTATION: 'tokens/holdstation.png',
    MAG7SSI: 'tokens/mag7ssi.png',
    MART: 'tokens/mart.jpg',
    MILADYCULT: 'tokens/miladycult.jpg',
    OPN1: 'tokens/opn1.png',
    P00LS: 'tokens/p00ls.png',
    PROSPER: 'tokens/prosper.png',
    REKTCOIN: 'tokens/rektcoin.png',
    SOPHIA: 'tokens/sophia.png',
    SUPERFORM: 'tokens/superform.png',
    UNION: 'tokens/union.png',
    XDATAV1: 'tokens/xdatav1.png',
    XRWA: 'tokens/xrwa.png',

  };

  const NETWORK_ALIASES = [
    [
      /^(ETH|ETHEREUM|ERC20|ETHEREUMERC20)$/i,
      'ethereum.svg',
    ],
    [
      /^(BSC|BNB|BNBCHAIN|BEP20|BNBSMARTCHAIN.*)$/i,
      'bnbchain.svg',
    ],
    [
      /^(SOL|SOLANA)$/i,
      'solana.svg',
    ],
    [
      /^(BASE|BASEEVM|BASE.*)$/i,
      'base.svg',
    ],
    [
      /^(ARB|ARBITRUM|ARBEVM|ARBITRUMONE.*)$/i,
      'arbitrum.svg',
    ],
    [
      /^(OP|OPETH|OPTIMISM|OPTIMISMEVM.*)$/i,
      'optimism.svg',
    ],
    [
      /^(MATIC|POL|POLYGON|POLYGONEVM.*)$/i,
      'polygon.svg',
    ],
    [
      /^(AVAX.*|AVALANCHE.*)$/i,
      'avalanche.svg',
    ],
    [
      /^(TRX|TRON|TRC20|TRONTRC20)$/i,
      'tron.svg',
    ],
    [
      /^(TON|THEOPENNETWORK.*)$/i,
      'ton.svg',
    ],
    [
      /^(APT|APTOS.*)$/i,
      'aptos.svg',
    ],
    [
      /^(XPL|PLASMA.*)$/i,
      'plasma.svg',
    ],
  ];

  const rootPath =
    './assets/symbols/';

  const normalized = value => (
    String(value || '')
      .trim()
      .toUpperCase()
      .replace(/[\s_().:/-]+/g, '')
  );

  function assetIcon(symbol) {
    const key = String(
      symbol || ''
    )
      .trim()
      .toUpperCase();

    return ASSET_ICONS[key] || '';
  }

  function networkIcon(
    chain,
    label = '',
  ) {
    const candidates = [
      normalized(chain),
      normalized(label),
    ].filter(Boolean);

    for (
      const [pattern, icon]
      of NETWORK_ALIASES
    ) {
      if (
        candidates.some(
          value => pattern.test(value)
        )
      ) {
        return icon;
      }
    }

    return '';
  }

  function fallbackLabel(value) {
    const text = String(
      value || '?'
    )
      .trim()
      .toUpperCase();

    return (
      text.slice(0, 3)
      || '?'
    );
  }

  function makeSymbol(
    kind,
    value,
    label = '',
  ) {
    const icon = (
      kind === 'network'
        ? networkIcon(
            value,
            label,
          )
        : assetIcon(value)
    );

    const symbol = document.createElement(
      'span'
    );

    symbol.className =
      'aurora-symbol';

    symbol.dataset.auroraSymbolKind =
      kind;

    symbol.dataset.auroraSymbolValue =
      String(value || '');

    symbol.setAttribute(
      'aria-hidden',
      'true',
    );

    if (icon) {
      const image =
        document.createElement('img');

      image.src =
        rootPath + icon;

      image.alt = '';

      image.loading = 'eager';

      image.decoding = 'async';

      image.setAttribute(
        'aria-hidden',
        'true',
      );

      image.addEventListener(
        'error',
        () => {
          symbol.textContent = '';

          const fallback =
            document.createElement(
              'span'
            );

          fallback.className =
            'aurora-symbol-fallback';

          fallback.textContent =
            fallbackLabel(
              value || label
            );

          symbol.append(
            fallback
          );
        },
        {
          once: true,
        },
      );

      symbol.append(image);

      return symbol;
    }

    const fallback =
      document.createElement(
        'span'
      );

    fallback.className =
      'aurora-symbol-fallback';

    fallback.textContent =
      fallbackLabel(
        value || label
      );

    symbol.append(fallback);

    return symbol;
  }

  function prependSymbol(
    element,
    kind,
    value,
    label = '',
    extraClass = '',
  ) {
    if (!element || !value) {
      return;
    }

    const current =
      element.querySelector(
        ':scope > .aurora-symbol'
      );

    const currentKind =
      current?.dataset
        .auroraSymbolKind || '';

    const currentValue =
      current?.dataset
        .auroraSymbolValue || '';

    if (
      current
      && currentKind === kind
      && currentValue
        === String(value)
    ) {
      return;
    }

    current?.remove();

    element.prepend(
      makeSymbol(
        kind,
        value,
        label,
      )
    );

    element.classList.add(
      'aurora-symbol-inline'
    );

    if (extraClass) {
      element.classList.add(
        extraClass
      );
    }
  }

  function replaceMark(
    host,
    kind,
    value,
    label = '',
  ) {
    if (!host || !value) {
      return;
    }

    const current =
      host.querySelector(
        ':scope > .aurora-symbol'
      );

    if (
      current
      && current.dataset
        .auroraSymbolKind === kind
      && current.dataset
        .auroraSymbolValue
        === String(value)
    ) {
      return;
    }

    host.textContent = '';

    host.append(
      makeSymbol(
        kind,
        value,
        label,
      )
    );

    host.classList.add(
      'aurora-symbol-host'
    );
  }

  function decorateDepositOptions() {
    document.querySelectorAll(
      '#depositCurrencyList '
      + '[data-deposit-currency]'
    ).forEach(button => {
      const symbol =
        button.dataset
          .depositCurrency;

      const host =
        button.querySelector(
          '.deposit-coin-mark'
        );

      replaceMark(
        host,
        'asset',
        symbol,
      );
    });

    document.querySelectorAll(
      '#depositNetworkList '
      + '[data-deposit-chain]'
    ).forEach(button => {
      const chain =
        button.dataset
          .depositChain;

      const label =
        button.querySelector(
          '.deposit-option-main strong'
        )?.textContent
        || chain;

      const host =
        button.querySelector(
          '.deposit-coin-mark'
        );

      replaceMark(
        host,
        'network',
        chain,
        label,
      );
    });
  }

  function decorateDepositFavorites() {
    document.querySelectorAll(
      '#depositFavorites '
      + '[data-deposit-currency]'
    ).forEach(button => {
      const symbol =
        button.dataset
          .depositCurrency;

      prependSymbol(
        button,
        'asset',
        symbol,
      );
    });
  }

  function decorateDepositResult() {
    const asset =
      document.querySelector(
        '#depositSelectedAsset'
      );

    const assetText =
      asset?.textContent
        ?.trim() || '';

    if (assetText) {
      prependSymbol(
        asset,
        'asset',
        assetText,
      );
    }

    const activeNetwork =
      document.querySelector(
        '#depositNetworkList '
        + '[data-deposit-chain].active'
      );

    const chain =
      activeNetwork?.dataset
        .depositChain || '';

    const networkLabel =
      document.querySelector(
        '#depositSelectedNetwork'
      );

    const label =
      networkLabel?.textContent
        ?.trim() || '';

    if (
      networkLabel
      && (chain || label)
    ) {
      prependSymbol(
        networkLabel,
        'network',
        chain || label,
        label,
      );
    }
  }

  function decorateDepositHistory() {
    document.querySelectorAll(
      '#depositHistoryBody tr'
    ).forEach(row => {
      const cells =
        row.querySelectorAll('td');

      if (cells.length < 3) {
        return;
      }

      const asset =
        cells[1].querySelector(
          'strong'
        );

      const currency =
        asset?.textContent
          ?.trim() || '';

      if (currency) {
        prependSymbol(
          asset,
          'asset',
          currency,
        );
      }

      const chainCell =
        cells[2];

      const chain =
        chainCell?.textContent
          ?.trim() || '';

      if (
        chain
        && chain !== '—'
      ) {
        prependSymbol(
          chainCell,
          'network',
          chain,
          chain,
          'aurora-network-symbol-inline',
        );
      }
    });
  }

  function decorateBalance() {
    prependSymbol(
      document.querySelector(
        '#privateUsdtTotal'
      ),
      'asset',
      'USDT',
    );

    prependSymbol(
      document.querySelector(
        '#privateEqtyTotal'
      ),
      'asset',
      'EQTY',
    );

    document.querySelectorAll(
      '#privateAssetsBody tr'
    ).forEach(row => {
      const asset =
        row.querySelector(
          'td:first-child strong'
        );

      const currency =
        asset?.textContent
          ?.trim() || '';

      if (currency) {
        prependSymbol(
          asset,
          'asset',
          currency,
        );
      }
    });
  }

  /*
   * Bots market artwork is presentation-only.
   *
   * app.js remains authoritative for table rows. Whenever
   * it replaces either tbody, the existing MutationObserver
   * schedules this decorator again.
   */
  function splitBotMarketAssets(value) {
    const market = String(
      value || ''
    )
      .trim();

    if (!market) {
      return [
        '',
        '',
      ];
    }

    for (
      const separator
      of [
        '_',
        '/',
        '-',
      ]
    ) {
      const index =
        market.lastIndexOf(
          separator
        );

      if (
        index > 0
        && index < market.length - 1
      ) {
        return [
          market
            .slice(
              0,
              index
            )
            .trim(),
          market
            .slice(
              index + 1
            )
            .trim(),
        ];
      }
    }

    return [
      market,
      '',
    ];
  }


  function decorateBotsMarkets() {
    document.querySelectorAll(
      '#botsTableBody '
      + '.strategy-cell small, '
      + '#archivedBotsTableBody '
      + '.strategy-cell small'
    ).forEach(label => {
      const storedMarket = String(
        label.dataset
          .auroraMarketValue
        || ''
      ).trim();

      const renderedText = String(
        label.textContent || ''
      );

      const market = (
        storedMarket
        || renderedText
          .split('·')[0]
          .trim()
      );

      if (!market) {
        return;
      }

      const [
        base,
        quote,
      ] = splitBotMarketAssets(
        market
      );

      if (!base) {
        return;
      }

      const decorationKey = (
        `${base}|${quote}`
      );

      const existing =
        label.querySelector(
          ':scope > '
          + '.aurora-market-symbols'
        );

      if (
        existing
        && existing.dataset
          .auroraMarket
          === decorationKey
      ) {
        label.dataset
          .auroraMarketValue = market;

        return;
      }

      existing?.remove();

      const group =
        document.createElement(
          'span'
        );

      group.className =
        'aurora-market-symbols';

      group.dataset
        .auroraMarket =
          decorationKey;

      group.setAttribute(
        'aria-hidden',
        'true',
      );

      group.setAttribute(
        'title',
        quote
          ? `${base} / ${quote}`
          : base,
      );

      [
        base,
        quote,
      ]
        .filter(Boolean)
        .forEach(symbol => {
          const host =
            document.createElement(
              'span'
            );

          host.className =
            'aurora-market-symbol-slot';

          prependSymbol(
            host,
            'asset',
            symbol,
            symbol,
            'aurora-market-symbol-inline',
          );

          group.append(
            host
          );
        });

      label.dataset
        .auroraMarketValue = market;

      label.prepend(
        group
      );
    });
  }


  /*
   * Bot Details artwork is presentation-only.
   *
   * renderBotDialog() remains authoritative for text and values.
   * The existing MutationObserver reruns this decorator whenever
   * app.js replaces subtitle or definition-list content.
   */
  function prependBotDetailMarketSymbols(
    host,
    market,
  ) {
    if (!host) {
      return;
    }

    const [
      base,
      quote,
    ] = splitBotMarketAssets(
      market
    );

    if (!base) {
      return;
    }

    const key = (
      `${base}|${quote}`
    );

    const existing =
      host.querySelector(
        ':scope > '
        + '.aurora-bot-detail-market-symbols'
      );

    if (
      existing
      && existing.dataset
        .auroraMarket
        === key
    ) {
      return;
    }

    existing?.remove();

    const group =
      document.createElement(
        'span'
      );

    group.className =
      'aurora-bot-detail-market-symbols';

    group.dataset
      .auroraMarket =
        key;

    group.setAttribute(
      'aria-hidden',
      'true',
    );

    group.setAttribute(
      'title',
      quote
        ? `${base} / ${quote}`
        : base,
    );

    [
      base,
      quote,
    ]
      .filter(Boolean)
      .forEach(symbol => {
        const slot =
          document.createElement(
            'span'
          );

        slot.className =
          'aurora-bot-detail-market-symbol-slot';

        prependSymbol(
          slot,
          'asset',
          symbol,
          symbol,
          'aurora-bot-detail-market-symbol-inline',
        );

        group.append(
          slot
        );
      });

    host.prepend(
      group
    );
  }


  function decorateBotDialogSymbols() {
    const subtitle =
      document.querySelector(
        '#dialogSubtitle'
      );

    if (subtitle) {
      const existing =
        subtitle.querySelector(
          ':scope > '
          + '.aurora-bot-detail-market-symbols'
        );

      const raw = (
        existing
          ? String(
              subtitle.dataset
                .auroraBotDetailText
              || ''
            ).trim()
          : String(
              subtitle.textContent
              || ''
            ).trim()
      );

      if (raw) {
        subtitle.dataset
          .auroraBotDetailText =
            raw;

        const parts = raw
          .split('·')
          .map(
            value =>
              value.trim()
          )
          .filter(Boolean);

        const market =
          parts.length > 1
            ? parts[1]
            : '';

        if (market) {
          prependBotDetailMarketSymbols(
            subtitle,
            market,
          );
        }
      }
    }

    const definitions =
      document.querySelector(
        '#botDefinitionList'
      );

    if (!definitions) {
      return;
    }

    definitions
      .querySelectorAll('dt')
      .forEach(term => {
        const value =
          term.nextElementSibling;

        if (!value) {
          return;
        }

        const label = String(
          term.textContent
          || ''
        ).trim();

        if (
          label === 'Market'
        ) {
          const existing =
            value.querySelector(
              ':scope > '
              + '.aurora-bot-detail-market-symbols'
            );

          const market = (
            existing
              ? String(
                  value.dataset
                    .auroraBotDetailMarket
                  || ''
                ).trim()
              : String(
                  value.textContent
                  || ''
                ).trim()
          );

          if (market) {
            value.dataset
              .auroraBotDetailMarket =
                market;

            prependBotDetailMarketSymbols(
              value,
              market,
            );
          }

          return;
        }

        if (
          label !== 'Base asset'
          && label !== 'Quote asset'
        ) {
          return;
        }

        const existingSymbol =
          value.querySelector(
            ':scope > .aurora-symbol'
          );

        const asset = (
          existingSymbol
            ? String(
                value.dataset
                  .auroraBotDetailAsset
                || ''
              ).trim()
            : String(
                value.textContent
                || ''
              ).trim()
        );

        if (!asset) {
          return;
        }

        value.dataset
          .auroraBotDetailAsset =
            asset;

        prependSymbol(
          value,
          'asset',
          asset,
          asset,
          'aurora-bot-detail-asset-symbol',
        );
      });
  }


  function decorate() {
    decorateDepositOptions();
    decorateDepositFavorites();
    decorateDepositResult();
    decorateDepositHistory();
    decorateBalance();
    decorateBotsMarkets();
    decorateBotDialogSymbols();
  }

  let scheduled = false;

  function scheduleDecorate() {
    if (scheduled) {
      return;
    }

    scheduled = true;

    requestAnimationFrame(
      () => {
        scheduled = false;
        decorate();
      }
    );
  }

  function start() {
    decorate();

    const observer =
      new MutationObserver(
        scheduleDecorate
      );

    observer.observe(
      document.body,
      {
        subtree: true,
        childList: true,
        characterData: true,
      },
    );
  }

  if (
    document.readyState
    === 'loading'
  ) {
    document.addEventListener(
      'DOMContentLoaded',
      start,
      {
        once: true,
      },
    );
  } else {
    start();
  }
})();

})();
