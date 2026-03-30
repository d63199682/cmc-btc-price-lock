(function () {
  const shell = document.querySelector('[data-page="entry"]');
  if (!shell) return;

  const form = document.getElementById('entryForm');
  const alertBox = document.getElementById('formAlert');
  const submitButton = document.getElementById('submitButton');
  const confirmationPanel = document.getElementById('confirmationPanel');
  const editAgainButton = document.getElementById('editAgainButton');
  const livePriceEl = document.getElementById('livePrice');
  const entryCountdownEl = document.getElementById('entryCountdown');
  const finalCountdownEl = document.getElementById('finalCountdown');
  const statusBadgeEl = document.getElementById('statusBadge');
  const formHelperEl = document.getElementById('formHelper');

  const state = {
    entryLockMs: Date.parse(shell.dataset.entryLockIso),
    finalMs: Date.parse(shell.dataset.finalTimeIso),
    nowMs: Date.parse(shell.dataset.nowIso),
    entryOpen: shell.dataset.entryOpen === 'true',
    tickInterval: null,
    refreshInterval: null,
    displayNameEdited: false,
  };

  const fieldMessageMap = {
    first_name: 'First name is required.',
    last_name: 'Last name is required.',
    display_name: 'Public display name is required.',
    email: 'Email is required.',
    phone: 'Mobile number is required.',
    country: 'Country of residence is required.',
    industry: 'Please select your industry.',
    prediction: 'Please enter your BTC/USD prediction for 11:00 PM.',
    confirm_resident_age: 'Please confirm that you are a Bermuda resident aged 18 or over.',
    accept_rules: 'Please agree to the Rules and Privacy Notice to continue.',
    consent_admin: 'Please consent to CMC Markets Bermuda administering this activation.',
  };

  const moneyFmt = (value) => {
    const num = Number(String(value).replace(/[$,]/g, ''));
    if (Number.isNaN(num)) return '—';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(num);
  };

  const fmtCountdown = (seconds) => {
    if (seconds <= 0) return '00:00:00';
    const days = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (days > 0) return `${days}d ${String(h).padStart(2, '0')}h ${String(m).padStart(2, '0')}m`;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };

  const showAlert = (message, type = 'error') => {
    if (!message) return;
    alertBox.hidden = false;
    alertBox.textContent = message;
    alertBox.className = `alert ${type}`;
  };

  const scrollToElement = (element) => {
    if (!element) return;
    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  const clearAlert = () => {
    alertBox.hidden = true;
    alertBox.textContent = '';
    alertBox.className = 'alert';
  };

  const clearFieldErrors = () => {
    form.querySelectorAll('.has-error').forEach((el) => el.classList.remove('has-error'));
    form.querySelectorAll('.has-error-line').forEach((el) => el.classList.remove('has-error-line'));
    form.querySelectorAll('[aria-invalid="true"]').forEach((el) => el.removeAttribute('aria-invalid'));
  };

  const locateField = (name) => form.querySelector(`[name="${name}"]`);

  const markFieldError = (name, message) => {
    const field = locateField(name);
    showAlert(message || fieldMessageMap[name] || 'Please review this field.', 'error');
    if (!field) {
      scrollToElement(alertBox);
      return;
    }
    field.setAttribute('aria-invalid', 'true');
    const lineWrap = field.closest('.checkbox-line');
    const fieldWrap = field.closest('.field');
    if (lineWrap) lineWrap.classList.add('has-error-line');
    if (fieldWrap) fieldWrap.classList.add('has-error');
    scrollToElement(lineWrap || fieldWrap || field);
    try {
      field.focus({ preventScroll: true });
    } catch (error) {
      // no-op
    }
  };

  const setFormEnabled = (enabled) => {
    Array.from(form.elements).forEach((el) => {
      if (el === editAgainButton) return;
      el.disabled = !enabled;
    });
    submitButton.disabled = !enabled;
    submitButton.textContent = enabled ? 'Submit prediction' : 'Entries closed';
  };

  const syncCountdowns = () => {
    state.nowMs += 1000;
    const lockLeft = Math.max(0, Math.floor((state.entryLockMs - state.nowMs) / 1000));
    const finalLeft = Math.max(0, Math.floor((state.finalMs - state.nowMs) / 1000));
    entryCountdownEl.textContent = fmtCountdown(lockLeft);
    finalCountdownEl.textContent = fmtCountdown(finalLeft);

    if (lockLeft <= 0) {
      state.entryOpen = false;
      setFormEnabled(false);
      formHelperEl.textContent = 'Entries are now closed. Follow the live dashboard for the final result at 11:00 PM.';
      statusBadgeEl.textContent = finalLeft > 0 ? 'Entries are locked · BTC/USD is still moving' : 'Official BTC/USD result has been locked';
    }
  };

  const generateDisplayName = () => {
    const first = String(form.querySelector('input[name="first_name"]').value || '').trim();
    const last = String(form.querySelector('input[name="last_name"]').value || '').trim();
    if (first && last) return `${first} ${last.charAt(0).toUpperCase()}.`;
    return first || '';
  };

  const hydrateDisplayName = (force = false) => {
    const display = form.querySelector('input[name="display_name"]');
    if (!display) return;
    if (state.displayNameEdited && !force) return;
    const generated = generateDisplayName();
    if (generated) display.value = generated;
  };

  const refreshStatus = async () => {
    try {
      const response = await fetch('/api/status', { cache: 'no-store' });
      if (!response.ok) return;
      const data = await response.json();
      livePriceEl.textContent = moneyFmt(data.live_price);
      state.entryLockMs = Date.parse(data.entry_lock_iso);
      state.finalMs = Date.parse(data.final_time_iso);
      state.nowMs = Date.parse(data.now_iso);
      state.entryOpen = Boolean(data.entry_open);
      statusBadgeEl.textContent = data.status_badge_copy || statusBadgeEl.textContent;
      if (!state.entryOpen) setFormEnabled(false);
    } catch (error) {
      console.error(error);
    }
  };

  const gatherFormData = () => {
    const formData = new FormData(form);
    let displayName = String(formData.get('display_name') || '').trim();
    if (!displayName) {
      displayName = generateDisplayName();
      const displayField = form.querySelector('input[name="display_name"]');
      if (displayField && displayName) displayField.value = displayName;
    }
    return {
      first_name: String(formData.get('first_name') || '').trim(),
      last_name: String(formData.get('last_name') || '').trim(),
      display_name: displayName,
      email: String(formData.get('email') || '').trim(),
      phone: String(formData.get('phone') || '').trim(),
      country: String(formData.get('country') || '').trim(),
      industry: String(formData.get('industry') || '').trim(),
      company: String(formData.get('company') || '').trim(),
      job_title: String(formData.get('job_title') || '').trim(),
      product_interest: formData.getAll('product_interest'),
      prediction: String(formData.get('prediction') || '').trim(),
      confirm_resident_age: Boolean(formData.get('confirm_resident_age')),
      accept_rules: Boolean(formData.get('accept_rules')),
      consent_admin: Boolean(formData.get('consent_admin')),
      marketing_opt_in: Boolean(formData.get('marketing_opt_in')),
    };
  };

  const validatePayload = (payload) => {
    const requiredFields = ['first_name', 'last_name', 'email', 'phone', 'country', 'industry', 'prediction'];
    for (const name of requiredFields) {
      if (!String(payload[name] || '').trim()) {
        markFieldError(name, fieldMessageMap[name]);
        return false;
      }
    }
    if (!payload.display_name) {
      payload.display_name = generateDisplayName();
    }
    if (!payload.display_name || payload.display_name.length < 2) {
      markFieldError('display_name', fieldMessageMap.display_name);
      return false;
    }
    if (payload.country.toLowerCase() !== 'bermuda') {
      markFieldError('country', 'This activation is limited to Bermuda residents.');
      return false;
    }
    const prediction = Number(String(payload.prediction).replace(/,/g, ''));
    if (!Number.isFinite(prediction) || prediction <= 0) {
      markFieldError('prediction', 'Please enter a valid BTC/USD prediction to 2 decimal places.');
      return false;
    }
    if (!payload.confirm_resident_age) {
      markFieldError('confirm_resident_age', fieldMessageMap.confirm_resident_age);
      return false;
    }
    if (!payload.accept_rules) {
      markFieldError('accept_rules', fieldMessageMap.accept_rules);
      return false;
    }
    if (!payload.consent_admin) {
      markFieldError('consent_admin', fieldMessageMap.consent_admin);
      return false;
    }
    return true;
  };

  const updateConfirmation = (participant) => {
    document.getElementById('confirmDisplayName').textContent = participant.display_name;
    document.getElementById('confirmPrediction').textContent = participant.prediction;
    document.getElementById('confirmEntryPrice').textContent = participant.entry_price;
    document.getElementById('confirmDirection').textContent = participant.direction;
    document.getElementById('confirmMargin').textContent = participant.margin_required;
    document.getElementById('confirmCost').textContent = participant.cost_of_trade_negative || participant.cost_of_trade;

    const directionHelp = participant.direction === 'LONG'
      ? 'You believe BTC/USD will be higher than the live price when you entered.'
      : participant.direction === 'SHORT'
        ? 'You believe BTC/USD will be lower than the live price when you entered.'
        : 'You are calling for very little change from the live price.';
    document.getElementById('confirmDirectionHelp').textContent = directionHelp;
    document.getElementById('confirmMarginHelp').textContent = `A minimum of ${Number(participant.margin_percent || 10).toFixed(0)}% of the notional value is needed to place this example trade.`;
    document.getElementById('confirmCostHelp').textContent = `On CMC Markets, this example would cost about ${participant.cost_of_trade} in spread, or ${participant.spread_per_unit} per Bitcoin, for exposure to about ${participant.notional_value} of BTC.`;

    confirmationPanel.hidden = false;
    confirmationPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const extractFieldErrors = (data) => {
    if (!data) return [];
    if (Array.isArray(data.field_errors)) return data.field_errors;
    if (Array.isArray(data.detail)) {
      return data.detail.map((item) => ({
        field: Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : null,
        message: item.msg || 'Please review this field.',
      }));
    }
    return [];
  };

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    clearAlert();
    clearFieldErrors();

    if (!state.entryOpen) {
      showAlert('Entries are now closed.', 'error');
      scrollToElement(alertBox);
      return;
    }

    const payload = gatherFormData();
    if (!validatePayload(payload)) return;

    submitButton.disabled = true;
    submitButton.textContent = 'Submitting…';
    try {
      const response = await fetch('/api/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const fieldErrors = extractFieldErrors(data);
        if (fieldErrors.length) {
          const firstError = fieldErrors[0];
          markFieldError(firstError.field, firstError.message || 'Please review this field.');
        } else if (response.status === 409 || response.status === 429) {
          markFieldError('prediction', data.detail || 'Please review your prediction and try again.');
        } else {
          showAlert(data.detail || 'Unable to submit your entry right now.', 'error');
          scrollToElement(alertBox);
        }
        return;
      }
      showAlert(data.message, 'success');
      updateConfirmation(data.participant);
    } catch (error) {
      showAlert(error.message || 'Something went wrong.', 'error');
      scrollToElement(alertBox);
    } finally {
      submitButton.disabled = !state.entryOpen;
      submitButton.textContent = state.entryOpen ? 'Submit prediction' : 'Entries closed';
    }
  });

  editAgainButton.addEventListener('click', () => {
    confirmationPanel.hidden = true;
    const predictionField = form.querySelector('input[name="prediction"]');
    predictionField.focus();
    predictionField.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });

  const displayField = form.querySelector('input[name="display_name"]');
  const firstField = form.querySelector('input[name="first_name"]');
  const lastField = form.querySelector('input[name="last_name"]');
  if (displayField) {
    displayField.addEventListener('input', () => {
      state.displayNameEdited = displayField.value.trim().length > 0;
    });
  }
  [firstField, lastField].forEach((field) => {
    if (!field) return;
    field.addEventListener('input', () => hydrateDisplayName());
    field.addEventListener('change', () => hydrateDisplayName());
  });

  // Browser autofill often happens after load, so resync a few times.
  [100, 400, 900].forEach((delay) => window.setTimeout(() => hydrateDisplayName(), delay));

  setFormEnabled(state.entryOpen);
  syncCountdowns();
  state.tickInterval = setInterval(syncCountdowns, 1000);
  state.refreshInterval = setInterval(refreshStatus, 60000);
  refreshStatus();
})();
