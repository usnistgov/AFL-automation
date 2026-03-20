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

var componentsUploadState = {
    parsedComponents: []
};
var EXACT_BALANCE_ERROR_TOL = 1e-12;

// ---- Driver query helper (unqueued) ----
async function queryDriver(params) {
    var qs = new URLSearchParams(params);
    var url = '/query_driver?' + qs.toString();
    var r = await authedFetch(url, { method: 'GET' });
    if (!r.ok) {
        var detail = '';
        try {
            detail = (await r.text()).trim();
        } catch (e) {
            detail = '';
        }
        var msg = 'Driver query failed (' + r.status + ')';
        if (detail) msg += ': ' + detail;
        throw new Error(msg);
    }
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
async function pollForResult(token, uuid, timeoutMs, onTick) {
    timeoutMs = timeoutMs || 120000;
    var start = Date.now();
    while (Date.now() - start < timeoutMs) {
        await new Promise(function(resolve) { setTimeout(resolve, 500); });
        if (onTick) {
            await onTick();
        }
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

function fmtDuration(seconds) {
    if (seconds === null || seconds === undefined || !isFinite(seconds)) return '';
    var s = Math.max(0, Math.round(seconds));
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var sec = s % 60;
    if (h > 0) return h + 'h ' + m + 'm ' + sec + 's';
    if (m > 0) return m + 'm ' + sec + 's';
    return sec + 's';
}

function renderBalanceProgress(progress) {
    var textEl = document.getElementById('balance-progress-text');
    var etaEl = document.getElementById('balance-progress-eta');
    var barEl = document.getElementById('balance-progress-bar');
    var targetEl = document.getElementById('balance-progress-target');
    if (!textEl || !etaEl || !barEl || !targetEl) return;

    if (!progress) {
        textEl.textContent = 'Idle';
        etaEl.textContent = '';
        barEl.style.width = '0%';
        targetEl.textContent = '';
        return;
    }

    var total = progress.total || 0;
    var completed = progress.completed || 0;
    var fraction = progress.fraction || (total > 0 ? completed / total : 0);
    if (!isFinite(fraction)) fraction = 0;
    fraction = Math.max(0, Math.min(1, fraction));

    var percent = Math.round(fraction * 100);
    var status = progress.active ? 'Running' : (progress.message === 'done' ? 'Done' : 'Idle');
    var elapsedText = fmtDuration(progress.elapsed_s);
    textEl.textContent = status + ': ' + completed + '/' + total + ' (' + percent + '%)' + (elapsedText ? ' elapsed ' + elapsedText : '');
    barEl.style.width = percent + '%';

    var etaText = fmtDuration(progress.eta_s);
    etaEl.textContent = etaText ? ('ETA ' + etaText) : '';

    if (progress.current_target) {
        var idx = (progress.current_target_idx !== null && progress.current_target_idx !== undefined)
            ? (progress.current_target_idx + 1)
            : null;
        targetEl.textContent = idx ? ('Current target [' + idx + ']: ' + progress.current_target) : ('Current target: ' + progress.current_target);
    } else {
        targetEl.textContent = '';
    }
}

async function fetchBalanceProgress() {
    try {
        var r = await fetch('/get_balance_progress');
        if (!r.ok) return null;
        return await r.json();
    } catch (e) {
        return null;
    }
}

function parseToleranceInput() {
    var tolEl = document.getElementById('balance-tol-input');
    if (!tolEl) throw new Error('Tolerance input not found.');
    var txt = tolEl.value.trim();
    if (!txt) throw new Error('Tolerance is required.');
    var tol = Number(txt);
    if (!isFinite(tol) || tol <= 0) throw new Error('Tolerance must be a finite number > 0.');
    return tol;
}

function getBalanceMultistepEnabled() {
    var el = document.getElementById('balance-enable-multistep-input');
    if (!el) return false;
    return !!el.checked;
}

function parseMinimumVolumeInput() {
    var minVolEl = document.getElementById('balance-min-volume-input');
    if (!minVolEl) throw new Error('Minimum volume input not found.');
    var txt = minVolEl.value.trim();
    if (!txt) throw new Error('Minimum volume is required.');
    return txt;
}

async function loadBalanceSettings() {
    try {
        var r = await fetch('/get_balance_settings');
        if (!r.ok) return;
        var settings = await r.json();
        var tolEl = document.getElementById('balance-tol-input');
        if (tolEl && settings && settings.tol !== undefined && settings.tol !== null) {
            tolEl.value = String(settings.tol);
        }
        var minVolEl = document.getElementById('balance-min-volume-input');
        if (minVolEl && settings && settings.minimum_volume !== undefined && settings.minimum_volume !== null) {
            minVolEl.value = String(settings.minimum_volume);
        }
        var multistepEl = document.getElementById('balance-enable-multistep-input');
        if (multistepEl && settings && settings.enable_multistep_dilution !== undefined && settings.enable_multistep_dilution !== null) {
            multistepEl.checked = !!settings.enable_multistep_dilution;
        }
    } catch (e) {
        // Ignore; leave existing input value.
    }
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

function invalidateBalanceResults() {
    balanceResultsByTarget = {};
    balanceReportArray = [];
}

function normalizeQtyDictForCompare(dict) {
    if (!dict || typeof dict !== 'object') return null;
    var out = {};
    Object.keys(dict).sort().forEach(function(k) {
        out[k] = String(dict[k]);
    });
    return out;
}

function shouldInvalidateBalanceForTargets(targets) {
    if (!Array.isArray(targets) || !Array.isArray(balanceReportArray) || balanceReportArray.length === 0) return false;
    if (balanceReportArray.length !== targets.length) return true;
    for (var i = 0; i < targets.length; i++) {
        var live = targets[i] || {};
        var reported = balanceReportArray[i] && balanceReportArray[i].target ? balanceReportArray[i].target : null;
        if (!reported) return true;
        if ((reported.name || '') !== (live.name || '')) return true;
        if (reported.masses && live.masses) {
            var reportedMasses = JSON.stringify(normalizeQtyDictForCompare(reported.masses));
            var liveMasses = JSON.stringify(normalizeQtyDictForCompare(live.masses));
            if (reportedMasses !== liveMasses) return true;
        }
    }
    return false;
}

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
    if (entry && entry.max_component_error !== undefined && entry.max_component_error !== null) {
        var direct = Math.abs(Number(entry.max_component_error));
        if (isFinite(direct)) return direct;
    }
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

function getBalanceStatus(entry) {
    if (!entry) return null;
    if (entry.balance_status) return entry.balance_status;

    var success = entry.success;
    if (success === undefined && entry.balance_success !== undefined) {
        success = entry.balance_success;
    }
    if (success !== true) return 'failed';

    var maxErr = getMaxError(entry);
    if (maxErr > EXACT_BALANCE_ERROR_TOL) return 'within_tolerance';
    return 'succeeded';
}

function getBalanceStatusCounts(entries) {
    var counts = {
        succeeded: 0,
        within_tolerance: 0,
        failed: 0
    };
    (entries || []).forEach(function(entry) {
        var status = getBalanceStatus(entry);
        if (status && counts[status] !== undefined) {
            counts[status] += 1;
        }
    });
    return counts;
}

function formatBalanceStatusSummary(entries, total) {
    var counts = getBalanceStatusCounts(entries);
    var parts = [];
    if (counts.succeeded > 0) parts.push(counts.succeeded + ' succeeded');
    if (counts.within_tolerance > 0) parts.push(counts.within_tolerance + ' within tolerance');
    if (counts.failed > 0) parts.push(counts.failed + ' failed');
    if (parts.length === 0) return total ? String(total) : '';
    return parts.join(', ');
}

function balanceCardClass(name, idx) {
    var entry = getBalanceEntry(name, idx);
    if (!entry) return '';
    var status = getBalanceStatus(entry);
    if (status === 'within_tolerance') return 'card-within-tolerance';
    if (status === 'succeeded') return 'card-balanced';
    return 'card-failed';
}

function balanceCardIndicator(name, idx) {
    var entry = getBalanceEntry(name, idx);
    if (!entry) return '';
    var status = getBalanceStatus(entry);
    if (status === 'within_tolerance') {
        return '<span class="card-status card-status-within-tolerance">!</span>';
    }
    return status === 'succeeded'
        ? '<span class="card-status card-status-ok">&#10003;</span>'
        : '<span class="card-status card-status-fail">&#10007;</span>';
}

function renderCompositionTableHtml(data, options) {
    options = options || {};
    var title = options.title || '';
    var forceCoreColumns = options.forceCoreColumns !== false;
    var activeColsOverride = Array.isArray(options.activeCols) ? options.activeCols : null;
    var rowData = data || {};
    var components = Array.isArray(rowData.components) ? rowData.components.slice() : [];
    if (components.length === 0) {
        var compSet = {};
        ['masses', 'volumes', 'concentrations', 'mass_fractions', 'volume_fractions', 'molarities', 'molalities'].forEach(function(groupKey) {
            var group = rowData[groupKey];
            if (!group || typeof group !== 'object') return;
            Object.keys(group).forEach(function(comp) { compSet[comp] = true; });
        });
        components = Object.keys(compSet).sort();
    }

    var colDefs = [
        {key: 'masses',           label: 'Mass',          required: true},
        {key: 'volumes',          label: 'Volume',        required: false},
        {key: 'concentrations',   label: 'Concentration', required: true},
        {key: 'mass_fractions',   label: 'Mass Fraction', required: true},
        {key: 'volume_fractions', label: 'Vol. Fraction', required: false},
        {key: 'molarities',       label: 'Molarity',      required: false},
        {key: 'molalities',       label: 'Molality',      required: false},
    ];

    var activeCols = activeColsOverride || colDefs.filter(function(col) {
        if (forceCoreColumns && col.required) return true;
        return rowData[col.key] && Object.keys(rowData[col.key]).length > 0;
    });
    if (activeCols.length === 0) {
        activeCols = [{key: 'masses', label: 'Mass', required: true}];
    }

    var bodyHtml = '<p class="empty-state">No components.</p>';
    if (components.length > 0) {
        var thead = '<tr><th>Component</th>'
            + activeCols.map(function(c) { return '<th>' + c.label + '</th>'; }).join('')
            + '</tr>';
        var tbody = components.map(function(comp) {
            var cells = activeCols.map(function(col) {
                var dict = rowData[col.key];
                if (!dict || !(comp in dict) || dict[comp] === null) return '<td>\u2014</td>';
                return '<td>' + fmtQty(dict[comp]) + '</td>';
            }).join('');
            return '<tr><td><strong>' + escHtml(comp) + '</strong></td>' + cells + '</tr>';
        }).join('');
        bodyHtml = '<table class="data-table"><thead>' + thead + '</thead><tbody>' + tbody + '</tbody></table>';
    }

    return '<div class="modal-composition-panel">'
        + (title ? ('<div class="modal-composition-title">' + escHtml(title) + '</div>') : '')
        + bodyHtml
        + '</div>';
}

function getSharedCompositionColumns(rows, forceCoreColumns) {
    var colDefs = [
        {key: 'masses', label: 'Mass', required: true},
        {key: 'volumes', label: 'Volume', required: false},
        {key: 'concentrations', label: 'Concentration', required: true},
        {key: 'mass_fractions', label: 'Mass Fraction', required: true},
        {key: 'volume_fractions', label: 'Vol. Fraction', required: false},
        {key: 'molarities', label: 'Molarity', required: false},
        {key: 'molalities', label: 'Molality', required: false},
    ];
    return colDefs;
}

function hasExtendedComposition(data) {
    if (!data || typeof data !== 'object') return false;
    return ['volumes', 'concentrations', 'mass_fractions', 'volume_fractions', 'molarities', 'molalities']
        .some(function(key) {
            return data[key] && Object.keys(data[key]).length > 0;
        });
}

async function enrichBalancedTargetForModal(balanceEntry) {
    if (!balanceEntry || !balanceEntry.balanced_target) return null;
    if (balanceEntry._balanced_target_enriched) return balanceEntry._balanced_target_enriched;
    if (balanceEntry._balanced_target_enrich_promise) return balanceEntry._balanced_target_enrich_promise;

    var source = balanceEntry.balanced_target;
    if (hasExtendedComposition(source)) {
        balanceEntry._balanced_target_enriched = source;
        return source;
    }

    balanceEntry._balanced_target_enrich_promise = (async function() {
        try {
            var r = await fetch(
                '/compute_stock_properties?stock=' +
                encodeURIComponent(JSON.stringify(source))
            );
            if (!r.ok) return source;
            var computed = await r.json();
            if (!computed || computed.error) return source;
            var merged = Object.assign({}, computed);
            if (!merged.name && source.name) merged.name = source.name;
            if (!merged.location && source.location) merged.location = source.location;
            balanceEntry._balanced_target_enriched = merged;
            return merged;
        } catch (e) {
            return source;
        } finally {
            balanceEntry._balanced_target_enrich_promise = null;
        }
    })();

    return balanceEntry._balanced_target_enrich_promise;
}

// ---- Detail Modal ----
var stocksData = [];
var allTargetsData = [];
var targetsData = [];
var stockHistoryEntries = [];
var stockHistoryFilterText = '';
var selectedStockHistoryEntry = null;
var currentModalIdx = -1;
var currentModalType = null;
var targetsPaginationState = {
    pageSize: 50,
    renderedCount: 0,
    failedFirst: false,
    scrollThresholdPx: 240
};
var storageSources = {
    components: 'unknown',
    stock_history: 'unknown',
    stocks: 'local',
};

function getTargetOriginalIndex(target, fallbackIdx) {
    if (target && target._originalIdx !== undefined && target._originalIdx !== null) {
        return target._originalIdx;
    }
    return fallbackIdx;
}

function getTargetBalanceEntry(target, fallbackIdx) {
    if (!target) return null;
    return getBalanceEntry(target.name, getTargetOriginalIndex(target, fallbackIdx));
}

function isFailedBalanceEntry(entry) {
    return !!entry && entry.success === false;
}

function normalizeTargetsForState(targets) {
    if (!Array.isArray(targets)) return [];
    return targets.map(function(target, idx) {
        var normalized = Object.assign({}, target || {});
        normalized._originalIdx = idx;
        return normalized;
    });
}

function setSourceBadge(elId, source) {
    var el = document.getElementById(elId);
    if (!el) return;
    el.textContent = 'Source: ' + (source || 'unknown');
}

function applyStorageSourceBadges() {
    setSourceBadge('components-source-badge', storageSources.components);
    setSourceBadge('stocks-history-source', storageSources.stock_history);
}

async function refreshStorageSources() {
    try {
        var r = await fetch('/get_storage_sources');
        if (!r.ok) return;
        var data = await r.json();
        if (data && typeof data === 'object') {
            storageSources.components = data.components || storageSources.components;
            storageSources.stock_history = data.stock_history || storageSources.stock_history;
            storageSources.stocks = data.stocks || storageSources.stocks;
            applyStorageSourceBadges();
        }
    } catch (e) {
        // ignore source refresh failures
    }
}

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
    var br = (type === 'target') ? getTargetBalanceEntry(data, idx) : null;
    if (br) {
        var maxE = getMaxError(br);
        var status = getBalanceStatus(br);
        if (status === 'succeeded') {
            summaryParts.push('<span class="badge-success">&#10003; Succeeded</span>');
        } else if (status === 'within_tolerance') {
            summaryParts.push('<span class="badge-within-tolerance">Within Tolerance (max err: ' + (maxE * 100).toFixed(2) + '%)</span>');
        } else {
            summaryParts.push('<span class="badge-failure">&#10007; Failed (max err: ' + (maxE * 100).toFixed(2) + '%)</span>');
        }
    }
    document.getElementById('detail-modal-summary').innerHTML =
        summaryParts.length
            ? summaryParts.join('')
            : '<span class="summary-item" style="color:#6c757d">No summary available</span>';

    // ---- Composition table(s) ----
    var targetCompHtml = renderCompositionTableHtml(data, {
        title: 'Target Composition',
        forceCoreColumns: true
    });
    var modalTableHtml = targetCompHtml;
    if (type === 'target' && br && br.balanced_target) {
        var realizedData = br._balanced_target_enriched || br.balanced_target;
        var sharedCols = getSharedCompositionColumns([data, realizedData], true);
        targetCompHtml = renderCompositionTableHtml(data, {
            title: 'Target Composition',
            activeCols: sharedCols,
            forceCoreColumns: true
        });
        var realizedCompHtml = renderCompositionTableHtml(realizedData, {
            title: 'Realized Composition',
            activeCols: sharedCols,
            forceCoreColumns: true
        });
        modalTableHtml = '<div class="modal-composition-stack">'
            + targetCompHtml
            + realizedCompHtml
            + '</div>';
    }
    document.getElementById('modal-table').innerHTML = modalTableHtml;

    if (type === 'target' && br && br.balanced_target && !br._balanced_target_enriched) {
        enrichBalancedTargetForModal(br).then(function(enriched) {
            if (!enriched) return;
            if (currentModalType !== 'target' || currentModalIdx !== idx) return;
            showDetailModal(data, type, idx);
        });
    }

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
    if (currentModalType === 'target' && currentModalIdx >= 0 && targetsData.length > 1) {
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
    var statusEl = document.getElementById('targets-list-status');
    var loadMoreWrap = document.getElementById('targets-load-more-wrap');
    container.innerHTML = '<p class="empty-state">Loading...</p>';
    if (statusEl) statusEl.textContent = '';
    if (loadMoreWrap) loadMoreWrap.hidden = true;
    try {
        var r = await fetch('/list_targets');
        if (!r.ok) {
            allTargetsData = [];
            targetsData = [];
            container.innerHTML = '<p class="empty-state">Failed to load targets.</p>';
            return;
        }
        allTargetsData = normalizeTargetsForState(await r.json());
        renderTargets(allTargetsData);
    } catch (e) {
        allTargetsData = [];
        targetsData = [];
        container.innerHTML = '<p class="empty-state">Error loading targets.</p>';
    }
}

function getOrderedTargetsForView(data) {
    var ordered = Array.isArray(data) ? data.slice() : [];
    if (!targetsPaginationState.failedFirst || balanceReportArray.length === 0) {
        return ordered;
    }
    ordered.sort(function(a, b) {
        var order = {
            failed: 0,
            within_tolerance: 1,
            succeeded: 2
        };
        var aStatus = getBalanceStatus(getTargetBalanceEntry(a, a && a._originalIdx)) || 'succeeded';
        var bStatus = getBalanceStatus(getTargetBalanceEntry(b, b && b._originalIdx)) || 'succeeded';
        if (aStatus !== bStatus) return order[aStatus] - order[bStatus];
        return getTargetOriginalIndex(a, 0) - getTargetOriginalIndex(b, 0);
    });
    return ordered;
}

function updateTargetsListStatus() {
    var total = targetsData.length;
    var shown = Math.min(targetsPaginationState.renderedCount, total);
    var statusEl = document.getElementById('targets-list-status');
    var loadMoreWrap = document.getElementById('targets-load-more-wrap');
    if (!statusEl || !loadMoreWrap) return;

    if (total === 0) {
        statusEl.textContent = '';
        loadMoreWrap.hidden = true;
        return;
    }

    var parts = ['Showing ' + shown + ' of ' + total];
    if (targetsPaginationState.failedFirst && balanceReportArray.length > 0) {
        parts.push('Failed First');
    }
    statusEl.textContent = parts.join(' | ');
    loadMoreWrap.hidden = shown >= total;
}

function buildTargetCardHtml(target, viewIdx) {
    var originalIdx = getTargetOriginalIndex(target, viewIdx);
    var locBadge = target.location
        ? '<span class="location-badge">' + escHtml(target.location) + '</span>'
        : '';
    var colorCls = balanceCardClass(target.name, originalIdx);
    var indicator = balanceCardIndicator(target.name, originalIdx);
    return '<div class="card clickable ' + colorCls + '" data-view-idx="' + viewIdx + '">'
        + '<div class="card-header">'
        + '<span class="card-name">' + escHtml(target.name || '') + '</span>'
        + locBadge
        + indicator
        + '</div>'
        + '<div class="component-list">' + renderComponentList(target) + '</div>'
        + '</div>';
}

function appendNextTargetsPage() {
    var container = document.getElementById('targets-list');
    if (!container) return false;
    if (targetsPaginationState.renderedCount >= targetsData.length) {
        updateTargetsListStatus();
        return false;
    }

    var start = targetsPaginationState.renderedCount;
    var end = Math.min(start + targetsPaginationState.pageSize, targetsData.length);
    var html = targetsData.slice(start, end).map(function(target, offset) {
        return buildTargetCardHtml(target, start + offset);
    }).join('');
    container.insertAdjacentHTML('beforeend', html);
    targetsPaginationState.renderedCount = end;
    updateTargetsListStatus();
    return true;
}

function fillTargetsViewportIfNeeded() {
    var panel = document.getElementById('targets-panel');
    if (!panel) return;
    while (targetsPaginationState.renderedCount < targetsData.length
        && panel.scrollHeight <= panel.clientHeight + 40) {
        if (!appendNextTargetsPage()) break;
    }
}

function maybeLoadMoreTargets() {
    var panel = document.getElementById('targets-panel');
    if (!panel) return;
    if (targetsPaginationState.renderedCount >= targetsData.length) return;
    var distanceToBottom = panel.scrollHeight - panel.scrollTop - panel.clientHeight;
    if (distanceToBottom <= targetsPaginationState.scrollThresholdPx) {
        appendNextTargetsPage();
        fillTargetsViewportIfNeeded();
    }
}

function handleTargetsListClick(event) {
    var card = event.target.closest('.card.clickable[data-view-idx]');
    if (!card) return;
    var idx = parseInt(card.getAttribute('data-view-idx'), 10);
    if (!isFinite(idx) || !targetsData[idx]) return;
    showDetailModal(targetsData[idx], 'target', idx);
}

function renderTargets(data) {
    var container = document.getElementById('targets-list');
    var titleEl = document.getElementById('targets-panel-title')
        || document.querySelector('#targets-panel .panel-title');
    var previousModalTarget = null;
    if (currentModalType === 'target' && currentModalIdx >= 0 && targetsData[currentModalIdx]) {
        previousModalTarget = targetsData[currentModalIdx];
    }

    targetsData = getOrderedTargetsForView(data);
    targetsPaginationState.renderedCount = 0;

    // Update panel title with count and balance results
    var titleText = 'Targets';
    if (targetsData.length) {
        if (balanceReportArray.length > 0) {
            titleText += ' (' + formatBalanceStatusSummary(balanceReportArray, targetsData.length) + ')';
        } else {
            titleText += ' (' + targetsData.length + ')';
        }
    }
    titleEl.textContent = titleText;
    if (!targetsData || targetsData.length === 0) {
        container.innerHTML = '<p class="empty-state">No targets configured.</p>';
        currentModalIdx = targetsData.length ? currentModalIdx : -1;
        updateTargetsListStatus();
        updateModalNav();
        return;
    }
    container.innerHTML = '';
    appendNextTargetsPage();
    fillTargetsViewportIfNeeded();

    if (previousModalTarget) {
        var originalIdx = getTargetOriginalIndex(previousModalTarget, currentModalIdx);
        for (var i = 0; i < targetsData.length; i++) {
            if (getTargetOriginalIndex(targetsData[i], i) === originalIdx) {
                currentModalIdx = i;
                break;
            }
        }
        updateModalNav();
    }
}

// ---- Balance Execution ----
async function runBalance() {
    var btn = document.getElementById('balance-btn');
    btn.disabled = true;
    btn.textContent = 'Balancing...';
    var tol = null;
    var minimumVolume = null;
    var enableMultistep = false;
    try {
        tol = parseToleranceInput();
        minimumVolume = parseMinimumVolumeInput();
        enableMultistep = getBalanceMultistepEnabled();
    } catch (e) {
        showStatus(e.message, true);
        btn.disabled = false;
        btn.textContent = 'Balance';
        return;
    }
    showStatus('Running balance...');
    try {
        var token = await login();
        renderBalanceProgress({
            active: false,
            completed: 0,
            total: 0,
            fraction: 0,
            elapsed_s: 0,
            eta_s: null,
            current_target: null,
            current_target_idx: null,
            message: 'saving tolerance',
        });
        var setResp = await authedFetch('/enqueue', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                task_name: 'set_config',
                tol: tol,
                minimum_volume: minimumVolume,
                enable_multistep_dilution: enableMultistep
            })
        });
        if (!setResp.ok) {
            showStatus('Failed to enqueue tolerance update.', true);
            return;
        }
        var setUuid = (await setResp.text()).trim().replace(/^"|"$/g, '');
        var setRet = await pollForResult(token, setUuid, 60000);
        if (setRet && typeof setRet === 'string' && setRet.indexOf('Error:') === 0) {
            throw new Error('Failed to set tolerance: ' + setRet);
        }

        var r = await authedFetch('/enqueue', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                task_name: 'balance',
                return_report: true,
                enable_multistep_dilution: enableMultistep
            })
        });
        if (!r.ok) {
            showStatus('Failed to enqueue balance', true);
            return;
        }
        var uuidText = await r.text();
        var uuid = uuidText.trim().replace(/^"|"$/g, '');
        showStatus('Waiting for result...');
        var returnVal = await pollForResult(token, uuid, 120000, async function() {
            var progress = await fetchBalanceProgress();
            if (progress) {
                renderBalanceProgress(progress);
            }
        });
        var finalProgress = await fetchBalanceProgress();
        if (finalProgress) {
            renderBalanceProgress(finalProgress);
        }
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
var MIXDOCTOR_ACTIVE_TAB_KEY = 'mixdoctor-active-tab';

