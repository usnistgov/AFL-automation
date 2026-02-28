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

// ---- Driver query helper (unqueued) ----
async function queryDriver(params) {
    var qs = new URLSearchParams(params);
    var url = '/query_driver?' + qs.toString();
    var r = await authedFetch(url, { method: 'GET' });
    if (!r.ok) throw new Error('Driver query failed');
    return r;
}

// ---- Solution diagnostics ----
function updateSolutionDiagnostics(diagnostics) {
    var body = document.getElementById('solution-diagnostics-body');
    if (!body) return;
    if (!diagnostics || diagnostics.length === 0) {
        body.innerHTML = '<p class="empty-state">No warnings or output from Solution creation.</p>';
        return;
    }

    var html = diagnostics.map(function(entry) {
        var name = entry.name ? entry.name : ('Stock #' + (entry.index + 1));
        var parts = [];
        parts.push('<div class="diagnostic-title">' + escHtml(name) + '</div>');

        var warnings = entry.warnings || [];
        if (warnings.length > 0) {
            var warnLines = warnings.map(function(w) {
                var category = w.category ? (w.category + ': ') : '';
                return category + (w.message || '');
            }).join('\n');
            parts.push('<div class="diagnostic-section-title">Warnings</div>');
            parts.push('<div class="diagnostic-pre">' + escHtml(warnLines) + '</div>');
        }

        if (entry.stdout) {
            parts.push('<div class="diagnostic-section-title">Stdout</div>');
            parts.push('<div class="diagnostic-pre">' + escHtml(entry.stdout) + '</div>');
        }

        if (entry.stderr) {
            parts.push('<div class="diagnostic-section-title">Stderr</div>');
            parts.push('<div class="diagnostic-pre">' + escHtml(entry.stderr) + '</div>');
        }

        if (warnings.length === 0 && !entry.stdout && !entry.stderr) {
            parts.push('<div class="diagnostic-pre">No warnings or output.</div>');
        }

        return '<div class="diagnostic-entry">' + parts.join('') + '</div>';
    }).join('');

    body.innerHTML = html;
}

function clearSolutionDiagnostics() {
    updateSolutionDiagnostics([]);
}

// ---- Polling ----
async function pollForResult(token, uuid, timeoutMs) {
    timeoutMs = timeoutMs || 120000;
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

// ---- Tab switching ----
function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId);
    });
    document.querySelectorAll('.tab-panel').forEach(function(panel) {
        panel.classList.toggle('active', panel.id === tabId);
    });
    if (tabId === 'components-tab') {
        loadComponentsEditor();
    }
    if (tabId === 'balance-tab') {
        loadStocks();
        loadTargets();
    }
    if (tabId === 'plot-sweep-tab') {
        initPlotSweepTab();
    }
    if (tabId === 'submit-tab') {
        initSubmitTab();
    }
}

// ---- Component names datalist ----
async function loadComponentNames() {
    try {
        var r = await fetch('/list_components');
        if (!r.ok) return;
        var components = await r.json();
        var datalist = document.getElementById('component-names-datalist');
        datalist.innerHTML = '';
        components.forEach(function(comp) {
            var opt = document.createElement('option');
            opt.value = typeof comp === 'object' ? comp.name : comp;
            datalist.appendChild(opt);
        });
    } catch (e) {
        // silently ignore
    }
}

// ---- Components editor ----
async function loadComponentsEditor() {
    var body = document.getElementById('components-table-body');
    if (!body) return;
    body.innerHTML = '<tr><td colspan="6" class="empty-state">Loading components...</td></tr>';
    try {
        var r = await fetch('/list_components');
        if (!r.ok) {
            body.innerHTML = '<tr><td colspan="6" class="empty-state">Failed to load components.</td></tr>';
            return;
        }
        var components = await r.json();
        renderComponentsTable(components);
    } catch (e) {
        body.innerHTML = '<tr><td colspan="6" class="empty-state">Error loading components.</td></tr>';
    }
}

function renderComponentsTable(components) {
    var body = document.getElementById('components-table-body');
    if (!body) return;
    if (!components || components.length === 0) {
        body.innerHTML = '<tr><td colspan="6" class="empty-state">No components in database.</td></tr>';
        return;
    }
    body.innerHTML = components.map(function(comp) {
        var name = comp.name || '';
        var density = comp.density || '';
        var formula = comp.formula || '';
        var sld = comp.sld || '';
        var uid = comp.uid || '';
        return [
            '<tr data-uid="', escHtml(uid), '">',
            '<td><input type="text" class="comp-name-input" value="', escHtml(name), '"></td>',
            '<td><input type="text" class="comp-density-input" value="', escHtml(density), '"></td>',
            '<td><input type="text" class="comp-formula-input" value="', escHtml(formula), '"></td>',
            '<td><input type="text" class="comp-sld-input" value="', escHtml(sld), '"></td>',
            '<td class="uid-cell">', escHtml(uid), '</td>',
            '<td><div class="components-actions">',
            '<button class="toolbar-btn comp-save-btn">Save</button>',
            '<button class="toolbar-btn comp-delete-btn">Delete</button>',
            '</div></td>',
            '</tr>'
        ].join('');
    }).join('');

    body.querySelectorAll('.comp-save-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var row = this.closest('tr');
            saveComponentRow(row);
        });
    });
    body.querySelectorAll('.comp-delete-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var row = this.closest('tr');
            deleteComponentRow(row);
        });
    });
}

async function saveComponentRow(row) {
    if (!row) return;
    var uid = row.getAttribute('data-uid');
    if (!uid) return;
    var name = row.querySelector('.comp-name-input').value.trim();
    var density = row.querySelector('.comp-density-input').value.trim();
    var formula = row.querySelector('.comp-formula-input').value.trim();
    var sld = row.querySelector('.comp-sld-input').value.trim();

    try {
        await queryDriver({
            r: 'update_component',
            uid: uid,
            name: name,
            density: density,
            formula: formula,
            sld: sld,
        });
        showStatus('Component updated.');
        loadComponentNames();
    } catch (e) {
        showStatus('Update failed: ' + e.message, true);
    }
}

async function deleteComponentRow(row) {
    if (!row) return;
    var uid = row.getAttribute('data-uid');
    var name = row.querySelector('.comp-name-input').value.trim();
    if (!uid) return;
    if (!confirm('Delete component "' + name + '"?')) return;
    try {
        await queryDriver({ r: 'remove_component', uid: uid });
        showStatus('Component removed.');
        loadComponentsEditor();
        loadComponentNames();
    } catch (e) {
        showStatus('Delete failed: ' + e.message, true);
    }
}

async function addComponentRow() {
    try {
        await queryDriver({ r: 'add_component' });
        showStatus('Component added.');
        loadComponentsEditor();
        loadComponentNames();
    } catch (e) {
        showStatus('Add failed: ' + e.message, true);
    }
}

// ---- Stock card management ----
var STOCK_PROPERTY_TYPES = [
    {value: 'mass', label: 'Mass', needsUnits: true, defaultUnit: 'mg'},
    {value: 'volume', label: 'Volume', needsUnits: true, defaultUnit: 'ul'},
    {value: 'concentration', label: 'Concentration', needsUnits: true, defaultUnit: 'mg/ml'},
    {value: 'mass_fraction', label: 'Mass Fraction', needsUnits: false},
    {value: 'volume_fraction', label: 'Volume Fraction', needsUnits: false},
    {value: 'molarity', label: 'Molarity', needsUnits: true, defaultUnit: 'mol/L'},
    {value: 'molality', label: 'Molality', needsUnits: true, defaultUnit: 'mol/kg'},
];

function createStockCard(prefill) {
    prefill = prefill || {};
    var card = document.createElement('div');
    card.className = 'stock-form-card';

    var hasSizeType = prefill.sizeType === 'total_mass' || prefill.sizeType === 'total_volume';
    var sizeDisabled = hasSizeType ? '' : ' disabled';
    card.innerHTML = [
        '<div class="stock-form-header">',
        '  <input type="text" class="stock-name-input" placeholder="Stock name" value="' + escHtml(prefill.name || '') + '">',
        '  <input type="text" class="stock-location-input" placeholder="Location (e.g. A1)" value="' + escHtml(prefill.location || '') + '">',
        '  <select class="stock-size-type">',
        '    <option value="none"' + (hasSizeType ? '' : ' selected') + '>No size</option>',
        '    <option value="total_mass"' + (prefill.sizeType === 'total_mass' ? ' selected' : '') + '>Total Mass</option>',
        '    <option value="total_volume"' + (prefill.sizeType === 'total_volume' ? ' selected' : '') + '>Total Volume</option>',
        '  </select>',
        '  <input type="text" class="stock-size-value" placeholder="e.g. 500 mg" value="' + escHtml(prefill.sizeValue || '') + '"' + sizeDisabled + '>',
        '  <button class="stock-duplicate-btn" title="Duplicate stock">&#x2398; Duplicate</button>',
        '  <button class="stock-remove-btn" title="Remove stock">&times;</button>',
        '</div>',
        '<table class="stock-comp-table">',
        '  <thead><tr><th>Component</th><th>Property</th><th>Value</th><th>Units</th><th>Solute</th><th></th></tr></thead>',
        '  <tbody class="stock-comp-tbody"></tbody>',
        '</table>',
        '<button class="add-comp-btn">+ Add Component</button>',
    ].join('');

    card.querySelector('.stock-remove-btn').addEventListener('click', function() {
        card.remove();
    });
    card.querySelector('.stock-duplicate-btn').addEventListener('click', function() {
        duplicateStockCard(card);
    });
    card.querySelector('.add-comp-btn').addEventListener('click', function() {
        addStockComponentRow(card, null);
    });
    card.querySelector('.stock-size-type').addEventListener('change', function() {
        var sizeValueInput = card.querySelector('.stock-size-value');
        sizeValueInput.disabled = this.value === 'none';
        if (this.value === 'none') sizeValueInput.value = '';
    });

    if (prefill.components && prefill.components.length > 0) {
        prefill.components.forEach(function(comp) {
            addStockComponentRow(card, comp);
        });
    } else {
        addStockComponentRow(card, null);
    }

    document.getElementById('stock-cards-container').appendChild(card);
    return card;
}

