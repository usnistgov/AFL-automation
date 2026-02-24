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

// ---- Tab switching ----
function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId);
    });
    document.querySelectorAll('.tab-panel').forEach(function(panel) {
        panel.classList.toggle('active', panel.id === tabId);
    });
    if (tabId === 'balance-tab') {
        loadStocks();
        loadTargets();
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
        '  <button class="stock-remove-btn" title="Remove stock">&times;</button>',
        '</div>',
        '<table class="stock-comp-table">',
        '  <thead><tr><th>Component</th><th>Property</th><th>Value</th><th>Units</th><th></th></tr></thead>',
        '  <tbody class="stock-comp-tbody"></tbody>',
        '</table>',
        '<button class="add-comp-btn">+ Add Component</button>',
    ].join('');

    card.querySelector('.stock-remove-btn').addEventListener('click', function() {
        card.remove();
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

    tr.innerHTML = [
        '<td><input type="text" class="comp-name-input" list="component-names-datalist" placeholder="Component name" value="' + escHtml(prefill.name || '') + '"></td>',
        '<td><select class="comp-prop-type">' + propTypeOptions + '</select></td>',
        '<td><input type="number" class="comp-value-input" placeholder="Value" value="' + escHtml(prefill.value !== undefined ? String(prefill.value) : '') + '" step="any"></td>',
        '<td><input type="text" class="comp-units-input" placeholder="Units" value="' + escHtml(defaultUnit) + '"' + unitsDisabled + '></td>',
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

        // Build a minimal stock dict for the backend calculation
        var stockData = {name: '__temp__'};
        var sizeType  = card.querySelector('.stock-size-type').value;
        var sizeValue = card.querySelector('.stock-size-value').value.trim();
        if (sizeType !== 'none' && sizeValue) stockData[sizeType] = sizeValue;

        stockData[oldGroupKey] = {};
        if (oldPt && oldPt.needsUnits && oldUnits) {
            stockData[oldGroupKey][compName] = oldValue + ' ' + oldUnits;
        } else {
            stockData[oldGroupKey][compName] = parseFloat(oldValue);
        }

        try {
            var resp = await fetch(
                '/query_driver?r=compute_stock_properties&stock=' +
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

    card.querySelectorAll('.stock-comp-row').forEach(function(row) {
        var compName = row.querySelector('.comp-name-input').value.trim();
        if (!compName) return;
        var propType = row.querySelector('.comp-prop-type').value;
        var value = row.querySelector('.comp-value-input').value.trim();
        var units = row.querySelector('.comp-units-input').value.trim();
        var groupKey = propTypeToGroup[propType];
        if (!groupKey || !value) return;

        if (!propGroups[groupKey]) propGroups[groupKey] = {};
        var pt = STOCK_PROPERTY_TYPES.find(function(p) { return p.value === propType; });
        if (pt && pt.needsUnits && units) {
            propGroups[groupKey][compName] = value + ' ' + units;
        } else {
            propGroups[groupKey][compName] = parseFloat(value);
        }
    });

    Object.keys(propGroups).forEach(function(key) {
        result[key] = propGroups[key];
    });

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

            var components = [];
            (stock.components || []).forEach(function(compName) {
                if (stock.masses && stock.masses[compName]) {
                    var m = stock.masses[compName];
                    components.push({name: compName, propType: 'mass',
                        value: typeof m === 'object' ? m.value : m,
                        units: typeof m === 'object' ? m.units : ''});
                } else if (stock.volumes && stock.volumes[compName]) {
                    var vol = stock.volumes[compName];
                    components.push({name: compName, propType: 'volume',
                        value: typeof vol === 'object' ? vol.value : vol,
                        units: typeof vol === 'object' ? vol.units : ''});
                } else if (stock.concentrations && stock.concentrations[compName]) {
                    var c = stock.concentrations[compName];
                    components.push({name: compName, propType: 'concentration',
                        value: typeof c === 'object' ? c.value : c,
                        units: typeof c === 'object' ? c.units : ''});
                } else if (stock.mass_fractions && stock.mass_fractions[compName] != null) {
                    components.push({name: compName, propType: 'mass_fraction',
                        value: stock.mass_fractions[compName]});
                } else if (stock.volume_fractions && stock.volume_fractions[compName] != null) {
                    components.push({name: compName, propType: 'volume_fraction',
                        value: stock.volume_fractions[compName]});
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

    document.querySelectorAll('.sweep-row').forEach(function(row) {
        if (!row.querySelector('.sweep-use').checked) return;
        var compName = row.querySelector('.sweep-comp-name').value.trim();
        if (!compName) return;
        var isRemainder = row.querySelector('.sweep-remainder').checked;
        var propType = row.querySelector('.sweep-prop-type').value;
        var units = row.querySelector('.sweep-units').value.trim();

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
            is_remainder: row.querySelector('.sweep-remainder').checked
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
            isRemainder: row.is_remainder
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
    createStockCard(null);
    loadSweepConfig();
});