function getInitialTabId() {
    var defaultTabId = 'components-tab';
    try {
        var savedTabId = localStorage.getItem(MIXDOCTOR_ACTIVE_TAB_KEY);
        if (savedTabId && document.querySelector('.tab-btn[data-tab="' + savedTabId + '"]')) {
            return savedTabId;
        }
    } catch (e) {
        // Ignore storage errors and fall back to the default tab.
    }
    return defaultTabId;
}

function switchTab(tabId) {
    try {
        localStorage.setItem(MIXDOCTOR_ACTIVE_TAB_KEY, tabId);
    } catch (e) {
        // Ignore storage errors; tab switching should still work.
    }
    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId);
    });
    document.querySelectorAll('.tab-panel').forEach(function(panel) {
        panel.classList.toggle('active', panel.id === tabId);
    });
    if (tabId === 'components-tab') {
        loadComponentsEditor();
        refreshStorageSources();
    }
    if (tabId === 'stocks-tab') {
        loadStockHistorySidebar();
        refreshStorageSources();
    }
    if (tabId === 'balance-tab') {
        loadBalanceSettings();
        fetchBalanceProgress().then(renderBalanceProgress);
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
        refreshStorageSources();
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
    body.innerHTML = components.map(componentRowHtml).join('');
    bindComponentRowHandlers(body);
}

async function saveComponentRow(row) {
    if (!row) return;
    var uid = row.getAttribute('data-uid');
    var name = row.querySelector('.comp-name-input').value.trim();
    var density = row.querySelector('.comp-density-input').value.trim();
    var formula = row.querySelector('.comp-formula-input').value.trim();
    var sld = row.querySelector('.comp-sld-input').value.trim();

    if (!name) {
        showStatus('Component name is required.', true);
        return;
    }

    if (density) {
        var hasDigit = /[0-9]/.test(density);
        var hasUnitLetters = /[a-zA-Z]/.test(density);
        if (!hasDigit || !hasUnitLetters) {
            showStatus('Density must include a numeric value and units (e.g. 1.0 g/ml).', true);
            return;
        }
    }

    var payload = {
        r: uid ? 'update_component' : 'add_component',
    };
    if (uid) payload.uid = uid;

    [
        ['name', name],
        ['density', density],
        ['formula', formula],
        ['sld', sld],
    ].forEach(function(entry) {
        var key = entry[0];
        var value = entry[1];
        if (value !== '') payload[key] = value;
    });

    try {
        var r = await queryDriver(payload);
        if (!uid) {
            var newUid = (await r.text()).trim().replace(/^"|"$/g, '');
            row.setAttribute('data-uid', newUid);
            var uidCell = row.querySelector('.uid-cell');
            if (uidCell) uidCell.textContent = newUid;
            showStatus('Component added.');
        } else {
            showStatus('Component updated.');
        }
        loadComponentsEditor();
        loadComponentNames();
    } catch (e) {
        showStatus('Save failed: ' + e.message, true);
    }
}