function addStockComponentRow(card, prefill) {
    prefill = prefill || {};
    var tbody = card.querySelector('.stock-comp-tbody');
    var tr = document.createElement('tr');
    tr.className = 'stock-comp-row';

    var defaultPropType = prefill.propType || 'mass';
    var propTypeOptions = STOCK_PROPERTY_TYPES.map(function(pt) {
        return '<option value="' + pt.value + '"' + (defaultPropType === pt.value ? ' selected' : '') + '>' + pt.label + '</option>';
    }).join('');

    var selectedType = STOCK_PROPERTY_TYPES.find(function(pt) { return pt.value === defaultPropType; }) || STOCK_PROPERTY_TYPES[0];
    var unitsDisabled = selectedType.needsUnits ? '' : ' disabled';
    var defaultUnit = prefill.units || (selectedType.needsUnits ? selectedType.defaultUnit : '');
    var soluteChecked = prefill.isSolute ? ' checked' : '';

    tr.innerHTML = [
        '<td><input type="text" class="comp-name-input" list="component-names-datalist" placeholder="Component name" value="' + escHtml(prefill.name || '') + '"></td>',
        '<td><select class="comp-prop-type">' + propTypeOptions + '</select></td>',
        '<td><input type="number" class="comp-value-input" placeholder="Value" value="' + escHtml(prefill.value !== undefined ? String(prefill.value) : '') + '" step="any"></td>',
        '<td><input type="text" class="comp-units-input" placeholder="Units" value="' + escHtml(defaultUnit) + '"' + unitsDisabled + '></td>',
        '<td><input type="checkbox" class="comp-solute"' + soluteChecked + '></td>',
        '<td><button class="remove-comp-btn" title="Remove">&times;</button></td>',
    ].join('');

    var propSelect = tr.querySelector('.comp-prop-type');
    propSelect.dataset.prevValue = propSelect.value;

    propSelect.addEventListener('change', async function() {
        var oldPropType = this.dataset.prevValue;
        var newPropType = this.value;
        this.dataset.prevValue = newPropType;

        var pt    = STOCK_PROPERTY_TYPES.find(function(p) { return p.value === newPropType; });
        var oldPt = STOCK_PROPERTY_TYPES.find(function(p) { return p.value === oldPropType; });
        var valueInput = tr.querySelector('.comp-value-input');
        var unitsInput = tr.querySelector('.comp-units-input');
        var compName   = tr.querySelector('.comp-name-input').value.trim();

        // Capture old quantity before touching the UI
        var oldValue = valueInput.value.trim();
        var oldUnits = unitsInput.value.trim();

        // Update units to new default immediately
        if (pt && pt.needsUnits) {
            unitsInput.disabled = false;
            unitsInput.value = pt.defaultUnit;
        } else {
            unitsInput.disabled = true;
            unitsInput.value = '';
        }

        if (!compName || !oldValue) return;

        var propTypeToGroup = {
            'mass':            'masses',
            'volume':          'volumes',
            'concentration':   'concentrations',
            'mass_fraction':   'mass_fractions',
            'volume_fraction': 'volume_fractions',
            'molarity':        'molarities',
            'molality':        'molalities',
        };

        var oldGroupKey = propTypeToGroup[oldPropType];
        var newGroupKey = propTypeToGroup[newPropType];
        if (!oldGroupKey || !newGroupKey) return;

        // Build a full stock dict so backend can construct a valid Solution
        var stockData = serializeStockCard(card);
        stockData.name = '__temp__';

        if (!stockData[oldGroupKey]) stockData[oldGroupKey] = {};
        if (oldPt && oldPt.needsUnits && oldUnits) {
            stockData[oldGroupKey][compName] = oldValue + ' ' + oldUnits;
        } else {
            stockData[oldGroupKey][compName] = parseFloat(oldValue);
        }
        if (stockData[newGroupKey] && stockData[newGroupKey][compName] !== undefined) {
            delete stockData[newGroupKey][compName];
            if (Object.keys(stockData[newGroupKey]).length === 0) {
                delete stockData[newGroupKey];
            }
        }

        try {
            var resp = await fetch(
                '/compute_stock_properties?stock=' +
                encodeURIComponent(JSON.stringify(stockData))
            );
            var result = await resp.json();
            var propData = result[newGroupKey];
            if (!propData || propData[compName] === undefined || propData[compName] === null) {
                valueInput.value = '';
                return;
            }
            var val = propData[compName];
            if (typeof val === 'object' && val.value !== undefined) {
                valueInput.value = +Number(val.value).toPrecision(6);
                if (pt && pt.needsUnits) unitsInput.value = val.units;
            } else if (typeof val === 'number') {
                valueInput.value = +Number(val).toPrecision(6);
            } else {
                valueInput.value = '';
            }
        } catch (e) {
            valueInput.value = '';
        }
    });

    tr.querySelector('.remove-comp-btn').addEventListener('click', function() {
        tr.remove();
    });

    tbody.appendChild(tr);
    return tr;
}

function extractStockCardPrefill(card) {
    var prefill = {};
    prefill.name = card.querySelector('.stock-name-input').value;
    prefill.location = card.querySelector('.stock-location-input').value;
    var sizeType = card.querySelector('.stock-size-type').value;
    if (sizeType !== 'none') {
        prefill.sizeType = sizeType;
        prefill.sizeValue = card.querySelector('.stock-size-value').value;
    }
    prefill.components = [];
    card.querySelectorAll('.stock-comp-row').forEach(function(row) {
        var comp = {};
        comp.name = row.querySelector('.comp-name-input').value;
        comp.propType = row.querySelector('.comp-prop-type').value;
        comp.value = row.querySelector('.comp-value-input').value;
        comp.units = row.querySelector('.comp-units-input').value;
        comp.isSolute = row.querySelector('.comp-solute').checked;
        prefill.components.push(comp);
    });
    return prefill;
}

function duplicateStockCard(sourceCard) {
    var prefill = extractStockCardPrefill(sourceCard);
    var newCard = createStockCard(prefill);
    // Scroll the new card into view
    newCard.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

function serializeStockCard(card) {
    var result = {};
    var name = card.querySelector('.stock-name-input').value.trim();
    var location = card.querySelector('.stock-location-input').value.trim();
    var sizeType = card.querySelector('.stock-size-type').value;
    var sizeValue = card.querySelector('.stock-size-value').value.trim();

    if (name) result.name = name;
    if (location) result.location = location;
    if (sizeType !== 'none' && sizeValue) result[sizeType] = sizeValue;

    var propTypeToGroup = {
        'mass': 'masses',
        'volume': 'volumes',
        'concentration': 'concentrations',
        'mass_fraction': 'mass_fractions',
        'volume_fraction': 'volume_fractions',
        'molarity': 'molarities',
        'molality': 'molalities',
    };

    var propGroups = {};
    var solutes = [];

    card.querySelectorAll('.stock-comp-row').forEach(function(row) {
        var compName = row.querySelector('.comp-name-input').value.trim();
        if (!compName) return;
        var propType = row.querySelector('.comp-prop-type').value;
        var value = row.querySelector('.comp-value-input').value.trim();
        var units = row.querySelector('.comp-units-input').value.trim();
        var isSolute = row.querySelector('.comp-solute').checked;
        var groupKey = propTypeToGroup[propType];
        if (!groupKey || !value) return;

        if (!propGroups[groupKey]) propGroups[groupKey] = {};
        var pt = STOCK_PROPERTY_TYPES.find(function(p) { return p.value === propType; });
        if (pt && pt.needsUnits && units) {
            propGroups[groupKey][compName] = value + ' ' + units;
        } else {
            propGroups[groupKey][compName] = parseFloat(value);
        }

        if (isSolute) solutes.push(compName);
    });

    Object.keys(propGroups).forEach(function(key) {
        result[key] = propGroups[key];
    });

    if (solutes.length > 0) result.solutes = solutes;

    return result;
}

async function uploadStocks() {
    var cards = document.querySelectorAll('.stock-form-card');
    var stocks = [];
    cards.forEach(function(card) {
        var serialized = serializeStockCard(card);
        if (serialized.name) stocks.push(serialized);
    });

    if (stocks.length === 0) {
        showStatus('No valid stocks to upload.', true);
        return;
    }

    var btn = document.getElementById('upload-stocks-btn');
    btn.disabled = true;
    showStatus('Uploading stocks...');

    try {
        var token = await login();
        var r = await authedFetch('/enqueue', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({task_name: 'upload_stocks', stocks: stocks, reset: true})
        });
        if (!r.ok) {
            showStatus('Failed to enqueue upload.', true);
            return;
        }
        var uuidText = await r.text();
        var uuid = uuidText.trim().replace(/^"|"$/g, '');
        var result = await pollForResult(token, uuid);

        var errEl = document.getElementById('stocks-upload-errors');
        if (result && result.success) {
            showStatus('Uploaded ' + result.count + ' stock(s).');
            errEl.innerHTML = '';
        } else {
            var errMsg = (result && result.error) ? result.error : 'Unknown error';
            showStatus('Upload failed.', true);
            errEl.innerHTML = '<div class="upload-error-list"><strong>Error:</strong> ' + escHtml(errMsg) + '</div>';
        }
        updateSolutionDiagnostics(result && result.diagnostics ? result.diagnostics : []);
    } catch (e) {
        showStatus('Upload error: ' + e.message, true);
    } finally {
        btn.disabled = false;
    }
}

