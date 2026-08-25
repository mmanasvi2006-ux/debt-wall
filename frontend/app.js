const els = {
  input: document.getElementById('ticker-input'),
  suggestions: document.getElementById('suggestions'),
  empty: document.getElementById('empty-state'),
  error: document.getElementById('error-state'),
  errorMessage: document.getElementById('error-message'),
  loading: document.getElementById('loading-state'),
  dashboard: document.getElementById('dashboard'),
};

let searchDebounce = null;
let wallChart = null;

// -------------------------------------------------------------------------
// Search box
// -------------------------------------------------------------------------

els.input.addEventListener('input', () => {
  const q = els.input.value.trim();
  clearTimeout(searchDebounce);
  if (!q) {
    hideSuggestions();
    return;
  }
  searchDebounce = setTimeout(() => runSearch(q), 180);
});

els.input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    const q = els.input.value.trim();
    if (q) loadDashboard(q);
    hideSuggestions();
  }
});

document.addEventListener('click', (e) => {
  if (!els.suggestions.contains(e.target) && e.target !== els.input) {
    hideSuggestions();
  }
});

document.querySelectorAll('.chip').forEach((chip) => {
  chip.addEventListener('click', () => {
    els.input.value = chip.dataset.ticker;
    loadDashboard(chip.dataset.ticker);
  });
});

async function runSearch(q) {
  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
    const results = await res.json();
    renderSuggestions(results);
  } catch (e) {
    hideSuggestions();
  }
}

function renderSuggestions(results) {
  if (!results.length) {
    hideSuggestions();
    return;
  }
  els.suggestions.innerHTML = '';
  results.forEach((r) => {
    const row = document.createElement('div');
    row.className = 'suggestion-item';
    row.innerHTML = `<span class="suggestion-ticker">${r.ticker}</span><span class="suggestion-name">${r.title}</span>`;
    row.addEventListener('click', () => {
      els.input.value = r.ticker;
      hideSuggestions();
      loadDashboard(r.ticker);
    });
    els.suggestions.appendChild(row);
  });
  els.suggestions.classList.remove('hidden');
}

function hideSuggestions() {
  els.suggestions.classList.add('hidden');
}

// -------------------------------------------------------------------------
// Dashboard loading
// -------------------------------------------------------------------------

async function loadDashboard(ticker) {
  showState('loading');
  try {
    const res = await fetch(`/api/dashboard/${encodeURIComponent(ticker)}`);
    const data = await res.json();
    if (!res.ok || data.error) {
      showError(data.error || 'Something went wrong loading that ticker.');
      return;
    }
    renderDashboard(data);
    showState('dashboard');
  } catch (e) {
    showError('Could not reach the server. Is the Flask app running?');
  }
}

function showState(name) {
  els.empty.classList.add('hidden');
  els.error.classList.add('hidden');
  els.loading.classList.add('hidden');
  els.dashboard.classList.add('hidden');
  if (name === 'loading') els.loading.classList.remove('hidden');
  if (name === 'dashboard') els.dashboard.classList.remove('hidden');
  if (name === 'empty') els.empty.classList.remove('hidden');
}

function showError(msg) {
  els.errorMessage.textContent = msg;
  showState('error');
  els.error.classList.remove('hidden');
}

// -------------------------------------------------------------------------
// Rendering
// -------------------------------------------------------------------------