async function deleteComponentRow(row) {
    if (!row) return;
    var uid = row.getAttribute('data-uid');
    var name = row.querySelector('.comp-name-input').value.trim();
    if (!uid) {
        row.remove();
        return;
    }
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

function resetComponentsUploadParseState() {
    componentsUploadState.parsedComponents = [];
    var submitBtn = document.getElementById('components-upload-submit-btn');
    if (submitBtn) submitBtn.disabled = true;
}

function openComponentsUploadModal() {
    resetComponentsUploadParseState();
    var summaryEl = document.getElementById('components-upload-summary');
    var errorsEl = document.getElementById('components-upload-errors');
    var previewEl = document.getElementById('components-upload-preview');
    var fileInput = document.getElementById('components-upload-file-input');
    if (summaryEl) summaryEl.innerHTML = '';
    if (errorsEl) errorsEl.innerHTML = '';
    if (previewEl) previewEl.innerHTML = '<p class="empty-state">Paste JSON and click Parse.</p>';
    if (fileInput) fileInput.value = '';
    document.getElementById('components-upload-modal-overlay').classList.add('visible');
}

function closeComponentsUploadModal() {
    document.getElementById('components-upload-modal-overlay').classList.remove('visible');
}

function resetComponentsUploadPreviewMessage(message) {
    var summaryEl = document.getElementById('components-upload-summary');
    var errorsEl = document.getElementById('components-upload-errors');
    var previewEl = document.getElementById('components-upload-preview');
    if (summaryEl) summaryEl.innerHTML = '';
    if (errorsEl) errorsEl.innerHTML = '';
    if (previewEl) previewEl.innerHTML = '<p class="empty-state">' + escHtml(message) + '</p>';
}

function handleComponentsUploadFileSelection(event) {
    var inputEl = event && event.target ? event.target : null;
    var file = inputEl && inputEl.files && inputEl.files[0] ? inputEl.files[0] : null;
    if (!file) return;

    var textInput = document.getElementById('components-upload-input');
    if (!textInput) return;

    resetComponentsUploadParseState();
    resetComponentsUploadPreviewMessage('Loading file. Click Parse to refresh preview.');

    var reader = new FileReader();
    reader.onload = function(loadEvent) {
        textInput.value = typeof loadEvent.target.result === 'string' ? loadEvent.target.result : '';
        resetComponentsUploadPreviewMessage('File loaded. Click Parse to refresh preview.');
        showStatus('Loaded component JSON file: ' + file.name);
    };
    reader.onerror = function() {
        resetComponentsUploadPreviewMessage('File load failed. Choose another file or paste JSON manually.');
        showStatus('Failed to read file: ' + file.name, true);
    };
    reader.readAsText(file);
}

function validateComponentDensity(density, label) {
    if (!density) return;
    var hasDigit = /[0-9]/.test(density);
    var hasUnitLetters = /[a-zA-Z]/.test(density);
    if (!hasDigit || !hasUnitLetters) {
        throw new Error(label + ' density must include a numeric value and units (e.g. 1.0 g/ml).');
    }
}

function normalizeJsonComponentEntry(entry, idx) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
        throw new Error('JSON component #' + (idx + 1) + ' must be an object.');
    }
    var out = {};
    ['uid', 'name', 'density', 'formula', 'sld'].forEach(function(key) {
        if (entry[key] === null || entry[key] === undefined) return;
        var value = String(entry[key]).trim();
        if (!value) return;
        out[key] = value;
    });
    if (!out.name) {
        throw new Error('JSON component #' + (idx + 1) + ' is missing a name.');
    }
    validateComponentDensity(out.density || '', 'Component "' + out.name + '"');
    return out;
}

function parseComponentsFromJson(raw) {
    var text = (raw || '').trim();
    if (!text) {
        throw new Error('Input is empty.');
    }
    var parsed = JSON.parse(text);
    var sourceComponents;
    if (Array.isArray(parsed)) {
        sourceComponents = parsed;
    } else if (parsed && typeof parsed === 'object' && Array.isArray(parsed.components)) {
        sourceComponents = parsed.components;
    } else {
        throw new Error('JSON must be an array of components or an object with a "components" array.');
    }
    return {
        components: sourceComponents.map(function(entry, idx) {
            return normalizeJsonComponentEntry(entry, idx);
        })
    };
}

function renderComponentsUploadResult(result) {
    var summaryEl = document.getElementById('components-upload-summary');
    var errorsEl = document.getElementById('components-upload-errors');
    var previewEl = document.getElementById('components-upload-preview');
    if (!summaryEl || !errorsEl || !previewEl) return;

    summaryEl.innerHTML = '<strong>Parsed components:</strong> ' + result.components.length;
    errorsEl.innerHTML = '';

    if (!result.components || result.components.length === 0) {
        previewEl.innerHTML = '<p class="empty-state">No valid components parsed.</p>';
        return;
    }

    var preview = result.components.slice(0, 5);
    var suffix = result.components.length > 5 ? '\n... (' + (result.components.length - 5) + ' more components)' : '';
    previewEl.innerHTML = '<pre class="diagnostic-pre">' + escHtml(JSON.stringify(preview, null, 2) + suffix) + '</pre>';
}

function parseComponentsUploadInput() {
    var input = document.getElementById('components-upload-input');
    if (!input) return;
    var submitBtn = document.getElementById('components-upload-submit-btn');
    resetComponentsUploadParseState();
    try {
        var result = parseComponentsFromJson(input.value);
        componentsUploadState.parsedComponents = result.components;
        renderComponentsUploadResult(result);
        if (submitBtn) submitBtn.disabled = result.components.length === 0;
        if (result.components.length === 0) {
            showStatus('Parse complete: no valid components found.', true);
        } else {
            showStatus('Parsed ' + result.components.length + ' component(s).');
        }
    } catch (e) {
        document.getElementById('components-upload-summary').innerHTML = '';
        document.getElementById('components-upload-errors').innerHTML =
            '<div class="upload-error-list"><strong>Parse error:</strong> ' + escHtml(e.message) + '</div>';
        document.getElementById('components-upload-preview').innerHTML =
            '<p class="empty-state">Fix parse errors and try again.</p>';
        if (submitBtn) submitBtn.disabled = true;
        showStatus('Parse failed: ' + e.message, true);
    }
}

async function uploadParsedComponentsFromModal() {
    if (!componentsUploadState.parsedComponents || componentsUploadState.parsedComponents.length === 0) {
        showStatus('No parsed components to upload.', true);
        return;
    }
    var submitBtn = document.getElementById('components-upload-submit-btn');
    submitBtn.disabled = true;
    showStatus('Uploading ' + componentsUploadState.parsedComponents.length + ' components...');
    try {
        var existingResp = await fetch('/list_components');
        if (!existingResp.ok) {
            throw new Error('Failed to load current components.');
        }
        var existingComponents = await existingResp.json();
        var existingByUid = {};
        existingComponents.forEach(function(existingComponent) {
            if (!existingComponent || typeof existingComponent !== 'object' || !existingComponent.uid) return;
            existingByUid[String(existingComponent.uid)] = existingComponent;
        });

        for (var i = 0; i < componentsUploadState.parsedComponents.length; i++) {
            var component = componentsUploadState.parsedComponents[i];
            var existingComponent = component.uid ? existingByUid[String(component.uid)] : null;
            var payload;
            if (existingComponent) {
                payload = Object.assign({}, existingComponent, component, {
                    r: 'update_component',
                    uid: component.uid
                });
            } else {
                payload = {
                    r: 'add_component'
                };
                if (component.uid) payload.uid = component.uid;
                ['name', 'density', 'formula', 'sld'].forEach(function(key) {
                    if (component[key]) payload[key] = component[key];
                });
            }
            await queryDriver(payload);
        }
        closeComponentsUploadModal();
        document.getElementById('components-upload-input').value = '';
        await loadComponentsEditor();
        await loadComponentNames();
        showStatus('Uploaded ' + componentsUploadState.parsedComponents.length + ' component(s).');
    } catch (e) {
        showStatus('Upload failed: ' + e.message, true);
    } finally {
        submitBtn.disabled = false;
    }
}

function buildComponentsDownloadFilename() {
    var now = new Date();
    function pad(value) {
        return String(value).padStart(2, '0');
    }
    return 'mixdoctor-components-'
        + now.getFullYear()
        + pad(now.getMonth() + 1)
        + pad(now.getDate())
        + '-'
        + pad(now.getHours())
        + pad(now.getMinutes())
        + pad(now.getSeconds())
        + '.json';
}

async function downloadComponentsJson() {
    try {
        var r = await fetch('/list_components');
        if (!r.ok) {
            throw new Error('Failed to load components for download.');
        }
        var components = await r.json();
        var blob = new Blob([JSON.stringify(components, null, 2)], {type: 'application/json'});
        var url = URL.createObjectURL(blob);
        var link = document.createElement('a');
        link.href = url;
        link.download = buildComponentsDownloadFilename();
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        showStatus('Components JSON downloaded.');
    } catch (e) {
        showStatus('Download failed: ' + e.message, true);
    }
}

function componentRowHtml(comp) {
    comp = comp || {};
    var name = comp.name || '';
    var density = comp.density || '';
    var formula = comp.formula || '';
    var sld = comp.sld || '';
    var uid = comp.uid || '';
    return [
        '<tr data-uid="', escHtml(uid), '">',
        '<td><input type="text" class="comp-name-input" value="', escHtml(name), '"></td>',
        '<td><input type="text" class="comp-density-input" placeholder="e.g. 1.0 g/ml" value="', escHtml(density), '"></td>',
        '<td><input type="text" class="comp-formula-input" placeholder="optional (e.g. H2O)" value="', escHtml(formula), '"></td>',
        '<td><input type="text" class="comp-sld-input" placeholder="optional (e.g. 6.35e-6 /A^2)" value="', escHtml(sld), '"></td>',
        '<td class="uid-cell">', escHtml(uid), '</td>',
        '<td><div class="components-actions">',
        '<button class="toolbar-btn comp-save-btn">Save</button>',
        '<button class="toolbar-btn comp-delete-btn">Delete</button>',
        '</div></td>',
        '</tr>'
    ].join('');
}

function bindComponentRowHandlers(body) {
    if (!body) return;
    body.querySelectorAll('.comp-save-btn').forEach(function(btn) {
        if (btn.dataset.bound === '1') return;
        btn.dataset.bound = '1';
        btn.addEventListener('click', function() {
            var row = this.closest('tr');
            saveComponentRow(row);
        });
    });
    body.querySelectorAll('.comp-delete-btn').forEach(function(btn) {
        if (btn.dataset.bound === '1') return;
        btn.dataset.bound = '1';
        btn.addEventListener('click', function() {
            var row = this.closest('tr');
            deleteComponentRow(row);
        });
    });
}