async function loadExistingStocksIntoCards() {
    showStatus('Loading stocks from server...');
    try {
        var r = await fetch('/list_stocks');
        if (!r.ok) { showStatus('Failed to load stocks.', true); return; }
        var stocks = await r.json();

        document.getElementById('stock-cards-container').innerHTML = '';

        stocks.forEach(function(stock) {
            var prefill = {
                name: stock.name || '',
                location: stock.location || '',
            };

            if (stock.total_mass) {
                prefill.sizeType = 'total_mass';
                var tm = stock.total_mass;
                prefill.sizeValue = typeof tm === 'object' ? tm.value + ' ' + tm.units : String(tm);
            } else if (stock.total_volume) {
                prefill.sizeType = 'total_volume';
                var tv = stock.total_volume;
                prefill.sizeValue = typeof tv === 'object' ? tv.value + ' ' + tv.units : String(tv);
            }

            var soluteList = stock.solutes || [];
            var components = [];
            (stock.components || []).forEach(function(compName) {
                var isSolute = soluteList.indexOf(compName) !== -1;
                if (stock.masses && stock.masses[compName]) {
                    var m = stock.masses[compName];
                    components.push({name: compName, propType: 'mass',
                        value: typeof m === 'object' ? m.value : m,
                        units: typeof m === 'object' ? m.units : '',
                        isSolute: isSolute});
                } else if (stock.volumes && stock.volumes[compName]) {
                    var vol = stock.volumes[compName];
                    components.push({name: compName, propType: 'volume',
                        value: typeof vol === 'object' ? vol.value : vol,
                        units: typeof vol === 'object' ? vol.units : '',
                        isSolute: isSolute});
                } else if (stock.concentrations && stock.concentrations[compName]) {
                    var c = stock.concentrations[compName];
                    components.push({name: compName, propType: 'concentration',
                        value: typeof c === 'object' ? c.value : c,
                        units: typeof c === 'object' ? c.units : '',
                        isSolute: isSolute});
                } else if (stock.mass_fractions && stock.mass_fractions[compName] != null) {
                    components.push({name: compName, propType: 'mass_fraction',
                        value: stock.mass_fractions[compName],
                        isSolute: isSolute});
                } else if (stock.volume_fractions && stock.volume_fractions[compName] != null) {
                    components.push({name: compName, propType: 'volume_fraction',
                        value: stock.volume_fractions[compName],
                        isSolute: isSolute});
                }
            });
            prefill.components = components;

            createStockCard(prefill);
        });

        showStatus('Loaded ' + stocks.length + ' stock(s) from server.');
    } catch (e) {
        showStatus('Error loading stocks: ' + e.message, true);
    }
}

// ---- Sweep table management ----
var SWEEP_PROPERTY_TYPES = [
    {value: 'mass_fraction', label: 'Mass Fraction', needsUnits: false},
    {value: 'volume_fraction', label: 'Volume Fraction', needsUnits: false},
    {value: 'concentration', label: 'Concentration', needsUnits: true, defaultUnit: 'mg/ml'},
    {value: 'molarity', label: 'Molarity', needsUnits: true, defaultUnit: 'mol/L'},
    {value: 'molality', label: 'Molality', needsUnits: true, defaultUnit: 'mol/kg'},
];

function addSweepRow(prefill) {
    prefill = prefill || {};
    var tbody = document.querySelector('#sweep-table tbody');
    var tr = document.createElement('tr');
    tr.className = 'sweep-row';

    var defaultPropType = prefill.propType || 'mass_fraction';
    var propTypeOptions = SWEEP_PROPERTY_TYPES.map(function(pt) {
        return '<option value="' + pt.value + '"' + (defaultPropType === pt.value ? ' selected' : '') + '>' + pt.label + '</option>';
    }).join('');

    var selectedType = SWEEP_PROPERTY_TYPES.find(function(pt) { return pt.value === defaultPropType; }) || SWEEP_PROPERTY_TYPES[0];
    var unitsDisabled = selectedType.needsUnits ? '' : ' disabled';
    var defaultUnit = prefill.units || (selectedType.needsUnits ? selectedType.defaultUnit : '');
    var isRemainder = prefill.isRemainder ? ' checked' : '';
    var isSolute = prefill.isSolute ? ' checked' : '';
    var useChecked = prefill.use === false ? '' : ' checked';

    tr.innerHTML = [
        '<td><input type="checkbox" class="sweep-use"' + useChecked + '></td>',
        '<td><input type="text" class="sweep-comp-name" list="component-names-datalist" placeholder="Component" value="' + escHtml(prefill.name || '') + '"></td>',
        '<td><select class="sweep-prop-type">' + propTypeOptions + '</select></td>',
        '<td><input type="number" class="sweep-start" placeholder="0" value="' + escHtml(prefill.start !== undefined ? String(prefill.start) : '0') + '" step="any"></td>',
        '<td><input type="number" class="sweep-stop" placeholder="1" value="' + escHtml(prefill.stop !== undefined ? String(prefill.stop) : '1') + '" step="any"></td>',
        '<td><input type="number" class="sweep-steps" placeholder="5" value="' + escHtml(prefill.steps !== undefined ? String(prefill.steps) : '5') + '" min="2" step="1"></td>',
        '<td><input type="text" class="sweep-units"' + unitsDisabled + ' placeholder="Units" value="' + escHtml(defaultUnit) + '"></td>',
        '<td><input type="checkbox" class="sweep-remainder"' + isRemainder + '></td>',
        '<td><input type="checkbox" class="sweep-solute"' + isSolute + '></td>',
        '<td><button class="remove-sweep-row-btn" title="Remove">&times;</button></td>',
    ].join('');

    tr.querySelector('.sweep-prop-type').addEventListener('change', function() {
        var pt = SWEEP_PROPERTY_TYPES.find(function(p) { return p.value === this.value; }, this);
        var unitsInput = tr.querySelector('.sweep-units');
        if (pt && pt.needsUnits) {
            unitsInput.disabled = false;
            unitsInput.value = pt.defaultUnit;
        } else {
            unitsInput.disabled = true;
            unitsInput.value = '';
        }
    });

    tr.querySelector('.sweep-remainder').addEventListener('change', function() {
        var isRem = this.checked;
        tr.classList.toggle('sweep-row-remainder', isRem);
        tr.querySelector('.sweep-start').disabled = isRem;
        tr.querySelector('.sweep-stop').disabled = isRem;
        tr.querySelector('.sweep-steps').disabled = isRem;
    });

    if (prefill.isRemainder) {
        tr.classList.add('sweep-row-remainder');
        tr.querySelector('.sweep-start').disabled = true;
        tr.querySelector('.sweep-stop').disabled = true;
        tr.querySelector('.sweep-steps').disabled = true;
    }

    tr.querySelector('.remove-sweep-row-btn').addEventListener('click', function() {
        tr.remove();
    });

    tbody.appendChild(tr);
    return tr;
}

function linspace(start, stop, num) {
    if (num < 2) return [start];
    var result = [];
    var step = (stop - start) / (num - 1);
    for (var i = 0; i < num; i++) {
        result.push(start + i * step);
    }
    return result;
}

function cartesianProduct(arrays) {
    return arrays.reduce(function(acc, arr) {
        var result = [];
        acc.forEach(function(existing) {
            arr.forEach(function(item) {
                result.push(existing.concat([item]));
            });
        });
        return result;
    }, [[]]);
}

function generateSweepTargets() {
    var prefix = document.getElementById('sweep-prefix').value.trim() || 'target';
    var sizeType = document.getElementById('sweep-size-type').value;
    var sizeValue = document.getElementById('sweep-size-value').value.trim();

    var activeRows = [];
    var remainderComponents = [];
    var soluteNames = [];

    document.querySelectorAll('.sweep-row').forEach(function(row) {
        if (!row.querySelector('.sweep-use').checked) return;
        var compName = row.querySelector('.sweep-comp-name').value.trim();
        if (!compName) return;
        var isRemainder = row.querySelector('.sweep-remainder').checked;
        var isSolute = row.querySelector('.sweep-solute').checked;
        var propType = row.querySelector('.sweep-prop-type').value;
        var units = row.querySelector('.sweep-units').value.trim();

        if (isSolute && soluteNames.indexOf(compName) === -1) soluteNames.push(compName);

        if (isRemainder) {
            remainderComponents.push({name: compName, propType: propType, units: units});
        } else {
            var start = parseFloat(row.querySelector('.sweep-start').value);
            var stop = parseFloat(row.querySelector('.sweep-stop').value);
            var steps = parseInt(row.querySelector('.sweep-steps').value, 10);
            if (isNaN(start) || isNaN(stop) || isNaN(steps) || steps < 1) return;
            activeRows.push({name: compName, propType: propType, units: units, values: linspace(start, stop, steps)});
        }
    });

    if (activeRows.length === 0) return [];

    var grid = cartesianProduct(activeRows.map(function(row) { return row.values; }));

    var propTypeToKey = {
        'mass_fraction': 'mass_fractions',
        'volume_fraction': 'volume_fractions',
        'concentration': 'concentrations',
        'molarity': 'molarities',
        'molality': 'molalities',
    };

    return grid.map(function(combo, i) {
        var target = {name: prefix + '-' + String(i + 1).padStart(4, '0')};
        if (sizeValue) target[sizeType] = sizeValue;

        activeRows.forEach(function(row, j) {
            var key = propTypeToKey[row.propType];
            if (!key) return;
            if (!target[key]) target[key] = {};
            var pt = SWEEP_PROPERTY_TYPES.find(function(p) { return p.value === row.propType; });
            if (pt && pt.needsUnits && row.units) {
                target[key][row.name] = combo[j] + ' ' + row.units;
            } else {
                target[key][row.name] = combo[j];
            }
        });

        remainderComponents.forEach(function(rem) {
            var key = propTypeToKey[rem.propType];
            if (!key) return;
            if (!target[key]) target[key] = {};
            target[key][rem.name] = null;
        });

        if (soluteNames.length > 0) target.solutes = soluteNames.slice();

        return target;
    });
}