function fmtUSD(v) {
  if (v === null || v === undefined) return '—';
  const abs = Math.abs(v);
  const sign = v < 0 ? '-' : '';
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

function fmtRatio(v) {
  if (v === null || v === undefined) return '—';
  return `${v.toFixed(2)}x`;
}

function fmtPct(v) {
  if (v === null || v === undefined) return '—';
  return `${(v * 100).toFixed(1)}%`;
}

function riskColor(score) {
  // 0 -> safe teal, 100 -> high red, passing through amber
  const safe = [79, 179, 164];
  const mid = [227, 162, 61];
  const high = [214, 83, 74];
  let a, b, t;
  if (score <= 50) { a = safe; b = mid; t = score / 50; }
  else { a = mid; b = high; t = (score - 50) / 50; }
  const c = a.map((v, i) => Math.round(v + (b[i] - v) * t));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

function renderDashboard(data) {
  document.getElementById('company-name').textContent = data.company;
  document.getElementById('company-meta').textContent = `${data.ticker} · CIK ${data.cik}`;

  const risk = data.refinancing_risk;
  const badge = document.getElementById('risk-badge');
  badge.className = `risk-badge ${risk.band.toLowerCase()}`;
  document.getElementById('risk-band').textContent = `${risk.band} refinancing risk`;
  document.getElementById('risk-score').textContent = risk.score;

  const m = data.credit_metrics;
  document.getElementById('kpi-total-debt').textContent = fmtUSD(m.total_debt);
  document.getElementById('kpi-net-debt').textContent = fmtUSD(m.net_debt);
  document.getElementById('kpi-coverage').textContent = fmtRatio(m.interest_coverage_ebitda ?? m.interest_coverage_ebit);
  document.getElementById('kpi-leverage').textContent = fmtRatio(m.debt_to_ebitda);
  document.getElementById('kpi-cash').textContent = fmtUSD(m.cash);

  renderWallChart(data.maturity_wall);
  renderLedger(m);
  renderRiskComponents(risk);

  const fy = data.maturity_wall.fiscal_year;
  document.getElementById('source-note').textContent =
    `Source: SEC EDGAR XBRL, company facts for CIK ${data.cik}` +
    (fy ? ` · maturity schedule as disclosed for FY${fy}` : '') +
    '. Figures reflect the most recent 10-K in which each tag was reported — line items can lag by a quarter or two depending on filing cadence.';
}

function renderWallChart(wall) {
  const labels = ['Year 1', 'Year 2', 'Year 3', 'Year 4', 'Year 5', 'Thereafter'];
  const values = labels.map((l) => wall.schedule[l] ?? null);
  const hasAny = values.some((v) => v !== null);

  const colors = ['#d6534a', '#dc7a4a', '#e3a23d', '#c9b24a', '#8fc06e', '#4fb3a4'];

  const ctx = document.getElementById('wall-chart').getContext('2d');
  if (wallChart) wallChart.destroy();

  if (!hasAny) {
    document.getElementById('wall-caption').textContent =
      "This filer didn't tag a standard debt maturity schedule in XBRL — common for companies with little long-term debt, or ones that disclose maturities in a non-standard table. Check the 10-K debt footnote directly.";
  } else {
    document.getElementById('wall-caption').textContent =
      'Bars closest to today carry the most refinancing risk — colored hot-to-cool from Year 1 out to Thereafter.';
  }

  wallChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors,
        borderRadius: 4,
        maxBarThickness: 64,
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => fmtUSD(ctx.parsed.y),
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: '#8890a0', font: { family: 'IBM Plex Mono', size: 11 } },
        },
        y: {
          grid: { color: '#2a2f3b' },
          ticks: {
            color: '#8890a0',
            font: { family: 'IBM Plex Mono', size: 11 },
            callback: (v) => fmtUSD(v),
          },
        },
      },
    },
  });
}

function renderLedger(m) {
  const rows = [
    ['Total Debt', fmtUSD(m.total_debt)],
    ['Cash & Equivalents', fmtUSD(m.cash)],
    ['Net Debt', fmtUSD(m.net_debt)],
    ['EBIT', fmtUSD(m.ebit)],
    ['EBITDA (est.)', fmtUSD(m.ebitda)],
    ['Interest Expense', fmtUSD(m.interest_expense)],
    ['Interest Coverage (EBIT)', fmtRatio(m.interest_coverage_ebit)],
    ['Interest Coverage (EBITDA)', fmtRatio(m.interest_coverage_ebitda)],
    ['Debt / EBITDA', fmtRatio(m.debt_to_ebitda)],
    ['Debt / Equity', fmtRatio(m.debt_to_equity)],
    ['Debt / Assets', m.debt_to_assets !== null ? fmtPct(m.debt_to_assets) : '—'],
    ['Current Ratio', fmtRatio(m.current_ratio)],
    ['Net Margin', fmtPct(m.net_margin)],
  ];
  const tbody = document.querySelector('#ledger-table tbody');
  tbody.innerHTML = rows.map(([label, val]) => `<tr><td>${label}</td><td>${val}</td></tr>`).join('');
}

function renderRiskComponents(risk) {
  const labels = {
    near_term_coverage: 'Near-term maturities vs. cash',
    interest_coverage: 'Interest coverage',
    leverage: 'Leverage (Debt/EBITDA)',
  };
  const container = document.getElementById('risk-components');
  container.innerHTML = '';
  Object.entries(risk.components).forEach(([key, val]) => {
    const row = document.createElement('div');
    row.className = 'risk-component-row';
    row.innerHTML = `
      <div class="rc-top">
        <span class="rc-label">${labels[key] || key}</span>
        <span class="rc-value">${val}</span>
      </div>
      <div class="rc-track"><div class="rc-fill" style="width:${val}%; background:${riskColor(val)}"></div></div>
    `;
    container.appendChild(row);
  });
}
