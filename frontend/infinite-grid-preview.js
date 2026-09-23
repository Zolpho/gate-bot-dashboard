'use strict';

(() => {
  const previewState = {
    prepared: null,
    draft: null,
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

    const gridNum = optionalValue(
      form,
      'grid_num',
    );

    const priceType = optionalValue(
      form,
      'price_type',
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

      profit_per_grid: String(
        form.get('profit_per_grid')
        || ''
      ).trim(),

      grid_num: (
        gridNum === null
          ? null
          : Number(gridNum)
      ),

      price_type: (
        priceType === null
          ? null
          : Number(priceType)
      ),

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
              + 'Infinity Grid remains preview-only.'
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
            grid.profit_per_grid
            || draft.profit_per_grid
            || '—'
          ),
        ),

        reviewMetric(
          'Number of grids',
          (
            grid.grid_num
            ?? 'Gate default'
          ),
        ),

        reviewMetric(
          'Grid type',
          (
            grid.price_type
            || 'Gate default'
          ),
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
      !errors.length
      && !warnings.length
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
      const result = await adminApi(
        '/api/bot-control/infinite-grid/prepare',
        {
          method: 'POST',
          body: JSON.stringify(
            draft
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