function previewSweep() {
    var targets = generateSweepTargets();
    var previewEl = document.getElementById('sweep-preview-area');

    if (targets.length === 0) {
        previewEl.innerHTML = '<p class="empty-state">No sweep rows configured. Add rows with Use checked.</p>';
        return;
    }

    var allKeys = [];
    targets.forEach(function(t) {
        Object.keys(t).forEach(function(k) {
            if (k !== 'name' && allKeys.indexOf(k) === -1) allKeys.push(k);
        });
    });

    var displayed = targets.length > 25 ? targets.slice(0, 20).concat(targets.slice(-5)) : targets;
    var hasEllipsis = targets.length > 25;

    var headerRow = '<tr><th>Name</th>' + allKeys.map(function(k) { return '<th>' + escHtml(k) + '</th>'; }).join('') + '</tr>';

    var rows = [];
    displayed.forEach(function(t, i) {
        if (hasEllipsis && i === 20) {
            rows.push('<tr><td colspan="' + (allKeys.length + 1) + '" style="text-align:center;color:#6c757d">... (' + (targets.length - 25) + ' more) ...</td></tr>');
        }
        var cells = allKeys.map(function(k) {
            var val = t[k];
            if (val === undefined || val === null) return '<td>\u2014</td>';
            if (typeof val === 'object') return '<td>' + escHtml(JSON.stringify(val)) + '</td>';
            return '<td>' + escHtml(String(val)) + '</td>';
        }).join('');
        rows.push('<tr><td>' + escHtml(t.name) + '</td>' + cells + '</tr>');
    });

    previewEl.innerHTML = '<p style="margin-bottom:6px;font-size:13px"><strong>' + targets.length + '</strong> targets will be generated.</p>'
        + '<table class="data-table preview-table"><thead>' + headerRow + '</thead><tbody>' + rows.join('') + '</tbody></table>';
}

// ---- Sweep config persistence ----

function serializeSweepConfig() {
    var rows = [];
    document.querySelectorAll('.sweep-row').forEach(function(row) {
        rows.push({
            use: row.querySelector('.sweep-use').checked,
            name: row.querySelector('.sweep-comp-name').value,
            prop_type: row.querySelector('.sweep-prop-type').value,
            start: row.querySelector('.sweep-start').value,
            stop: row.querySelector('.sweep-stop').value,
            steps: row.querySelector('.sweep-steps').value,
            units: row.querySelector('.sweep-units').value,
            is_remainder: row.querySelector('.sweep-remainder').checked,
            is_solute: row.querySelector('.sweep-solute').checked
        });
    });
    return {
        prefix: document.getElementById('sweep-prefix').value,
        size_type: document.getElementById('sweep-size-type').value,
        size_value: document.getElementById('sweep-size-value').value,
        rows: rows
    };
}

function applySweepConfig(config) {
    if (!config || !config.rows) return;
    document.getElementById('sweep-prefix').value = config.prefix || 'target';
    document.getElementById('sweep-size-type').value = config.size_type || 'total_mass';
    document.getElementById('sweep-size-value').value = config.size_value || '';
    document.querySelector('#sweep-table tbody').innerHTML = '';
    config.rows.forEach(function(row) {
        addSweepRow({
            use: row.use,
            name: row.name,
            propType: row.prop_type,
            start: row.start !== '' ? row.start : undefined,
            stop: row.stop !== '' ? row.stop : undefined,
            steps: row.steps !== '' ? row.steps : undefined,
            units: row.units,
            isRemainder: row.is_remainder,
            isSolute: row.is_solute
        });
    });
}

async function saveSweepConfig() {
    var config = serializeSweepConfig();
    try {
        var token = await login();
        await authedFetch('/enqueue', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({task_name: 'save_sweep_config', sweep_config: config})
        });
    } catch (e) {
        // silently ignore - save is best-effort
    }
}

async function loadSweepConfig() {
    try {
        var r = await fetch('/load_sweep_config');
        if (r.ok) {
            var config = await r.json();
            if (config && config.rows && config.rows.length > 0) {
                applySweepConfig(config);
                return;
            }
        }
    } catch (e) {
        // silently ignore
    }
    addSweepRow(null);
}

async function uploadTargets() {
    var targets = generateSweepTargets();

    if (targets.length === 0) {
        showStatus('No targets to upload.', true);
        return;
    }

    var btn = document.getElementById('upload-targets-btn');
    btn.disabled = true;
    showStatus('Uploading ' + targets.length + ' targets...');

    try {
        var token = await login();
        var r = await authedFetch('/enqueue', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({task_name: 'upload_targets', targets: targets, reset: true})
        });
        if (!r.ok) {
            showStatus('Failed to enqueue upload.', true);
            return;
        }
        var uuidText = await r.text();
        var uuid = uuidText.trim().replace(/^"|"$/g, '');
        var result = await pollForResult(token, uuid, 60000);

        var errEl = document.getElementById('sweeps-upload-errors');
        if (result && result.success) {
            showStatus('Uploaded ' + result.count + ' target(s).');
            errEl.innerHTML = '';
            saveSweepConfig();
        } else if (result && result.errors) {
            showStatus('Upload failed with ' + result.errors.length + ' error(s).', true);
            errEl.innerHTML = '<div class="upload-error-list"><strong>Errors:</strong><ul>'
                + result.errors.map(function(e) {
                    return '<li>' + escHtml('[' + e.index + '] ' + e.name + ': ' + e.error) + '</li>';
                }).join('')
                + '</ul></div>';
        } else {
            showStatus('Upload failed.', true);
        }
    } catch (e) {
        showStatus('Upload error: ' + e.message, true);
    } finally {
        btn.disabled = false;
    }
}

// ---- Plot Sweep ----
var plotSweepState = {
    baseTargets: [],
    balancedTargets: [],
    selectedBalancedIds: [],
    lastUpdated: null,
    error: null,
    loaded: false
};

var plotSweepInitialized = false;
var PLOT_SWEEP_SETTINGS_KEY = 'mixdoctor_plot_settings';

var PLOT_PROPERTY_TYPES = [
    {value: 'mass', label: 'Mass', key: 'masses', unitAware: true},
    {value: 'volume', label: 'Volume', key: 'volumes', unitAware: true},
    {value: 'concentration', label: 'Concentration', key: 'concentrations', unitAware: true},
    {value: 'mass_fraction', label: 'Mass Fraction', key: 'mass_fractions', unitAware: false},
    {value: 'volume_fraction', label: 'Volume Fraction', key: 'volume_fractions', unitAware: false},
    {value: 'molarity', label: 'Molarity', key: 'molarities', unitAware: true},
    {value: 'molality', label: 'Molality', key: 'molalities', unitAware: true},
];

function getPlotPropertyMeta(value) {
    return PLOT_PROPERTY_TYPES.find(function(p) { return p.value === value; }) || PLOT_PROPERTY_TYPES[0];
}

function setPlotSweepStatus(msg, isError) {
    var el = document.getElementById('plot-sweep-status');
    if (!el) return;
    el.textContent = msg || '';
    el.style.color = isError ? '#dc3545' : '#6c757d';
}

async function loadPlotSweepData() {
    setPlotSweepStatus('Loading data...');
    plotSweepState.error = null;
    try {
        var baseReq = fetch('/list_targets');
        var balReq = fetch('/list_balanced_targets');
        var results = await Promise.all([baseReq, balReq]);
        var baseResp = results[0];
        var balResp = results[1];
        plotSweepState.baseTargets = baseResp.ok ? await baseResp.json() : [];
        plotSweepState.balancedTargets = balResp.ok ? await balResp.json() : [];
        plotSweepState.balancedTargets.forEach(function(entry, idx) {
            entry._balanced_idx = idx;
        });
        plotSweepState.selectedBalancedIds = [];
        var subStatus = document.getElementById('plot-sweep-subsample-status');
        if (subStatus) subStatus.textContent = '';
        plotSweepState.lastUpdated = new Date();
        plotSweepState.loaded = true;
        setPlotSweepStatus(
            'Base: ' + plotSweepState.baseTargets.length +
            ' | Balanced: ' + plotSweepState.balancedTargets.length
        );
        populatePlotSweepComponentOptions();
        renderPlotSweep(false);
        if (submitTabInitialized) renderSubmitPreview();
    } catch (e) {
        plotSweepState.error = e.message;
        setPlotSweepStatus('Failed to load data', true);
    }
}

