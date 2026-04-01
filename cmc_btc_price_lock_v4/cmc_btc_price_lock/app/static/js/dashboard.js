(function () {
  const shell = document.querySelector('[data-page="dashboard"]');
  if (!shell) return;

  const els = {
    livePrice: document.getElementById('boardLivePrice'),
    livePriceCard: document.querySelector('.dashboard-stat-live'),
    lockCountdown: document.getElementById('boardLockCountdown'),
    finalCountdown: document.getElementById('boardFinalCountdown'),
    lastUpdate: document.getElementById('boardLastUpdate'),
    entryStateBanner: document.getElementById('entryStateBanner'),
    saturdayCopy: document.getElementById('dashboardSaturdayCopy'),
    leaderboardEyebrow: document.getElementById('leaderboardEyebrow'),
    leaderboardTitle: document.getElementById('leaderboardTitle'),
    leaderboardSubcopy: document.getElementById('leaderboardSubcopy'),
    winnerBadge: document.getElementById('winnerBadge'),
    leaderboardBody: document.getElementById('leaderboardBody'),
    tickerTrack: document.getElementById('tickerTrack'),
    exampleCopy: document.getElementById('dashboardExampleCopy'),
    dashboardFooter: document.getElementById('dashboardFooter'),
    dashboardRules: document.getElementById('dashboardRules'),
  };

  const state = {
    nowMs: Date.now(),
    entryLockMs: Date.now(),
    finalMs: Date.now(),
    phase: 'open',
    previousLivePrice: null,
  };

  const moneyFmt = (value) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value || 0));
  const pctFmt = (value) => `${Number(value || 0).toFixed(2)}%`;
  const countdownFmt = (seconds) => {
    if (seconds <= 0) return '00:00:00';
    const days = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (days > 0) return `${days}d ${String(h).padStart(2, '0')}h ${String(m).padStart(2, '0')}m`;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };
  const timeFmt = (isoString) => {
    if (!isoString) return '—';
    const date = new Date(isoString);
    return date.toLocaleTimeString('en-BM', { hour: 'numeric', minute: '2-digit', second: '2-digit' });
  };

  const flashLivePrice = (nextPrice) => {
    if (!els.livePriceCard) return;
    if (state.previousLivePrice === null || Number(nextPrice) === Number(state.previousLivePrice)) {
      state.previousLivePrice = Number(nextPrice);
      return;
    }
    els.livePriceCard.classList.remove('price-flash-up', 'price-flash-down');
    void els.livePriceCard.offsetWidth;
    const cls = Number(nextPrice) > Number(state.previousLivePrice) ? 'price-flash-up' : 'price-flash-down';
    els.livePriceCard.classList.add(cls);
    state.previousLivePrice = Number(nextPrice);
  };

  const renderWinnerBadge = (label, winner = false) => {
    els.winnerBadge.innerHTML = `<span class="badge-icon" aria-hidden="true">🏆</span> ${label}`;
    if (winner) els.winnerBadge.classList.add('winner-glow');
    else els.winnerBadge.classList.remove('winner-glow');
  };

  const updateCountdowns = () => {
    state.nowMs += 1000;
    const lockLeft = Math.max(0, Math.floor((state.entryLockMs - state.nowMs) / 1000));
    const finalLeft = Math.max(0, Math.floor((state.finalMs - state.nowMs) / 1000));
    els.lockCountdown.textContent = countdownFmt(lockLeft);
    els.finalCountdown.textContent = countdownFmt(finalLeft);
  };

  const renderRules = (rules) => {
    els.dashboardRules.innerHTML = '';
    rules.slice(0, 4).forEach((rule) => {
      const div = document.createElement('div');
      div.textContent = rule;
      els.dashboardRules.appendChild(div);
    });
  };

  const renderTicker = (ticker) => {
    els.tickerTrack.innerHTML = '';
    if (!ticker.length) {
      const pill = document.createElement('div');
      pill.className = 'ticker-pill';
      pill.textContent = 'Waiting for the next prediction';
      els.tickerTrack.appendChild(pill);
      return;
    }
    ticker.slice(0, 5).forEach((item) => {
      const pill = document.createElement('div');
      pill.className = 'ticker-pill';
      pill.textContent = item.message;
      els.tickerTrack.appendChild(pill);
    });
  };

  const rankMarkup = (phase, index) => {
    if (phase === 'final' && index === 0) {
      return `<span class="rank-pill winner"><span class="badge-icon" aria-hidden="true">🏆</span> Winner</span>`;
    }
    if (index === 0) return '<span class="rank-pill leader">Current leader</span>';
    return `#${index + 1}`;
  };

  const renderLeaders = (leaders, phase, finalReferencePrice) => {
    if (!leaders.length) {
      els.leaderboardBody.innerHTML = '<tr><td colspan="10" class="empty-row">Waiting for the first predictions…</td></tr>';
    } else {
      els.leaderboardBody.innerHTML = leaders.map((row, index) => {
        const winnerClass = phase === 'final' && index === 0 ? 'winner-row' : '';
        const pnlClass = Number(row.pnl) >= 0 ? 'pnl-positive' : 'pnl-negative';
        return `
          <tr class="${winnerClass}">
            <td class="rank-cell">${rankMarkup(phase, index)}</td>
            <td>${row.display_name}<br><span class="helper-text muted">${moneyFmt(row.distance)} away</span></td>
            <td>${moneyFmt(row.entry_price)}</td>
            <td>${moneyFmt(row.prediction)}</td>
            <td>${row.direction}</td>
            <td>${moneyFmt(row.position_value)}</td>
            <td>${moneyFmt(row.entry_margin_required)}</td>
            <td>-${moneyFmt(row.cost_of_trade).replace('$', '$')}</td>
            <td class="${pnlClass}">${Number(row.pnl) >= 0 ? '+' : '-'}${moneyFmt(Math.abs(row.pnl))}</td>
            <td class="${pnlClass}">${Number(row.roi) >= 0 ? '+' : ''}${pctFmt(row.roi)}</td>
          </tr>
        `;
      }).join('');
    }

    if (phase === 'final' && typeof finalReferencePrice === 'number') {
      els.leaderboardEyebrow.textContent = 'Official result';
      els.leaderboardTitle.textContent = `Winner locked to the official BTC/USD reference of ${moneyFmt(finalReferencePrice)}`;
      els.leaderboardSubcopy.textContent = 'Row one is the verified scooter winner, subject to eligibility checks and residency verification.';
      renderWinnerBadge('Winner locked · Black Yamaha RAY-ZR', true);
    } else if (phase === 'locked') {
      els.leaderboardEyebrow.textContent = 'Entries locked';
      els.leaderboardTitle.textContent = 'Entries are closed. One final hour of BTC/USD movement remains.';
      els.leaderboardSubcopy.textContent = 'Winner will be based on the official 11:00 PM BTC/USD reference price.';
      renderWinnerBadge('Winner updates at 11:00 PM');
    } else {
      els.leaderboardEyebrow.textContent = 'Current leaders';
      els.leaderboardTitle.textContent = 'Closest to the live BTC/USD market right now';
      els.leaderboardSubcopy.textContent = 'Live BTC/USD Price updates every 10 seconds. Final winner locks at 11:00 PM.';
      renderWinnerBadge('Winner updates at 11:00 PM');
    }
  };

  const refresh = async () => {
    try {
      const response = await fetch('/api/public-state', { cache: 'no-store' });
      if (!response.ok) return;
      const data = await response.json();
      state.nowMs = Date.parse(data.now_iso);
      state.entryLockMs = Date.parse(data.entry_lock_iso);
      state.finalMs = Date.parse(data.final_time_iso);
      state.phase = data.phase;
      flashLivePrice(data.live_price);
      els.livePrice.textContent = moneyFmt(data.live_price);
      els.lastUpdate.textContent = timeFmt(data.now_iso);
      els.entryStateBanner.textContent = data.entry_open ? 'Entries are open — scan the QR code now' : 'Entries are closed — follow the live result';
      els.saturdayCopy.textContent = data.saturday_copy;
      els.exampleCopy.textContent = data.example_copy;
      els.dashboardFooter.textContent = data.dashboard_footer;
      renderRules(data.rules || []);
      renderTicker(data.ticker || []);
      renderLeaders(data.leaders || [], data.phase, data.final_reference_price);
      updateCountdowns();
    } catch (error) {
      console.error(error);
    }
  };

  refresh();
  setInterval(refresh, 10000);
  setInterval(updateCountdowns, 1000);
})();
