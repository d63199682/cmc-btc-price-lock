(function () {
  const shell = document.querySelector('[data-page="admin"]');
  if (!shell || shell.dataset.authenticated !== 'true') return;

  const alertBox = document.getElementById('adminAlert');
  const configForm = document.getElementById('adminConfigForm');
  const participantsTableBody = document.getElementById('participantsTableBody');
  const stateStrip = document.getElementById('adminStateStrip');
  const finalReferenceForm = document.getElementById('finalReferenceForm');
  const sendSummaryButton = document.getElementById('sendSummaryButton');

  const moneyFmt = (value) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value || 0));
  const pctFmt = (value) => `${Number(value || 0).toFixed(2)}%`;
  const timeFmt = (isoString) => new Date(isoString).toLocaleString('en-BM', { hour: 'numeric', minute: '2-digit', second: '2-digit', month: 'short', day: 'numeric' });

  const showAlert = (message, type = 'success') => {
    alertBox.hidden = false;
    alertBox.textContent = message;
    alertBox.className = `alert ${type}`;
    window.clearTimeout(showAlert.timer);
    showAlert.timer = window.setTimeout(() => {
      alertBox.hidden = true;
    }, 5000);
  };

  const sourceLabel = (value) => {
    if (value === 'demo') return 'Demo (local simulation)';
    if (value === 'coingecko') return 'CoinGecko';
    if (value === 'coinbase') return 'Coinbase';
    return value || '—';
  };

  const renderState = (state) => {
    stateStrip.innerHTML = [
      `Phase: ${state.phase}`,
      `Live BTC/USD: ${moneyFmt(state.live_price)}`,
      `Price source: ${sourceLabel(state.price_source)}`,
      `Entries open: ${state.entry_open ? 'Yes' : 'No'}`,
      `Entry lock: ${timeFmt(state.entry_lock_iso)}`,
      `Final time: ${timeFmt(state.final_time_iso)}`,
      `Final reference: ${state.final_reference_price ? moneyFmt(state.final_reference_price) : 'Not locked'}`,
    ].map((item) => `<span class="state-chip">${item}</span>`).join('');
  };

  const participantActionMarkup = (participant) => {
    if (participant.is_disqualified) {
      return `<button class="table-button" data-action="reinstate" data-id="${participant.id}">Reinstate</button>`;
    }
    return `<button class="table-button danger" data-action="disqualify" data-id="${participant.id}">Disqualify</button>`;
  };

  const renderParticipants = (participants) => {
    if (!participants.length) {
      participantsTableBody.innerHTML = '<tr><td colspan="10" class="empty-row">No participants yet.</td></tr>';
      return;
    }
    participantsTableBody.innerHTML = participants.map((participant) => {
      const statusClass = participant.is_disqualified ? 'status-tag disqualified' : 'status-tag';
      const statusLabel = participant.is_disqualified ? `Disqualified${participant.disqualification_reason ? `: ${participant.disqualification_reason}` : ''}` : 'Eligible';
      const pnlClass = Number(participant.pnl) >= 0 ? 'pnl-positive' : 'pnl-negative';
      return `
        <tr>
          <td>
            <strong>${participant.display_name}</strong><br>
            <span class="helper-text muted">${participant.email}</span>
          </td>
          <td>
            <div>${participant.phone}</div>
            <div class="helper-text muted">${participant.country}</div>
          </td>
          <td>
            <div>${participant.industry}</div>
            <div class="helper-text muted">${participant.company || '—'}${participant.job_title ? ` · ${participant.job_title}` : ''}</div>
          </td>
          <td>${moneyFmt(participant.prediction)}</td>
          <td>${participant.direction}</td>
          <td class="${pnlClass}">${Number(participant.pnl) >= 0 ? '+' : '-'}${moneyFmt(Math.abs(participant.pnl))}</td>
          <td class="${pnlClass}">${Number(participant.roi) >= 0 ? '+' : ''}${pctFmt(participant.roi)}</td>
          <td>${timeFmt(participant.updated_at)}</td>
          <td><span class="${statusClass}">${statusLabel}</span></td>
          <td><div class="action-row">${participantActionMarkup(participant)}</div></td>
        </tr>
      `;
    }).join('');
  };

  const fetchState = async () => {
    const response = await fetch('/api/admin/state', { cache: 'no-store' });
    if (!response.ok) throw new Error('Unable to load admin state.');
    const data = await response.json();
    renderState(data.state);
    renderParticipants(data.participants || []);
  };

  configForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const formData = new FormData(configForm);
    const payload = {
      public_base_url: String(formData.get('public_base_url') || '').trim(),
      qr_image_url: '',
      event_date_display: String(formData.get('event_date_display') || '').trim(),
      event_series_name: String(formData.get('event_series_name') || '').trim(),
      event_partner_name: String(formData.get('event_partner_name') || '').trim(),
      event_support_copy: String(formData.get('event_support_copy') || '').trim(),
      event_location: String(formData.get('event_location') || '').trim(),
      entry_lock_local: String(formData.get('entry_lock_local') || '').trim(),
      final_time_local: String(formData.get('final_time_local') || '').trim(),
      lead_export_email: String(formData.get('lead_export_email') || '').trim(),
      price_provider: String(formData.get('price_provider') || '').trim(),
      manual_price: Number(formData.get('manual_price') || 0),
      final_reference_price: formData.get('final_reference_price') ? Number(formData.get('final_reference_price')) : null,
      rules: String(formData.get('rules') || '').split('\n').map((item) => item.trim()).filter(Boolean),
      hero_copy: String(formData.get('hero_copy') || '').trim(),
      education_copy: String(formData.get('education_copy') || '').trim(),
      example_copy: String(formData.get('example_copy') || '').trim(),
      saturday_copy: String(formData.get('saturday_copy') || '').trim(),
      status_badge_copy: String(formData.get('status_badge_copy') || '').trim(),
      privacy_notice: String(formData.get('privacy_notice') || '').trim(),
      dashboard_footer: String(formData.get('dashboard_footer') || '').trim(),
      marketing_opt_in_enabled: formData.get('marketing_opt_in_enabled') === 'on',
      leaderboard_size: Number(formData.get('leaderboard_size') || 5),
    };
    try {
      const response = await fetch('/api/admin/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Unable to save settings.');
      showAlert(data.message || 'Settings updated.');
      await fetchState();
    } catch (error) {
      showAlert(error.message || 'Unable to save settings.', 'error');
    }
  });

  finalReferenceForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const formData = new FormData(finalReferenceForm);
    try {
      const response = await fetch('/api/admin/final-reference', {
        method: 'POST',
        body: formData,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Unable to lock final price.');
      showAlert(data.message || 'Final reference price locked.');
      finalReferenceForm.reset();
      await fetchState();
    } catch (error) {
      showAlert(error.message || 'Unable to lock final reference.', 'error');
    }
  });

  participantsTableBody.addEventListener('click', async (event) => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const action = button.dataset.action;
    const id = button.dataset.id;
    try {
      if (action === 'disqualify') {
        const reason = window.prompt('Reason for disqualification:', 'Manual review');
        if (!reason) return;
        const formData = new FormData();
        formData.append('reason', reason);
        const response = await fetch(`/api/admin/disqualify/${id}`, { method: 'POST', body: formData });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Unable to disqualify participant.');
        showAlert('Participant disqualified.');
      } else {
        const response = await fetch(`/api/admin/reinstate/${id}`, { method: 'POST' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Unable to reinstate participant.');
        showAlert('Participant reinstated.');
      }
      await fetchState();
    } catch (error) {
      showAlert(error.message || 'Unable to update participant.', 'error');
    }
  });

  sendSummaryButton.addEventListener('click', async () => {
    try {
      const response = await fetch('/api/admin/send-summary', { method: 'POST' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Unable to send summary email.');
      showAlert(data.message || 'Summary sent.');
    } catch (error) {
      showAlert(error.message || 'Unable to send summary email.', 'error');
    }
  });

  fetchState().catch((error) => showAlert(error.message, 'error'));
  setInterval(() => fetchState().catch(() => undefined), 60000);
})();