function collectPlotSweepComponents() {
    var compSet = {};
    [plotSweepState.baseTargets, plotSweepState.balancedTargets].forEach(function(list) {
        (list || []).forEach(function(entry) {
            (entry.components || []).forEach(function(comp) {
                compSet[comp] = true;
            });
        });
    });
    return Object.keys(compSet).sort();
}

function populatePlotSweepPropertyOptions() {
    var selects = document.querySelectorAll('.plot-sweep-prop-select');
    selects.forEach(function(select) {
        var current = select.value;
        select.innerHTML = '';
        PLOT_PROPERTY_TYPES.forEach(function(p) {
            var opt = document.createElement('option');
            opt.value = p.value;
            opt.textContent = p.label;
            select.appendChild(opt);
        });
        if (current) select.value = current;
    });
}

function populatePlotSweepComponentOptions() {
    var components = collectPlotSweepComponents();
    var selects = [
        {id: 'plot-sweep-x', idx: 0},
        {id: 'plot-sweep-y', idx: 1},
        {id: 'plot-sweep-x3', idx: 0},
        {id: 'plot-sweep-y3', idx: 1},
        {id: 'plot-sweep-z3', idx: 2},
        {id: 'plot-sweep-a', idx: 0},
        {id: 'plot-sweep-b', idx: 1},
        {id: 'plot-sweep-c', idx: 2}
    ];
    selects.forEach(function(entry) {
        var id = entry.id;
        var prefIdx = entry.idx;
        var sel = document.getElementById(id);
        if (!sel) return;
        var current = sel.value;
        sel.innerHTML = '';
        var placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = 'Select...';
        sel.appendChild(placeholder);
        components.forEach(function(comp) {
            var opt = document.createElement('option');
            opt.value = comp;
            opt.textContent = comp;
            sel.appendChild(opt);
        });
        if (current && components.indexOf(current) !== -1) {
            sel.value = current;
        } else {
            sel.value = components.length > prefIdx ? components[prefIdx] : (components[0] || '');
        }
    });
}

function loadPlotSweepSettings() {
    try {
        var raw = localStorage.getItem(PLOT_SWEEP_SETTINGS_KEY);
        if (!raw) return {};
        return JSON.parse(raw) || {};
    } catch (e) {
        return {};
    }
}

function savePlotSweepSettings(settings) {
    try {
        localStorage.setItem(PLOT_SWEEP_SETTINGS_KEY, JSON.stringify(settings));
    } catch (e) {
        // ignore
    }
}

function applyPlotSweepSettings(settings) {
    settings = settings || {};
    var typeSel = document.getElementById('plot-sweep-type');
    if (typeSel && settings.type) typeSel.value = settings.type;
    var mapping = {
        x: 'plot-sweep-x',
        y: 'plot-sweep-y',
        x3: 'plot-sweep-x3',
        y3: 'plot-sweep-y3',
        z3: 'plot-sweep-z3',
        a: 'plot-sweep-a',
        b: 'plot-sweep-b',
        c: 'plot-sweep-c',
        xProp: 'plot-sweep-x-prop',
        yProp: 'plot-sweep-y-prop',
        x3Prop: 'plot-sweep-x3-prop',
        y3Prop: 'plot-sweep-y3-prop',
        z3Prop: 'plot-sweep-z3-prop',
        aProp: 'plot-sweep-a-prop',
        bProp: 'plot-sweep-b-prop',
        cProp: 'plot-sweep-c-prop',
        xUnits: 'plot-sweep-x-units',
        yUnits: 'plot-sweep-y-units',
        x3Units: 'plot-sweep-x3-units',
        y3Units: 'plot-sweep-y3-units',
        z3Units: 'plot-sweep-z3-units',
        aUnits: 'plot-sweep-a-units',
        bUnits: 'plot-sweep-b-units',
        cUnits: 'plot-sweep-c-units'
    };
    Object.keys(mapping).forEach(function(key) {
        var sel = document.getElementById(mapping[key]);
        if (sel && settings[key]) sel.value = settings[key];
    });
    updatePlotSweepAxesVisibility();
}

function getPlotSweepSettingsFromUI() {
    return {
        type: document.getElementById('plot-sweep-type').value,
        x: document.getElementById('plot-sweep-x').value,
        y: document.getElementById('plot-sweep-y').value,
        x3: document.getElementById('plot-sweep-x3').value,
        y3: document.getElementById('plot-sweep-y3').value,
        z3: document.getElementById('plot-sweep-z3').value,
        a: document.getElementById('plot-sweep-a').value,
        b: document.getElementById('plot-sweep-b').value,
        c: document.getElementById('plot-sweep-c').value,
        xProp: document.getElementById('plot-sweep-x-prop').value,
        yProp: document.getElementById('plot-sweep-y-prop').value,
        x3Prop: document.getElementById('plot-sweep-x3-prop').value,
        y3Prop: document.getElementById('plot-sweep-y3-prop').value,
        z3Prop: document.getElementById('plot-sweep-z3-prop').value,
        aProp: document.getElementById('plot-sweep-a-prop').value,
        bProp: document.getElementById('plot-sweep-b-prop').value,
        cProp: document.getElementById('plot-sweep-c-prop').value,
        xUnits: document.getElementById('plot-sweep-x-units').value,
        yUnits: document.getElementById('plot-sweep-y-units').value,
        x3Units: document.getElementById('plot-sweep-x3-units').value,
        y3Units: document.getElementById('plot-sweep-y3-units').value,
        z3Units: document.getElementById('plot-sweep-z3-units').value,
        aUnits: document.getElementById('plot-sweep-a-units').value,
        bUnits: document.getElementById('plot-sweep-b-units').value,
        cUnits: document.getElementById('plot-sweep-c-units').value
    };
}

function updatePlotSweepAxesVisibility() {
    var type = document.getElementById('plot-sweep-type').value;
    document.querySelectorAll('.plot-sweep-axes').forEach(function(el) {
        el.classList.remove('active');
    });
    var activeClass = type === '3d'
        ? '.plot-sweep-axes-3d'
        : (type === 'ternary' ? '.plot-sweep-axes-ternary' : '.plot-sweep-axes-2d');
    var active = document.querySelector(activeClass);
    if (active) active.classList.add('active');
}

function getPropertyValue(entry, propKey, component) {
    if (!entry || !propKey || !component) return null;
    var group = entry[propKey];
    if (!group || !(component in group)) return null;
    var val = group[component];
    if (val === null || val === undefined) return null;
    if (typeof val === 'object' && val.value !== undefined) {
        var v = parseFloat(val.value);
        return isFinite(v) ? v : null;
    }
    if (typeof val === 'number') return isFinite(val) ? val : null;
    var parsed = parseFloat(val);
    return isFinite(parsed) ? parsed : null;
}

function getPropertyUnits(entry, propKey, component) {
    if (!entry || !propKey || !component) return '';
    var group = entry[propKey];
    if (!group || !(component in group)) return '';
    var val = group[component];
    if (val && typeof val === 'object' && val.units) return val.units;
    return '';
}

function findUnits(entries, propKey, component) {
    for (var i = 0; i < entries.length; i++) {
        var units = getPropertyUnits(entries[i], propKey, component);
        if (units) return units;
    }
    return '';
}

