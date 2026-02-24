// MixDoctor GUI - main.js

// ---- Authentication ----
async function login() {
    var token = localStorage.getItem('afl_token');
    if (token) return token;
    var r = await fetch('/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username: 'dashboard', password: 'domo_arigato'})
    });
    if (!r.ok) { showStatus('Login failed', true); throw new Error('login failed'); }
    token = (await r.json()).token;
    localStorage.setItem('afl_token', token);
    return token;
}

async function authedFetch(url, options) {
    options = options || {};
    var token = await login();
    options.headers = Object.assign({}, options.headers || {}, {
        'Authorization': 'Bearer ' + token
    });
    return fetch(url, options);
}

// ---- Status messages ----
var statusTimer = null;
function showStatus(msg, isError) {
    var el = document.getElementById('status-message');
    el.textContent = msg;
    el.style.background = isError ? '#dc3545' : '#343a40';
    el.classList.add('visible');
    if (statusTimer) clearTimeout(statusTimer);
    statusTimer = setTimeout(function() { el.classList.remove('visible'); }, 3000);
}

// ---- HTML escaping ----
function escHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// ---- Polling ----
async function pollForResult(token, uuid, timeoutMs) {
    timeoutMs = timeoutMs || 30000;
    var start = Date.now();
    while (Date.now() - start < timeoutMs) {
        await new Promise(function(resolve) { setTimeout(resolve, 500); });
        var resp = await fetch('/get_queue', {
            headers: {'Authorization': 'Bearer ' + token}
        });
        if (!resp.ok) throw new Error('queue fetch failed');
        var q = await resp.json();
        var history = (q[0] || []);
        for (var i = 0; i < history.length; i++) {
            if (history[i].uuid === uuid) {
                return history[i].meta ? history[i].meta.return_val : null;
            }
        }
    }
    throw new Error('timeout waiting for balance result');
}

// ---- Quantity formatting ----
function fmtQty(val) {
    if (val === null || val === undefined) return '\u2014';
    if (typeof val === 'object' && val.value !== undefined) {
        var v = val.value;
        if (typeof v === 'number') {
            if (!isFinite(v)) return '\u2014';
            v = +v.toPrecision(4);
        }
        return escHtml(v + ' ' + (val.units || ''));
    }
    if (typeof val === 'number') {
        if (!isFinite(val)) return '\u2014';
        return escHtml(+val.toPrecision(4) + '');
    }
    return escHtml(String(val));
}

// ---- Component summary chips on cards ----
function renderComponentList(data) {
    var components = data.components || [];
    if (components.length === 0) return '<span class="component-chip">no components</span>';
    return components.map(function(comp) {
        var label = comp + ': ';
        if (data.concentrations && data.concentrations[comp] != null) {
            var c = data.concentrations[comp];
            label += (typeof c === 'object' && c.value !== undefined)
                ? +Number(c.value).toPrecision(4) + ' ' + c.units
                : c;
        } else if (data.masses && data.masses[comp] != null) {
            var m = data.masses[comp];
            label += (typeof m === 'object' && m.value !== undefined)
                ? +Number(m.value).toPrecision(4) + ' ' + m.units
                : m;
        } else if (data.mass_fractions && data.mass_fractions[comp] != null) {
            label += +Number(data.mass_fractions[comp]).toPrecision(3);
        } else {
            label += '?';
        }
        return '<span class="component-chip">' + escHtml(label) + '</span>';
    }).join('');
}

// ---- Balance result state ----
// Maps target name -> full balance report entry from balance_report()
var balanceResultsByTarget = {};
// Ordered array of balance report entries (same order as targets list)
var balanceReportArray = [];

function updateBalanceCounter(report) {
    // Clear the header counter -- balance info is now shown in the panel title
    var el = document.getElementById('balance-counter');
    el.textContent = '';
    // Store the report array for index-based lookup and panel title rendering
    balanceReportArray = (report && Array.isArray(report)) ? report : [];
}

function buildBalanceResultsMap(report) {
    balanceResultsByTarget = {};
    if (!report || !Array.isArray(report)) return;
    report.forEach(function(entry) {
        var name = entry.target && entry.target.name;
        if (name) balanceResultsByTarget[name] = entry;
    });
}

// Look up balance entry by index first (reliable since both the balance
// report and list_targets iterate self.config['targets'] in the same order),
// falling back to name lookup.  Index-first is essential because multiple
// targets can share the same name (e.g. sub-1 mg/ml concentrations all
// round to "000mgml"), causing the name-keyed map to retain only the last
// entry for each duplicate name.
function getBalanceEntry(name, idx) {
    if (idx !== undefined && idx < balanceReportArray.length) {
        return balanceReportArray[idx];
    }
    return balanceResultsByTarget[name] || null;
}

