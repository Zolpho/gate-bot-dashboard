(() => {
  'use strict';

  const STORAGE_KEY =
    'gate-dashboard-ui';

  const MODES = new Set([
    'classic',
    'aurora',
  ]);

  const THEME_COLORS = {
    classic: '#0b1110',
    aurora: '#030907',
  };

  const readStoredMode = () => {
    try {
      const value = String(
        window.localStorage.getItem(
          STORAGE_KEY
        ) || ''
      ).trim().toLowerCase();

      if (MODES.has(value)) {
        return value;
      }
    } catch (_) {
      // Storage can be unavailable.
    }

    return 'classic';
  };

  const writeStoredMode = mode => {
    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        mode
      );
    } catch (_) {
      // A UI preference must never block
      // the dashboard from loading.
    }
  };

  const mode = readStoredMode();

  document.documentElement.dataset
    .dashboardUi = mode;

  const themeMeta =
    document.querySelector(
      'meta[name="theme-color"]'
    );

  if (themeMeta) {
    themeMeta.setAttribute(
      'content',
      THEME_COLORS[mode]
        || THEME_COLORS.classic
    );
  }

  document.querySelectorAll(
    '[data-dashboard-ui-stylesheet]'
  ).forEach(link => {
    const owner = String(
      link.dataset
        .dashboardUiStylesheet
      || ''
    ).trim().toLowerCase();

    link.disabled = (
      owner !== mode
    );
  });

  window.GateDashboardUi =
    Object.freeze({
      mode,
      storageKey: STORAGE_KEY,
    });

  const installSelector = () => {
    if (
      document.querySelector(
        '[data-dashboard-ui-selector]'
      )
    ) {
      return;
    }

    const host =
      document.querySelector(
        '.topbar'
      );

    if (!host) {
      return;
    }

    const wrapper =
      document.createElement(
        'label'
      );

    wrapper.className =
      'dashboard-ui-switcher';

    wrapper.dataset
      .dashboardUiSelector = '1';

    const label =
      document.createElement(
        'span'
      );

    label.textContent = 'Interface';

    const select =
      document.createElement(
        'select'
      );

    select.className =
      'dashboard-ui-select';

    select.setAttribute(
      'aria-label',
      'Dashboard interface'
    );

    [
      ['classic', 'Classic'],
      ['aurora', 'Aurora'],
    ].forEach(
      ([value, text]) => {
        const option =
          document.createElement(
            'option'
          );

        option.value = value;
        option.textContent = text;

        select.append(
          option
        );
      }
    );

    select.value = mode;

    select.addEventListener(
      'change',
      () => {
        const next = String(
          select.value || ''
        ).trim().toLowerCase();

        if (
          !MODES.has(next)
          || next === mode
        ) {
          select.value = mode;
          return;
        }

        writeStoredMode(
          next
        );

        /*
         * Reload the same application shell.
         *
         * This deliberately restores the
         * canonical DOM before applying a
         * different presentation layer.
         *
         * In-memory admin authorization is
         * therefore not carried across the
         * interface change.
         */
        window.location.reload();
      }
    );

    wrapper.append(
      label,
      select
    );

    host.append(
      wrapper
    );
  };

  if (
    document.readyState
    === 'loading'
  ) {
    document.addEventListener(
      'DOMContentLoaded',
      installSelector,
      {
        once: true,
      }
    );
  } else {
    installSelector();
  }
})();