function renderPlotSweep(saveSettings) {
    if (saveSettings !== false) savePlotSweepSettings(getPlotSweepSettingsFromUI());
    var noteEl = document.getElementById('plot-sweep-note');
    var plotEl = document.getElementById('plot-sweep-plot');
    if (!plotEl) return;
    if (!window.Plotly) {
        plotEl.innerHTML = '<div class="empty-state">Plotly failed to load.</div>';
        return;
    }

    var settings = getPlotSweepSettingsFromUI();
    var axes = [];
    var props = [];
    var units = [];
    if (settings.type === '3d') {
        axes = [settings.x3, settings.y3, settings.z3];
        props = [settings.x3Prop, settings.y3Prop, settings.z3Prop];
        units = [settings.x3Units, settings.y3Units, settings.z3Units];
    } else if (settings.type === 'ternary') {
        axes = [settings.a, settings.b, settings.c];
        props = [settings.aProp, settings.bProp, settings.cProp];
        units = [settings.aUnits, settings.bUnits, settings.cUnits];
    } else {
        axes = [settings.x, settings.y];
        props = [settings.xProp, settings.yProp];
        units = [settings.xUnits, settings.yUnits];
    }

    if (axes.some(function(a) { return !a; }) || props.some(function(p) { return !p; })) {
        plotEl.innerHTML = '<div class="empty-state">Select all axis components.</div>';
        return;
    }

    var propMeta = props.map(function(p) { return getPlotPropertyMeta(p); });

    var datasets = [];
    datasets.push({label: 'Base', entries: plotSweepState.baseTargets});
    datasets.push({label: 'Balanced', entries: plotSweepState.balancedTargets});

    var traces = [];
    var selectedSet = {};
    plotSweepState.selectedBalancedIds.forEach(function(id) { selectedSet[id] = true; });
    datasets.forEach(function(ds) {
        var x = [];
        var y = [];
        var z = [];
        var a = [];
        var b = [];
        var c = [];
        var text = [];
        var sx = [];
        var sy = [];
        var sz = [];
        var sa = [];
        var sb = [];
        var sc = [];
        var stext = [];
        ds.entries.forEach(function(entry) {
            var v1 = getPropertyValue(entry, propMeta[0].key, axes[0]);
            var v2 = getPropertyValue(entry, propMeta[1].key, axes[1]);
            var v3 = axes[2] ? getPropertyValue(entry, propMeta[2].key, axes[2]) : null;
            if (v1 === null || v2 === null || (axes[2] && v3 === null)) return;
            var label = entry.name || entry.source_target_name || '';
            var isSelected = (ds.label === 'Balanced') && selectedSet[entry._balanced_idx];
            if (settings.type === 'ternary') {
                a.push(v1);
                b.push(v2);
                c.push(v3);
                if (isSelected) {
                    sa.push(v1); sb.push(v2); sc.push(v3); stext.push(label);
                }
            } else if (settings.type === '3d') {
                x.push(v1);
                y.push(v2);
                z.push(v3);
                if (isSelected) {
                    sx.push(v1); sy.push(v2); sz.push(v3); stext.push(label);
                }
            } else {
                x.push(v1);
                y.push(v2);
                if (isSelected) {
                    sx.push(v1); sy.push(v2); stext.push(label);
                }
            }
            text.push(label);
        });

        if (settings.type === 'ternary') {
            traces.push({
                type: 'scatterternary',
                mode: 'markers',
                name: ds.label,
                a: a,
                b: b,
                c: c,
                text: text,
                hovertemplate: '%{text}<br>' +
                    axes[0] + ' (' + propMeta[0].label + ')= %{a}<br>' +
                    axes[1] + ' (' + propMeta[1].label + ')= %{b}<br>' +
                    axes[2] + ' (' + propMeta[2].label + ')= %{c}<extra>' + ds.label + '</extra>'
            });
        } else if (settings.type === '3d') {
            traces.push({
                type: 'scatter3d',
                mode: 'markers',
                name: ds.label,
                x: x,
                y: y,
                z: z,
                text: text,
                hovertemplate: '%{text}<br>' +
                    axes[0] + ' (' + propMeta[0].label + ')= %{x}<br>' +
                    axes[1] + ' (' + propMeta[1].label + ')= %{y}<br>' +
                    axes[2] + ' (' + propMeta[2].label + ')= %{z}<extra>' + ds.label + '</extra>'
            });
        } else {
            traces.push({
                type: 'scatter',
                mode: 'markers',
                name: ds.label,
                x: x,
                y: y,
                text: text,
                hovertemplate: '%{text}<br>' +
                    axes[0] + ' (' + propMeta[0].label + ')= %{x}<br>' +
                    axes[1] + ' (' + propMeta[1].label + ')= %{y}<extra>' + ds.label + '</extra>'
            });
        }

        if (ds.label === 'Balanced' && stext.length > 0) {
            if (settings.type === 'ternary') {
                traces.push({
                    type: 'scatterternary',
                    mode: 'markers',
                    name: 'Selected',
                    a: sa,
                    b: sb,
                    c: sc,
                    text: stext,
                    marker: {size: 10, symbol: 'circle-open', line: {width: 2, color: '#ff7f0e'}},
                    hovertemplate: '%{text}<br>' +
                        axes[0] + ' (' + propMeta[0].label + ')= %{a}<br>' +
                        axes[1] + ' (' + propMeta[1].label + ')= %{b}<br>' +
                        axes[2] + ' (' + propMeta[2].label + ')= %{c}<extra>Selected</extra>'
                });
            } else if (settings.type === '3d') {
                traces.push({
                    type: 'scatter3d',
                    mode: 'markers',
                    name: 'Selected',
                    x: sx,
                    y: sy,
                    z: sz,
                    text: stext,
                    marker: {size: 6, symbol: 'circle-open', line: {width: 2, color: '#ff7f0e'}},
                    hovertemplate: '%{text}<br>' +
                        axes[0] + ' (' + propMeta[0].label + ')= %{x}<br>' +
                        axes[1] + ' (' + propMeta[1].label + ')= %{y}<br>' +
                        axes[2] + ' (' + propMeta[2].label + ')= %{z}<extra>Selected</extra>'
                });
            } else {
                traces.push({
                    type: 'scatter',
                    mode: 'markers',
                    name: 'Selected',
                    x: sx,
                    y: sy,
                    text: stext,
                    marker: {size: 10, symbol: 'circle-open', line: {width: 2, color: '#ff7f0e'}},
                    hovertemplate: '%{text}<br>' +
                        axes[0] + ' (' + propMeta[0].label + ')= %{x}<br>' +
                        axes[1] + ' (' + propMeta[1].label + ')= %{y}<extra>Selected</extra>'
                });
            }
        }
    });

    if (traces.length === 0 || traces.every(function(t) { return (t.x && t.x.length === 0) || (t.a && t.a.length === 0); })) {
        plotEl.innerHTML = '<div class="empty-state">No data points for this selection.</div>';
        return;
    }

    var axisUnits = {
        x: units[0] || (propMeta[0].unitAware ? findUnits(datasets[0].entries, propMeta[0].key, axes[0]) : ''),
        y: units[1] || (propMeta[1].unitAware ? findUnits(datasets[0].entries, propMeta[1].key, axes[1]) : ''),
        z: axes[2] ? (units[2] || (propMeta[2].unitAware ? findUnits(datasets[0].entries, propMeta[2].key, axes[2]) : '')) : ''
    };

    var xLabel = axes[0] + ' (' + propMeta[0].label + (axisUnits.x ? ', ' + axisUnits.x : '') + ')';
    var yLabel = axes[1] + ' (' + propMeta[1].label + (axisUnits.y ? ', ' + axisUnits.y : '') + ')';
    var zLabel = axes[2] ? axes[2] + ' (' + propMeta[2].label + (axisUnits.z ? ', ' + axisUnits.z : '') + ')' : '';

    var layout = {
        margin: {l: 50, r: 20, t: 30, b: 50},
        legend: {orientation: 'h'},
        font: {size: 12},
        title: 'Sweep plot'
    };

    if (settings.type === 'ternary') {
        layout.ternary = {
            sum: null,
            aaxis: {title: axes[0]},
            baxis: {title: axes[1]},
            caxis: {title: axes[2]}
        };
    } else if (settings.type === '3d') {
        layout.scene = {
            xaxis: {title: xLabel},
            yaxis: {title: yLabel},
            zaxis: {title: zLabel}
        };
    } else {
        layout.xaxis = {title: xLabel};
        layout.yaxis = {title: yLabel};
    }

    Plotly.react(plotEl, traces, layout, {responsive: true, displaylogo: false});

    if (noteEl) {
        var notes = [];
        if (settings.type === 'ternary') {
            if (props.some(function(p) { return p.indexOf('fraction') === -1; })) {
                notes.push('Ternary plots are most meaningful for fraction-based properties.');
            }
            if (props[0] !== props[1] || props[0] !== props[2]) {
                notes.push('Ternary axes use different properties.');
            }
        }
        if (units.some(function(u, idx) { return u && !propMeta[idx].unitAware; })) {
            notes.push('Units are ignored for fraction-based properties.');
        }
        if (units.some(function(u) { return u; })) {
            notes.push('Unit labels do not rescale values.');
        }
        noteEl.textContent = notes.join(' ');
    }
}

function initPlotSweepTab() {
    if (plotSweepInitialized) {
        var plotEl = document.getElementById('plot-sweep-plot');
        Plotly && Plotly.Plots && plotEl && Plotly.Plots.resize(plotEl);
        return;
    }
    plotSweepInitialized = true;
    populatePlotSweepPropertyOptions();
    populatePlotSweepComponentOptions();
    var settings = loadPlotSweepSettings();
    if (!settings.type) settings.type = '2d';
    if (!settings.xProp) settings.xProp = 'mass_fraction';
    if (!settings.yProp) settings.yProp = 'mass_fraction';
    if (!settings.x3Prop) settings.x3Prop = 'mass_fraction';
    if (!settings.y3Prop) settings.y3Prop = 'mass_fraction';
    if (!settings.z3Prop) settings.z3Prop = 'mass_fraction';
    if (!settings.aProp) settings.aProp = 'mass_fraction';
    if (!settings.bProp) settings.bProp = 'mass_fraction';
    if (!settings.cProp) settings.cProp = 'mass_fraction';
    applyPlotSweepSettings(settings);

    document.getElementById('plot-sweep-type').addEventListener('change', function() {
        updatePlotSweepAxesVisibility();
        renderPlotSweep();
    });
    document.querySelectorAll('.plot-sweep-prop-select').forEach(function(el) {
        el.addEventListener('change', function() {
            updatePlotSweepUnitInputs();
            renderPlotSweep();
        });
    });
    document.querySelectorAll('.plot-sweep-unit-input').forEach(function(el) {
        el.addEventListener('change', function() { renderPlotSweep(); });
    });
    [
        'plot-sweep-x', 'plot-sweep-y',
        'plot-sweep-x3', 'plot-sweep-y3', 'plot-sweep-z3',
        'plot-sweep-a', 'plot-sweep-b', 'plot-sweep-c'
    ].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.addEventListener('change', function() { renderPlotSweep(); });
    });

    document.getElementById('plot-sweep-refresh-btn').addEventListener('click', function() {
        loadPlotSweepData();
    });
    document.getElementById('plot-sweep-plot-btn').addEventListener('click', function() {
        renderPlotSweep();
    });

    document.getElementById('plot-sweep-subsample-btn').addEventListener('click', function() {
        selectBalancedSubsample();
        renderPlotSweep();
    });

    updatePlotSweepUnitInputs();
    loadPlotSweepData();
}