function getMaxError(entry) {
    var maxErr = 0;
    var errors = entry.diagnosis && entry.diagnosis.component_errors;
    if (errors) {
        Object.keys(errors).forEach(function(k) {
            var a = Math.abs(errors[k]);
            if (a > maxErr) maxErr = a;
        });
    }
    return maxErr;
}

function balanceCardClass(name, idx) {
    var entry = getBalanceEntry(name, idx);
    if (!entry) return '';
    return entry.success ? 'card-balanced' : 'card-failed';
}

function balanceCardIndicator(name, idx) {
    var entry = getBalanceEntry(name, idx);
    if (!entry) return '';
    return entry.success
        ? '<span class="card-status card-status-ok">&#10003;</span>'
        : '<span class="card-status card-status-fail">&#10007;</span>';
}

// ---- Detail Modal ----
var stocksData = [];
var targetsData = [];
var currentModalIdx = -1;
var currentModalType = null;

function showDetailModal(data, type, idx) {
    currentModalIdx = (idx !== undefined) ? idx : -1;
    currentModalType = type;
    updateModalNav();

    document.getElementById('modal-title').textContent =
        (type === 'stock' ? 'Stock: ' : 'Target: ') + (data.name || '');

    var locBadge = document.getElementById('modal-location-badge');
    if (data.location) {
        locBadge.textContent = data.location;
        locBadge.style.display = 'inline';
    } else {
        locBadge.style.display = 'none';
    }

    // ---- Summary bar ----
    var summaryParts = [];
    if (data.total_mass) {
        summaryParts.push('<span class="summary-item"><strong>Total Mass:</strong> ' + fmtQty(data.total_mass) + '</span>');
    }
    if (data.total_volume) {
        summaryParts.push('<span class="summary-item"><strong>Total Volume:</strong> ' + fmtQty(data.total_volume) + '</span>');
    }
    var br = (type === 'target') ? getBalanceEntry(data.name, idx) : null;
    if (br) {
        var maxE = getMaxError(br);
        summaryParts.push(br.success
            ? '<span class="badge-success">&#10003; Balanced</span>'
            : '<span class="badge-failure">&#10007; Failed (max err: ' + (maxE * 100).toFixed(2) + '%)</span>');
    }
    document.getElementById('detail-modal-summary').innerHTML =
        summaryParts.length
            ? summaryParts.join('')
            : '<span class="summary-item" style="color:#6c757d">No summary available</span>';

    // ---- Composition table ----
    var components = data.components || [];
    var colDefs = [
        {key: 'masses',           label: 'Mass',          required: true},
        {key: 'volumes',          label: 'Volume',         required: false},
        {key: 'concentrations',   label: 'Concentration',  required: true},
        {key: 'mass_fractions',   label: 'Mass Fraction',  required: true},
        {key: 'volume_fractions', label: 'Vol. Fraction',  required: false},
        {key: 'molarities',       label: 'Molarity',       required: false},
        {key: 'molalities',       label: 'Molality',       required: false},
    ];

    var activeCols = colDefs.filter(function(col) {
        if (col.required) return true;
        return data[col.key] && Object.keys(data[col.key]).length > 0;
    });

    var thead = '<tr><th>Component</th>'
        + activeCols.map(function(c) { return '<th>' + c.label + '</th>'; }).join('')
        + '</tr>';

    var tbody = components.map(function(comp) {
        var cells = activeCols.map(function(col) {
            var dict = data[col.key];
            if (!dict || !(comp in dict) || dict[comp] === null) return '<td>\u2014</td>';
            return '<td>' + fmtQty(dict[comp]) + '</td>';
        }).join('');
        return '<tr><td><strong>' + escHtml(comp) + '</strong></td>' + cells + '</tr>';
    }).join('');

    document.getElementById('modal-table').innerHTML = components.length > 0
        ? '<table class="data-table"><thead>' + thead + '</thead><tbody>' + tbody + '</tbody></table>'
        : '<p class="empty-state">No components.</p>';

    // ---- Balance results (targets only, if balance has run) ----
    var balanceHtml = '';
    if (type === 'target' && br) {
        balanceHtml = renderBalanceResults(br);
    }
    document.getElementById('modal-balance-results').innerHTML = balanceHtml;

    document.getElementById('detail-modal-overlay').classList.add('visible');
}

function closeDetailModal() {
    document.getElementById('detail-modal-overlay').classList.remove('visible');
    currentModalIdx = -1;
    currentModalType = null;
}

