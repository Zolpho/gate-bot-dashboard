'use strict';

(() => {
  const previewState = {
    prepared: null,
    draft: null,

    /*
     * Preserve one request ID across an ambiguous/retryable
     * browser submission. The backend remains authoritative
     * for idempotency.
     */
    requestId: '',
  };

  const query = selector => (
    document.querySelector(selector)
  );


  function selectedInfinityAccountId() {
    return String(
      query('#infiniteGridAccount')?.value
      || query('#spotGridAccount')?.value
      || ''
    )
      .trim()
      .toLowerCase();
  }


  function setInfinityFormError(message = '') {
    const element = query(
      '#infiniteGridFormError'
    );

    if (!element) {
      return;
    }

    element.textContent = message;

    element.classList.toggle(
      'hidden',
      !message,
    );
  }


  function clearInfinityReview(
    message = (
      'Enter the strategy parameters and choose '
      + '<strong>Review Infinity Grid</strong>.'
    ),
  ) {
    previewState.prepared = null;
    previewState.draft = null;
    previewState.requestId = '';

    query(
      '#infiniteGridReview'
    )?.classList.add(
      'hidden'
    );

    const empty = query(
      '#infiniteGridReviewEmpty'
    );

    if (empty) {
      empty.innerHTML = message;
      empty.classList.remove(
        'hidden'
      );
    }

    const status = query(
      '#infiniteGridReviewStatus'
    );

    if (status) {
      status.innerHTML = '';
    }

    const metrics = query(
      '#infiniteGridReviewMetrics'
    );

    if (metrics) {
      metrics.innerHTML = '';
    }

    const validation = query(
      '#infiniteGridValidationMessages'
    );

    if (validation) {
      validation.innerHTML = '';
    }

    const payload = query(
      '#infiniteGridPayloadPreview'
    );

    if (payload) {
      payload.textContent = '';
    }

    const result = query(
      '#infiniteGridCreateResult'
    );

    if (result) {
      result.textContent = '';
      result.classList.add(
        'hidden'
      );
    }

    const openButton = query(
      '#openInfiniteGridConfirmation'
    );

    if (openButton) {
      openButton.disabled = true;
    }

    const confirmationText = query(
      '#infiniteGridConfirmText'
    );

    if (confirmationText) {
      confirmationText.value = '';
    }

    const confirmationError = query(
      '#infiniteGridConfirmError'
    );

    if (confirmationError) {
      confirmationError.textContent = '';
      confirmationError.classList.add(
        'hidden'
      );
    }

    const dialog = query(
      '#infiniteGridConfirmDialog'
    );

    if (dialog?.open) {
      dialog.close();
    }
  }


  function invalidateInfinityReview() {
    if (
      !previewState.prepared
      && !previewState.draft
    ) {
      return;
    }

    clearInfinityReview(
      'Parameters changed. Choose '
      + '<strong>Review Infinity Grid</strong> again.',
    );
  }


  function resetInfinityGridPreviewForm(
    {
      clearAccount = false,
    } = {},
  ) {
    const form = query(
      '#infiniteGridForm'
    );

    if (!form) {
      return;
    }

    const selected = (
      selectedInfinityAccountId()
    );

    form.reset();

    const account = query(
      '#infiniteGridAccount'
    );

    if (account) {
      if (clearAccount) {
        account.innerHTML = '';
        account.value = '';

      } else if (
        selected
        && Array.from(
          account.options
        ).some(
          option => (
            option.value === selected
          )
        )
      ) {
        account.value = selected;
      }
    }

    form.querySelector(
      '.bot-control-advanced'
    )?.removeAttribute(
      'open'
    );

    setInfinityFormError('');
    clearInfinityReview();

    if (clearAccount) {
      const chip = query(
        '#infiniteGridAccountChip'
      );

      if (chip) {
        chip.textContent = '—';
        chip.classList.add(
          'hidden'
        );
      }
    }
  }


  function populateInfinityAccountSelector() {
    const select = query(
      '#infiniteGridAccount'
    );

    if (!select) {
      return;
    }

    const accounts = (
      typeof botControlAccounts === 'function'
        ? botControlAccounts()
        : []
    );

    const previous = (
      select.value
    );

    const spotAccount = String(
      query('#spotGridAccount')?.value
      || ''
    )
      .trim()
      .toLowerCase();

    select.innerHTML = accounts
      .map(account => (
        `<option value="${
          escapeHtml(
            account.account_id
          )
        }">`
        + `${
          escapeHtml(
            account.account_name
            || account.account_id
          )
        }`
        + '</option>'
      ))
      .join('');

    const ids = accounts.map(
      account => account.account_id
    );

    let target = '';

    if (
      spotAccount
      && ids.includes(
        spotAccount
      )
    ) {
      target = spotAccount;

    } else if (
      previous
      && ids.includes(
        previous
      )
    ) {
      target = previous;

    } else if (
      state.selectedAccount
      && ids.includes(
        state.selectedAccount
      )
    ) {
      target = state.selectedAccount;

    } else {
      target = ids[0] || '';
    }

    select.value = target;

    const field = query(
      '#infiniteGridAccountField'
    );

    const chip = query(
      '#infiniteGridAccountChip'
    );

    const singleAccount = (
      accounts.length === 1
    );

    field?.classList.toggle(
      'hidden',
      singleAccount,
    );

    field?.setAttribute(
      'aria-hidden',
      String(
        singleAccount
      ),
    );

    if (chip) {
      const account = (
        singleAccount
          ? accounts[0]
          : null
      );

      chip.textContent = (
        account
          ? (
            account.account_name
            || account.account_id
          )
          : '—'
      );

      chip.classList.toggle(
        'hidden',
        !singleAccount,
      );

      chip.setAttribute(
        'aria-hidden',
        String(
          !singleAccount
        ),
      );
    }
  }


  function syncBotControlAccount(
    accountId,
  ) {
    const normalized = String(
      accountId || ''
    )
      .trim()
      .toLowerCase();

    if (!normalized) {
      return;
    }

    for (const selector of [
      '#spotGridAccount',
      '#infiniteGridAccount',
    ]) {
      const select = query(
        selector
      );

      if (
        select
        && Array.from(
          select.options
        ).some(
          option => (
            option.value === normalized
          )
        )
      ) {
        select.value = normalized;
      }
    }

    if (
      typeof invalidateSpotGridReview
      === 'function'
    ) {
      invalidateSpotGridReview();
    }

    invalidateInfinityReview();

    if (
      typeof renderBotControlCreateState
      === 'function'
    ) {
      renderBotControlCreateState();
    }

    if (
      typeof updateSpotGridConfirmButton
      === 'function'
    ) {
      updateSpotGridConfirmButton();
    }

    if (
      typeof renderSidebarSyncScope
      === 'function'
    ) {
      renderSidebarSyncScope();
    }

    renderInfinityGridCreateState();
    updateInfinityGridConfirmButton();
  }


  function renderInfiniteGridPreviewAccess() {
    populateInfinityAccountSelector();

    const workspace = query(
      '#infiniteGridPreviewWorkspace'
    );

    if (!workspace) {
      return;
    }

    const available = (
      typeof botControlAvailable
      === 'function'
      && botControlAvailable()
    );

    workspace.setAttribute(
      'aria-hidden',
      String(!available),
    );

    renderInfinityGridCreateState();
    updateInfinityGridConfirmButton();
  }


  function infinityGridCreateAvailableForAccount(
    accountId,
  ) {
    return Boolean(
      typeof infinityGridSubmissionAvailableForAccount
        === 'function'
      && infinityGridSubmissionAvailableForAccount(
        accountId
      )
    );
  }


  function renderInfinityGridCreateState() {
    const badge = query(
      '#infiniteGridPreviewState'
    );

    const detail = query(
      '#infiniteGridCreateStateDetail'
    );

    if (!badge) {
      return;
    }

    const armed = Boolean(
      typeof infinityGridCreationArmed
        === 'function'
      && infinityGridCreationArmed()
    );

    const simulation = Boolean(
      typeof botCreationSimulation
        === 'function'
      && botCreationSimulation()
    );

    const liveGloballyEnabled = Boolean(
      typeof botCreationLive
        === 'function'
      && botCreationLive()
    );

    const liveForAccount = Boolean(
      armed
      && liveGloballyEnabled
      && typeof botControlAccountLiveEnabled
        === 'function'
      && botControlAccountLiveEnabled(
        selectedInfinityAccountId()
      )
    );

    if (!armed) {
      badge.textContent = 'REVIEW ONLY';

      if (detail) {
        detail.textContent = (
          'Infinity Create rollout disabled'
        );
      }

    } else if (simulation) {
      badge.textContent = 'SIMULATION';

      if (detail) {
        detail.textContent = 'No Gate write';
      }

    } else if (liveForAccount) {
      badge.textContent = 'LIVE WRITE';

      if (detail) {
        detail.textContent = (
          'Real Gate Infinity create enabled'
        );
      }

    } else if (liveGloballyEnabled) {
      badge.textContent = 'REVIEW ONLY';

      if (detail) {
        detail.textContent = (
          'Creation not armed for this account'
        );
      }

    } else {
      badge.textContent = 'REVIEW ONLY';

      if (detail) {
        detail.textContent = 'Creation disabled';
      }
    }

    badge.className = (
      `status-badge ${
        liveForAccount
          ? 'warning'
          : armed && simulation
            ? 'running'
            : 'disabled'
      }`
    );
  }


  function percentToGateRatioText(
    value,
  ) {
    const raw = String(
      value || ''
    ).trim();

    if (
      !/^\d+(?:\.\d+)?$/.test(
        raw
      )
    ) {
      throw new Error(
        'Profit per grid must be entered as a '
        + 'decimal percentage such as 0.5 or 1.'
      );
    }

    const [
      whole,
      fraction = '',
    ] = raw.split('.');

    const digits = (
      whole + fraction
    ).replace(
      /^0+(?=\d)/,
      '',
    ) || '0';

    const scale = (
      fraction.length + 2
    );

    const padded = (
      digits.padStart(
        scale + 1,
        '0',
      )
    );

    const integerPart = (
      padded.slice(
        0,
        -scale,
      )
      || '0'
    );

    const fractionalPart = (
      padded.slice(
        -scale,
      ).replace(
        /0+$/,
        '',
      )
    );

    return fractionalPart
      ? `${integerPart}.${fractionalPart}`
      : integerPart;
  }


  function optionalValue(
    form,
    name,
  ) {
    const value = String(
      form.get(name) || ''
    ).trim();

    return value || null;
  }


  function infinityGridDraftFromForm(
    formElement,
  ) {
    const form = new FormData(
      formElement
    );

    return {
      account_id: String(
        form.get('account_id')
        || ''
      )
        .trim()
        .toLowerCase(),

      market: String(
        form.get('market')
        || ''
      )
        .trim()
        .toUpperCase(),

      money: String(
        form.get('money')
        || ''
      ).trim(),

      price_floor: String(
        form.get('price_floor')
        || ''
      ).trim(),

      profit_per_grid_percent: String(
        form.get('profit_per_grid_percent')
        || ''
      ).trim(),

      trigger_price: optionalValue(
        form,
        'trigger_price',
      ),

      stop_profit: optionalValue(
        form,
        'stop_profit',
      ),

      stop_loss: optionalValue(
        form,
        'stop_loss',
      ),
    };
  }


  function infinityGridPreparePayloadFromDraft(
    draft,
  ) {
    const {
      profit_per_grid_percent,
      ...payload
    } = draft;

    return {
      ...payload,

      profit_per_grid:
        percentToGateRatioText(
          profit_per_grid_percent
        ),
    };
  }


  function reviewMetric(
    label,
    value,
  ) {
    return (
      '<div class="bot-control-review-item">'
      + `<span>${
        escapeHtml(label)
      }</span>`
      + `<strong>${
        escapeHtml(
          value ?? '—'
        )
      }</strong>`
      + '</div>'
    );
  }


  function renderInfinityGridReview() {
    const prepared = (
      previewState.prepared
    );

    const draft = (
      previewState.draft
    );

    if (
      !prepared
      || !draft
    ) {
      return;
    }

    query(
      '#infiniteGridReviewEmpty'
    )?.classList.add(
      'hidden'
    );

    query(
      '#infiniteGridReview'
    )?.classList.remove(
      'hidden'
    );

    const market = (
      prepared.market
      || {}
    );

    const snapshot = (
      prepared.market_snapshot
      || {}
    );

    const balance = (
      prepared.balance
      || {}
    );

    const grid = (
      prepared.grid
      || {}
    );

    const estimate = (
      prepared.infinity_estimate
      || {}
    );

    const ready = Boolean(
      prepared.can_create
    );

    const status = query(
      '#infiniteGridReviewStatus'
    );

    if (status) {
      status.innerHTML = (
        `<div class="bot-control-message ${
          ready
            ? 'success'
            : 'error'
        }">`
        + (
          ready
            ? (
              'Preflight passed. No Gate write was performed. '
              + 'Review the values below before final confirmation.'
            )
            : (
              'Preflight failed. No Gate write was performed.'
            )
        )
        + '</div>'
      );
    }

    const metrics = query(
      '#infiniteGridReviewMetrics'
    );

    if (metrics) {
      metrics.innerHTML = [
        reviewMetric(
          'Account',
          prepared.account?.name
          || prepared.account?.id,
        ),

        reviewMetric(
          'Market',
          market.id,
        ),

        reviewMetric(
          'Current price',
          snapshot.last
            ? (
              `${snapshot.last} ${
                market.quote || ''
              }`
            )
            : '—',
        ),

        reviewMetric(
          'Investment',
          (
            `${
              balance.requested_investment
              || '—'
            } ${
              market.quote || ''
            }`
          ),
        ),

        reviewMetric(
          'Available balance',
          (
            `${
              balance.available
              || '—'
            } ${
              balance.currency
              || ''
            }`
          ),
        ),

        reviewMetric(
          'Remaining balance',
          (
            balance.remaining_after_investment
              !== null
            && balance.remaining_after_investment
              !== undefined
          )
            ? (
              `${
                balance.remaining_after_investment
              } ${
                balance.currency || ''
              }`
            )
            : '—',
        ),

        reviewMetric(
          'Price floor',
          (
            `${grid.price_floor || draft.price_floor || '—'} `
            + `${market.quote || ''}`
          ),
        ),

        reviewMetric(
          'Profit per grid',
          (
            draft.profit_per_grid_percent
              ? (
                `${
                  draft.profit_per_grid_percent
                }%`
              )
              : '—'
          ),
        ),

        reviewMetric(
          'Gate profit ratio',
          (
            grid.profit_per_grid
            || prepared
              .gate_create_payload_preview
              ?.create_params
              ?.profit_per_grid
            || '—'
          ),
        ),

        reviewMetric(
          'Estimated levels to floor',
          (
            estimate.estimated_levels_to_floor
            ?? '—'
          ),
        ),

        reviewMetric(
          'Estimated Gate minimum',
          (
            estimate.calibrated
            && estimate.estimated_gate_minimum
              ? (
                  `${
                    estimate.estimated_gate_minimum
                  } ${
                    market.quote || ''
                  }`
                )
              : 'Not calibrated for these settings'
          ),
        ),

        reviewMetric(
          'Recommended minimum',
          (
            estimate.calibrated
            && estimate.recommended_minimum
              ? (
                  `${
                    estimate.recommended_minimum
                  } ${
                    market.quote || ''
                  }`
                )
              : '—'
          ),
        ),

        reviewMetric(
          'Infinity ladder',
          'Native geometric · Gate-derived levels',
        ),

        reviewMetric(
          'Upper price',
          'No fixed upper bound',
        ),

        reviewMetric(
          'Gate market status',
          market.trade_status
          || '—',
        ),
      ].join('');
    }

    const errors = (
      prepared.errors
      || []
    );

    const warnings = (
      prepared.warnings
      || []
    );

    const messages = [];

    if (
      !estimate.calibrated
    ) {
      messages.push(
        '<div class="bot-control-message warning">'
        + 'Minimum-investment estimation is not '
        + 'calibrated for these settings. Gate remains '
        + 'authoritative at submission.'
        + '</div>'
      );
    }

    errors.forEach(
      message => {
        messages.push(
          '<div class="bot-control-message error">'
          + `${
            escapeHtml(
              message
            )
          }`
          + '</div>'
        );
      },
    );

    warnings.forEach(
      message => {
        messages.push(
          '<div class="bot-control-message warning">'
          + `${
            escapeHtml(
              message
            )
          }`
          + '</div>'
        );
      },
    );

    if (
      !messages.length
    ) {
      messages.push(
        '<div class="bot-control-message success">'
        + 'No validation warnings.'
        + '</div>'
      );
    }

    const validation = query(
      '#infiniteGridValidationMessages'
    );

    if (validation) {
      validation.innerHTML = (
        messages.join('')
      );
    }

    const payload = query(
      '#infiniteGridPayloadPreview'
    );

    if (payload) {
      payload.textContent = (
        JSON.stringify(
          prepared
            .gate_create_payload_preview,
          null,
          2,
        )
      );
    }

    const openButton = query(
      '#openInfiniteGridConfirmation'
    );

    if (openButton) {
      openButton.disabled = (
        !ready
        || !infinityGridCreateAvailableForAccount(
          draft.account_id
          || selectedInfinityAccountId()
        )
      );
    }

    query(
      '#infiniteGridCreateResult'
    )?.classList.add(
      'hidden'
    );

    renderInfinityGridCreateState();
  }


  function infinityConfirmRow(
    label,
    value,
  ) {
    return (
      '<div class="bot-control-confirm-row">'
      + `<span>${
        escapeHtml(label)
      }</span>`
      + `<strong>${
        escapeHtml(
          value ?? '—'
        )
      }</strong>`
      + '</div>'
    );
  }


  function updateInfinityGridConfirmButton() {
    const button = query(
      '#confirmInfiniteGridCreate'
    );

    if (!button) {
      return;
    }

    const accountId = (
      previewState.draft?.account_id
      || selectedInfinityAccountId()
    );

    const available = (
      infinityGridCreateAvailableForAccount(
        accountId
      )
    );

    const required = (
      typeof botCreationRequiredConfirmation
        === 'function'
        ? botCreationRequiredConfirmation()
        : ''
    );

    button.disabled = !(
      available
      && previewState.prepared?.can_create
      && query(
        '#infiniteGridConfirmText'
      )?.value === required
    );

    button.textContent = (
      typeof botCreationSimulation
        === 'function'
      && botCreationSimulation()
      && typeof botCreationEnabled
        === 'function'
      && !botCreationEnabled()
        ? 'Simulate Infinity Grid'
        : (
          typeof botCreationLive
            === 'function'
          && botCreationLive()
            ? 'Create live Infinity Grid'
            : 'Create Infinity Grid'
        )
    );
  }


  function openInfiniteGridConfirmation() {
    const prepared = (
      previewState.prepared
    );

    const draft = (
      previewState.draft
    );

    if (
      !prepared?.can_create
      || !draft
    ) {
      return;
    }

    const accountId = String(
      draft.account_id || ''
    )
      .trim()
      .toLowerCase();

    if (
      !infinityGridCreateAvailableForAccount(
        accountId
      )
    ) {
      showToast(
        (
          typeof infinityGridCreationArmed
            === 'function'
          && !infinityGridCreationArmed()
        )
          ? (
            'Infinity Grid creation is still '
            + 'disabled by its rollout arm.'
          )
          : (
            'Infinity Grid creation is not '
            + 'available for this account.'
          ),
        true,
      );

      return;
    }

    const market = (
      prepared.market
      || {}
    );

    const balance = (
      prepared.balance
      || {}
    );

    const grid = (
      prepared.grid
      || {}
    );

    const estimate = (
      prepared.infinity_estimate
      || {}
    );

    const optionalRows = [];

    if (draft.trigger_price) {
      optionalRows.push(
        infinityConfirmRow(
          'Trigger price',
          (
            `${draft.trigger_price} ${
              market.quote || ''
            }`
          ),
        ),
      );
    }

    if (draft.stop_profit) {
      optionalRows.push(
        infinityConfirmRow(
          'Take-profit price',
          (
            `${draft.stop_profit} ${
              market.quote || ''
            }`
          ),
        ),
      );
    }

    if (draft.stop_loss) {
      optionalRows.push(
        infinityConfirmRow(
          'Stop-loss price',
          (
            `${draft.stop_loss} ${
              market.quote || ''
            }`
          ),
        ),
      );
    }

    const summary = query(
      '#infiniteGridConfirmSummary'
    );

    if (summary) {
      summary.innerHTML = [
        infinityConfirmRow(
          'Account',
          (
            prepared.account?.name
            || prepared.account?.id
          ),
        ),

        infinityConfirmRow(
          'Market',
          market.id,
        ),

        infinityConfirmRow(
          'Current market price',
          prepared.market_snapshot?.last
            ? (
              `${
                prepared.market_snapshot.last
              } ${market.quote || ''}`
            )
            : '—',
        ),

        infinityConfirmRow(
          'Investment',
          (
            `${draft.money} ${
              market.quote || ''
            }`
          ),
        ),

        infinityConfirmRow(
          'Available before creation',
          (
            `${balance.available || '—'} ${
              balance.currency || ''
            }`
          ),
        ),

        infinityConfirmRow(
          'Remaining after investment',
          (
            balance.remaining_after_investment
              !== null
            && balance.remaining_after_investment
              !== undefined
          )
            ? (
              `${
                balance.remaining_after_investment
              } ${balance.currency || ''}`
            )
            : '—',
        ),

        infinityConfirmRow(
          'Price floor',
          (
            `${
              grid.price_floor
              || draft.price_floor
              || '—'
            } ${market.quote || ''}`
          ),
        ),

        infinityConfirmRow(
          'Profit per grid',
          (
            `${draft.profit_per_grid_percent}%`
          ),
        ),

        infinityConfirmRow(
          'Estimated levels to floor',
          String(
            estimate.estimated_levels_to_floor
            ?? '—'
          ),
        ),

        infinityConfirmRow(
          'Recommended minimum',
          (
            estimate.calibrated
            && estimate.recommended_minimum
              ? (
                  `${
                    estimate.recommended_minimum
                  } ${
                    market.quote || ''
                  }`
                )
              : 'Not calibrated'
          ),
        ),

        infinityConfirmRow(
          'Grid model',
          'Native geometric',
        ),

        ...optionalRows,
      ].join('');
    }

    const simulation = (
      botCreationSimulation()
    );

    const live = Boolean(
      botCreationLive()
      && botControlAccountLiveEnabled(
        accountId
      )
    );

    const notice = query(
      '#infiniteGridCreateNotice'
    );

    if (notice) {
      notice.classList.toggle(
        'enabled',
        live,
      );

      notice.textContent = live
        ? (
          'LIVE GATE WRITE ENABLED. Submitting this '
          + 'confirmation sends a real Infinity Grid '
          + 'creation request to Gate and can place '
          + 'live orders.'
        )
        : simulation
          ? (
            'SIMULATION MODE. This exercises the complete '
            + 'Bot Control workflow and audit trail, but '
            + 'NO request is sent to Gate.'
          )
          : (
            'Infinity Grid creation is unavailable. '
            + 'No Gate write can be submitted.'
          );
    }

    const required = (
      botCreationRequiredConfirmation()
    );

    const requiredElement = query(
      '#infiniteGridRequiredConfirmation'
    );

    if (requiredElement) {
      requiredElement.textContent = required;
    }

    const input = query(
      '#infiniteGridConfirmText'
    );

    if (input) {
      input.placeholder = required;
      input.value = '';
    }

    const error = query(
      '#infiniteGridConfirmError'
    );

    if (error) {
      error.textContent = '';
      error.classList.add(
        'hidden'
      );
    }

    updateInfinityGridConfirmButton();

    const dialog = query(
      '#infiniteGridConfirmDialog'
    );

    if (
      dialog
      && !dialog.open
    ) {
      dialog.showModal();
    }

    setTimeout(
      () => query(
        '#infiniteGridConfirmText'
      )?.focus(),
      0,
    );
  }


  async function submitInfiniteGridCreate() {
    const prepared = (
      previewState.prepared
    );

    const draft = (
      previewState.draft
    );

    if (
      !prepared?.can_create
      || !draft
    ) {
      return;
    }

    const accountId = String(
      draft.account_id || ''
    )
      .trim()
      .toLowerCase();

    if (
      !infinityGridCreateAvailableForAccount(
        accountId
      )
    ) {
      return;
    }

    const button = query(
      '#confirmInfiniteGridCreate'
    );

    const errorBox = query(
      '#infiniteGridConfirmError'
    );

    const modeBefore = (
      botCreationMode()
    );

    const armBefore = (
      infinityGridCreationArmed()
    );

    const availableBefore = (
      infinityGridCreateAvailableForAccount(
        accountId
      )
    );

    try {
      await refreshBotControlRuntimeHealth();

      state.botControlCapabilities = (
        await adminApi(
          '/api/auth/capabilities'
        )
      );

      renderBotControlAccess();

    } catch (error) {
      if (errorBox) {
        errorBox.textContent = (
          'Unable to refresh Bot Control safety '
          + 'state. No Infinity Create request '
          + 'was submitted.'
        );

        errorBox.classList.remove(
          'hidden'
        );
      }

      return;
    }

    const modeAfter = (
      botCreationMode()
    );

    const armAfter = (
      infinityGridCreationArmed()
    );

    const availableAfter = (
      infinityGridCreateAvailableForAccount(
        accountId
      )
    );

    if (
      modeAfter !== modeBefore
      || armAfter !== armBefore
      || availableAfter !== availableBefore
      || !availableAfter
    ) {
      query(
        '#infiniteGridConfirmDialog'
      )?.close();

      showToast(
        'Infinity Grid safety state changed on '
        + 'the server. No Create request was '
        + 'submitted. Review the strategy again.',
        true,
      );

      return;
    }

    const required = (
      botCreationRequiredConfirmation()
    );

    if (
      query(
        '#infiniteGridConfirmText'
      )?.value !== required
    ) {
      return;
    }

    if (!previewState.requestId) {
      previewState.requestId = (
        generateBotControlRequestId(
          'infinite-grid'
        )
      );
    }

    const requestId = (
      previewState.requestId
    );

    const payload = {
      ...infinityGridPreparePayloadFromDraft(
        draft
      ),

      request_id:
        requestId,

      confirmation:
        required,
    };

    if (button) {
      button.disabled = true;

      button.textContent = (
        botCreationLive()
          ? 'Submitting to Gate…'
          : 'Simulating…'
      );
    }

    if (errorBox) {
      errorBox.textContent = '';
      errorBox.classList.add(
        'hidden'
      );
    }

    let result;

    /*
     * Only the backend Create mutation belongs in this
     * try/catch. If it returns successfully, later UI
     * refresh failures must never be presented as a
     * failed/unknown Create submission.
     */
    try {
      result = await adminApi(
        '/api/bot-control/infinite-grid/create',
        {
          method: 'POST',
          body: JSON.stringify(
            payload
          ),
        },
      );

    } catch (error) {
      /*
       * Keep the SAME request ID. Backend audit and
       * idempotency decide whether replay is safe.
       */
      if (errorBox) {
        errorBox.textContent = (
          botControlErrorMessage(
            error
          )
        );

        errorBox.classList.remove(
          'hidden'
        );
      }

      updateInfinityGridConfirmButton();
      return;
    }

    const simulated = Boolean(
      result.simulation
      || result.status === 'simulated'
    );

    query(
      '#infiniteGridConfirmDialog'
    )?.close();

    const inspector = query(
      '#apiInspector'
    );

    if (inspector) {
      inspector.textContent = (
        JSON.stringify(
          result,
          null,
          2,
        )
      );
    }

    const resultBox = query(
      '#infiniteGridCreateResult'
    );

    if (resultBox) {
      resultBox.innerHTML = (
        `<strong>${
          simulated
            ? (
              'Simulation completed. '
              + 'No Gate write performed.'
            )
            : 'Gate submission completed.'
        }</strong>`
        + '<br>'
        + `Request ID: ${
          escapeHtml(
            requestId
          )
        }`
        + '<br>'
        + (
          simulated
            ? (
              'Strategy ID: none · '
              + 'simulation only'
            )
            : (
              `Strategy ID: ${
                escapeHtml(
                  result.strategy?.strategy_id
                  || result.gate?.data?.strategy_id
                  || 'pending'
                )
              }`
            )
        )
      );

      resultBox.classList.remove(
        'hidden'
      );
    }

    showToast(
      simulated
        ? (
          'Infinity Grid simulation completed. '
          + `Request ${requestId}.`
        )
        : (
          'Infinity Grid creation submitted to Gate. '
          + `Request ${requestId}.`
        )
    );

    await openBotControlRequestDetail(
      requestId
    );

    try {
      await loadBotControlActivity({
        quiet: true,
      });

    } catch (_error) {
      showToast(
        'Create succeeded, but Bot Control '
        + 'Activity could not be refreshed. '
        + `Request ${requestId}.`,
        true,
      );
    }

    try {
      await loadCore();

    } catch (_error) {
      showToast(
        'Create succeeded, but the dashboard '
        + 'could not be refreshed. '
        + `Request ${requestId}.`,
        true,
      );
    }

    updateInfinityGridConfirmButton();
  }


  async function prepareInfiniteGrid(
    event,
  ) {
    event.preventDefault();

    if (
      typeof botControlAvailable
      !== 'function'
      || !botControlAvailable()
    ) {
      openAdminDialog();
      return;
    }

    const formElement = (
      event.currentTarget
    );

    const button = query(
      '#prepareInfiniteGridButton'
    );

    setInfinityFormError('');

    previewState.prepared = null;
    previewState.draft = null;
    previewState.requestId = '';

    const draft = (
      infinityGridDraftFromForm(
        formElement
      )
    );

    if (button) {
      button.disabled = true;
      button.textContent = (
        'Checking Gate…'
      );
    }

    try {
      const requestPayload = (
        infinityGridPreparePayloadFromDraft(
          draft
        )
      );

      const result = await adminApi(
        '/api/bot-control/infinite-grid/prepare',
        {
          method: 'POST',
          body: JSON.stringify(
            requestPayload
          ),
        },
      );

      if (
        result.write_performed
        !== false
      ) {
        throw new Error(
          'Safety invariant failed: Infinity '
          + 'prepare reported a write.'
        );
      }

      previewState.draft = draft;
      previewState.prepared = result;

      renderInfinityGridReview();

    } catch (error) {
      setInfinityFormError(
        botControlErrorMessage(
          error
        )
      );

    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = (
          'Review Infinity Grid'
        );
      }
    }
  }


  function install() {
    query(
      '#infiniteGridForm'
    )?.addEventListener(
      'submit',
      prepareInfiniteGrid,
    );

    query(
      '#resetInfiniteGridButton'
    )?.addEventListener(
      'click',
      () => (
        resetInfinityGridPreviewForm()
      ),
    );

    query(
      '#infiniteGridForm'
    )?.addEventListener(
      'input',
      invalidateInfinityReview,
    );

    query(
      '#infiniteGridForm'
    )?.addEventListener(
      'change',
      invalidateInfinityReview,
    );

    query(
      '#infiniteGridAccount'
    )?.addEventListener(
      'change',
      event => (
        syncBotControlAccount(
          event.currentTarget.value
        )
      ),
    );

    query(
      '#spotGridAccount'
    )?.addEventListener(
      'change',
      event => (
        syncBotControlAccount(
          event.currentTarget.value
        )
      ),
    );

    query(
      '#openInfiniteGridConfirmation'
    )?.addEventListener(
      'click',
      openInfiniteGridConfirmation,
    );

    query(
      '#infiniteGridConfirmText'
    )?.addEventListener(
      'input',
      updateInfinityGridConfirmButton,
    );

    query(
      '#confirmInfiniteGridCreate'
    )?.addEventListener(
      'click',
      submitInfiniteGridCreate,
    );

    query(
      '#closeInfiniteGridConfirmDialog'
    )?.addEventListener(
      'click',
      () => query(
        '#infiniteGridConfirmDialog'
      )?.close(),
    );

    query(
      '#cancelInfiniteGridCreate'
    )?.addEventListener(
      'click',
      () => query(
        '#infiniteGridConfirmDialog'
      )?.close(),
    );

    query(
      '#infiniteGridConfirmDialog'
    )?.addEventListener(
      'click',
      event => {
        if (
          event.target
          === query(
            '#infiniteGridConfirmDialog'
          )
        ) {
          query(
            '#infiniteGridConfirmDialog'
          )?.close();
        }
      },
    );

    renderInfiniteGridPreviewAccess();
  }


  window.renderInfiniteGridPreviewAccess = (
    renderInfiniteGridPreviewAccess
  );

  window.resetInfiniteGridPreviewForm = (
    resetInfinityGridPreviewForm
  );

  if (
    document.readyState
    === 'loading'
  ) {
    document.addEventListener(
      'DOMContentLoaded',
      install,
      {
        once: true,
      },
    );

  } else {
    install();
  }
})();