function updatePlotSweepUnitInputs() {
    var pairs = [
        ['plot-sweep-x-prop', 'plot-sweep-x-units'],
        ['plot-sweep-y-prop', 'plot-sweep-y-units'],
        ['plot-sweep-x3-prop', 'plot-sweep-x3-units'],
        ['plot-sweep-y3-prop', 'plot-sweep-y3-units'],
        ['plot-sweep-z3-prop', 'plot-sweep-z3-units'],
        ['plot-sweep-a-prop', 'plot-sweep-a-units'],
        ['plot-sweep-b-prop', 'plot-sweep-b-units'],
        ['plot-sweep-c-prop', 'plot-sweep-c-units'],
    ];
    pairs.forEach(function(pair) {
        var propSel = document.getElementById(pair[0]);
        var unitInput = document.getElementById(pair[1]);
        if (!propSel || !unitInput) return;
        var meta = getPlotPropertyMeta(propSel.value);
        unitInput.disabled = !meta.unitAware;
        unitInput.placeholder = meta.unitAware ? 'e.g. mg/ml' : 'n/a';
    });
}

function selectBalancedSubsample() {
    var statusEl = document.getElementById('plot-sweep-subsample-status');
    var countInput = document.getElementById('plot-sweep-subsample-count');
    if (!countInput) return;
    var n = parseInt(countInput.value, 10);
    if (!n || n < 1) {
        plotSweepState.selectedBalancedIds = [];
        if (statusEl) statusEl.textContent = 'Enter a positive integer.';
        return;
    }
    var settings = getPlotSweepSettingsFromUI();
    var axes = [];
    var props = [];
    if (settings.type === '3d') {
        axes = [settings.x3, settings.y3, settings.z3];
        props = [settings.x3Prop, settings.y3Prop, settings.z3Prop];
    } else if (settings.type === 'ternary') {
        axes = [settings.a, settings.b, settings.c];
        props = [settings.aProp, settings.bProp, settings.cProp];
    } else {
        axes = [settings.x, settings.y];
        props = [settings.xProp, settings.yProp];
    }
    var propMeta = props.map(function(p) { return getPlotPropertyMeta(p); });
    var available = (plotSweepState.balancedTargets || []).filter(function(entry) {
        var v1 = getPropertyValue(entry, propMeta[0].key, axes[0]);
        var v2 = getPropertyValue(entry, propMeta[1].key, axes[1]);
        var v3 = axes[2] ? getPropertyValue(entry, propMeta[2].key, axes[2]) : 0;
        return v1 !== null && v2 !== null && (!axes[2] || v3 !== null);
    });
    if (available.length === 0) {
        plotSweepState.selectedBalancedIds = [];
        if (statusEl) statusEl.textContent = 'No balanced points available.';
        return;
    }
    var indices = available.map(function(entry) { return entry._balanced_idx; });
    for (var i = indices.length - 1; i > 0; i--) {
        var j = Math.floor(Math.random() * (i + 1));
        var tmp = indices[i];
        indices[i] = indices[j];
        indices[j] = tmp;
    }
    plotSweepState.selectedBalancedIds = indices.slice(0, Math.min(n, indices.length));
    if (statusEl) {
        statusEl.textContent = 'Selected ' + plotSweepState.selectedBalancedIds.length + ' balanced points.';
    }
    if (submitTabInitialized) renderSubmitPreview();
}

// ---- Submit Tab ----
var submitTabInitialized = false;
var submitState = {
    context: null
};

function setSubmitStatus(msg, isError) {
    var el = document.getElementById('submit-status');
    if (!el) return;
    el.textContent = msg || '';
    el.style.color = isError ? '#dc3545' : '#6c757d';
}

function setSubmitContextStatus(msg, isError) {
    var el = document.getElementById('submit-context-status');
    if (!el) return;
    el.textContent = msg || '';
    el.style.color = isError ? '#dc3545' : '#6c757d';
}

function getSubmitSampleMode() {
    var selected = document.querySelector('input[name="submit-sample-mode"]:checked');
    return selected ? selected.value : 'balanced_all';
}

function normalizeQtyValue(v) {
    if (v === null || v === undefined) return null;
    if (typeof v === 'object' && v.value !== undefined) {
        if (!v.units) return String(v.value);
        return String(v.value) + ' ' + String(v.units);
    }
    return v;
}

function clonePropMapForSolution(map, quantityLike) {
    if (!map || typeof map !== 'object') return null;
    var out = {};
    Object.keys(map).forEach(function(k) {
        var val = map[k];
        if (val === undefined) return;
        out[k] = quantityLike ? normalizeQtyValue(val) : val;
    });
    return Object.keys(out).length > 0 ? out : null;
}

function buildSolutionSampleFromDisplayEntry(entry, idx) {
    var sample = {};
    if (!entry || typeof entry !== 'object') return sample;
    sample.name = entry.name || entry.source_target_name || ('sample-' + (idx + 1));
    if (entry.location) sample.location = entry.location;
    if (entry.solutes && Array.isArray(entry.solutes) && entry.solutes.length > 0) {
        sample.solutes = entry.solutes.slice();
    }

    var totalMass = normalizeQtyValue(entry.total_mass);
    var totalVolume = normalizeQtyValue(entry.total_volume);
    if (totalMass) sample.total_mass = totalMass;
    if (totalVolume) sample.total_volume = totalVolume;

    var quantityGroups = ['masses', 'volumes', 'concentrations', 'molarities', 'molalities'];
    quantityGroups.forEach(function(key) {
        var mapped = clonePropMapForSolution(entry[key], true);
        if (mapped) sample[key] = mapped;
    });
    var fractionGroups = ['mass_fractions', 'volume_fractions'];
    fractionGroups.forEach(function(key) {
        var mapped = clonePropMapForSolution(entry[key], false);
        if (mapped) sample[key] = mapped;
    });
    return sample;
}

function collectSubmitSourceEntries() {
    var mode = getSubmitSampleMode();
    var entries = [];
    if (mode === 'no_sample') return entries;
    var balanced = plotSweepState.balancedTargets || [];
    if (mode === 'plot_subsample') {
        var idSet = {};
        (plotSweepState.selectedBalancedIds || []).forEach(function(id) { idSet[id] = true; });
        entries = balanced.filter(function(entry) { return idSet[entry._balanced_idx]; });
    } else {
        entries = balanced.slice();
    }
    return entries;
}

function parseJsonText(text, label) {
    var trimmed = (text || '').trim();
    if (!trimmed) return null;
    try {
        return JSON.parse(trimmed);
    } catch (e) {
        throw new Error('Invalid JSON for ' + label + ': ' + e.message);
    }
}

function collectProcessSampleKwargsFromUI() {
    var kwargs = {};
    kwargs.predict_next = !!document.getElementById('submit-kw-predict-next').checked;
    kwargs.enqueue_next = !!document.getElementById('submit-kw-enqueue-next').checked;
    kwargs.calibrate_sensor = !!document.getElementById('submit-kw-calibrate-sensor').checked;

    var name = document.getElementById('submit-kw-name').value.trim();
    var sampleUuid = document.getElementById('submit-kw-sample-uuid').value.trim();
    var campaign = document.getElementById('submit-kw-al-campaign-name').value.trim();
    var alUuid = document.getElementById('submit-kw-al-uuid').value.trim();
    if (name) kwargs.name = name;
    if (sampleUuid) kwargs.sample_uuid = sampleUuid;
    if (campaign) kwargs.AL_campaign_name = campaign;
    if (alUuid) kwargs.AL_uuid = alUuid;

    var predictCombine = parseJsonText(document.getElementById('submit-kw-predict-combine').value, 'predict_combine_comps');
    if (predictCombine !== null) kwargs.predict_combine_comps = predictCombine;

    var advanced = parseJsonText(document.getElementById('submit-kw-advanced-json').value, 'advanced kwargs');
    if (advanced !== null) {
        if (typeof advanced !== 'object' || Array.isArray(advanced)) {
            throw new Error('Advanced kwargs JSON must be an object.');
        }
        Object.keys(advanced).forEach(function(k) {
            kwargs[k] = advanced[k];
        });
    }
    return kwargs;
}

function collectConfigOverridesFromUI() {
    var overrides = {};
    if (document.getElementById('submit-override-prepare-volume-enabled').checked) {
        var prepareVolume = document.getElementById('submit-override-prepare-volume').value.trim();
        if (prepareVolume) overrides.prepare_volume = prepareVolume;
    }
    if (document.getElementById('submit-override-data-tag-enabled').checked) {
        var dataTag = document.getElementById('submit-override-data-tag').value.trim();
        if (dataTag) overrides.data_tag = dataTag;
    }
    if (document.getElementById('submit-override-al-components-enabled').checked) {
        var alComponents = parseJsonText(document.getElementById('submit-override-al-components').value, 'AL_components');
        if (!Array.isArray(alComponents)) {
            throw new Error('AL_components override must be a JSON array.');
        }
        overrides.AL_components = alComponents;
    }
    if (document.getElementById('submit-override-composition-format-enabled').checked) {
        var rawFormat = document.getElementById('submit-override-composition-format').value.trim();
        if (!rawFormat) {
            throw new Error('composition_format override is enabled but empty.');
        }
        try {
            overrides.composition_format = JSON.parse(rawFormat);
        } catch (e) {
            overrides.composition_format = rawFormat;
        }
    }
    return overrides;
}