function addComponentRow() {
    var body = document.getElementById('components-table-body');
    if (!body) return;

    var emptyRow = body.querySelector('.empty-state');
    if (emptyRow) {
        body.innerHTML = '';
    }

    body.insertAdjacentHTML('afterbegin', componentRowHtml({}));
    bindComponentRowHandlers(body);

    var firstRow = body.querySelector('tr');
    if (firstRow) {
        var nameInput = firstRow.querySelector('.comp-name-input');
        if (nameInput) nameInput.focus();
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

function parseStockTagsInput() {
    var el = document.getElementById('stocks-tags-input');
    if (!el) return [];
    var raw = el.value.trim();
    if (!raw) return [];
    return raw.split(',').map(function(tag) {
        return tag.trim();
    }).filter(function(tag) {
        return tag.length > 0;
    });
}

function stockToPrefill(stock) {
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
    var rawComponentNames = stock.components || [];
    if ((!rawComponentNames || rawComponentNames.length === 0) && stock && typeof stock === 'object') {
        var componentSet = {};
        ['masses', 'volumes', 'concentrations', 'mass_fractions', 'volume_fractions', 'molarities', 'molalities'].forEach(function(groupKey) {
            var group = stock[groupKey];
            if (!group || typeof group !== 'object') return;
            Object.keys(group).forEach(function(name) {
                componentSet[name] = true;
            });
        });
        rawComponentNames = Object.keys(componentSet);
    }
    var components = [];
    rawComponentNames.forEach(function(compName) {
        var isSolute = soluteList.indexOf(compName) !== -1;
        if (stock.masses && stock.masses[compName] != null) {
            var m = stock.masses[compName];
            components.push({name: compName, propType: 'mass',
                value: typeof m === 'object' ? m.value : m,
                units: typeof m === 'object' ? m.units : '',
                isSolute: isSolute});
        } else if (stock.volumes && stock.volumes[compName] != null) {
            var vol = stock.volumes[compName];
            components.push({name: compName, propType: 'volume',
                value: typeof vol === 'object' ? vol.value : vol,
                units: typeof vol === 'object' ? vol.units : '',
                isSolute: isSolute});
        } else if (stock.concentrations && stock.concentrations[compName] != null) {
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
        } else if (stock.molarities && stock.molarities[compName] != null) {
            var molarity = stock.molarities[compName];
            components.push({name: compName, propType: 'molarity',
                value: typeof molarity === 'object' ? molarity.value : molarity,
                units: typeof molarity === 'object' ? molarity.units : '',
                isSolute: isSolute});
        } else if (stock.molalities && stock.molalities[compName] != null) {
            var molality = stock.molalities[compName];
            components.push({name: compName, propType: 'molality',
                value: typeof molality === 'object' ? molality.value : molality,
                units: typeof molality === 'object' ? molality.units : '',
                isSolute: isSolute});
        }
    });
    prefill.components = components;
    return prefill;
}

function loadStocksIntoCards(stocks) {
    document.getElementById('stock-cards-container').innerHTML = '';
    if (!stocks || stocks.length === 0) {
        createStockCard(null);
        return;
    }
    stocks.forEach(function(stock) {
        createStockCard(stockToPrefill(stock));
    });
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
    var tags = parseStockTagsInput();

    try {
        var token = await login();
        var r = await authedFetch('/enqueue', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({task_name: 'upload_stocks', stocks: stocks, reset: true, tags: tags})
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
            loadStockHistorySidebar();
            refreshStorageSources();
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
        loadStocksIntoCards(stocks);

        showStatus('Loaded ' + stocks.length + ' stock(s) from server.');
    } catch (e) {
        showStatus('Error loading stocks: ' + e.message, true);
    }
}

function getUniqueHistoryComponents(entry) {
    if (!entry || !Array.isArray(entry.components)) return [];
    var seen = {};
    var out = [];
    entry.components.forEach(function(name) {
        var trimmed = String(name || '').trim();
        if (!trimmed || seen[trimmed]) return;
        seen[trimmed] = true;
        out.push(trimmed);
    });
    out.sort();
    return out;
}

function getFilteredStockHistoryEntries() {
    var needle = String(stockHistoryFilterText || '').trim().toLowerCase();
    if (!needle) return stockHistoryEntries.slice();
    return stockHistoryEntries.filter(function(entry) {
        var parts = [];
        parts.push(entry.created_at || '');
        parts.push(String(entry.count || 0));
        if (Array.isArray(entry.tags)) {
            parts.push(entry.tags.join(' '));
        }
        if (Array.isArray(entry.components)) {
            parts.push(entry.components.join(' '));
        }
        if (Array.isArray(entry.stock_names)) {
            parts.push(entry.stock_names.join(' '));
        }
        return parts.join(' ').toLowerCase().indexOf(needle) !== -1;
    });
}

function quantityTextForMeta(val) {
    if (val === null || val === undefined) return '';
    if (typeof val === 'object' && val.value !== undefined) {
        return String(val.value) + (val.units ? (' ' + String(val.units)) : '');
    }
    return String(val);
}

function formatStockHistoryModalMeta(stock) {
    var parts = [];
    if (stock.location) parts.push('location: ' + stock.location);
    if (stock.total_mass) parts.push('total_mass: ' + quantityTextForMeta(stock.total_mass));
    if (stock.total_volume) parts.push('total_volume: ' + quantityTextForMeta(stock.total_volume));
    if (Array.isArray(stock.solutes) && stock.solutes.length > 0) {
        parts.push('solutes: ' + stock.solutes.join(', '));
    }
    return parts;
}

function renderStockHistoryModalStocks(stocks) {
    var container = document.getElementById('stock-history-modal-stocks');
    if (!container) return;
    if (!Array.isArray(stocks) || stocks.length === 0) {
        container.innerHTML = '<p class="empty-state">No stocks in this snapshot.</p>';
        return;
    }
    container.innerHTML = stocks.map(function(stock, idx) {
        var title = stock.name ? stock.name : ('Stock #' + (idx + 1));
        var location = stock.location ? ('<span class="location-badge">' + escHtml(stock.location) + '</span>') : '';
        var metaParts = formatStockHistoryModalMeta(stock);
        var metaHtml = metaParts.length > 0
            ? ('<div class="stock-history-modal-stock-meta">' + metaParts.map(function(text) {
                return escHtml(text);
            }).join(' | ') + '</div>')
            : '';
        var tableHtml = renderCompositionTableHtml(stock, {
            title: '',
            forceCoreColumns: true
        });
        return '<div class="stock-history-modal-stock-entry">'
            + '<div class="stock-history-modal-stock-header">'
            + '<span class="stock-history-modal-stock-name">' + escHtml(title) + '</span>'
            + location
            + '</div>'
            + metaHtml
            + tableHtml
            + '</div>';
    }).join('');
}

async function fetchStockHistorySnapshotData(snapshotId) {
    if (!snapshotId) throw new Error('snapshot_id is required');
    var r = await fetch('/load_stock_history?snapshot_id=' + encodeURIComponent(snapshotId));
    if (!r.ok) throw new Error('Failed to load stock snapshot.');
    var payload = await r.json();
    if (!payload || !payload.success) {
        throw new Error((payload && payload.error) ? payload.error : 'Invalid stock snapshot response.');
    }
    return payload;
}

async function populateStockHistoryModalDetails(entry) {
    var stockContainer = document.getElementById('stock-history-modal-stocks');
    if (!stockContainer || !entry || !entry.id) return;
    stockContainer.innerHTML = '<p class="empty-state">Loading stocks...</p>';
    try {
        if (!entry._snapshotPayload || !Array.isArray(entry._snapshotPayload.stocks)) {
            entry._snapshotPayload = await fetchStockHistorySnapshotData(entry.id);
        }
        renderStockHistoryModalStocks(entry._snapshotPayload.stocks || []);
    } catch (e) {
        stockContainer.innerHTML = '<p class="empty-state">Failed to load stock details.</p>';
    }
}

function openStockHistoryModal(entry) {
    if (!entry) return;
    selectedStockHistoryEntry = entry;
    var createdAt = entry.created_at || 'unknown time';
    var count = Number(entry.count || 0);
    var tags = Array.isArray(entry.tags) ? entry.tags.filter(function(tag) { return !!String(tag).trim(); }) : [];
    var components = getUniqueHistoryComponents(entry);

    var titleEl = document.getElementById('stock-history-modal-title');
    var metaEl = document.getElementById('stock-history-modal-meta');
    var tagsEl = document.getElementById('stock-history-modal-tags');
    var compsEl = document.getElementById('stock-history-modal-components');
    if (!titleEl || !metaEl || !tagsEl || !compsEl) return;

    titleEl.textContent = createdAt;
    metaEl.innerHTML = '<strong>' + escHtml(String(count)) + '</strong> stock(s)';
    tagsEl.innerHTML = tags.length > 0
        ? ('<strong>tags:</strong> ' + escHtml(tags.join(', ')))
        : '<span class="empty-state">No tags.</span>';
    compsEl.innerHTML = components.length > 0
        ? components.map(function(name) {
            return '<span class="stock-history-comp-chip">' + escHtml(name) + '</span>';
        }).join('')
        : '<p class="empty-state">No component summary available.</p>';

    var stocksEl = document.getElementById('stock-history-modal-stocks');
    if (stocksEl) {
        stocksEl.innerHTML = '<p class="empty-state">Loading stocks...</p>';
    }
    document.getElementById('stock-history-modal-overlay').classList.add('visible');
    populateStockHistoryModalDetails(entry);
}

function closeStockHistoryModal() {
    document.getElementById('stock-history-modal-overlay').classList.remove('visible');
    selectedStockHistoryEntry = null;
    var loadBtn = document.getElementById('stock-history-modal-load-btn');
    if (loadBtn) {
        loadBtn.disabled = false;
        loadBtn.textContent = 'Load';
    }
}

async function loadStockHistorySnapshot(snapshotId, options) {
    if (!snapshotId) return false;
    options = options || {};
    var setServerConfig = options.setServerConfig !== false;
    var switchToStocksTab = options.switchToStocksTab !== false;
    showStatus('Loading stock snapshot...');
    try {
        var payload = await fetchStockHistorySnapshotData(snapshotId);

        var stocks = Array.isArray(payload.stocks) ? payload.stocks : [];
        if (setServerConfig) {
            var token = await login();
            var setResp = await authedFetch('/enqueue', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    task_name: 'set_config',
                    stocks: stocks
                })
            });
            if (!setResp.ok) {
                showStatus('Failed to enqueue stock snapshot load.', true);
                return false;
            }
            var setUuid = (await setResp.text()).trim().replace(/^"|"$/g, '');
            var setRet = await pollForResult(token, setUuid, 60000);
            if (setRet && typeof setRet === 'string' && setRet.indexOf('Error:') === 0) {
                showStatus('Failed to apply stock snapshot config.', true);
                return false;
            }
        }

        loadStocksIntoCards(stocks);
        var tagsEl = document.getElementById('stocks-tags-input');
        if (tagsEl && payload.snapshot && Array.isArray(payload.snapshot.tags)) {
            tagsEl.value = payload.snapshot.tags.join(', ');
        }
        if (switchToStocksTab) {
            switchTab('stocks-tab');
        }
        loadStocks();
        showStatus('Loaded stock snapshot with ' + (payload.snapshot ? payload.snapshot.count : 0) + ' stock(s).');
        return true;
    } catch (e) {
        showStatus('Error loading stock snapshot: ' + e.message, true);
        return false;
    }
}

async function loadSelectedStockHistoryFromModal() {
    if (!selectedStockHistoryEntry || !selectedStockHistoryEntry.id) {
        showStatus('No stock snapshot selected.', true);
        return;
    }
    var loadBtn = document.getElementById('stock-history-modal-load-btn');
    if (loadBtn) {
        loadBtn.disabled = true;
        loadBtn.textContent = 'Loading...';
    }
    try {
        var ok = await loadStockHistorySnapshot(selectedStockHistoryEntry.id, {
            setServerConfig: true,
            switchToStocksTab: true
        });
        if (ok) closeStockHistoryModal();
    } finally {
        if (loadBtn) {
            loadBtn.disabled = false;
            loadBtn.textContent = 'Load';
        }
    }
}

function renderStockHistorySidebar(payload) {
    var container = document.getElementById('stocks-history-list');
    if (!container) return;
    var history = (payload && payload.history) ? payload.history : [];
    var source = (payload && payload.source) ? payload.source : 'unknown';
    storageSources.stock_history = source;
    applyStorageSourceBadges();

    if (!history || history.length === 0) {
        stockHistoryEntries = [];
        container.innerHTML = '<p class="empty-state">No stock history yet.</p>';
        return;
    }

    stockHistoryEntries = history.slice();
    var filteredHistory = getFilteredStockHistoryEntries();
    if (filteredHistory.length === 0) {
        container.innerHTML = '<p class="empty-state">No history entries match the filter.</p>';
        return;
    }

    container.innerHTML = filteredHistory.map(function(entry) {
        var tags = Array.isArray(entry.tags) && entry.tags.length > 0
            ? ('<div class="stocks-history-tags">tags: ' + escHtml(entry.tags.join(', ')) + '</div>')
            : '';
        var components = getUniqueHistoryComponents(entry);
        var componentsHtml = components.length > 0
            ? ('<div class="stocks-history-components">components: ' + escHtml(components.join(', ')) + '</div>')
            : '';
        return '<div class="stocks-history-entry" data-stock-snapshot-id="' + escHtml(entry.id || '') + '">'
            + '<div class="stocks-history-title">' + escHtml(entry.created_at || 'unknown time') + '</div>'
            + '<div class="stocks-history-meta">' + escHtml(String(entry.count || 0)) + ' stock(s)</div>'
            + tags
            + componentsHtml
            + '</div>';
    }).join('');

    container.querySelectorAll('.stocks-history-entry').forEach(function(el) {
        el.addEventListener('click', function() {
            var snapshotId = this.getAttribute('data-stock-snapshot-id');
            var entry = stockHistoryEntries.find(function(item) {
                return item && item.id === snapshotId;
            });
            if (entry) {
                openStockHistoryModal(entry);
            }
        });
    });
}

async function loadStockHistorySidebar() {
    var container = document.getElementById('stocks-history-list');
    if (!container) return;
    container.innerHTML = '<p class="empty-state">Loading stock history...</p>';
    try {
        var r = await fetch('/list_stock_history');
        if (!r.ok) {
            container.innerHTML = '<p class="empty-state">Failed to load stock history.</p>';
            return;
        }
        var payload = await r.json();
        renderStockHistorySidebar(payload);
    } catch (e) {
        container.innerHTML = '<p class="empty-state">Error loading stock history.</p>';
    }
}

// ---- Sweep table management ----
var SWEEP_PROPERTY_TYPES = [
    {value: 'mass', label: 'Mass', needsUnits: true, defaultUnit: 'mg'},
    {value: 'volume', label: 'Volume', needsUnits: true, defaultUnit: 'ul'},
    {value: 'mass_fraction', label: 'Mass Fraction', needsUnits: false},
    {value: 'volume_fraction', label: 'Volume Fraction', needsUnits: false},
    {value: 'concentration', label: 'Concentration', needsUnits: true, defaultUnit: 'mg/ml'},
    {value: 'molarity', label: 'Molarity', needsUnits: true, defaultUnit: 'mol/L'},
    {value: 'molality', label: 'Molality', needsUnits: true, defaultUnit: 'mol/kg'},
];
var SWEEP_PROP_TYPE_TO_KEY = {
    'mass': 'masses',
    'volume': 'volumes',
    'mass_fraction': 'mass_fractions',
    'volume_fraction': 'volume_fractions',
    'concentration': 'concentrations',
    'molarity': 'molarities',
    'molality': 'molalities',
};
var TARGET_UPLOAD_PROPERTY_TO_GROUP = {
    'mass': 'masses',
    'volume': 'volumes',
    'concentration': 'concentrations',
    'mass_fraction': 'mass_fractions',
    'volume_fraction': 'volume_fractions',
    'molarity': 'molarities',
    'molality': 'molalities',
};
var TARGET_UPLOAD_UNIT_REQUIRED = {
    'mass': true,
    'volume': true,
    'concentration': true,
    'mass_fraction': false,
    'volume_fraction': false,
    'molarity': true,
    'molality': true,
};
var TARGET_UPLOAD_RESERVED_COLUMNS = {
    'name': true,
    'location': true,
    'total_mass': true,
    'total_volume': true,
    'solutes': true,
};
var targetUploadState = {
    parsedTargets: [],
    rowErrors: [],
    warnings: [],
    format: ''
};
var SWEEP_NAME_PROPERTY_TYPES = [
    {value: 'mass', label: 'Mass', short: 'm', needsUnits: true, defaultUnit: 'mg'},
    {value: 'volume', label: 'Volume', short: 'v', needsUnits: true, defaultUnit: 'ul'},
    {value: 'mass_fraction', label: 'Mass Fraction', short: 'mf', needsUnits: false},
    {value: 'volume_fraction', label: 'Volume Fraction', short: 'vf', needsUnits: false},
    {value: 'concentration', label: 'Concentration', short: 'conc', needsUnits: true, defaultUnit: 'mg/ml'},
    {value: 'molarity', label: 'Molarity', short: 'mol', needsUnits: true, defaultUnit: 'mol/L'},
    {value: 'molality', label: 'Molality', short: 'mlt', needsUnits: true, defaultUnit: 'mol/kg'},
];

