(() => {
  'use strict';

  if (
    document.documentElement.dataset.dashboardUi
    !== 'aurora'
  ) {
    return;
  }


  const projectAuroraWithdrawalStages = () => {
    const root =
      document.querySelector(
        '#treasuryWithdrawalAction'
      );

    if (!root) {
      return false;
    }

    const existing =
      root.querySelector(
        '[data-aurora-withdrawal-stage-grid]'
      );

    if (existing) {
      return true;
    }

    const routeBuilder =
      root.querySelector(
        '#treasuryWithdrawalRouteBuilder'
      );

    const unavailable =
      root.querySelector(
        '#treasuryWithdrawalUnavailable'
      );

    const form =
      root.querySelector(
        '#treasuryWithdrawalForm'
      );

    const formError =
      root.querySelector(
        '#treasuryWithdrawalFormError'
      );

    const preflight =
      root.querySelector(
        '#treasuryWithdrawalPreflight'
      );

    const requestButton =
      root.querySelector(
        '#createTreasuryWithdrawalRequest'
      );

    if (
      !routeBuilder
      || !unavailable
      || !form
      || !formError
      || !preflight
      || !requestButton
    ) {
      return false;
    }

    const heading = (
      kicker,
      title,
      signal
    ) => {
      const node =
        document.createElement(
          'div'
        );

      node.className =
        'aurora-withdrawal-stage-heading';

      node.innerHTML = (
        '<div>'
        + '<span class="'
        + 'aurora-withdrawal-stage-kicker'
        + '">'
        + kicker
        + '</span>'
        + '<strong>'
        + title
        + '</strong>'
        + '</div>'
        + '<span class="'
        + 'aurora-withdrawal-stage-signal'
        + '">'
        + signal
        + '</span>'
      );

      return node;
    };

    const grid =
      document.createElement(
        'div'
      );

    grid.className =
      'aurora-withdrawal-stage-grid';

    grid.dataset
      .auroraWithdrawalStageGrid = '1';

    grid.setAttribute(
      'aria-label',
      'Aurora withdrawal stages'
    );

    const destination =
      document.createElement(
        'div'
      );

    destination.className = (
      'aurora-withdrawal-stage '
      + 'aurora-withdrawal-stage-destination'
    );

    destination.dataset
      .auroraStage = '01';

    destination.append(
      heading(
        'Destination',
        'Choose the route',
        'ROUTE'
      )
    );

    const safety =
      document.createElement(
        'div'
      );

    safety.className = (
      'aurora-withdrawal-stage '
      + 'aurora-withdrawal-stage-safety'
    );

    safety.dataset
      .auroraStage = '02';

    safety.append(
      heading(
        'Safety preflight',
        'Verify the withdrawal',
        'READ ONLY'
      )
    );

    const idle =
      document.createElement(
        'div'
      );

    idle.className =
      'aurora-withdrawal-stage-idle';

    idle.textContent = (
      'Route funding and Gate safety data '
      + 'appear here when a destination is ready.'
    );

    safety.append(
      idle
    );

    const request =
      document.createElement(
        'div'
      );

    request.className = (
      'aurora-withdrawal-stage '
      + 'aurora-withdrawal-stage-request'
    );

    request.dataset
      .auroraStage = '03';

    request.append(
      heading(
        'Request',
        'Create the audited request',
        'LOCKED'
      )
    );

    const requestBody =
      document.createElement(
        'div'
      );

    requestBody.className =
      'aurora-withdrawal-request-body';

    const orbit =
      document.createElement(
        'div'
      );

    orbit.className =
      'aurora-withdrawal-request-orbit';

    orbit.innerHTML =
      '<span></span>'
      + '<span></span>'
      + '<span></span>';

    const placeholder =
      document.createElement(
        'div'
      );

    placeholder.className =
      'aurora-withdrawal-stage-placeholder';

    placeholder.innerHTML = (
      '<span class="'
      + 'aurora-withdrawal-placeholder-icon'
      + '">03</span>'
      + '<strong>'
      + 'Awaiting safety preflight'
      + '</strong>'
      + '<p>'
      + 'This stage becomes active only after '
      + 'the current form matches a valid preflight.'
      + '</p>'
    );

    const requestAction =
      document.createElement(
        'div'
      );

    requestAction.className =
      'aurora-withdrawal-request-action';

    /*
     * Insert the new grid at the exact position
     * occupied by the Classic route builder.
     */
    root.insertBefore(
      grid,
      routeBuilder
    );

    /*
     * Move existing Classic-controlled nodes.
     *
     * IDs and element objects are preserved.
     * This happens before deferred app.js binds
     * its listeners.
     */
    destination.append(
      routeBuilder,
      unavailable
    );

    safety.append(
      form,
      formError
    );

    requestAction.append(
      requestButton
    );

    requestBody.append(
      orbit,
      placeholder,
      preflight,
      requestAction
    );

    request.append(
      requestBody
    );

    grid.append(
      destination,
      safety,
      request
    );

    return true;
  };

  projectAuroraWithdrawalStages();

(() => {
  'use strict';

  const root = document.querySelector(
    '#treasuryWithdrawalAction',
  );

  if (!root) {
    return;
  }

  const selectors = {
    destinationStage:
      '.aurora-withdrawal-stage-destination',
    safetyStage:
      '.aurora-withdrawal-stage-safety',
    requestStage:
      '.aurora-withdrawal-stage-request',
    routeStatus:
      '#treasuryWithdrawalRouteStatus',
    unavailable:
      '#treasuryWithdrawalUnavailable',
    form:
      '#treasuryWithdrawalForm',
    preflightContext:
      '#treasuryWithdrawalPreflightContext',
    preflight:
      '#treasuryWithdrawalPreflight',
    requestButton:
      '#createTreasuryWithdrawalRequest',
    capability:
      '#treasuryWithdrawalState',
    destinationCount:
      '#treasuryWithdrawalDestinationCount',
  };

  const element = name => (
    root.querySelector(
      selectors[name],
    )
  );

  const visible = node => Boolean(
    node
    && !node.hidden
    && !node.classList.contains(
      'hidden',
    )
  );

  const compactText = (
    node,
    fallback,
  ) => {
    const value = String(
      node?.textContent || '',
    )
      .replace(
        /\s+/g,
        ' ',
      )
      .trim();

    if (!value) {
      return fallback;
    }

    if (value.length <= 118) {
      return value;
    }

    return (
      value.slice(
        0,
        115,
      )
      + '…'
    );
  };

  const setData = (
    node,
    key,
    value,
  ) => {
    if (
      node
      && node.dataset[key] !== value
    ) {
      node.dataset[key] = value;
    }
  };

  const setText = (
    node,
    value,
  ) => {
    if (
      node
      && node.textContent !== value
    ) {
      node.textContent = value;
    }
  };

  const createDeck = () => {
    const existing = document.querySelector(
      '[data-aurora-withdrawal-command]',
    );

    if (existing) {
      return existing;
    }

    const deck = document.createElement(
      'aside',
    );

    deck.className =
      'aurora-withdrawal-command-deck';

    deck.dataset.auroraWithdrawalCommand =
      'true';

    deck.setAttribute(
      'aria-hidden',
      'true',
    );

    deck.innerHTML = [
      '<div class="aurora-command-crown">',
        '<div class="aurora-command-identity">',
          '<span class="aurora-command-beacon"></span>',
          '<span class="aurora-command-overline">',
            'WITHDRAWAL MISSION CONTROL',
          '</span>',
          '<strong>',
            'Route funds through the safety gate',
          '</strong>',
        '</div>',
        '<div class="aurora-command-status-stack">',
          '<div class="aurora-command-guard">',
            '<span>EXECUTION GUARD</span>',
            '<strong data-aurora-readout="guard">',
              'CHECKING',
            '</strong>',
          '</div>',
          '<div class="aurora-command-destinations">',
            '<span>APPROVED ROUTES</span>',
            '<strong data-aurora-readout="destinations">',
              'CHECKING',
            '</strong>',
          '</div>',
        '</div>',
      '</div>',

      '<div class="aurora-command-vector">',
        '<article ',
          'class="aurora-command-node" ',
          'data-aurora-command-node="route"',
        '>',
          '<span class="aurora-command-index">',
            '01',
          '</span>',
          '<div>',
            '<small>DESTINATION VECTOR</small>',
            '<strong>ROUTE</strong>',
            '<p data-aurora-readout="route">',
              'Waiting for route data',
            '</p>',
          '</div>',
        '</article>',

        '<span class="aurora-command-link"></span>',

        '<article ',
          'class="aurora-command-node" ',
          'data-aurora-command-node="safety"',
        '>',
          '<span class="aurora-command-index">',
            '02',
          '</span>',
          '<div>',
            '<small>READ-ONLY GATE</small>',
            '<strong>PREFLIGHT</strong>',
            '<p data-aurora-readout="safety">',
              'Awaiting approved destination',
            '</p>',
          '</div>',
        '</article>',

        '<span class="aurora-command-link"></span>',

        '<article ',
          'class="aurora-command-node" ',
          'data-aurora-command-node="request"',
        '>',
          '<span class="aurora-command-index">',
            '03',
          '</span>',
          '<div>',
            '<small>AUDITED LOCAL ACTION</small>',
            '<strong>REQUEST</strong>',
            '<p data-aurora-readout="request">',
              'Locked until preflight matches',
            '</p>',
          '</div>',
        '</article>',
      '</div>',

      '<div class="aurora-command-floor">',
        '<span>',
          '<i></i>',
          'CLASSIC FINANCIAL LOGIC',
        '</span>',
        '<span>',
          'AURORA PRESENTATION LAYER',
          '<i></i>',
        '</span>',
      '</div>',
    ].join('');

    root.insertAdjacentElement(
      'beforebegin',
      deck,
    );

    return deck;
  };

  const deck = createDeck();

  const readout = name => (
    deck.querySelector(
      `[data-aurora-readout="${name}"]`,
    )
  );

  const commandNode = name => (
    deck.querySelector(
      `[data-aurora-command-node="${name}"]`,
    )
  );


  /*
   * AURORA A6D9C DAILY LIMIT PROJECTION
   *
   * Read-only presentation projection.
   *
   * daily_limit_remaining comes from the existing withdrawal
   * capabilities/preflight contract and participates in the
   * authoritative safety checks.
   *
   * No financial arithmetic is performed here.
   */
  const projectDailyLimit = () => {
    const summary = root.querySelector(
      '#treasuryWithdrawalFundingSummary',
    );

    if (!summary) {
      return;
    }

    const grid = summary.querySelector(
      '.treasury-withdrawal-funding-summary-grid',
    );

    if (!grid) {
      return;
    }

    let cell = grid.querySelector(
      '[data-aurora-daily-limit-cell]',
    );

    if (!cell) {
      grid.insertAdjacentHTML(
        'beforeend',
        '<div data-aurora-daily-limit-cell>'
        + '<span>Daily limit remaining</span>'
        + '<strong data-aurora-daily-limit-value>'
        + '—'
        + '</strong>'
        + '</div>',
      );

      cell = grid.querySelector(
        '[data-aurora-daily-limit-cell]',
      );
    }

    const value = cell?.querySelector(
      '[data-aurora-daily-limit-value]',
    );

    if (!value) {
      return;
    }

    const capabilities = (
      typeof state !== 'undefined'
      && state.treasuryWithdrawalCapabilities
      && typeof state.treasuryWithdrawalCapabilities
        === 'object'
        ? state.treasuryWithdrawalCapabilities
        : null
    );

    const gateLimits = (
      capabilities?.gate_limits
      && typeof capabilities.gate_limits === 'object'
        ? capabilities.gate_limits
        : null
    );

    const raw = (
      gateLimits?.daily_limit_remaining
    );

    const currency = String(
      capabilities?.currency
      || (
        typeof state !== 'undefined'
          ? state.treasuryWithdrawalAsset
          : ''
      )
      || '',
    ).trim().toUpperCase();

    const hasValue = Boolean(
      raw !== undefined
      && raw !== null
      && String(raw).trim() !== ''
    );

    let display = '—';

    if (hasValue) {
      const formatted = String(
        typeof treasuryAmount === 'function'
          ? treasuryAmount(
              raw,
              currency,
            )
          : raw,
      ).trim();

      display = (
        formatted
        || String(raw).trim()
      );

      if (
        currency
        && !display
          .toUpperCase()
          .includes(currency)
      ) {
        display = `${display} ${currency}`;
      }
    }

    setText(
      value,
      display,
    );
  };


  const synchronize = () => {
    const destinationStage = element(
      'destinationStage',
    );

    const safetyStage = element(
      'safetyStage',
    );

    const requestStage = element(
      'requestStage',
    );

    const form = element(
      'form',
    );

    const unavailable = element(
      'unavailable',
    );

    const preflight = element(
      'preflight',
    );

    const preflightContext = element(
      'preflightContext',
    );

    const requestButton = element(
      'requestButton',
    );

    const routeReady = visible(
      form,
    );

    const routeBlocked = visible(
      unavailable,
    );

    const preflightValid =
      root.classList.contains(
        'has-valid-preflight',
      );

    const requestReady = Boolean(
      requestButton
      && !requestButton.disabled,
    );

    const routeState = (
      routeBlocked
        ? 'blocked'
        : routeReady
          ? 'ready'
          : 'active'
    );

    const safetyState = (
      preflightValid
        ? 'verified'
        : routeReady
          ? 'active'
          : 'waiting'
    );

    const requestState = (
      requestReady
        ? 'ready'
        : preflightValid
          ? 'active'
          : 'locked'
    );

    const focus = (
      requestReady
      || preflightValid
        ? 'request'
        : routeReady
          ? 'safety'
          : 'route'
    );

    setData(
      root,
      'auroraPhase',
      focus,
    );

    setData(
      deck,
      'auroraFocus',
      focus,
    );

    setData(
      destinationStage,
      'auroraState',
      routeState,
    );

    setData(
      safetyStage,
      'auroraState',
      safetyState,
    );

    setData(
      requestStage,
      'auroraState',
      requestState,
    );

    setData(
      commandNode('route'),
      'auroraState',
      routeState,
    );

    setData(
      commandNode('safety'),
      'auroraState',
      safetyState,
    );

    setData(
      commandNode('request'),
      'auroraState',
      requestState,
    );

    setText(
      readout('guard'),
      compactText(
        element(
          'capability',
        ),
        'CHECKING',
      ),
    );

    setText(
      readout('destinations'),
      compactText(
        element(
          'destinationCount',
        ),
        'CHECKING',
      ),
    );

    setText(
      readout('route'),
      compactText(
        element(
          'routeStatus',
        ),
        routeBlocked
          ? 'Destination unavailable'
          : 'Waiting for route data',
      ),
    );

    const safetySource = (
      visible(
        preflightContext,
      )
        ? preflightContext
        : null
    );

    setText(
      readout('safety'),
      preflightValid
        ? 'Verified · current form matches preflight'
        : compactText(
            safetySource,
            routeReady
              ? 'Ready for safety preflight'
              : 'Awaiting approved destination',
          ),
    );

    setText(
      readout('request'),
      requestReady
        ? 'Audited request is ready'
        : preflightValid
          ? 'Preflight valid · request gate active'
          : 'Locked until preflight matches',
    );
    projectDailyLimit();
  };

  let frame = 0;

  const schedule = () => {
    if (frame) {
      return;
    }

    frame = window.requestAnimationFrame(
      () => {
        frame = 0;
        synchronize();
      },
    );
  };

  const observer = new MutationObserver(
    schedule,
  );

  observer.observe(
    root,
    {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: [
        'class',
        'hidden',
        'disabled',
        'aria-hidden',
      ],
    },
  );

  synchronize();
})();


/* ============================================================
   AURORA A7C3 DEPOSIT FOCUS STABILITY

   openDepositDialog() intentionally focuses the search field.
   Preserve keyboard focus, but restore the operator's viewport
   so opening the inline workflow does not move the whole page.
   ============================================================ */

(() => {
  const installAuroraDepositFocusStability = () => {
    const trigger = document.getElementById('depositButton');
    const search = document.getElementById('depositCurrencySearch');

    if (!trigger || !search) return;

    if (trigger.dataset.auroraDepositFocusStability === '1') {
      return;
    }

    let pendingViewport = null;

    trigger.addEventListener('click', () => {
      pendingViewport = {
        left: window.scrollX,
        top: window.scrollY,
      };
    });

    search.addEventListener('focus', () => {
      if (!pendingViewport) return;

      const viewport = pendingViewport;
      pendingViewport = null;

      window.scrollTo({
        left: viewport.left,
        top: viewport.top,
        behavior: 'auto',
      });
    });

    trigger.dataset.auroraDepositFocusStability = '1';
  };

  if (document.readyState === 'loading') {
    document.addEventListener(
      'DOMContentLoaded',
      installAuroraDepositFocusStability,
      { once: true },
    );
  } else {
    installAuroraDepositFocusStability();
  }
})();


/* ============================================================
   AURORA A7C17 — SELECTED NETWORK EDITOR

   Presentation-only controller.

   Existing app.js remains owner of actual Deposit Network
   selection and address loading.
   ============================================================ */

(() => {
  const list =
    document.getElementById(
      'depositNetworkList'
    );

  const step =
    document.getElementById(
      'depositNetworkStep'
    );

  const details =
    document.getElementById(
      'depositDetailsStep'
    );

  if (
    !list
    || !step
    || !details
  ) {
    return;
  }

  if (
    list.dataset
      .auroraNetworkEditor
    === '1'
  ) {
    return;
  }

  list.dataset
    .auroraNetworkEditor = '1';


  const addressPhaseActive = () =>
    !details.classList.contains(
      'deposit-step-disabled'
    );


  const activeNetworkRow = () =>
    list.querySelector(
      '[data-deposit-chain].active'
    );


  const syncAccessibility = () => {
    const active =
      activeNetworkRow();

    if (!active) {
      return;
    }

    const expanded =
      step.classList.contains(
        'aurora-network-edit-open'
      )
      && addressPhaseActive();

    active.setAttribute(
      'aria-expanded',
      String(expanded),
    );

    active.removeAttribute(
      'title',
    );
  };


  const setExpanded = expanded => {
    const next =
      Boolean(expanded)
      && addressPhaseActive();

    step.classList.toggle(
      'aurora-network-edit-open',
      next,
    );

    syncAccessibility();
  };


  list.addEventListener(
    'click',
    event => {
      const row =
        event.target.closest(
          '[data-deposit-chain]'
        );

      if (
        !row
        || !list.contains(row)
        || row.disabled
        || !addressPhaseActive()
      ) {
        return;
      }

      const isActive =
        row.classList.contains(
          'active'
        );

      const expanded =
        step.classList.contains(
          'aurora-network-edit-open'
        );


      /*
       * Clicking the already-selected route means
       * "show/change Network" in Aurora.
       *
       * Stop only this click from reaching app.js so
       * selecting the same Network does not regenerate
       * the Deposit address unnecessarily.
       */
      if (isActive) {
        event.preventDefault();
        event.stopPropagation();

        setExpanded(
          !expanded
        );

        return;
      }


      /*
       * Alternative Network clicks are NOT intercepted.
       *
       * They continue bubbling to the existing app.js
       * [data-deposit-chain] handler, which remains the
       * owner of real Network selection/address loading.
       *
       * Collapse only after that click has propagated.
       */
      if (expanded) {
        window.setTimeout(
          () => {
            setExpanded(false);
          },
          0,
        );
      }
    },
  );


  /*
   * Clicking elsewhere closes the presentation chooser.
   */
  document.addEventListener(
    'click',
    event => {
      if (
        !step.classList.contains(
          'aurora-network-edit-open'
        )
      ) {
        return;
      }

      if (
        step.contains(
          event.target
        )
      ) {
        return;
      }

      setExpanded(false);
    },
  );


  /*
   * Escape closes the chooser and returns focus to
   * the currently-selected Network.
   */
  document.addEventListener(
    'keydown',
    event => {
      if (
        event.key !== 'Escape'
        || !step.classList.contains(
          'aurora-network-edit-open'
        )
      ) {
        return;
      }

      setExpanded(false);

      activeNetworkRow()
        ?.focus();
    },
  );


  /*
   * app.js re-renders Network rows when selection changes.
   * Keep the presentation metadata synchronized without
   * taking ownership of that rendering.
   */
  const observer =
    new MutationObserver(
      () => {
        if (
          !addressPhaseActive()
        ) {
          setExpanded(false);
          return;
        }

        syncAccessibility();
      },
    );


  observer.observe(
    list,
    {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: [
        'class',
      ],
    },
  );


  observer.observe(
    details,
    {
      attributes: true,
      attributeFilter: [
        'class',
      ],
    },
  );


  setExpanded(false);
})();

})();
