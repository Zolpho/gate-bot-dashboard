(() => {
  'use strict';

  /*
   * Rootadmin Wallet-account authorization control surface.
   *
   * Shared by Classic and Aurora.
   *
   * This module changes local dashboard policy only.
   * No Treasury, Trading, Bot Control, Bot, or Gate
   * execution endpoint is referenced here.
   */

  const permissionsState = {
    items: [],
    loading: false,
    saving: new Set(),
    historyLoading: new Set(),
  };

  const capabilityDefinitions = [
    {
      key: 'transfers_enabled',
      title: 'Transfers',
      description: (
        'Direct Wallet transfers from this account. '
        + 'Withdrawal JIT funding is governed by '
        + 'Withdrawals instead.'
      ),
    },
    {
      key: 'withdrawals_enabled',
      title: 'Withdrawals',
      description: (
        'Withdrawal JIT funding and external Gate '
        + 'withdrawal for this owner Wallet account.'
      ),
    },
    {
      key: 'trading_enabled',
      title: 'Trading',
      description: (
        'New Spot Grid/manual orders and amendments. '
        + 'Bot Stop and order cancellation stay '
        + 'risk-reducing and separate.'
      ),
    },
  ];

  const textValue = value => String(
    value === null || value === undefined
      ? ''
      : value
  );

  const escapePolicyHtml = value => (
    textValue(value)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;')
  );

  const isRootAdmin = () => Boolean(
    state.adminUser
    && state.adminAuthorization
    && state.adminUser.role === 'super_admin'
  );

  const accountPolicy = accountId => (
    permissionsState.items.find(
      item => (
        textValue(item.account_id).toLowerCase()
        === textValue(accountId).toLowerCase()
      )
    )
    || null
  );

  const accountLabel = policy => (
    textValue(
      policy.account_name
      || policy.account_id
    ).trim()
    || 'Wallet account'
  );

  const formatPolicyTime = value => {
    const raw = textValue(value).trim();

    if (!raw) {
      return 'Never';
    }

    const parsed = new Date(raw);

    if (Number.isNaN(parsed.getTime())) {
      return raw;
    }

    return parsed.toLocaleString();
  };

  const setPermissionsError = (
    message = ''
  ) => {
    const box = document.querySelector(
      '#accountPermissionsError'
    );

    if (!box) {
      return;
    }

    const normalized = textValue(
      message
    ).trim();

    box.textContent = normalized;

    box.classList.toggle(
      'hidden',
      !normalized
    );
  };

  const setPermissionsLoading = loading => {
    permissionsState.loading = Boolean(
      loading
    );

    document.querySelector(
      '#accountPermissionsLoading'
    )?.classList.toggle(
      'hidden',
      !permissionsState.loading
    );

    const refresh = document.querySelector(
      '#refreshAccountPermissions'
    );

    if (refresh) {
      refresh.disabled = (
        permissionsState.loading
      );
    }
  };

  const policyHistoryBody = accountId => {
    const normalized = textValue(
      accountId
    );

    return Array.from(
      document.querySelectorAll(
        '[data-account-policy-history-body]'
      )
    ).find(
      item => (
        textValue(
          item.dataset
            .accountPolicyHistoryBody
        ) === normalized
      )
    ) || null;
  };

  const changedPolicyValues = (
    card,
    policy
  ) => {
    const payload = {};

    capabilityDefinitions.forEach(
      definition => {
        const input = card.querySelector(
          (
            '[data-account-policy-capability="'
            + definition.key
            + '"]'
          )
        );

        if (!input) {
          return;
        }

        const requested = Boolean(
          input.checked
        );

        const stored = Boolean(
          policy[definition.key]
        );

        if (requested !== stored) {
          payload[definition.key] = (
            requested
          );
        }
      }
    );

    return payload;
  };

  const updatePolicySaveState = card => {
    if (!card) {
      return;
    }

    const accountId = textValue(
      card.dataset.accountPolicyCard
    ).trim();

    const policy = accountPolicy(
      accountId
    );

    const button = card.querySelector(
      '[data-account-policy-save]'
    );

    if (!policy || !button) {
      return;
    }

    const reason = textValue(
      card.querySelector(
        '[data-account-policy-reason]'
      )?.value
    ).trim();

    const hasChanges = (
      Object.keys(
        changedPolicyValues(
          card,
          policy
        )
      ).length > 0
    );

    const saving = (
      permissionsState.saving.has(
        accountId
      )
    );

    button.disabled = Boolean(
      !hasChanges
      || reason.length < 10
      || saving
    );

    button.textContent = (
      saving
        ? 'Saving…'
        : 'Save policy'
    );

    const helper = card.querySelector(
      '[data-account-policy-save-helper]'
    );

    if (!helper) {
      return;
    }

    if (!hasChanges) {
      helper.textContent = (
        'No unsaved permission changes.'
      );
    } else if (reason.length < 10) {
      helper.textContent = (
        'Add a reason of at least 10 characters.'
      );
    } else {
      helper.textContent = (
        'Ready to save this Wallet account policy.'
      );
    }
  };

  const capabilityHtml = (
    policy,
    definition
  ) => {
    const checked = Boolean(
      policy[definition.key]
    );

    return `
      <label class="account-policy-capability">
        <span class="account-policy-capability-copy">
          <strong>${escapePolicyHtml(
            definition.title
          )}</strong>

          <small>${escapePolicyHtml(
            definition.description
          )}</small>
        </span>

        <span class="account-policy-switch">
          <input
            type="checkbox"
            data-account-policy-capability="${escapePolicyHtml(
              definition.key
            )}"
            ${checked ? 'checked' : ''}
            aria-label="${escapePolicyHtml(
              (
                definition.title
                + ' for '
                + accountLabel(policy)
              )
            )}"
          >

          <span
            class="account-policy-switch-track"
            aria-hidden="true"
          ></span>
        </span>
      </label>
    `;
  };

  const policyCardHtml = policy => {
    const accountId = textValue(
      policy.account_id
    );

    const statusClass = (
      policy.exists
        ? 'configured'
        : 'fail-closed'
    );

    const statusLabel = (
      policy.exists
        ? 'Configured'
        : 'Fail closed · not configured'
    );

    const accountState = (
      policy.account_enabled
        ? 'Enabled'
        : 'Disabled'
    );

    const gateConfigState = (
      policy.account_configured
        ? 'Configured'
        : 'Not configured'
    );

    const type = textValue(
      policy.account_type
    ).trim();

    return `
      <article
        class="account-policy-card"
        data-account-policy-card="${escapePolicyHtml(
          accountId
        )}"
      >
        <div class="account-policy-card-head">
          <div class="account-policy-identity">
            <span>Wallet account</span>

            <strong>${escapePolicyHtml(
              accountLabel(policy)
            )}</strong>

            <code>${escapePolicyHtml(
              accountId
            )}</code>
          </div>

          <span
            class="account-policy-status ${statusClass}"
          >
            ${escapePolicyHtml(
              statusLabel
            )}
          </span>
        </div>

        <div class="account-policy-meta">
          <span>
            <small>Last updated</small>
            <strong>${escapePolicyHtml(
              formatPolicyTime(
                policy.updated_at
              )
            )}</strong>
          </span>

          <span>
            <small>Actor</small>
            <strong>${escapePolicyHtml(
              policy.updated_by || '—'
            )}</strong>
          </span>

          <span>
            <small>Wallet state</small>
            <strong>${escapePolicyHtml(
              accountState
            )}</strong>
          </span>

          <span>
            <small>Gate config</small>
            <strong>${escapePolicyHtml(
              gateConfigState
            )}</strong>
          </span>

          ${type
            ? `
              <span>
                <small>Account type</small>
                <strong>${escapePolicyHtml(
                  type
                )}</strong>
              </span>
            `
            : ''
          }
        </div>

        <div class="account-policy-capabilities">
          ${capabilityDefinitions.map(
            definition => capabilityHtml(
              policy,
              definition
            )
          ).join('')}
        </div>

        <div class="account-policy-save-zone">
          <label>
            <span>Change reason</span>

            <textarea
              rows="2"
              minlength="10"
              maxlength="1000"
              data-account-policy-reason
              placeholder="Explain why these permissions are changing."
            ></textarea>
          </label>

          <div class="account-policy-save-actions">
            <span
              class="account-policy-save-helper"
              data-account-policy-save-helper
            >
              No unsaved permission changes.
            </span>

            <button
              type="button"
              class="button primary"
              data-account-policy-save="${escapePolicyHtml(
                accountId
              )}"
              disabled
            >
              Save policy
            </button>
          </div>
        </div>

        <details class="account-policy-history">
          <summary>
            <span>Policy history</span>
            <small>Audit events</small>
          </summary>

          <div
            class="account-policy-history-body"
            data-account-policy-history-body="${escapePolicyHtml(
              accountId
            )}"
          >
            <button
              type="button"
              class="button secondary"
              data-account-policy-history-load="${escapePolicyHtml(
                accountId
              )}"
            >
              Load history
            </button>
          </div>
        </details>
      </article>
    `;
  };

  const renderPolicyList = () => {
    const list = document.querySelector(
      '#accountPermissionsList'
    );

    if (!list) {
      return;
    }

    if (!isRootAdmin()) {
      list.innerHTML = '';
      return;
    }

    if (!permissionsState.items.length) {
      list.innerHTML = `
        <div class="account-permissions-empty">
          No Wallet accounts are available.
        </div>
      `;

      return;
    }

    list.innerHTML = (
      permissionsState.items
        .map(policyCardHtml)
        .join('')
    );

    list.querySelectorAll(
      '[data-account-policy-card]'
    ).forEach(
      card => {
        updatePolicySaveState(
          card
        );
      }
    );
  };

  const renderPolicyHistory = (
    accountId,
    events
  ) => {
    const body = policyHistoryBody(
      accountId
    );

    if (!body) {
      return;
    }

    if (!events.length) {
      body.innerHTML = `
        <div class="account-policy-history-empty">
          No policy events recorded.
        </div>
      `;

      return;
    }

    body.innerHTML = `
      <div class="account-policy-history-list">
        ${events.map(
          event => {
            const oldState = (
              event.old_enabled === null
              || event.old_enabled === undefined
                ? 'unset'
                : (
                    event.old_enabled
                      ? 'enabled'
                      : 'disabled'
                  )
            );

            const newState = (
              event.new_enabled
                ? 'enabled'
                : 'disabled'
            );

            return `
              <div class="account-policy-event">
                <div class="account-policy-event-head">
                  <strong>${escapePolicyHtml(
                    textValue(
                      event.capability
                    ).replaceAll(
                      '_',
                      ' '
                    )
                  )}</strong>

                  <time>${escapePolicyHtml(
                    formatPolicyTime(
                      event.created_at
                    )
                  )}</time>
                </div>

                <div class="account-policy-event-change">
                  <span>${escapePolicyHtml(
                    oldState
                  )}</span>

                  <b aria-hidden="true">→</b>

                  <span>${escapePolicyHtml(
                    newState
                  )}</span>
                </div>

                <div class="account-policy-event-meta">
                  <span>
                    Actor
                    <strong>${escapePolicyHtml(
                      event.username || '—'
                    )}</strong>
                  </span>

                  <span>
                    Reason
                    <strong>${escapePolicyHtml(
                      event.reason || '—'
                    )}</strong>
                  </span>
                </div>
              </div>
            `;
          }
        ).join('')}
      </div>
    `;
  };

  const loadPolicyHistory = async accountId => {
    if (
      !isRootAdmin()
      || !accountId
      || permissionsState
        .historyLoading
        .has(accountId)
    ) {
      return;
    }

    const body = policyHistoryBody(
      accountId
    );

    if (!body) {
      return;
    }

    permissionsState
      .historyLoading
      .add(accountId);

    body.innerHTML = `
      <div class="account-policy-history-loading">
        Loading policy history…
      </div>
    `;

    try {
      const result = await adminApi(
        (
          '/api/auth/account-policies/'
          + encodeURIComponent(accountId)
          + '/events?limit=200'
        )
      );

      if (
        result.gate_write_performed
        !== false
      ) {
        throw new Error(
          'Safety invariant failed: policy history '
          + 'lookup reported a Gate write.'
        );
      }

      renderPolicyHistory(
        accountId,
        Array.isArray(result.items)
          ? result.items
          : []
      );

    } catch (error) {
      if (
        staleAdminSessionError(error)
      ) {
        return;
      }

      body.innerHTML = `
        <div class="account-policy-history-error">
          ${escapePolicyHtml(
            error.message
            || 'Unable to load policy history.'
          )}
        </div>
      `;

      showToast(
        (
          error.message
          || 'Unable to load policy history.'
        ),
        true
      );

    } finally {
      permissionsState
        .historyLoading
        .delete(accountId);
    }
  };

  const loadAccountPermissions = async ({
    quiet = false,
  } = {}) => {
    if (!isRootAdmin()) {
      return;
    }

    setPermissionsError('');
    setPermissionsLoading(true);

    try {
      const result = await adminApi(
        '/api/auth/account-policies'
      );

      if (
        result.gate_write_performed
        !== false
      ) {
        throw new Error(
          'Safety invariant failed: policy listing '
          + 'reported a Gate write.'
        );
      }

      permissionsState.items = (
        Array.isArray(result.items)
          ? result.items
          : []
      );

      renderPolicyList();

    } catch (error) {
      if (
        staleAdminSessionError(error)
      ) {
        return;
      }

      const message = (
        error.message
        || 'Unable to load Wallet account policies.'
      );

      setPermissionsError(
        message
      );

      if (!quiet) {
        showToast(
          message,
          true
        );
      }

    } finally {
      setPermissionsLoading(false);
    }
  };

  const saveAccountPolicy = async (
    accountId,
    button
  ) => {
    if (
      !isRootAdmin()
      || !accountId
      || permissionsState.saving.has(
        accountId
      )
    ) {
      return;
    }

    const policy = accountPolicy(
      accountId
    );

    const card = button.closest(
      '[data-account-policy-card]'
    );

    if (!policy || !card) {
      return;
    }

    const changes = changedPolicyValues(
      card,
      policy
    );

    const reason = textValue(
      card.querySelector(
        '[data-account-policy-reason]'
      )?.value
    ).trim();

    if (!Object.keys(changes).length) {
      showToast(
        'No Wallet account permission changes to save.',
        true
      );

      return;
    }

    if (reason.length < 10) {
      showToast(
        'Add a change reason of at least 10 characters.',
        true
      );

      card.querySelector(
        '[data-account-policy-reason]'
      )?.focus();

      return;
    }

    permissionsState.saving.add(
      accountId
    );

    updatePolicySaveState(
      card
    );

    setPermissionsError('');

    try {
      const result = await adminApi(
        (
          '/api/auth/account-policies/'
          + encodeURIComponent(accountId)
        ),
        {
          method: 'PATCH',
          body: JSON.stringify({
            ...changes,
            reason,
          }),
        }
      );

      if (
        result.gate_write_performed
        !== false
      ) {
        throw new Error(
          'Safety invariant failed: policy update '
          + 'reported a Gate write.'
        );
      }

      if (result.policy) {
        Object.assign(
          policy,
          result.policy
        );
      }

      renderPolicyList();

      showToast(
        (
          result.status === 'unchanged'
            ? (
                'No policy change for '
                + accountId
                + '.'
              )
            : (
                'Wallet account policy updated for '
                + accountId
                + '.'
              )
        )
      );

    } catch (error) {
      if (
        staleAdminSessionError(error)
      ) {
        return;
      }

      const message = (
        error.message
        || 'Unable to update Wallet account policy.'
      );

      setPermissionsError(
        message
      );

      showToast(
        message,
        true
      );

    } finally {
      permissionsState.saving.delete(
        accountId
      );

      document.querySelectorAll(
        '[data-account-policy-card]'
      ).forEach(
        item => {
          updatePolicySaveState(
            item
          );
        }
      );
    }
  };

  const closeAccountPermissionsDialog = () => {
    const dialog = document.querySelector(
      '#accountPermissionsDialog'
    );

    if (dialog?.open) {
      dialog.close();
    }
  };

  const clearAccountPermissionsState = () => {
    permissionsState.items = [];
    permissionsState.loading = false;
    permissionsState.saving.clear();
    permissionsState.historyLoading.clear();

    setPermissionsError('');
    setPermissionsLoading(false);

    const list = document.querySelector(
      '#accountPermissionsList'
    );

    if (list) {
      list.innerHTML = '';
    }

    closeAccountPermissionsDialog();
  };

  const renderAccountPermissionsAccess = () => {
    const button = document.querySelector(
      '#accountPermissionsButton'
    );

    if (!button) {
      return;
    }

    const visible = isRootAdmin();

    button.classList.toggle(
      'hidden',
      !visible
    );

    button.setAttribute(
      'aria-hidden',
      String(!visible)
    );

    button.tabIndex = (
      visible
        ? 0
        : -1
    );

    if (!visible) {
      clearAccountPermissionsState();
    }
  };

  const openAccountPermissionsDialog = async () => {
    if (!isRootAdmin()) {
      showToast(
        (
          'Only the root administrator can manage '
          + 'Wallet account permissions.'
        ),
        true
      );

      return;
    }

    const dialog = document.querySelector(
      '#accountPermissionsDialog'
    );

    if (!dialog) {
      return;
    }

    if (!dialog.open) {
      dialog.showModal();
    }

    await loadAccountPermissions();
  };

  const list = document.querySelector(
    '#accountPermissionsList'
  );

  list?.addEventListener(
    'input',
    event => {
      const card = event.target.closest(
        '[data-account-policy-card]'
      );

      if (card) {
        updatePolicySaveState(
          card
        );
      }
    }
  );

  list?.addEventListener(
    'change',
    event => {
      const card = event.target.closest(
        '[data-account-policy-card]'
      );

      if (card) {
        updatePolicySaveState(
          card
        );
      }
    }
  );

  list?.addEventListener(
    'click',
    event => {
      const saveButton = event.target.closest(
        '[data-account-policy-save]'
      );

      if (saveButton) {
        void saveAccountPolicy(
          textValue(
            saveButton.dataset
              .accountPolicySave
          ),
          saveButton
        );

        return;
      }

      const historyButton = (
        event.target.closest(
          '[data-account-policy-history-load]'
        )
      );

      if (historyButton) {
        void loadPolicyHistory(
          textValue(
            historyButton.dataset
              .accountPolicyHistoryLoad
          )
        );
      }
    }
  );

  document.querySelector(
    '#accountPermissionsButton'
  )?.addEventListener(
    'click',
    () => {
      void openAccountPermissionsDialog();
    }
  );

  document.querySelector(
    '#closeAccountPermissionsDialog'
  )?.addEventListener(
    'click',
    closeAccountPermissionsDialog
  );

  document.querySelector(
    '#refreshAccountPermissions'
  )?.addEventListener(
    'click',
    () => {
      void loadAccountPermissions();
    }
  );

  document.querySelector(
    '#accountPermissionsDialog'
  )?.addEventListener(
    'click',
    event => {
      if (
        event.target
        === document.querySelector(
          '#accountPermissionsDialog'
        )
      ) {
        closeAccountPermissionsDialog();
      }
    }
  );

  window.renderAccountPermissionsAccess = (
    renderAccountPermissionsAccess
  );

  window.clearAccountPermissionsState = (
    clearAccountPermissionsState
  );

  /*
   * app.js executes first. Its initial auth render may
   * therefore happen before these hooks exist. Reconcile
   * the rootadmin button immediately after installation.
   */
  renderAccountPermissionsAccess();
})();