var sweepPreviewTimer = null;

function scheduleSweepPreview() {
    if (sweepPreviewTimer) clearTimeout(sweepPreviewTimer);
    sweepPreviewTimer = setTimeout(function() {
        previewSweep();
    }, 150);
}

function getSweepNamePropertyMeta(value) {
    return SWEEP_NAME_PROPERTY_TYPES.find(function(p) { return p.value === value; }) || SWEEP_NAME_PROPERTY_TYPES[0];
}

function getSweepComponentOptions() {
    var seen = {};
    var names = [];
    document.querySelectorAll('.sweep-row .sweep-comp-name').forEach(function(input) {
        var name = (input.value || '').trim();
        if (!name || seen[name]) return;
        seen[name] = true;
        names.push(name);
    });
    return names.sort();
}

function refreshSweepNameRuleComponentOptions() {
    var components = getSweepComponentOptions();
    document.querySelectorAll('.sweep-name-comp').forEach(function(sel) {
        var current = sel.value;
        sel.innerHTML = '<option value="">Select...</option>';
        components.forEach(function(comp) {
            var opt = document.createElement('option');
            opt.value = comp;
            opt.textContent = comp;
            sel.appendChild(opt);
        });
        if (current && components.indexOf(current) === -1) {
            var custom = document.createElement('option');
            custom.value = current;
            custom.textContent = current;
            sel.appendChild(custom);
        }
        sel.value = current;
    });
}

function addSweepNameRuleRow(prefill) {
    prefill = prefill || {};
    var body = document.getElementById('sweep-name-rule-body');
    if (!body) return null;
    var tr = document.createElement('tr');
    tr.className = 'sweep-name-rule-row';

    tr.innerHTML = [
        '<td><select class="sweep-name-comp"></select></td>',
        '<td style="text-align:center"><input type="checkbox" class="sweep-name-include-units"></td>',
        '<td style="text-align:center"><input type="checkbox" class="sweep-name-show-component"></td>',
        '<td style="text-align:center"><input type="checkbox" class="sweep-name-include-index"></td>',
        '<td><input type="text" class="sweep-name-formatter"></td>',
        '<td><button class="name-rule-remove-btn" title="Remove">&times;</button></td>'
    ].join('');
    body.appendChild(tr);
    refreshSweepNameRuleComponentOptions();

    var compSel = tr.querySelector('.sweep-name-comp');
    var includeUnits = tr.querySelector('.sweep-name-include-units');
    var showComponent = tr.querySelector('.sweep-name-show-component');
    var includeIndex = tr.querySelector('.sweep-name-include-index');
    var fmtInput = tr.querySelector('.sweep-name-formatter');

    if (prefill.component) compSel.value = prefill.component;
    fmtInput.value = prefill.formatter || '4.3f';
    includeUnits.checked = !!prefill.include_units;
    showComponent.checked = prefill.show_component !== false;
    includeIndex.checked = !!prefill.include_index;
    fmtInput.placeholder = '4.3f';

    compSel.addEventListener('change', scheduleSweepPreview);
    includeUnits.addEventListener('change', scheduleSweepPreview);
    showComponent.addEventListener('change', scheduleSweepPreview);
    includeIndex.addEventListener('change', scheduleSweepPreview);
    fmtInput.addEventListener('input', scheduleSweepPreview);
    tr.querySelector('.name-rule-remove-btn').addEventListener('click', function() {
        tr.remove();
        scheduleSweepPreview();
    });
    return tr;
}

function collectSweepNameRulesFromUI() {
    var rules = [];
    document.querySelectorAll('.sweep-name-rule-row').forEach(function(row) {
        var component = row.querySelector('.sweep-name-comp').value.trim();
        if (!component) return;
        var includeUnits = row.querySelector('.sweep-name-include-units').checked;
        var showComponent = row.querySelector('.sweep-name-show-component').checked;
        var includeIndex = row.querySelector('.sweep-name-include-index').checked;
        var formatter = row.querySelector('.sweep-name-formatter').value.trim() || '4.3f';
        rules.push({
            component: component,
            include_units: includeUnits,
            show_component: showComponent,
            include_index: includeIndex,
            formatter: formatter,
        });
    });
    return rules;
}

function parseQuantityString(qty) {
    if (!qty || typeof qty !== 'string') return null;
    var m = qty.trim().match(/^([-+]?[\d.]+(?:e[-+]?\d+)?)\s*(.*)$/i);
    if (!m) return null;
    var val = Number(m[1]);
    if (!isFinite(val)) return null;
    return {value: val, units: (m[2] || '').trim()};
}

function formatSweepNameValue(value, formatter) {
    if (!isFinite(value)) return null;
    if (!formatter) return String(+Number(value).toPrecision(4));
    var fmt = formatter.trim();
    var match = fmt.match(/^(?:\d+)?(?:\.(\d+))?f$/i);
    if (match) {
        var decimals = match[1] ? parseInt(match[1], 10) : 6;
        return Number(value).toFixed(decimals);
    }
    return String(+Number(value).toPrecision(4));
}

function getSweepNameSourceMap() {
    var out = {};
    document.querySelectorAll('.sweep-row').forEach(function(row) {
        if (!row.querySelector('.sweep-use').checked) return;
        var component = row.querySelector('.sweep-comp-name').value.trim();
        if (!component || out[component]) return;
        out[component] = {
            prop_type: row.querySelector('.sweep-prop-type').value,
            units: row.querySelector('.sweep-units').value.trim(),
        };
    });
    return out;
}

function buildSweepNameFromTarget(target, idx, prefix, rules, sourceMap) {
    var segments = [];
    var includeIndex = false;
    (rules || []).forEach(function(rule) {
        var source = sourceMap ? sourceMap[rule.component] : null;
        if (!source || !source.prop_type) return;
        var key = SWEEP_PROP_TYPE_TO_KEY[source.prop_type];
        if (!key || !target[key] || !(rule.component in target[key])) return;
        var raw = target[key][rule.component];
        if (raw === null || raw === undefined) return;

        var meta = getSweepNamePropertyMeta(source.prop_type);
        var value = null;
        var unit = '';
        if (meta.needsUnits) {
            var parsed = parseQuantityString(raw);
            if (!parsed) return;
            value = parsed.value;
            unit = source.units || parsed.units || '';
            if (source.units && parsed.units && source.units !== parsed.units) {
                var converted = convertPlotUnits(value, parsed.units, source.units, source.prop_type);
                if (converted !== null && isFinite(converted)) {
                    value = converted;
                    unit = source.units;
                } else {
                    unit = parsed.units;
                }
            }
        } else {
            value = Number(raw);
            if (!isFinite(value)) return;
        }

        var formatted = formatSweepNameValue(value, rule.formatter);
        if (formatted === null) return;
        var suffix = (meta.needsUnits && rule.include_units && unit) ? unit.replace(/\s+/g, '') : '';
        if (rule.show_component === false) {
            segments.push(formatted + suffix);
        } else {
            segments.push(rule.component + '_' + meta.short + formatted + suffix);
        }
        if (rule.include_index) includeIndex = true;
    });

    var base = '';
    if (segments.length === 0) {
        base = prefix + '-' + String(idx + 1).padStart(4, '0');
    } else {
        base = prefix + '-' + segments.join('-');
    }
    if (includeIndex && segments.length > 0) {
        return base + '-' + String(idx + 1);
    }
    return base;
}

function evaluateSweepNameRuleOnTarget(target, rule, sourceMap) {
    var source = sourceMap ? sourceMap[rule.component] : null;
    if (!source || !source.prop_type) return {ok: false, reason: 'component not used in sweep'};
    var key = SWEEP_PROP_TYPE_TO_KEY[source.prop_type];
    if (!key || !target[key]) return {ok: false, reason: 'property not present'};
    if (!(rule.component in target[key])) return {ok: false, reason: 'component not present'};
    var raw = target[key][rule.component];
    if (raw === null || raw === undefined) return {ok: false, reason: 'value unresolved'};
    var meta = getSweepNamePropertyMeta(source.prop_type);
    if (meta.needsUnits) {
        var parsed = parseQuantityString(raw);
        if (!parsed) return {ok: false, reason: 'invalid quantity'};
    } else if (!isFinite(Number(raw))) {
        return {ok: false, reason: 'non-numeric value'};
    }
    return {ok: true, reason: '', prop_type: source.prop_type};
}

function updateSweepNamePreview(targets) {
    var el = document.getElementById('sweep-name-preview');
    if (!el) return;
    var rules = collectSweepNameRulesFromUI();
    var sourceMap = getSweepNameSourceMap();
    if (!rules.length) {
        el.innerHTML = 'Name preview: <span class="empty">No rules. Using prefix-index naming.</span>';
        return;
    }
    if (!targets || targets.length === 0) {
        el.innerHTML = 'Name preview: <span class="empty">No targets yet.</span>';
        return;
    }
    var names = targets.slice(0, 3).map(function(t) { return t.name; });
    var suffix = targets.length > 3 ? ' ...' : '';
    var firstTarget = targets[0];
    var diagnostics = rules.map(function(rule) {
        var check = evaluateSweepNameRuleOnTarget(firstTarget, rule, sourceMap);
        var propLabel = check.prop_type ? getSweepNamePropertyMeta(check.prop_type).label : 'Sweep Property';
        var ruleLabel = rule.component + ' / ' + propLabel;
        if (check.ok) return '<span style="color:#155724">OK: ' + escHtml(ruleLabel) + '</span>';
        return '<span style="color:#856404">Unmatched: ' + escHtml(ruleLabel + ' (' + check.reason + ')') + '</span>';
    }).join(' | ');
    el.innerHTML = 'Name preview: <code>' + escHtml(names.join(', ') + suffix) + '</code>'
        + '<div style="margin-top:4px;font-size:11px;">' + diagnostics + '</div>';
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
    var nameRules = collectSweepNameRulesFromUI();
    var sourceMap = getSweepNameSourceMap();

    return grid.map(function(combo, i) {
        var target = {name: ''};
        if (sizeValue) target[sizeType] = sizeValue;

        activeRows.forEach(function(row, j) {
            var key = SWEEP_PROP_TYPE_TO_KEY[row.propType];
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
            var key = SWEEP_PROP_TYPE_TO_KEY[rem.propType];
            if (!key) return;
            if (!target[key]) target[key] = {};
            target[key][rem.name] = null;
        });

        if (soluteNames.length > 0) target.solutes = soluteNames.slice();
        target.name = buildSweepNameFromTarget(target, i, prefix, nameRules, sourceMap);

        return target;
    });
}

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
        scheduleSweepPreview();
    });

    tr.querySelector('.sweep-remainder').addEventListener('change', function() {
        var isRem = this.checked;
        tr.classList.toggle('sweep-row-remainder', isRem);
        tr.querySelector('.sweep-start').disabled = isRem;
        tr.querySelector('.sweep-stop').disabled = isRem;
        tr.querySelector('.sweep-steps').disabled = isRem;
        scheduleSweepPreview();
    });

    if (prefill.isRemainder) {
        tr.classList.add('sweep-row-remainder');
        tr.querySelector('.sweep-start').disabled = true;
        tr.querySelector('.sweep-stop').disabled = true;
        tr.querySelector('.sweep-steps').disabled = true;
    }

    tr.querySelector('.remove-sweep-row-btn').addEventListener('click', function() {
        tr.remove();
        refreshSweepNameRuleComponentOptions();
        scheduleSweepPreview();
    });

    tr.querySelectorAll('input,select').forEach(function(el) {
        el.addEventListener('change', scheduleSweepPreview);
        el.addEventListener('input', function() {
            if (el.classList.contains('sweep-comp-name')) {
                refreshSweepNameRuleComponentOptions();
            }
            scheduleSweepPreview();
        });
    });

    tbody.appendChild(tr);
    refreshSweepNameRuleComponentOptions();
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