function renderSubmitPreview() {
    var listEl = document.getElementById('submit-preview-list');
    var titleEl = document.getElementById('submit-preview-title');
    if (!listEl || !titleEl) return;
    var mode = getSubmitSampleMode();
    var cards = [];
    if (mode === 'no_sample') {
        cards.push({
            name: 'No Sample',
            summary: 'Will call process_sample with an empty sample payload.',
            componentHtml: '<span class="component-chip">predict/enqueue flow only</span>'
        });
    } else {
        var entries = collectSubmitSourceEntries();
        cards = entries.map(function(entry, i) {
            var modeLabel = mode === 'plot_subsample' ? 'Plot subset' : 'Balanced';
            var summary = modeLabel + ' #' + (i + 1);
            return {
                name: entry.name || entry.source_target_name || ('sample-' + (i + 1)),
                summary: summary,
                location: entry.location || '',
                componentHtml: '<div class="component-list">' + renderComponentList(entry) + '</div>'
            };
        });
    }

    titleEl.textContent = 'Samples to Submit (' + cards.length + ')';
    if (cards.length === 0) {
        listEl.innerHTML = '<p class="empty-state">No samples selected for this mode.</p>';
        return;
    }
    listEl.innerHTML = cards.map(function(card) {
        var locBadge = card.location ? '<span class="location-badge">' + escHtml(card.location) + '</span>' : '';
        return '<div class="card">'
            + '<div class="card-header">'
            + '<span class="card-name">' + escHtml(card.name) + '</span>'
            + locBadge
            + '</div>'
            + '<div style="font-size:12px;color:#6c757d;margin-bottom:6px;">' + escHtml(card.summary) + '</div>'
            + (card.componentHtml || '')
            + '</div>';
    }).join('');
}

function applySubmitContextToUI(ctx) {
    if (!ctx) return;
    if (ctx.orchestrator_uri) {
        document.getElementById('submit-orchestrator-uri').value = ctx.orchestrator_uri;
    }
    var cfg = ctx.config || {};
    if (cfg.prepare_volume !== undefined && cfg.prepare_volume !== null) {
        document.getElementById('submit-override-prepare-volume').value = String(cfg.prepare_volume);
    }
    if (cfg.data_tag !== undefined && cfg.data_tag !== null) {
        document.getElementById('submit-override-data-tag').value = String(cfg.data_tag);
    }
    if (cfg.AL_components !== undefined && cfg.AL_components !== null) {
        document.getElementById('submit-override-al-components').value = JSON.stringify(cfg.AL_components);
    }
    if (cfg.composition_format !== undefined && cfg.composition_format !== null) {
        if (typeof cfg.composition_format === 'string') {
            document.getElementById('submit-override-composition-format').value = cfg.composition_format;
        } else {
            document.getElementById('submit-override-composition-format').value = JSON.stringify(cfg.composition_format);
        }
    }

    var health = ctx.health || {};
    var statusParts = [];
    if (health.client_has_load !== undefined) statusParts.push('load=' + (health.client_has_load ? 'ok' : 'missing'));
    if (health.client_has_prep !== undefined) statusParts.push('prep=' + (health.client_has_prep ? 'ok' : 'missing'));
    if (health.client_has_agent !== undefined) statusParts.push('agent=' + (health.client_has_agent ? 'ok' : 'missing'));
    if (health.instrument_count !== undefined) statusParts.push('instrument=' + health.instrument_count);
    setSubmitContextStatus(statusParts.join(' | '), !(ctx.success !== false));
}

async function loadSubmitContext() {
    var uri = document.getElementById('submit-orchestrator-uri').value.trim();
    setSubmitStatus('');
    setSubmitContextStatus('Loading orchestrator context...', false);
    try {
        var params = { r: 'get_orchestrator_context' };
        if (uri) params.orchestrator_uri = uri;
        var resp = await queryDriver(params);
        if (!resp.ok) {
            throw new Error('context request failed');
        }
        var data = await resp.json();
        submitState.context = data;
        if (data.success === false) {
            setSubmitContextStatus(data.error || 'Failed to load context.', true);
            return;
        }
        applySubmitContextToUI(data);
        setSubmitStatus('Orchestrator context refreshed.', false);
    } catch (e) {
        setSubmitContextStatus('Failed: ' + e.message, true);
    }
}

async function submitSamplesToOrchestrator() {
    var mode = getSubmitSampleMode();
    var sampleEntries = collectSubmitSourceEntries();
    var samples = [];
    if (mode === 'no_sample') {
        samples = [{}];
    } else {
        samples = sampleEntries.map(function(entry, idx) {
            return buildSolutionSampleFromDisplayEntry(entry, idx);
        });
    }
    if (samples.length === 0) {
        showStatus('No samples to submit for this mode.', true);
        return;
    }

    var kwargs;
    var overrides;
    try {
        kwargs = collectProcessSampleKwargsFromUI();
        overrides = collectConfigOverridesFromUI();
    } catch (e) {
        showStatus(e.message, true);
        return;
    }

    if (mode === 'no_sample' && !kwargs.predict_next && !kwargs.enqueue_next) {
        showStatus('No Sample mode requires predict_next or enqueue_next.', true);
        return;
    }

    var orchestratorUri = document.getElementById('submit-orchestrator-uri').value.trim();
    if (!orchestratorUri) {
        showStatus('Orchestrator URI is required.', true);
        return;
    }

    var btn = document.getElementById('submit-run-btn');
    btn.disabled = true;
    setSubmitStatus('Submitting...', false);
    try {
        var token = await login();
        var payload = {
            task_name: 'submit_orchestrator_grid',
            orchestrator_uri: orchestratorUri,
            sample_mode: mode,
            samples: samples,
            process_sample_kwargs: kwargs,
            config_overrides: overrides
        };
        var r = await authedFetch('/enqueue', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        if (!r.ok) throw new Error('Failed to enqueue submit task');
        var uuidText = await r.text();
        var uuid = uuidText.trim().replace(/^"|"$/g, '');
        var result = await pollForResult(token, uuid, 180000);
        if (!result || result.success === false) {
            var errMsg = (result && result.error) ? result.error : 'Unknown error';
            setSubmitStatus('Submission failed: ' + errMsg, true);
            showStatus('Submission failed.', true);
            return;
        }
        setSubmitStatus(
            'Submitted ' + (result.count || 0) + ' task(s) to orchestrator.',
            false
        );
        showStatus('Orchestrator submission complete.');
    } catch (e) {
        setSubmitStatus('Submit error: ' + e.message, true);
        showStatus('Submit error: ' + e.message, true);
    } finally {
        btn.disabled = false;
    }
}

function initSubmitTab() {
    if (submitTabInitialized) {
        renderSubmitPreview();
        return;
    }
    submitTabInitialized = true;

    document.getElementById('submit-refresh-context-btn').addEventListener('click', function() {
        loadSubmitContext();
    });
    document.getElementById('submit-run-btn').addEventListener('click', function() {
        submitSamplesToOrchestrator();
    });

    document.querySelectorAll('input[name="submit-sample-mode"]').forEach(function(el) {
        el.addEventListener('change', renderSubmitPreview);
    });

    var previewTriggers = [
        'submit-kw-predict-next', 'submit-kw-enqueue-next', 'submit-kw-calibrate-sensor',
        'submit-kw-name', 'submit-kw-sample-uuid', 'submit-kw-al-campaign-name', 'submit-kw-al-uuid',
        'submit-kw-predict-combine', 'submit-kw-advanced-json',
        'submit-override-prepare-volume-enabled', 'submit-override-data-tag-enabled',
        'submit-override-al-components-enabled', 'submit-override-composition-format-enabled',
        'submit-override-prepare-volume', 'submit-override-data-tag',
        'submit-override-al-components', 'submit-override-composition-format'
    ];
    previewTriggers.forEach(function(id) {
        var el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('change', renderSubmitPreview);
        el.addEventListener('input', renderSubmitPreview);
    });

    if (!plotSweepState.loaded) {
        loadPlotSweepData();
    }
    renderSubmitPreview();
    loadSubmitContext();
}

// ---- Init ----
document.addEventListener('DOMContentLoaded', function() {
    // Tab switching
    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            switchTab(this.getAttribute('data-tab'));
        });
    });

    // Stocks tab
    document.getElementById('add-stock-btn').addEventListener('click', function() {
        createStockCard(null);
    });
    document.getElementById('upload-stocks-btn').addEventListener('click', uploadStocks);
    document.getElementById('load-stocks-from-server-btn').addEventListener('click', loadExistingStocksIntoCards);
    var clearDiagBtn = document.getElementById('solution-diagnostics-clear-btn');
    if (clearDiagBtn) {
        clearDiagBtn.addEventListener('click', clearSolutionDiagnostics);
    }

    // Components tab
    var compRefreshBtn = document.getElementById('components-refresh-btn');
    if (compRefreshBtn) {
        compRefreshBtn.addEventListener('click', loadComponentsEditor);
    }
    var compAddBtn = document.getElementById('components-add-btn');
    if (compAddBtn) {
        compAddBtn.addEventListener('click', addComponentRow);
    }

    // Sweeps tab
    document.getElementById('add-sweep-row-btn').addEventListener('click', function() {
        addSweepRow(null);
    });
    document.getElementById('preview-sweep-btn').addEventListener('click', previewSweep);
    document.getElementById('upload-targets-btn').addEventListener('click', uploadTargets);

    // Balance tab
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

    // Initialize
    loadComponentNames();
    loadComponentsEditor();
    createStockCard(null);
    loadSweepConfig();
});
