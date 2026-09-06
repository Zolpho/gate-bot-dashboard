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



  /*
   * Bot Control artwork is presentation-only.
   *
   * app.js remains authoritative for:
   * - form state;
   * - preflight state;
   * - live/simulation policy;
   * - confirmations;
   * - create/stop submission.
   *
   * Dynamic Bot Control renderers replace their HTML, so
   * the existing Aurora MutationObserver re-applies these
   * decorations after each renderer update.
   */

  function prependBotControlMarketSymbols(
    host,
    market,
  ) {
    if (!host) {
      return;
    }

    const canonicalMarket = String(
      market || ''
    ).trim();

    if (!canonicalMarket) {
      return;
    }

    const [
      base,
      quote,
    ] = splitBotMarketAssets(
      canonicalMarket
    );

    const existing = host.querySelector(
      ':scope > .aurora-bot-control-market-symbols'
    );

    if (
      existing
      && existing.dataset.auroraMarket
      === canonicalMarket
    ) {
      return;
    }

    if (existing) {
      existing.remove();
    }

    const group = document.createElement(
      'span'
    );

    group.className =
      'aurora-bot-control-market-symbols';

    group.dataset.auroraMarket =
      canonicalMarket;

    group.setAttribute(
      'aria-hidden',
      'true',
    );

    group.title = [
      base,
      quote,
    ]
      .filter(Boolean)
      .join(' / ');

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
          'aurora-bot-control-market-symbol-slot';

        group.appendChild(
          slot
        );

        prependSymbol(
          slot,
          'asset',
          symbol,
          symbol,
          'aurora-bot-control-market-symbol-inline',
        );
      });

    host.insertBefore(
      group,
      host.firstChild,
    );
  }


  function botControlCanonicalValue(
    host,
    datasetKey,
  ) {
    if (!host) {
      return '';
    }

    const stored = String(
      host.dataset?.[datasetKey]
      || ''
    ).trim();

    if (stored) {
      return stored;
    }

    const value = String(
      host.textContent || ''
    ).trim();

    if (
      value
      && host.dataset
    ) {
      host.dataset[
        datasetKey
      ] = value;
    }

    return value;
  }


  function botControlAssetFromValue(
    value,
  ) {
    const text = String(
      value || ''
    ).trim();

    const match = text.match(
      /(?:^|\s)([A-Za-z][A-Za-z0-9]{1,14})$/
    );

    if (!match) {
      return '';
    }

    return String(
      match[1] || ''
    ).toUpperCase();
  }


  function decorateBotControlLabelledRows() {
    const rows =
      document.querySelectorAll(
        [
          '#spotGridReviewMetrics .bot-control-review-item',
          '#spotGridConfirmSummary .bot-control-confirm-row',
          '#botControlAttentionList .bot-control-attention-field',
          '#stopBotConfirmSummary .bot-stop-strategy-meta > div',
          '#stopBotReturnEstimate .bot-stop-return-asset',
        ].join(', ')
      );

    rows.forEach(row => {
      const label = Array.from(
        row.children || []
      ).find(child => (
        child.tagName === 'SPAN'
      ));

      const value = Array.from(
        row.children || []
      ).find(child => (
        child.tagName === 'STRONG'
      ));

      if (
        !label
        || !value
      ) {
        return;
      }

      const labelText = String(
        label.textContent || ''
      ).trim();

      if (labelText === 'Market') {
        const market =
          botControlCanonicalValue(
            value,
            'auroraBotControlMarket',
          );

        if (market) {
          prependBotControlMarketSymbols(
            value,
            market,
          );
        }

        return;
      }

      if (
        labelText !== 'Base asset'
        && labelText !== 'Quote asset'
      ) {
        return;
      }

      const canonical =
        botControlCanonicalValue(
          value,
          'auroraBotControlAssetValue',
        );

      const asset =
        botControlAssetFromValue(
          canonical
        );

      if (!asset) {
        return;
      }

      prependSymbol(
        value,
        'asset',
        asset,
        asset,
        'aurora-bot-control-asset-inline',
      );
    });
  }


  function decorateBotControlActivityMarkets() {
    document
      .querySelectorAll(
        '#botControlActivityBody tr'
      )
      .forEach(row => {
        const cells =
          row.querySelectorAll(
            'td'
          );

        /*
         * Activity contract:
         * 1 time
         * 2 account
         * 3 user
         * 4 action
         * 5 market
         */
        if (cells.length < 5) {
          return;
        }

        const marketCell =
          cells[4];

        const market =
          botControlCanonicalValue(
            marketCell,
            'auroraBotControlMarket',
          );

        if (
          !market
          || market === '—'
        ) {
          return;
        }

        prependBotControlMarketSymbols(
          marketCell,
          market,
        );
      });
  }


  function decorateBotControlMarketInput() {
    const form = document.querySelector(
      '#spotGridForm'
    );

    if (!form) {
      return;
    }

    const marketLabel = Array.from(
      form.querySelectorAll(
        'label'
      )
    ).find(label => (
      String(
        label.textContent || ''
      )
        .trim()
        .toLowerCase()
        .startsWith('market')
    ));

    if (!marketLabel) {
      return;
    }

    const input =
      marketLabel.querySelector(
        'input'
      );

    if (!input) {
      return;
    }

    let group =
      marketLabel.querySelector(
        ':scope > .aurora-bot-control-market-input-symbols'
      );

    if (!group) {
      group =
        document.createElement(
          'span'
        );

      group.className =
        'aurora-bot-control-market-input-symbols';

      group.setAttribute(
        'aria-hidden',
        'true',
      );

      marketLabel.insertBefore(
        group,
        input,
      );
    }

    const market = String(
      input.value || ''
    ).trim();

    if (!market) {
      group.hidden = true;
      group.replaceChildren();
      delete group.dataset.auroraMarket;
    } else if (
      group.dataset.auroraMarket
      !== market
    ) {
      group.replaceChildren();

      const [
        base,
        quote,
      ] = splitBotMarketAssets(
        market
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
            'aurora-bot-control-market-symbol-slot';

          group.appendChild(
            slot
          );

          prependSymbol(
            slot,
            'asset',
            symbol,
            symbol,
            'aurora-bot-control-market-symbol-inline',
          );
        });

      group.dataset.auroraMarket =
        market;

      group.title = [
        base,
        quote,
      ]
        .filter(Boolean)
        .join(' / ');

      group.hidden = false;
    } else {
      group.hidden = false;
    }

    if (
      input.dataset
      && !input.dataset
        .auroraBotControlSymbolListener
    ) {
      input.dataset
        .auroraBotControlSymbolListener =
        '1';

      input.addEventListener(
        'input',
        scheduleDecorate,
      );

      input.addEventListener(
        'change',
        scheduleDecorate,
      );
    }
  }


  function decorateBotControlSymbols() {
    decorateBotControlMarketInput();
    decorateBotControlLabelledRows();
    decorateBotControlActivityMarkets();
  }



  /*
   * AURORA A7C94
   * Treasury symbol projection.
   *
   * Presentation only:
   * - native selects remain native
   * - text remains authoritative
   * - app.js state / API behavior is untouched
   * - existing MutationObserver is reused
   */


  function treasuryCanonicalText(
    element
  ) {
    if (!element) {
      return '';
    }

    const existing =
      element.querySelector(
        ':scope > .aurora-symbol'
      );

    if (!existing) {
      const rendered = String(
        element.textContent || ''
      ).trim();

      if (rendered) {
        element.dataset
          .auroraTreasuryCanonical =
            rendered;
      }

      return rendered;
    }

    return String(
      element.dataset
        .auroraTreasuryCanonical
      || ''
    ).trim();
  }


  function treasuryAssetFromAmount(
    value
  ) {
    const raw = String(
      value || ''
    ).trim();

    if (
      !raw
      || raw === '—'
    ) {
      return '';
    }

    const match = raw.match(
      /^\s*[-+]?(?:(?:\d{1,3}(?:,\d{3})+)|\d+)(?:\.\d+)?\s+([A-Za-z][A-Za-z0-9._-]{1,14})(?=\s*(?:\+|$))/
    );

    return match
      ? match[1].toUpperCase()
      : '';
  }


  function decorateTreasuryAmount(
    element,
    extraClass = '',
  ) {
    const raw =
      treasuryCanonicalText(
        element
      );

    const asset =
      treasuryAssetFromAmount(
        raw
      );

    if (!asset) {
      return;
    }

    prependSymbol(
      element,
      'asset',
      asset,
      asset,
      extraClass,
    );
  }


  function decorateTreasuryDirectValue(
    element,
    kind,
    value,
    label = '',
    extraClass = '',
  ) {
    const canonical = String(
      value || ''
    ).trim();

    if (
      !element
      || !canonical
      || canonical === '—'
    ) {
      return;
    }

    if (
      !element.querySelector(
        ':scope > .aurora-symbol'
      )
    ) {
      element.dataset
        .auroraTreasuryCanonical =
          String(
            element.textContent || ''
          ).trim();
    }

    prependSymbol(
      element,
      kind,
      canonical,
      label || canonical,
      extraClass,
    );
  }


  function decorateTreasurySelect(
    select,
    kind,
    value,
    label = '',
  ) {
    if (!select) {
      return;
    }

    const field =
      select.closest('label');

    if (!field) {
      return;
    }

    field.classList.add(
      'aurora-symbol-select-field'
    );

    let host =
      field.querySelector(
        ':scope > '
        + '.aurora-select-symbol-host'
      );

    if (!host) {
      host =
        document.createElement(
          'span'
        );

      host.className =
        'aurora-select-symbol-host';

      host.setAttribute(
        'aria-hidden',
        'true',
      );

      field.insertBefore(
        host,
        select,
      );
    }

    const canonical = String(
      value || ''
    ).trim();

    const display = String(
      label || canonical
    ).trim();

    if (!canonical) {
      select.classList.remove(
        'aurora-symbol-select-active'
      );

      if (!host.hidden) {
        host.hidden = true;
      }

      if (
        host.dataset
          .auroraSelectSymbolKey
      ) {
        host.replaceChildren();

        delete host.dataset
          .auroraSelectSymbolKey;
      }

      return;
    }

    const key = (
      `${kind}|${canonical}|${display}`
    );

    select.classList.add(
      'aurora-symbol-select-active'
    );

    host.hidden = false;

    if (
      host.dataset
        .auroraSelectSymbolKey
      !== key
    ) {
      host.replaceChildren(
        makeSymbol(
          kind,
          canonical,
          display,
        )
      );

      host.dataset
        .auroraSelectSymbolKey =
          key;
    }

    if (
      !select.dataset
        .auroraTreasurySymbolListener
    ) {
      select.dataset
        .auroraTreasurySymbolListener =
          '1';

      select.addEventListener(
        'change',
        scheduleDecorate,
      );
    }
  }


  function decorateTreasuryLabelledGrid(
    root,
    rowSelector,
    specifications
  ) {
    if (!root) {
      return;
    }

    root.querySelectorAll(
      rowSelector
    ).forEach(row => {
      const label =
        row.querySelector(
          ':scope > span'
        );

      const value =
        row.querySelector(
          ':scope > strong'
        );

      if (
        !label
        || !value
      ) {
        return;
      }

      const labelText = String(
        label.textContent || ''
      ).trim();

      const specification =
        specifications[labelText];

      if (!specification) {
        return;
      }

      if (
        specification === 'amount'
      ) {
        decorateTreasuryAmount(
          value,
          'aurora-treasury-value-symbol',
        );

        return;
      }

      const raw =
        treasuryCanonicalText(
          value
        );

      decorateTreasuryDirectValue(
        value,
        specification,
        raw,
        raw,
        'aurora-treasury-value-symbol',
      );
    });
  }


  function decorateTreasuryTransferSymbols() {
    const currencySelect =
      document.querySelector(
        '#treasuryUserTransferCurrency'
      );

    if (currencySelect) {
      decorateTreasurySelect(
        currencySelect,
        'asset',
        currencySelect.value,
        currencySelect.value,
      );
    }

    const preview =
      document.querySelector(
        '#treasuryUserTransferPreview'
      );

    decorateTreasuryLabelledGrid(
      preview,
      '.treasury-user-transfer-card',
      {
        'Asset': 'asset',
        'Amount': 'amount',
        'Balance before': 'amount',
        'Balance after': 'amount',
      },
    );

    document.querySelectorAll(
      '#treasuryActivityBody tr'
    ).forEach(row => {
      const cells =
        row.querySelectorAll('td');

      if (cells.length < 5) {
        return;
      }

      decorateTreasuryAmount(
        cells[4],
        'aurora-treasury-table-symbol',
      );
    });

    document.querySelectorAll(
      '#treasuryLockList '
      + '.treasury-lock-field'
    ).forEach(field => {
      const label =
        field.querySelector(
          ':scope > span'
        );

      const value =
        field.querySelector(
          ':scope > strong'
        );

      if (
        String(
          label?.textContent || ''
        ).trim() !== 'Currency'
      ) {
        return;
      }

      const currency =
        treasuryCanonicalText(
          value
        );

      decorateTreasuryDirectValue(
        value,
        'asset',
        currency,
        currency,
        'aurora-treasury-value-symbol',
      );
    });

    decorateTreasuryAmount(
      document.querySelector(
        '#treasuryRequestSummary '
        + '.treasury-request-heading h3'
      ),
      'aurora-treasury-value-symbol',
    );
  }


  function decorateTreasuryWithdrawalSymbols() {
    const assetSelect =
      document.querySelector(
        '#treasuryWithdrawalAsset'
      );

    if (assetSelect) {
      decorateTreasurySelect(
        assetSelect,
        'asset',
        assetSelect.value,
        assetSelect.value,
      );
    }

    const networkSelect =
      document.querySelector(
        '#treasuryWithdrawalNetwork'
      );

    if (networkSelect) {
      const option =
        networkSelect.selectedOptions?.[0];

      const label = String(
        option?.textContent
        || networkSelect.value
        || ''
      )
        .replace(
          /\s+·\s+currently unavailable$/i,
          ''
        )
        .trim();

      decorateTreasurySelect(
        networkSelect,
        'network',
        networkSelect.value,
        label,
      );
    }

    document.querySelectorAll(
      '#treasuryWithdrawalFundingSummary '
      + '.treasury-withdrawal-funding-summary-grid '
      + '> div > strong'
    ).forEach(value => {
      decorateTreasuryAmount(
        value,
        'aurora-treasury-value-symbol',
      );
    });

    document.querySelectorAll(
      '#treasuryWithdrawalPreflight '
      + '.treasury-withdrawal-preflight-grid '
      + '> div > strong'
    ).forEach(value => {
      decorateTreasuryAmount(
        value,
        'aurora-treasury-value-symbol',
      );
    });

    document.querySelectorAll(
      '#treasuryWithdrawalRequestBody tr'
    ).forEach(row => {
      const cells =
        row.querySelectorAll('td');

      if (cells.length < 5) {
        return;
      }

      decorateTreasuryAmount(
        cells[3],
        'aurora-treasury-table-symbol',
      );

      decorateTreasuryAmount(
        cells[4],
        'aurora-treasury-table-symbol',
      );
    });

    decorateTreasuryAmount(
      document.querySelector(
        '#treasuryWithdrawalRequestSummary '
        + '.treasury-request-heading h3'
      ),
      'aurora-treasury-value-symbol',
    );

    decorateTreasuryLabelledGrid(
      document.querySelector(
        '#treasuryWithdrawalRequestSummary'
      ),
      '.treasury-request-grid > div',
      {
        'Asset': 'asset',
        'Network': 'network',
        'Estimated fee': 'amount',
        'Minimum JIT': 'amount',
      },
    );

    document.querySelectorAll(
      '#treasuryWithdrawalLockDetail '
      + '.treasury-lock-field'
    ).forEach(field => {
      const label =
        field.querySelector(
          ':scope > span'
        );

      const value =
        field.querySelector(
          ':scope > strong'
        );

      if (
        String(
          label?.textContent || ''
        ).trim() !== 'Currency'
      ) {
        return;
      }

      const currency =
        treasuryCanonicalText(
          value
        );

      decorateTreasuryDirectValue(
        value,
        'asset',
        currency,
        currency,
        'aurora-treasury-value-symbol',
      );
    });

    decorateTreasuryLabelledGrid(
      document.querySelector(
        '#treasuryWithdrawalDestinationReviewList'
      ),
      '.treasury-destination-review-grid > div',
      {
        'Asset': 'asset',
        'Network': 'network',
      },
    );
  }



  /*
   * ==========================================================
   * AURORA A7C101 — TRADING TOKEN / MARKET SYMBOLS
   * ==========================================================
   *
   * Presentation only.
   *
   * No Trading listener, request, write capability or state
   * transition is owned here. Runtime text remains canonical.
   * When trading.js / trading-limit.js replace text or rows,
   * the existing shared symbol MutationObserver simply
   * decorates the newly rendered presentation again.
   */

  function tradingTextWithoutAuroraSymbols(
    element,
  ) {
    if (!element) {
      return '';
    }

    const clone = element.cloneNode(true);

    clone.querySelectorAll(
      '.aurora-trading-asset-symbol, '
      + '.aurora-trading-market-symbols'
    ).forEach(
      node => node.remove()
    );

    return String(
      clone.textContent || ''
    ).trim();
  }

  function tradingMarketAssets(
    value,
  ) {
    const canonical = String(
      value || ''
    )
      .trim()
      .toUpperCase();

    if (!canonical) {
      return [
        '',
        '',
      ];
    }

    const direct = canonical.match(
      /^([A-Z0-9.]{1,24})\s*(?:\/|_|-)\s*([A-Z0-9.]{1,24})$/
    );

    if (direct) {
      return [
        direct[1],
        direct[2],
      ];
    }

    const fallback = splitBotMarketAssets(
      canonical
    );

    return [
      String(
        fallback?.[0] || ''
      ).trim().toUpperCase(),
      String(
        fallback?.[1] || ''
      ).trim().toUpperCase(),
    ];
  }

  function tradingCurrentMarketAssets() {
    const pairInput = document.querySelector(
      '#tradingPair'
    );

    const marketTitle = document.querySelector(
      '#tradingMarketTitle'
    );

    const candidates = [
      String(
        pairInput?.value || ''
      ),
      tradingTextWithoutAuroraSymbols(
        marketTitle
      ),
    ];

    for (const candidate of candidates) {
      const [
        base,
        quote,
      ] = tradingMarketAssets(
        candidate
      );

      if (
        base
        && quote
      ) {
        return [
          base,
          quote,
        ];
      }
    }

    return [
      '',
      '',
    ];
  }

  function tradingCreateAssetSymbol(
    asset,
  ) {
    const canonical = String(
      asset || ''
    )
      .trim()
      .toUpperCase();

    if (!canonical) {
      return null;
    }

    const wrapper = document.createElement(
      'span'
    );

    wrapper.className =
      'aurora-trading-asset-symbol';

    wrapper.dataset.auroraTradingAsset =
      canonical;

    wrapper.setAttribute(
      'aria-hidden',
      'true'
    );

    const icon = assetIcon(
      canonical
    );

    if (icon) {
      const image = document.createElement(
        'img'
      );

      image.className =
        'aurora-trading-symbol-image';

      image.src =
        `./assets/symbols/${icon}`;

      image.alt = '';

      image.draggable = false;

      wrapper.append(
        image
      );

      return wrapper;
    }

    const fallback = document.createElement(
      'span'
    );

    fallback.className =
      'aurora-trading-symbol-fallback';

    fallback.textContent =
      canonical.slice(
        0,
        2,
      );

    wrapper.append(
      fallback
    );

    return wrapper;
  }

  function tradingPrependAssetSymbol(
    element,
    asset,
  ) {
    if (
      !element
      || !asset
    ) {
      return;
    }

    const canonical = String(
      asset
    )
      .trim()
      .toUpperCase();

    const existing = Array.from(
      element.children
    ).find(
      child => (
        child.classList
          ?.contains(
            'aurora-trading-asset-symbol'
          )
      )
    );

    if (
      existing
      && existing.dataset
        .auroraTradingAsset
        === canonical
    ) {
      return;
    }

    Array.from(
      element.children
    )
      .filter(
        child => (
          child.classList
            ?.contains(
              'aurora-trading-asset-symbol'
            )
        )
      )
      .forEach(
        child => child.remove()
      );

    const symbol = tradingCreateAssetSymbol(
      canonical
    );

    if (!symbol) {
      return;
    }

    element.prepend(
      symbol
    );
  }

  function tradingPrependMarketSymbols(
    element,
    market,
  ) {
    if (!element) {
      return;
    }

    const [
      base,
      quote,
    ] = tradingMarketAssets(
      market
    );

    if (
      !base
      || !quote
    ) {
      return;
    }

    const canonicalMarket =
      `${base}_${quote}`;

    const existing = Array.from(
      element.children
    ).find(
      child => (
        child.classList
          ?.contains(
            'aurora-trading-market-symbols'
          )
      )
    );

    if (
      existing
      && existing.dataset
        .auroraTradingMarket
        === canonicalMarket
    ) {
      return;
    }

    Array.from(
      element.children
    )
      .filter(
        child => (
          child.classList
            ?.contains(
              'aurora-trading-market-symbols'
            )
        )
      )
      .forEach(
        child => child.remove()
      );

    const group = document.createElement(
      'span'
    );

    group.className =
      'aurora-trading-market-symbols';

    group.dataset.auroraTradingMarket =
      canonicalMarket;

    group.setAttribute(
      'aria-hidden',
      'true'
    );

    [
      base,
      quote,
    ].forEach(
      asset => {
        const symbol =
          tradingCreateAssetSymbol(
            asset
          );

        if (symbol) {
          group.append(
            symbol
          );
        }
      }
    );

    if (!group.children.length) {
      return;
    }

    element.prepend(
      group
    );
  }

  function tradingAssetFromNumericText(
    value,
  ) {
    const match = String(
      value || ''
    ).match(
      /^\s*[-+]?(?:(?:\d{1,3}(?:,\d{3})+)|\d+)(?:\.\d+)?\s+([A-Za-z][A-Za-z0-9._-]{1,14})(?=\s+(?:available|locked)\b|\s*$)/i
    );

    return String(
      match?.[1] || ''
    )
      .trim()
      .toUpperCase();
  }

  function tradingAssetFromKnownSuffix(
    value,
  ) {
    const match = String(
      value || ''
    ).match(
      /^\s*[-+]?(?:(?:\d{1,3}(?:,\d{3})+)|\d+)(?:\.\d+)?\s+([A-Za-z][A-Za-z0-9._-]{1,14})\s*$/
    );

    return String(
      match?.[1] || ''
    )
      .trim()
      .toUpperCase();
  }

  function decorateTradingMarketHeader(
    base,
    quote,
  ) {
    const title = document.querySelector(
      '#tradingMarketTitle'
    );

    if (title) {
      const raw =
        tradingTextWithoutAuroraSymbols(
          title
        );

      const [
        titleBase,
        titleQuote,
      ] = tradingMarketAssets(
        raw
      );

      if (
        titleBase
        && titleQuote
      ) {
        tradingPrependMarketSymbols(
          title,
          `${titleBase}_${titleQuote}`,
        );
      }
    }

    const quoteTargets = [
      '#tradingLastPrice',
      '#tradingBestBid',
      '#tradingBestAsk',
      '#tradingHigh24h',
      '#tradingLow24h',
      '#tradingSpread',
    ];

    quoteTargets.forEach(
      selector => {
        tradingPrependAssetSymbol(
          document.querySelector(
            selector
          ),
          quote,
        );
      }
    );

    const baseTargets = [
      '#tradingBaseVolume',
      '#tradingVolumeValue',
    ];

    baseTargets.forEach(
      selector => {
        tradingPrependAssetSymbol(
          document.querySelector(
            selector
          ),
          base,
        );
      }
    );

    tradingPrependAssetSymbol(
      document.querySelector(
        '#tradingQuoteVolume'
      ),
      quote,
    );
  }

  function decorateTradingTicketAssets(
    base,
    quote,
  ) {
    tradingPrependAssetSymbol(
      document.querySelector(
        '#tradingLimitPriceAsset'
      ),
      quote,
    );

    tradingPrependAssetSymbol(
      document.querySelector(
        '#tradingLimitAmountAsset'
      ),
      base,
    );

    tradingPrependAssetSymbol(
      document.querySelector(
        '#tradingLimitTotalAsset'
      ),
      quote,
    );

    const available = document.querySelector(
      '#tradingLimitAvailable'
    );

    if (available) {
      const asset =
        tradingAssetFromNumericText(
          tradingTextWithoutAuroraSymbols(
            available
          )
        );

      if (asset) {
        tradingPrependAssetSymbol(
          available,
          asset,
        );
      }
    }
  }

  function decorateTradingBalanceAssets(
    base,
    quote,
  ) {
    [
      '#tradingBaseBalanceLabel',
      '#tradingBaseAvailable',
      '#tradingBaseLocked',
    ].forEach(
      selector => {
        tradingPrependAssetSymbol(
          document.querySelector(
            selector
          ),
          base,
        );
      }
    );

    [
      '#tradingQuoteBalanceLabel',
      '#tradingQuoteAvailable',
      '#tradingQuoteLocked',
    ].forEach(
      selector => {
        tradingPrependAssetSymbol(
          document.querySelector(
            selector
          ),
          quote,
        );
      }
    );
  }

  function decorateTradingBookHeaders(
    base,
    quote,
  ) {
    const bookHeaders =
      document.querySelectorAll(
        '#tab-trading '
        + '.trading-book-head > span'
      );

    const bookAssets = [
      quote,
      base,
      quote,
    ];

    bookHeaders.forEach(
      (
        element,
        index,
      ) => {
        tradingPrependAssetSymbol(
          element,
          bookAssets[index] || '',
        );
      }
    );

    const tradeHeaders =
      document.querySelectorAll(
        '#tab-trading '
        + '.trading-trades-head > span'
      );

    const tradeAssets = [
      quote,
      base,
      quote,
      '',
    ];

    tradeHeaders.forEach(
      (
        element,
        index,
      ) => {
        tradingPrependAssetSymbol(
          element,
          tradeAssets[index] || '',
        );
      }
    );
  }

  function decorateTradingPreviewAssets(
    base,
    quote,
  ) {
    document.querySelectorAll(
      '#tradingLimitOrderPreview '
      + '.trading-order-preview-card'
    ).forEach(
      card => {
        const label = String(
          card.querySelector(
            'span'
          )?.textContent || ''
        )
          .trim()
          .toLowerCase();

        const value = card.querySelector(
          'strong'
        );

        if (!value) {
          return;
        }

        let asset = '';

        if (
          label === 'price'
          || label === 'total'
          || label === 'best bid'
          || label === 'best ask'
        ) {
          asset = quote;
        } else if (
          label === 'amount'
        ) {
          asset = base;
        } else if (
          label === 'funds required'
          || label === 'available'
          || label === 'remaining'
        ) {
          const rawValue =
            tradingTextWithoutAuroraSymbols(
              value
            );

          asset =
            tradingAssetFromNumericText(
              rawValue
            )
            || tradingAssetFromKnownSuffix(
              rawValue
            );
        }

        if (asset) {
          tradingPrependAssetSymbol(
            value,
            asset,
          );
        }
      }
    );
  }

  function decorateTradingOrderMarkets() {
    const tableTargets = [
      [
        '#tradingOpenOrders',
        0,
      ],
      [
        '#tradingRecentOrders',
        1,
      ],
    ];

    tableTargets.forEach(
      ([
        selector,
        pairCellIndex,
      ]) => {
        const body = document.querySelector(
          selector
        );

        if (!body) {
          return;
        }

        Array.from(
          body.rows || []
        ).forEach(
          row => {
            const cell =
              row.cells?.[
                pairCellIndex
              ];

            const code =
              cell?.querySelector(
                'code'
              );

            if (!code) {
              return;
            }

            const market =
              tradingTextWithoutAuroraSymbols(
                code
              );

            const [
              base,
              quote,
            ] = tradingMarketAssets(
              market
            );

            if (
              base
              && quote
            ) {
              tradingPrependMarketSymbols(
                code,
                `${base}_${quote}`,
              );
            }
          }
        );
      }
    );
  }

  function decorateTradingSymbols() {
    const root = document.querySelector(
      '#tab-trading'
    );

    if (!root) {
      return;
    }

    const [
      base,
      quote,
    ] = tradingCurrentMarketAssets();

    if (
      base
      && quote
    ) {
      decorateTradingMarketHeader(
        base,
        quote,
      );

      decorateTradingTicketAssets(
        base,
        quote,
      );

      decorateTradingBalanceAssets(
        base,
        quote,
      );

      decorateTradingBookHeaders(
        base,
        quote,
      );

      decorateTradingPreviewAssets(
        base,
        quote,
      );
    }

    decorateTradingOrderMarkets();
  }

  function decorateTreasurySymbols() {
    decorateTreasuryTransferSymbols();

    decorateTreasuryWithdrawalSymbols();
  }


  function decorate() {
    decorateDepositOptions();
    decorateDepositFavorites();
    decorateDepositResult();
    decorateDepositHistory();
    decorateBalance();
    decorateBotsMarkets();
    decorateBotDialogSymbols();
    decorateBotControlSymbols();

    decorateTreasurySymbols();

    decorateTradingSymbols();
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