function updateModalNav() {
    var prevBtn = document.getElementById('modal-nav-prev');
    var nextBtn = document.getElementById('modal-nav-next');
    if (currentModalType === 'target' && targetsData.length > 1) {
        prevBtn.style.display = '';
        nextBtn.style.display = '';
        prevBtn.disabled = currentModalIdx <= 0;
        nextBtn.disabled = currentModalIdx >= targetsData.length - 1;
    } else {
        prevBtn.style.display = 'none';
        nextBtn.style.display = 'none';
    }
}

function navigateModal(delta) {
    if (currentModalType !== 'target') return;
    var newIdx = currentModalIdx + delta;
    if (newIdx < 0 || newIdx >= targetsData.length) return;
    showDetailModal(targetsData[newIdx], 'target', newIdx);
}

// ---- Render balance results for a single entry (inside modal) ----
function renderBalanceResults(entry) {
    var parts = [];
    parts.push('<hr class="modal-section-divider">');

    // Transfers table
    if (entry.transfers && Object.keys(entry.transfers).length > 0) {
        var rows = Object.keys(entry.transfers).map(function(stock) {
            return '<tr><td>' + escHtml(stock) + '</td><td>' + escHtml(String(entry.transfers[stock])) + '</td></tr>';
        }).join('');
        parts.push('<div class="result-section-title">Transfers</div>');
        parts.push('<table class="data-table"><thead><tr><th>Stock</th><th>Mass</th></tr></thead><tbody>' + rows + '</tbody></table>');
    }

    // Component errors table
    var compErrors = entry.diagnosis && entry.diagnosis.component_errors;
    if (compErrors && Object.keys(compErrors).length > 0) {
        var rows = Object.keys(compErrors).map(function(comp) {
            var err = compErrors[comp];
            var pct = (err * 100).toFixed(2);
            var absErr = Math.abs(err);
            var cls = absErr >= 0.05 ? 'error-red' : (absErr >= 0.01 ? 'error-yellow' : 'error-green');
            return '<tr><td>' + escHtml(comp) + '</td><td class="' + cls + '">' + pct + '%</td></tr>';
        }).join('');
        parts.push('<div class="result-section-title">Component Errors</div>');
        parts.push('<table class="data-table"><thead><tr><th>Component</th><th>Relative Error</th></tr></thead><tbody>' + rows + '</tbody></table>');
    }

    // Failure details
    var details = entry.diagnosis && entry.diagnosis.details;
    if (details && details.length > 0) {
        parts.push('<div class="result-section-title">Failure Details</div>');
        details.forEach(function(d) {
            var affComp = (d.affected_components && d.affected_components.length > 0)
                ? '<div class="failure-affected">Components: ' + escHtml(d.affected_components.join(', ')) + '</div>'
                : '';
            var affStock = (d.affected_stocks && d.affected_stocks.length > 0)
                ? '<div class="failure-affected">Stocks: ' + escHtml(d.affected_stocks.join(', ')) + '</div>'
                : '';
            parts.push('<div class="failure-detail-card">'
                + '<span class="failure-code-chip">' + escHtml(d.code) + '</span>'
                + '<div class="failure-description">' + escHtml(d.description) + '</div>'
                + affComp + affStock
                + '</div>');
        });
    }

    return parts.join('');
}

// ---- Load & Render Stocks ----
async function loadStocks() {
    var container = document.getElementById('stocks-list');
    container.innerHTML = '<p class="empty-state">Loading...</p>';
    try {
        var r = await fetch('/list_stocks');
        if (!r.ok) {
            container.innerHTML = '<p class="empty-state">Failed to load stocks.</p>';
            return;
        }
        stocksData = await r.json();
        renderStocks(stocksData);
    } catch (e) {
        container.innerHTML = '<p class="empty-state">Error loading stocks.</p>';
    }
}

function renderStocks(data) {
    var container = document.getElementById('stocks-list');
    var titleEl = document.querySelector('#stocks-panel .panel-title');
    titleEl.textContent = 'Stocks' + (data && data.length ? ' (' + data.length + ')' : '');
    if (!data || data.length === 0) {
        container.innerHTML = '<p class="empty-state">No stocks configured.</p>';
        return;
    }
    container.innerHTML = data.map(function(stock, idx) {
        var locBadge = stock.location
            ? '<span class="location-badge">' + escHtml(stock.location) + '</span>'
            : '';
        return '<div class="card clickable" data-idx="' + idx + '">'
            + '<div class="card-header">'
            + '<span class="card-name">' + escHtml(stock.name || '') + '</span>'
            + locBadge
            + '</div>'
            + '<div class="component-list">' + renderComponentList(stock) + '</div>'
            + '</div>';
    }).join('');

    container.querySelectorAll('.card.clickable').forEach(function(card) {
        card.addEventListener('click', function() {
            var idx = parseInt(this.getAttribute('data-idx'), 10);
            showDetailModal(stocksData[idx], 'stock');
        });
    });
}