function previewSweep() {
    var targets = generateSweepTargets();
    var previewEl = document.getElementById('sweep-preview-area');
    updateSweepNamePreview(targets);

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
        name_rules: collectSweepNameRulesFromUI(),
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
    var nameRuleBody = document.getElementById('sweep-name-rule-body');
    if (nameRuleBody) {
        nameRuleBody.innerHTML = '';
        (config.name_rules || []).forEach(function(rule) {
            addSweepNameRuleRow(rule);
        });
    }
    refreshSweepNameRuleComponentOptions();
    scheduleSweepPreview();
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
            invalidateBalanceResults();
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

// ---- Balance target upload modal ----
function resetTargetUploadParseState() {
    targetUploadState.parsedTargets = [];
    targetUploadState.rowErrors = [];
    targetUploadState.warnings = [];
    targetUploadState.format = '';
    var submitBtn = document.getElementById('target-upload-submit-btn');
    if (submitBtn) submitBtn.disabled = true;
}

function openTargetUploadModal() {
    resetTargetUploadParseState();
    var summaryEl = document.getElementById('target-upload-summary');
    var errorsEl = document.getElementById('target-upload-errors');
    var previewEl = document.getElementById('target-upload-preview');
    if (summaryEl) summaryEl.innerHTML = '';
    if (errorsEl) errorsEl.innerHTML = '';
    if (previewEl) previewEl.innerHTML = '<p class="empty-state">Paste input and click Parse.</p>';
    document.getElementById('target-upload-modal-overlay').classList.add('visible');
}

function closeTargetUploadModal() {
    document.getElementById('target-upload-modal-overlay').classList.remove('visible');
}

function parseDelimitedLine(line, delimiter) {
    var out = [];
    var cur = '';
    var inQuotes = false;
    for (var i = 0; i < line.length; i++) {
        var ch = line[i];
        if (ch === '"') {
            if (inQuotes && i + 1 < line.length && line[i + 1] === '"') {
                cur += '"';
                i++;
            } else {
                inQuotes = !inQuotes;
            }
            continue;
        }
        if (!inQuotes && ch === delimiter) {
            out.push(cur);
            cur = '';
            continue;
        }
        cur += ch;
    }
    out.push(cur);
    return out;
}

function parseSolutesCell(raw) {
    var txt = (raw || '').trim();
    if (!txt) return null;
    if (txt[0] === '[') {
        try {
            var parsed = JSON.parse(txt);
            if (Array.isArray(parsed)) return parsed.map(function(v) { return String(v).trim(); }).filter(Boolean);
        } catch (e) {
            // fall through to delimiter-based parsing
        }
    }
    return txt.split(/[;,]/).map(function(v) { return v.trim(); }).filter(Boolean);
}

function parseDelimitedHeaderCell(header, idx) {
    var h = (header || '').trim();
    if (!h) {
        throw new Error('Header column ' + (idx + 1) + ' is empty.');
    }
    var hLower = h.toLowerCase();
    if (TARGET_UPLOAD_RESERVED_COLUMNS[hLower]) {
        return {type: 'reserved', key: hLower, raw: h};
    }
    var parts = h.split('.');
    if (parts.length < 2) {
        throw new Error(
            'Invalid header "' + h + '". Expected "component.property" or "component.property.units".'
        );
    }
    var component = parts[0].trim();
    var prop = parts[1].trim().toLowerCase();
    var units = parts.slice(2).join('.').trim();
    if (!component) {
        throw new Error('Invalid header "' + h + '": missing component name.');
    }
    if (!TARGET_UPLOAD_PROPERTY_TO_GROUP[prop]) {
        throw new Error(
            'Invalid header "' + h + '": unsupported property "' + parts[1].trim() + '".'
        );
    }
    return {
        type: 'component',
        component: component,
        property: prop,
        group: TARGET_UPLOAD_PROPERTY_TO_GROUP[prop],
        units: units,
        raw: h
    };
}

function normalizeJsonTargetEntry(entry, idx) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
        throw new Error('JSON target #' + (idx + 1) + ' must be an object.');
    }
    var out = pruneEmptyStringKeys(entry);
    if (!out || typeof out !== 'object' || Array.isArray(out)) out = {};
    if (!out.name) out.name = 'target-' + (idx + 1);
    return out;
}

function pruneEmptyStringKeys(value) {
    if (value === null || value === undefined) return value;

    if (typeof value === 'string') {
        var trimmed = value.trim();
        return trimmed ? trimmed : undefined;
    }

    if (Array.isArray(value)) {
        var arr = value.map(pruneEmptyStringKeys).filter(function(item) {
            return item !== undefined;
        });
        return arr.length > 0 ? arr : undefined;
    }

    if (typeof value === 'object') {
        var out = {};
        Object.keys(value).forEach(function(rawKey) {
            var key = (rawKey || '').trim();
            if (!key) return;
            var pruned = pruneEmptyStringKeys(value[rawKey]);
            if (pruned === undefined) return;
            if (pruned && typeof pruned === 'object' && !Array.isArray(pruned) && Object.keys(pruned).length === 0) return;
            out[key] = pruned;
        });
        return Object.keys(out).length > 0 ? out : undefined;
    }

    return value;
}

function parseTargetsFromJson(raw) {
    var parsed = JSON.parse(raw);
    var sourceTargets;
    if (Array.isArray(parsed)) {
        sourceTargets = parsed;
    } else if (parsed && typeof parsed === 'object' && Array.isArray(parsed.targets)) {
        sourceTargets = parsed.targets;
    } else {
        throw new Error('JSON must be an array of targets or an object with a "targets" array.');
    }
    var targets = sourceTargets.map(function(entry, idx) {
        return normalizeJsonTargetEntry(entry, idx);
    });
    return {
        targets: targets,
        rowErrors: [],
        warnings: [],
        format: 'json'
    };
}

function buildTargetFromDelimitedRow(rowFields, headerMeta, rowNumber) {
    var target = {};
    var rowErrors = [];
    var rowWarnings = [];

    headerMeta.forEach(function(meta, idx) {
        var raw = idx < rowFields.length ? rowFields[idx] : '';
        var cell = (raw || '').trim();
        if (!cell) return;

        if (meta.type === 'reserved') {
            if (meta.key === 'solutes') {
                var solutes = parseSolutesCell(cell);
                if (solutes && solutes.length > 0) target.solutes = solutes;
            } else {
                target[meta.key] = cell;
            }
            return;
        }

        if (!target[meta.group]) target[meta.group] = {};
        if (target[meta.group][meta.component] !== undefined) {
            rowErrors.push(
                'Row ' + rowNumber + ': duplicate value for ' + meta.component + '.' + meta.property + '.'
            );
            return;
        }

        if (!TARGET_UPLOAD_UNIT_REQUIRED[meta.property]) {
            var lower = cell.toLowerCase();
            if (lower === 'null' || lower === 'none' || lower === 'remainder') {
                target[meta.group][meta.component] = null;
                return;
            }
            var frac = Number(cell);
            if (!isFinite(frac)) {
                rowErrors.push(
                    'Row ' + rowNumber + ': non-numeric value "' + cell + '" for ' + meta.raw + '.'
                );
                return;
            }
            if (meta.units) {
                rowWarnings.push(
                    'Row ' + rowNumber + ': ignoring units in header "' + meta.raw + '" for unitless property.'
                );
            }
            target[meta.group][meta.component] = frac;
            return;
        }

        if (meta.units) {
            var qty = parseQuantityString(cell);
            var numeric = qty ? qty.value : Number(cell);
            if (!isFinite(numeric)) {
                rowErrors.push(
                    'Row ' + rowNumber + ': expected numeric value for ' + meta.raw + ', got "' + cell + '".'
                );
                return;
            }
            target[meta.group][meta.component] = String(numeric) + ' ' + meta.units;
            return;
        }

        var parsedQty = parseQuantityString(cell);
        if (!parsedQty || !parsedQty.units) {
            rowErrors.push(
                'Row ' + rowNumber + ': missing units for ' + meta.raw + '. Add units in header or value.'
            );
            return;
        }
        target[meta.group][meta.component] = String(parsedQty.value) + ' ' + parsedQty.units;
    });

    if (!target.name) target.name = 'target-' + rowNumber;
    return {target: target, rowErrors: rowErrors, rowWarnings: rowWarnings};
}

function parseTargetsFromDelimited(raw, delimiter) {
    var lines = raw.split(/\r?\n/).filter(function(line) { return line.trim() !== ''; });
    if (lines.length < 2) {
        throw new Error('Delimited input must contain a header row and at least one data row.');
    }
    var headers = parseDelimitedLine(lines[0], delimiter).map(function(h) { return (h || '').trim(); });
    if (headers.length === 0) {
        throw new Error('Missing header row.');
    }
    var headerMeta = headers.map(parseDelimitedHeaderCell);
    var targets = [];
    var rowErrors = [];
    var warnings = [];

    for (var i = 1; i < lines.length; i++) {
        var rowNumber = i + 1;
        var fields = parseDelimitedLine(lines[i], delimiter);
        if (fields.length > headers.length) {
            rowErrors.push(
                'Row ' + rowNumber + ': found ' + fields.length + ' columns but header has ' + headers.length + '.'
            );
            continue;
        }
        while (fields.length < headers.length) fields.push('');
        var built = buildTargetFromDelimitedRow(fields, headerMeta, rowNumber);
        if (built.rowErrors.length > 0) {
            rowErrors = rowErrors.concat(built.rowErrors);
            warnings = warnings.concat(built.rowWarnings);
            continue;
        }
        warnings = warnings.concat(built.rowWarnings);
        targets.push(built.target);
    }

    return {
        targets: targets,
        rowErrors: rowErrors,
        warnings: warnings,
        format: delimiter === '\t' ? 'tsv' : 'csv'
    };
}

function parseTargetsFromText(raw) {
    var text = (raw || '').trim();
    if (!text) throw new Error('Input is empty.');
    var first = text[0];
    if (first === '{' || first === '[') {
        return parseTargetsFromJson(text);
    }
    var firstLine = text.split(/\r?\n/, 1)[0] || '';
    var delimiter = firstLine.indexOf('\t') !== -1 ? '\t' : ',';
    return parseTargetsFromDelimited(text, delimiter);
}

function renderTargetUploadResult(result) {
    var summaryEl = document.getElementById('target-upload-summary');
    var errorsEl = document.getElementById('target-upload-errors');
    var previewEl = document.getElementById('target-upload-preview');
    if (!summaryEl || !errorsEl || !previewEl) return;

    var summary = [];
    summary.push('<strong>Format:</strong> ' + escHtml((result.format || '').toUpperCase()));
    summary.push('<strong>Parsed targets:</strong> ' + result.targets.length);
    summary.push('<strong>Row errors:</strong> ' + result.rowErrors.length);
    if (result.warnings.length > 0) {
        summary.push('<strong>Warnings:</strong> ' + result.warnings.length);
    }
    summaryEl.innerHTML = summary.join(' | ');

    if (result.rowErrors.length > 0 || result.warnings.length > 0) {
        var parts = [];
        if (result.rowErrors.length > 0) {
            parts.push('<div><strong>Errors:</strong><ul>'
                + result.rowErrors.slice(0, 100).map(function(e) { return '<li>' + escHtml(e) + '</li>'; }).join('')
                + '</ul></div>');
        }
        if (result.warnings.length > 0) {
            parts.push('<div><strong>Warnings:</strong><ul>'
                + result.warnings.slice(0, 100).map(function(w) { return '<li>' + escHtml(w) + '</li>'; }).join('')
                + '</ul></div>');
        }
        errorsEl.innerHTML = '<div class="upload-error-list">' + parts.join('') + '</div>';
    } else {
        errorsEl.innerHTML = '';
    }

    if (!result.targets || result.targets.length === 0) {
        previewEl.innerHTML = '<p class="empty-state">No valid targets parsed.</p>';
        return;
    }
    var preview = result.targets.slice(0, 5);
    var suffix = result.targets.length > 5 ? '\n... (' + (result.targets.length - 5) + ' more targets)' : '';
    previewEl.innerHTML = '<pre class="diagnostic-pre">' + escHtml(JSON.stringify(preview, null, 2) + suffix) + '</pre>';
}

function parseTargetUploadInput() {
    var input = document.getElementById('target-upload-input');
    if (!input) return;
    var raw = input.value;
    var submitBtn = document.getElementById('target-upload-submit-btn');
    resetTargetUploadParseState();
    try {
        var result = parseTargetsFromText(raw);
        targetUploadState.parsedTargets = result.targets;
        targetUploadState.rowErrors = result.rowErrors;
        targetUploadState.warnings = result.warnings;
        targetUploadState.format = result.format;
        renderTargetUploadResult(result);
        if (submitBtn) submitBtn.disabled = result.targets.length === 0;
        if (result.targets.length === 0) {
            showStatus('Parse complete: no valid targets found.', true);
        } else if (result.rowErrors.length > 0) {
            showStatus(
                'Parsed ' + result.targets.length + ' target(s) with ' + result.rowErrors.length + ' row error(s).',
                true
            );
        } else {
            showStatus('Parsed ' + result.targets.length + ' target(s).');
        }
    } catch (e) {
        document.getElementById('target-upload-summary').innerHTML = '';
        document.getElementById('target-upload-errors').innerHTML =
            '<div class="upload-error-list"><strong>Parse error:</strong> ' + escHtml(e.message) + '</div>';
        document.getElementById('target-upload-preview').innerHTML =
            '<p class="empty-state">Fix parse errors and try again.</p>';
        if (submitBtn) submitBtn.disabled = true;
        showStatus('Parse failed: ' + e.message, true);
    }
}