// ---- Load & Render Targets ----
async function loadTargets() {
    var container = document.getElementById('targets-list');
    container.innerHTML = '<p class="empty-state">Loading...</p>';
    try {
        var r = await fetch('/list_targets');
        if (!r.ok) {
            container.innerHTML = '<p class="empty-state">Failed to load targets.</p>';
            return;
        }
        targetsData = await r.json();
        renderTargets(targetsData);
    } catch (e) {
        container.innerHTML = '<p class="empty-state">Error loading targets.</p>';
    }
}

function renderTargets(data) {
    var container = document.getElementById('targets-list');
    // Update panel title with count and balance results
    var titleEl = document.querySelector('#targets-panel .panel-title');
    var titleText = 'Targets';
    if (data && data.length) {
        if (balanceReportArray.length > 0) {
            var ok = balanceReportArray.filter(function(e) { return e.success; }).length;
            titleText += ' (' + ok + '/' + data.length + ' succeeded)';
        } else {
            titleText += ' (' + data.length + ')';
        }
    }
    titleEl.textContent = titleText;
    if (!data || data.length === 0) {
        container.innerHTML = '<p class="empty-state">No targets configured.</p>';
        return;
    }
    container.innerHTML = data.map(function(target, idx) {
        var locBadge = target.location
            ? '<span class="location-badge">' + escHtml(target.location) + '</span>'
            : '';
        var colorCls = balanceCardClass(target.name, idx);
        var indicator = balanceCardIndicator(target.name, idx);
        return '<div class="card clickable ' + colorCls + '" data-idx="' + idx + '">'
            + '<div class="card-header">'
            + '<span class="card-name">' + escHtml(target.name || '') + '</span>'
            + locBadge
            + indicator
            + '</div>'
            + '<div class="component-list">' + renderComponentList(target) + '</div>'
            + '</div>';
    }).join('');

    container.querySelectorAll('.card.clickable').forEach(function(card) {
        card.addEventListener('click', function() {
            var idx = parseInt(this.getAttribute('data-idx'), 10);
            showDetailModal(targetsData[idx], 'target', idx);
        });
    });
}

// ---- Balance Execution ----
async function runBalance() {
    var btn = document.getElementById('balance-btn');
    btn.disabled = true;
    btn.textContent = 'Balancing...';
    showStatus('Running balance...');
    try {
        var token = await login();
        var r = await authedFetch('/enqueue', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({task_name: 'balance', return_report: true})
        });
        if (!r.ok) {
            showStatus('Failed to enqueue balance', true);
            return;
        }
        var uuidText = await r.text();
        var uuid = uuidText.trim().replace(/^"|"$/g, '');
        showStatus('Waiting for result...');
        var returnVal = await pollForResult(token, uuid);
        if (returnVal !== null && returnVal !== undefined) {
            buildBalanceResultsMap(returnVal);
            updateBalanceCounter(returnVal);
            showStatus('Balance complete.');
        } else {
            showStatus('Balance complete (no report).', true);
        }
        // Reload panels -- targets will now show balance state colors
        loadStocks();
        loadTargets();
    } catch (e) {
        showStatus('Balance error: ' + e.message, true);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Balance';
    }
}

// ---- Init ----
document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('refresh-btn').addEventListener('click', function() {
        loadStocks();
        loadTargets();
        showStatus('Refreshed.');
    });
    document.getElementById('balance-btn').addEventListener('click', runBalance);

    // Modal close & navigation handlers
    document.getElementById('detail-modal-close').addEventListener('click', closeDetailModal);
    document.getElementById('modal-nav-prev').addEventListener('click', function() { navigateModal(-1); });
    document.getElementById('modal-nav-next').addEventListener('click', function() { navigateModal(1); });
    document.getElementById('detail-modal-overlay').addEventListener('click', function(e) {
        if (e.target === this) closeDetailModal();
    });
    document.addEventListener('keydown', function(e) {
        var modalOpen = document.getElementById('detail-modal-overlay').classList.contains('visible');
        if (!modalOpen) return;
        if (e.key === 'Escape') closeDetailModal();
        if (e.key === 'ArrowLeft') navigateModal(-1);
        if (e.key === 'ArrowRight') navigateModal(1);
    });

    loadStocks();
    loadTargets();
});