async function uploadParsedTargetsFromModal() {
    if (!targetUploadState.parsedTargets || targetUploadState.parsedTargets.length === 0) {
        showStatus('No parsed targets to upload.', true);
        return;
    }
    var submitBtn = document.getElementById('target-upload-submit-btn');
    submitBtn.disabled = true;
    showStatus('Uploading ' + targetUploadState.parsedTargets.length + ' targets...');
    try {
        var token = await login();
        var r = await authedFetch('/enqueue', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                task_name: 'upload_targets',
                targets: targetUploadState.parsedTargets,
                reset: true
            })
        });
        if (!r.ok) {
            showStatus('Failed to enqueue upload.', true);
            return;
        }
        var uuidText = await r.text();
        var uuid = uuidText.trim().replace(/^"|"$/g, '');
        var result = await pollForResult(token, uuid, 60000);
        var errorsEl = document.getElementById('target-upload-errors');
        if (result && result.success) {
            showStatus('Uploaded ' + result.count + ' target(s).');
            invalidateBalanceResults();
            closeTargetUploadModal();
            loadTargets();
        } else if (result && result.errors) {
            showStatus('Upload failed with ' + result.errors.length + ' error(s).', true);
            errorsEl.innerHTML = '<div class="upload-error-list"><strong>Errors:</strong><ul>'
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
        submitBtn.disabled = false;
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
    {value: 'mass', label: 'Mass', key: 'masses', unitAware: true, defaultUnit: 'mg'},
    {value: 'volume', label: 'Volume', key: 'volumes', unitAware: true, defaultUnit: 'ul'},
    {value: 'concentration', label: 'Concentration', key: 'concentrations', unitAware: true, defaultUnit: 'mg/ml'},
    {value: 'mass_fraction', label: 'Mass Fraction', key: 'mass_fractions', unitAware: false},
    {value: 'volume_fraction', label: 'Volume Fraction', key: 'volume_fractions', unitAware: false},
    {value: 'molarity', label: 'Molarity', key: 'molarities', unitAware: true, defaultUnit: 'mol/L'},
    {value: 'molality', label: 'Molality', key: 'molalities', unitAware: true, defaultUnit: 'mol/kg'},
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
        var allBalancedTargets = balResp.ok ? await balResp.json() : [];
        var balancedCounts = getBalanceStatusCounts(allBalancedTargets);
        plotSweepState.balancedTargets = allBalancedTargets.filter(function(entry) {
            return getBalanceStatus(entry) !== 'failed';
        });
        plotSweepState.balancedTargets.forEach(function(entry, idx) {
            entry._balanced_idx = idx;
        });
        plotSweepState.selectedBalancedIds = [];
        var subStatus = document.getElementById('plot-sweep-subsample-status');
        if (subStatus) subStatus.textContent = '';
        plotSweepState.lastUpdated = new Date();
        plotSweepState.loaded = true;
        var plotStatus = 'Base: ' + plotSweepState.baseTargets.length
            + ' | Balanced: ' + plotSweepState.balancedTargets.length;
        if (balancedCounts.within_tolerance > 0) {
            plotStatus += ' (' + balancedCounts.within_tolerance + ' within tolerance)';
        }
        if (balancedCounts.failed > 0) {
            plotStatus += ' | Failed excluded: ' + balancedCounts.failed;
        }
        setPlotSweepStatus(plotStatus);
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

function _normalizeUnit(unit) {
    if (!unit) return '';
    return String(unit)
        .trim()
        .toLowerCase()
        .replace(/\s+/g, '')
        .replace(/μ/g, 'u');
}

function _unitScale(unit, scaleMap) {
    var n = _normalizeUnit(unit);
    return (n in scaleMap) ? scaleMap[n] : null;
}

function _convertWithScale(value, fromUnit, toUnit, scaleMap) {
    var from = _unitScale(fromUnit, scaleMap);
    var to = _unitScale(toUnit, scaleMap);
    if (from === null || to === null) return null;
    return value * (from / to);
}

function convertPlotUnits(value, fromUnit, toUnit, propType) {
    if (!toUnit || !fromUnit || _normalizeUnit(toUnit) === _normalizeUnit(fromUnit)) return value;

    if (propType === 'mass') {
        return _convertWithScale(value, fromUnit, toUnit, {
            'kg': 1000.0, 'g': 1.0, 'mg': 1e-3, 'ug': 1e-6
        });
    }
    if (propType === 'volume') {
        return _convertWithScale(value, fromUnit, toUnit, {
            'l': 1.0, 'ml': 1e-3, 'ul': 1e-6
        });
    }
    if (propType === 'concentration') {
        return _convertWithScale(value, fromUnit, toUnit, {
            'g/l': 1.0,
            'mg/ml': 1.0,
            'kg/m^3': 1.0,
            'g/ml': 1000.0,
            'mg/l': 1e-3,
            'ug/ml': 1e-3,
            'ug/l': 1e-6
        });
    }
    if (propType === 'molarity') {
        return _convertWithScale(value, fromUnit, toUnit, {
            'mol/l': 1.0,
            'mmol/l': 1e-3,
            'umol/l': 1e-6,
            'm': 1.0,
            'mm': 1e-3,
            'um': 1e-6
        });
    }
    if (propType === 'molality') {
        return _convertWithScale(value, fromUnit, toUnit, {
            'mol/kg': 1.0,
            'mmol/kg': 1e-3,
            'umol/kg': 1e-6
        });
    }
    return null;
}

function getPlotAxisValue(entry, meta, component, requestedUnits, conversionWarnings) {
    if (!entry || !meta || !component) return null;
    var group = entry[meta.key];
    if (!group || !(component in group)) return null;
    var raw = group[component];
    if (raw === null || raw === undefined) return null;

    var v = null;
    var srcUnits = '';
    if (typeof raw === 'object' && raw.value !== undefined) {
        v = parseFloat(raw.value);
        srcUnits = raw.units || '';
    } else if (typeof raw === 'number') {
        v = raw;
    } else {
        v = parseFloat(raw);
    }
    if (!isFinite(v)) return null;

    if (meta.unitAware && requestedUnits && srcUnits) {
        var converted = convertPlotUnits(v, srcUnits, requestedUnits, meta.value);
        if (converted !== null && isFinite(converted)) {
            v = converted;
        } else if (conversionWarnings) {
            conversionWarnings.push(
                meta.label + ': unsupported conversion "' + srcUnits + '" -> "' + requestedUnits + '"'
            );
        }
    }
    return v;
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
    var conversionWarnings = [];
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
        var colors = [];
        var sx = [];
        var sy = [];
        var sz = [];
        var sa = [];
        var sb = [];
        var sc = [];
        var stext = [];
        ds.entries.forEach(function(entry) {
            var v1 = getPlotAxisValue(entry, propMeta[0], axes[0], units[0], conversionWarnings);
            var v2 = getPlotAxisValue(entry, propMeta[1], axes[1], units[1], conversionWarnings);
            var v3 = axes[2] ? getPlotAxisValue(entry, propMeta[2], axes[2], units[2], conversionWarnings) : null;
            if (v1 === null || v2 === null || (axes[2] && v3 === null)) return;
            var label = entry.name || entry.source_target_name || '';
            var isSelected = (ds.label === 'Balanced') && selectedSet[entry._balanced_idx];
            var status = getBalanceStatus(entry);
            var color = status === 'within_tolerance' ? '#d39e00' : '#28a745';
            if (settings.type === 'ternary') {
                a.push(v1);
                b.push(v2);
                c.push(v3);
                colors.push(ds.label === 'Balanced' ? color : '#1f77b4');
                if (isSelected) {
                    sa.push(v1); sb.push(v2); sc.push(v3); stext.push(label);
                }
            } else if (settings.type === '3d') {
                x.push(v1);
                y.push(v2);
                z.push(v3);
                colors.push(ds.label === 'Balanced' ? color : '#1f77b4');
                if (isSelected) {
                    sx.push(v1); sy.push(v2); sz.push(v3); stext.push(label);
                }
            } else {
                x.push(v1);
                y.push(v2);
                colors.push(ds.label === 'Balanced' ? color : '#1f77b4');
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
                showlegend: true,
                a: a,
                b: b,
                c: c,
                marker: {size: 10, color: colors},
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
                showlegend: true,
                x: x,
                y: y,
                z: z,
                marker: {size: 7, color: colors},
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
                showlegend: true,
                x: x,
                y: y,
                marker: {size: 10, color: colors},
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
                    marker: {size: 14, symbol: 'circle-open', line: {width: 2, color: '#ff7f0e'}},
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
                    marker: {size: 9, symbol: 'circle-open', line: {width: 2, color: '#ff7f0e'}},
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
                    marker: {size: 14, symbol: 'circle-open', line: {width: 2, color: '#ff7f0e'}},
                    hovertemplate: '%{text}<br>' +
                        axes[0] + ' (' + propMeta[0].label + ')= %{x}<br>' +
                        axes[1] + ' (' + propMeta[1].label + ')= %{y}<extra>Selected</extra>'
                });
            }
        }
    });

    var noPointData = (
        traces.length === 0 ||
        traces.every(function(t) {
            if (Array.isArray(t.x)) return t.x.length === 0;
            if (Array.isArray(t.a)) return t.a.length === 0;
            return true;
        })
    );

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

    if (noPointData) {
        if (settings.type === '3d') {
            layout.scene.annotations = [{
                text: 'No data points for this selection.',
                x: 0.5,
                y: 0.5,
                z: 0.5,
                showarrow: false,
                font: {color: '#6c757d', size: 14}
            }];
        } else {
            layout.annotations = [{
                text: 'No data points for this selection.',
                x: 0.5,
                y: 0.5,
                xref: 'paper',
                yref: 'paper',
                showarrow: false,
                font: {color: '#6c757d', size: 14}
            }];
        }
    }

    Plotly.react(plotEl, traces, layout, {responsive: true, displaylogo: false});

    if (noteEl) {
        var notes = ['Series: Base, Balanced'];
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
        if (conversionWarnings.length > 0) {
            notes.push(conversionWarnings[0]);
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
        if (meta.unitAware) {
            if (!unitInput.dataset.lastProp && !unitInput.value.trim()) {
                unitInput.value = meta.defaultUnit || '';
            } else if (unitInput.dataset.lastProp && unitInput.dataset.lastProp !== meta.value) {
                unitInput.value = meta.defaultUnit || '';
            }
        } else {
            unitInput.value = '';
        }
        unitInput.dataset.lastProp = meta.value;
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
var submitPreviewEntries = [];

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

function getSubmitDestinationMode() {
    var selected = document.querySelector('input[name="submit-destination-mode"]:checked');
    return selected ? selected.value : 'orchestrator';
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

function buildMassOnlySampleFromDisplayEntry(entry, idx) {
    var sample = {};
    if (!entry || typeof entry !== 'object') return sample;
    sample.name = entry.name || entry.source_target_name || ('sample-' + (idx + 1));
    if (entry.location) sample.location = entry.location;
    if (entry.solutes && Array.isArray(entry.solutes) && entry.solutes.length > 0) {
        sample.solutes = entry.solutes.slice();
    }
    var masses = clonePropMapForSolution(entry.masses, true);
    if (masses) sample.masses = masses;
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

function collectPrepareKwargsFromUI() {
    var kwargs = {};
    kwargs.enable_multistep_dilution = !!document.getElementById('submit-prepare-kw-enable-multistep').checked;
    var dest = document.getElementById('submit-prepare-kw-dest').value.trim();
    if (dest) kwargs.dest = dest;

    var advanced = parseJsonText(document.getElementById('submit-prepare-kw-advanced-json').value, 'prepare advanced kwargs');
    if (advanced !== null) {
        if (typeof advanced !== 'object' || Array.isArray(advanced)) {
            throw new Error('Prepare advanced kwargs JSON must be an object.');
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

function applyDefaultSubmitCompositionFormat() {
    var formatEl = document.getElementById('submit-override-composition-format');
    if (!formatEl) return;
    if (!formatEl.value.trim()) {
        formatEl.value = 'masses';
    }
}

function syncSubmitDestinationUI() {
    var mode = getSubmitDestinationMode();
    var orchestratorSection = document.getElementById('submit-orchestrator-section');
    var prepareSection = document.getElementById('submit-prepare-section');
    var processKwargsSection = document.getElementById('submit-process-kwargs-section');
    var prepareKwargsSection = document.getElementById('submit-prepare-kwargs-section');
    var noSampleOption = document.getElementById('submit-no-sample-option');
    var refreshBtn = document.getElementById('submit-refresh-context-btn');

    if (orchestratorSection) orchestratorSection.style.display = mode === 'orchestrator' ? '' : 'none';
    if (prepareSection) prepareSection.style.display = mode === 'prepare' ? '' : 'none';
    if (processKwargsSection) processKwargsSection.style.display = mode === 'orchestrator' ? '' : 'none';
    if (prepareKwargsSection) prepareKwargsSection.style.display = mode === 'prepare' ? '' : 'none';
    if (noSampleOption) noSampleOption.style.display = mode === 'orchestrator' ? '' : 'none';
    if (refreshBtn) refreshBtn.textContent = mode === 'orchestrator' ? 'Refresh Orchestrator' : 'Refresh Prepare Server';

    if (mode === 'prepare') {
        var selected = document.querySelector('input[name="submit-sample-mode"]:checked');
        if (selected && selected.value === 'no_sample') {
            var fallback = document.querySelector('input[name="submit-sample-mode"][value="balanced_all"]');
            if (fallback) fallback.checked = true;
        }
    }
}

function renderSubmitPreview() {
    var listEl = document.getElementById('submit-preview-list');
    var titleEl = document.getElementById('submit-preview-title');
    if (!listEl || !titleEl) return;
    var mode = getSubmitSampleMode();
    var destinationMode = getSubmitDestinationMode();
    var destinationVerb = destinationMode === 'prepare' ? 'prepare' : 'process_sample';
    var cards = [];
    submitPreviewEntries = [];
    if (mode === 'no_sample') {
        cards.push({
            name: 'No Sample',
            summary: 'Will call ' + destinationVerb + ' with an empty sample payload.',
            componentHtml: '<span class="component-chip">predict/enqueue flow only</span>'
        });
    } else {
        var entries = collectSubmitSourceEntries();
        cards = entries.map(function(entry, i) {
            var modeLabel = mode === 'plot_subsample' ? 'Plot subset' : 'Balanced';
            var summary = modeLabel + ' #' + (i + 1);
            submitPreviewEntries.push(entry);
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
    listEl.innerHTML = cards.map(function(card, idx) {
        var locBadge = card.location ? '<span class="location-badge">' + escHtml(card.location) + '</span>' : '';
        var isClickable = mode !== 'no_sample';
        return '<div class="card' + (isClickable ? ' clickable submit-preview-card' : '') + '"' + (isClickable ? (' data-idx="' + idx + '"') : '') + '>'
            + '<div class="card-header">'
            + '<span class="card-name">' + escHtml(card.name) + '</span>'
            + locBadge
            + '</div>'
            + '<div style="font-size:12px;color:#6c757d;margin-bottom:6px;">' + escHtml(card.summary) + '</div>'
            + (card.componentHtml || '')
            + '</div>';
    }).join('');

    if (mode !== 'no_sample') {
        listEl.querySelectorAll('.submit-preview-card').forEach(function(cardEl) {
            cardEl.addEventListener('click', function() {
                var idx = parseInt(this.getAttribute('data-idx'), 10);
                if (isNaN(idx) || idx < 0 || idx >= submitPreviewEntries.length) return;
                var entry = submitPreviewEntries[idx];
                var modalData = Object.assign({}, entry);
                if (entry.source_target_name) {
                    modalData.name = entry.source_target_name;
                }
                var reportIdx = -1;
                if (entry.source_target_name) {
                    for (var i = 0; i < balanceReportArray.length; i++) {
                        var report = balanceReportArray[i];
                        if (!report || !report.target) continue;
                        if (report.target.name === entry.source_target_name) {
                            reportIdx = i;
                            break;
                        }
                    }
                }
                showDetailModal(modalData, 'target', reportIdx);
            });
        });
    }
}

function applySubmitContextToUI(ctx) {
    if (!ctx) return;
    if (ctx.orchestrator_uri) {
        document.getElementById('submit-orchestrator-uri').value = ctx.orchestrator_uri;
    }
    if (ctx.prepare_uri) {
        document.getElementById('submit-prepare-uri').value = ctx.prepare_uri;
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
    } else {
        applyDefaultSubmitCompositionFormat();
    }
    if (cfg.enable_multistep_dilution !== undefined && cfg.enable_multistep_dilution !== null) {
        document.getElementById('submit-prepare-kw-enable-multistep').checked = !!cfg.enable_multistep_dilution;
    }

    var health = ctx.health || {};
    var statusParts = [];
    if (health.client_has_load !== undefined) statusParts.push('load=' + (health.client_has_load ? 'ok' : 'missing'));
    if (health.client_has_prep !== undefined) statusParts.push('prep=' + (health.client_has_prep ? 'ok' : 'missing'));
    if (health.client_has_agent !== undefined) statusParts.push('agent=' + (health.client_has_agent ? 'ok' : 'missing'));
    if (health.instrument_count !== undefined) statusParts.push('instrument=' + health.instrument_count);
    if (health.prep_targets_count !== undefined) statusParts.push('prep_targets=' + health.prep_targets_count);
    if (health.mixing_locations_count !== undefined) statusParts.push('mixing_locations=' + health.mixing_locations_count);
    setSubmitContextStatus(statusParts.join(' | '), !(ctx.success !== false));
}

async function loadSubmitContext() {
    var destinationMode = getSubmitDestinationMode();
    var uri = destinationMode === 'orchestrator'
        ? document.getElementById('submit-orchestrator-uri').value.trim()
        : document.getElementById('submit-prepare-uri').value.trim();
    var destinationLabel = destinationMode === 'orchestrator' ? 'orchestrator' : 'prepare server';
    setSubmitStatus('');
    setSubmitContextStatus('Loading ' + destinationLabel + ' context...', false);
    try {
        var params = { r: destinationMode === 'orchestrator' ? 'get_orchestrator_context' : 'get_prepare_context' };
        if (uri) {
            if (destinationMode === 'orchestrator') params.orchestrator_uri = uri;
            else params.prepare_uri = uri;
        }
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
        setSubmitStatus((destinationMode === 'orchestrator' ? 'Orchestrator' : 'Prepare server') + ' context refreshed.', false);
    } catch (e) {
        setSubmitContextStatus('Failed: ' + e.message, true);
    }
}

async function submitSamples() {
    var destinationMode = getSubmitDestinationMode();
    var mode = getSubmitSampleMode();
    var sampleEntries = collectSubmitSourceEntries();
    var samples = [];
    if (mode === 'no_sample' && destinationMode === 'orchestrator') {
        samples = [{}];
    } else {
        samples = sampleEntries.map(function(entry, idx) {
            return buildMassOnlySampleFromDisplayEntry(entry, idx);
        });
    }
    if (samples.length === 0) {
        showStatus('No samples to submit for this mode.', true);
        return;
    }

    var processSampleKwargs = {};
    var prepareKwargs = {};
    var overrides;
    try {
        if (destinationMode === 'orchestrator') {
            processSampleKwargs = collectProcessSampleKwargsFromUI();
        } else {
            prepareKwargs = collectPrepareKwargsFromUI();
        }
        overrides = collectConfigOverridesFromUI();
    } catch (e) {
        showStatus(e.message, true);
        return;
    }

    if (destinationMode === 'orchestrator') {
        if (mode === 'no_sample' && !processSampleKwargs.predict_next && !processSampleKwargs.enqueue_next) {
            showStatus('No Sample mode requires predict_next or enqueue_next.', true);
            return;
        }
    } else if (mode === 'no_sample') {
        showStatus('Prepare submissions require at least one sample.', true);
        return;
    }

    var orchestratorUri = document.getElementById('submit-orchestrator-uri').value.trim();
    var prepareUri = document.getElementById('submit-prepare-uri').value.trim();
    if (destinationMode === 'orchestrator' && !orchestratorUri) {
        showStatus('Orchestrator URI is required.', true);
        return;
    }
    if (destinationMode === 'prepare' && !prepareUri) {
        showStatus('Prepare server URI is required.', true);
        return;
    }

    var btn = document.getElementById('submit-run-btn');
    btn.disabled = true;
    setSubmitStatus('Submitting...', false);
    try {
        var token = await login();
        var payload;
        if (destinationMode === 'orchestrator') {
            payload = {
                task_name: 'submit_orchestrator_grid',
                orchestrator_uri: orchestratorUri,
                sample_mode: mode,
                samples: samples,
                process_sample_kwargs: processSampleKwargs,
                config_overrides: overrides
            };
        } else {
            payload = {
                task_name: 'submit_prepare_grid',
                prepare_uri: prepareUri,
                sample_mode: mode,
                samples: samples,
                prepare_kwargs: prepareKwargs,
                config_overrides: overrides
            };
        }
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
        if (destinationMode === 'orchestrator') {
            setSubmitStatus('Submitted ' + (result.count || 0) + ' task(s) to orchestrator.', false);
            showStatus('Orchestrator submission complete.');
        } else {
            setSubmitStatus('Submitted ' + (result.count || 0) + ' task(s) to prepare server.', false);
            showStatus('Prepare server submission complete.');
        }
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
        submitSamples();
    });
    document.querySelectorAll('input[name="submit-destination-mode"]').forEach(function(el) {
        el.addEventListener('change', function() {
            syncSubmitDestinationUI();
            renderSubmitPreview();
            loadSubmitContext();
        });
    });

    document.querySelectorAll('input[name="submit-sample-mode"]').forEach(function(el) {
        el.addEventListener('change', renderSubmitPreview);
    });

    var previewTriggers = [
        'submit-kw-predict-next', 'submit-kw-enqueue-next',
        'submit-kw-name', 'submit-kw-sample-uuid', 'submit-kw-al-campaign-name', 'submit-kw-al-uuid',
        'submit-kw-predict-combine', 'submit-kw-advanced-json',
        'submit-prepare-kw-enable-multistep', 'submit-prepare-kw-dest', 'submit-prepare-kw-advanced-json',
        'submit-orchestrator-uri', 'submit-prepare-uri',
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
    syncSubmitDestinationUI();
    applyDefaultSubmitCompositionFormat();
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
    var stockHistoryFilterInput = document.getElementById('stocks-history-filter-input');
    if (stockHistoryFilterInput) {
        stockHistoryFilterInput.addEventListener('input', function() {
            stockHistoryFilterText = this.value || '';
            renderStockHistorySidebar({
                history: stockHistoryEntries,
                source: storageSources.stock_history
            });
        });
    }
    var clearDiagBtn = document.getElementById('solution-diagnostics-clear-btn');
    if (clearDiagBtn) {
        clearDiagBtn.addEventListener('click', clearSolutionDiagnostics);
    }

    // Components tab
    var compRefreshBtn = document.getElementById('components-refresh-btn');
    if (compRefreshBtn) {
        compRefreshBtn.addEventListener('click', loadComponentsEditor);
    }
    var compUploadBtn = document.getElementById('components-upload-json-btn');
    if (compUploadBtn) {
        compUploadBtn.addEventListener('click', openComponentsUploadModal);
    }
    var compDownloadBtn = document.getElementById('components-download-json-btn');
    if (compDownloadBtn) {
        compDownloadBtn.addEventListener('click', downloadComponentsJson);
    }
    var compAddBtn = document.getElementById('components-add-btn');
    if (compAddBtn) {
        compAddBtn.addEventListener('click', addComponentRow);
    }

    // Sweeps tab
    document.getElementById('add-sweep-row-btn').addEventListener('click', function() {
        addSweepRow(null);
        scheduleSweepPreview();
    });
    document.getElementById('preview-sweep-btn').addEventListener('click', previewSweep);
    document.getElementById('upload-targets-btn').addEventListener('click', uploadTargets);
    document.getElementById('add-sweep-name-rule-btn').addEventListener('click', function() {
        addSweepNameRuleRow(null);
        scheduleSweepPreview();
    });
    var sweepNameBuilder = document.getElementById('sweep-name-builder');
    if (sweepNameBuilder) {
        sweepNameBuilder.addEventListener('input', scheduleSweepPreview);
        sweepNameBuilder.addEventListener('change', scheduleSweepPreview);
    }
    ['sweep-prefix', 'sweep-size-type', 'sweep-size-value'].forEach(function(id) {
        var el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('input', scheduleSweepPreview);
        el.addEventListener('change', scheduleSweepPreview);
    });

    // Balance tab
    document.getElementById('refresh-btn').addEventListener('click', function() {
        loadStocks();
        loadTargets();
        showStatus('Refreshed.');
    });
    document.getElementById('balance-upload-targets-btn').addEventListener('click', openTargetUploadModal);
    document.getElementById('balance-btn').addEventListener('click', runBalance);
    var targetsListEl = document.getElementById('targets-list');
    if (targetsListEl) {
        targetsListEl.addEventListener('click', handleTargetsListClick);
    }
    var targetsPanelEl = document.getElementById('targets-panel');
    if (targetsPanelEl) {
        targetsPanelEl.addEventListener('scroll', maybeLoadMoreTargets, {passive: true});
    }
    var failedFirstEl = document.getElementById('targets-failed-first-input');
    if (failedFirstEl) {
        targetsPaginationState.failedFirst = !!failedFirstEl.checked;
        failedFirstEl.addEventListener('change', function() {
            targetsPaginationState.failedFirst = !!this.checked;
            renderTargets(allTargetsData);
        });
    }
    var loadMoreTargetsBtn = document.getElementById('targets-load-more-btn');
    if (loadMoreTargetsBtn) {
        loadMoreTargetsBtn.addEventListener('click', function() {
            appendNextTargetsPage();
            fillTargetsViewportIfNeeded();
        });
    }

    // Stock history modal
    document.getElementById('stock-history-modal-close').addEventListener('click', closeStockHistoryModal);
    document.getElementById('stock-history-modal-cancel-btn').addEventListener('click', closeStockHistoryModal);
    document.getElementById('stock-history-modal-load-btn').addEventListener('click', loadSelectedStockHistoryFromModal);
    document.getElementById('stock-history-modal-overlay').addEventListener('click', function(e) {
        if (e.target === this) closeStockHistoryModal();
    });

    // Target upload modal
    document.getElementById('target-upload-modal-close').addEventListener('click', closeTargetUploadModal);
    document.getElementById('target-upload-cancel-btn').addEventListener('click', closeTargetUploadModal);
    document.getElementById('target-upload-parse-btn').addEventListener('click', parseTargetUploadInput);
    document.getElementById('target-upload-submit-btn').addEventListener('click', uploadParsedTargetsFromModal);
    document.getElementById('target-upload-modal-overlay').addEventListener('click', function(e) {
        if (e.target === this) closeTargetUploadModal();
    });
    document.getElementById('target-upload-input').addEventListener('input', function() {
        var summaryEl = document.getElementById('target-upload-summary');
        var errorsEl = document.getElementById('target-upload-errors');
        var previewEl = document.getElementById('target-upload-preview');
        resetTargetUploadParseState();
        if (summaryEl) summaryEl.innerHTML = '';
        if (errorsEl) errorsEl.innerHTML = '';
        if (previewEl) previewEl.innerHTML = '<p class="empty-state">Input changed. Click Parse to refresh preview.</p>';
    });

    // Components upload modal
    document.getElementById('components-upload-modal-close').addEventListener('click', closeComponentsUploadModal);
    document.getElementById('components-upload-cancel-btn').addEventListener('click', closeComponentsUploadModal);
    document.getElementById('components-upload-parse-btn').addEventListener('click', parseComponentsUploadInput);
    document.getElementById('components-upload-submit-btn').addEventListener('click', uploadParsedComponentsFromModal);
    document.getElementById('components-upload-modal-overlay').addEventListener('click', function(e) {
        if (e.target === this) closeComponentsUploadModal();
    });
    document.getElementById('components-upload-file-input').addEventListener('change', handleComponentsUploadFileSelection);
    document.getElementById('components-upload-input').addEventListener('input', function() {
        resetComponentsUploadParseState();
        resetComponentsUploadPreviewMessage('Input changed. Click Parse to refresh preview.');
    });

    // Modal close & navigation handlers
    document.getElementById('detail-modal-close').addEventListener('click', closeDetailModal);
    document.getElementById('modal-nav-prev').addEventListener('click', function() { navigateModal(-1); });
    document.getElementById('modal-nav-next').addEventListener('click', function() { navigateModal(1); });
    document.getElementById('detail-modal-overlay').addEventListener('click', function(e) {
        if (e.target === this) closeDetailModal();
    });
    document.addEventListener('keydown', function(e) {
        var stockHistoryModalOpen = document.getElementById('stock-history-modal-overlay').classList.contains('visible');
        if (stockHistoryModalOpen && e.key === 'Escape') {
            closeStockHistoryModal();
            return;
        }
        var uploadModalOpen = document.getElementById('target-upload-modal-overlay').classList.contains('visible');
        if (uploadModalOpen && e.key === 'Escape') {
            closeTargetUploadModal();
            return;
        }
        var componentsUploadModalOpen = document.getElementById('components-upload-modal-overlay').classList.contains('visible');
        if (componentsUploadModalOpen && e.key === 'Escape') {
            closeComponentsUploadModal();
            return;
        }
        var modalOpen = document.getElementById('detail-modal-overlay').classList.contains('visible');
        if (!modalOpen) return;
        if (e.key === 'Escape') closeDetailModal();
        if (e.key === 'ArrowLeft') navigateModal(-1);
        if (e.key === 'ArrowRight') navigateModal(1);
    });

    // Initialize
    loadComponentNames();
    loadComponentsEditor();
    loadExistingStocksIntoCards();
    loadStockHistorySidebar();
    loadSweepConfig();
    scheduleSweepPreview();
    loadBalanceSettings();
    fetchBalanceProgress().then(renderBalanceProgress);
    refreshStorageSources();
    switchTab(getInitialTabId());
});
