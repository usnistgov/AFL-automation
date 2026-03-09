// ============================================================================
// Tiled Plot Viewer (Direct Tiled HTTP)
// ============================================================================

let entryIds = [];
let tiledClient = null;
const FIELD_CANDIDATES = window.TiledHttpClient.DEFAULT_FIELD_CANDIDATES;

const AppState = {
    entries: [],               // [{id, metadata, fullLink, table, numericColumns}]
    dataIndex: 0,
    xarrayHtmlLoaded: false,
    sampleDim: 'entry',
    scatterVariables: [],
    xVariable: null,
    compositionVariable: 'sample_composition',
    compositionColorVariable: null,
    metadataNumericFields: [],
    cmin: 0.0,
    cmax: 1.0,
    colorscale: 'Bluered',
    xmin: 0.001,
    xmax: 1.0,
    logX: true,
    logY: true
};

function showError(message) {
    const errorContainer = document.getElementById('error-container');
    const errorText = document.getElementById('error-text');
    errorText.textContent = message;
    errorContainer.style.display = 'block';
}

function hideError() {
    document.getElementById('error-container').style.display = 'none';
}

function setStatus(status, text) {
    const indicator = document.getElementById('status-indicator');
    indicator.className = `status-${status}`;
    indicator.querySelector('.status-text').textContent = text;
}

function setLoading(isLoading) {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
        overlay.style.display = isLoading ? 'flex' : 'none';
    }
}

function resolveMeta(metadata, field) {
    return window.TiledHttpClient.resolveMetadataValue(metadata, field, FIELD_CANDIDATES);
}

function parseEntryIds() {
    const urlParams = new URLSearchParams(window.location.search);
    const urlEntryIds = urlParams.get('entry_ids');

    if (urlEntryIds) {
        return JSON.parse(decodeURIComponent(urlEntryIds));
    }

    const storedIds = sessionStorage.getItem('plotEntryIds');
    if (storedIds) {
        sessionStorage.removeItem('plotEntryIds');
        return JSON.parse(storedIds);
    }

    throw new Error('No entry IDs provided');
}

function normalizeFullPayload(payload) {
    if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
        return payload;
    }
    if (Array.isArray(payload)) {
        return { value: payload };
    }
    return {};
}

function isNumericArray(values) {
    if (!Array.isArray(values) || values.length === 0) return false;
    let hasNumber = false;
    for (const value of values) {
        if (value === null || value === undefined || value === '') continue;
        const n = Number(value);
        if (!Number.isFinite(n)) return false;
        hasNumber = true;
    }
    return hasNumber;
}

function toNumericArray(values) {
    return (values || []).map(v => {
        if (v === null || v === undefined || v === '') return null;
        const n = Number(v);
        return Number.isFinite(n) ? n : null;
    });
}

function preferredXColumn(columns) {
    const preferences = ['q', 'Q', 'SAXS_q', 'USAXS_q', 'x', 'index'];
    for (const name of preferences) {
        if (columns.includes(name)) return name;
    }
    return columns[0] || null;
}

function getSampleComposition(entry) {
    const value = window.TiledHttpClient.resolveMetadataValue(entry.metadata, 'sample_composition', FIELD_CANDIDATES);
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return {};
    }
    const parsed = {};
    for (const [k, v] of Object.entries(value)) {
        const n = Number(v);
        if (Number.isFinite(n)) {
            parsed[k] = n;
        }
    }
    return parsed;
}

async function loadEntryMetadata(entryId) {
    const payload = await tiledClient.metadata(entryId);
    const data = payload?.data;
    if (!data) {
        throw new Error(`Metadata missing for ${entryId}`);
    }
    return {
        id: entryId,
        metadata: data.attributes?.metadata || {},
        structureFamily: data.attributes?.structure_family || 'unknown',
        fullLink: data.links?.full || null,
        varCatalog: null,
        sampleDim: null,
        numSamples: 0,
        table: null,
        numericColumns: []
    };
}

async function ensureEntryDataLoaded(entry) {
    if (entry.structureFamily === 'container') {
        await ensureContainerCatalogLoaded(entry);
        return {};
    }
    if (entry.table !== null) {
        return entry.table;
    }
    if (!entry.fullLink) {
        entry.table = {};
        entry.numericColumns = [];
        return entry.table;
    }

    const fullData = await tiledClient.full(entry.fullLink, {
        format: 'application/json',
        responseType: 'json',
        entryId: entry.id
    });
    const table = normalizeFullPayload(fullData);

    entry.table = table;
    entry.numericColumns = Object.keys(table).filter(name => isNumericArray(table[name]));
    return table;
}

function detectSampleDim(varCatalog) {
    const counts = {};
    for (const info of Object.values(varCatalog)) {
        for (const dim of info.dims) {
            counts[dim] = (counts[dim] || 0) + 1;
        }
    }
    const ranked = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    // Prefer dims that themselves have a coordinate entry in the catalog
    for (const [dim] of ranked) {
        if (varCatalog[dim]) return dim;
    }
    return ranked[0]?.[0] || null;
}

async function ensureContainerCatalogLoaded(entry) {
    if (entry.varCatalog !== null) return;

    const params = window.TiledHttpClient.buildSearchParams({ limit: 100, fields: ['structure_family', 'structure'] });
    const result = await tiledClient.search(params, { path: entry.id });
    const items = result?.data || [];

    const catalog = {};
    for (const item of items) {
        const s = item.attributes?.structure || {};
        catalog[item.id] = {
            fullLink: item.links?.full || null,
            shape: s.shape || [],
            dims: s.dims || [],
            kind: s.data_type?.kind || 'f',
            data: null
        };
    }

    entry.varCatalog = catalog;
    entry.sampleDim = detectSampleDim(catalog);
    entry.numSamples = entry.sampleDim
        ? (catalog[entry.sampleDim]?.shape?.[0] ?? 1)
        : 1;
    entry.numericColumns = Object.entries(catalog)
        .filter(([_, v]) => 'fiu'.includes(v.kind) && v.shape.length > 0)
        .map(([name]) => name);
}

async function ensureVariableLoaded(entry, varName) {
    const varInfo = entry.varCatalog?.[varName];
    if (!varInfo) throw new Error(`Variable ${varName} not in catalog`);
    if (varInfo.data !== null) return varInfo.data;

    varInfo.data = await tiledClient.full(varInfo.fullLink, { format: 'application/json' });
    return varInfo.data;
}

function collectMetadataNumericFields(entries) {
    const candidates = [
        'run_time_minutes',
        'meta_started',
        'meta_ended'
    ];
    const fields = new Set();

    for (const entry of entries) {
        const metadata = entry.metadata || {};
        const quick = {
            run_time_minutes: resolveMeta(metadata, 'run_time_minutes')
        };
        for (const [key, value] of Object.entries(quick)) {
            const n = Number(value);
            if (Number.isFinite(n)) {
                fields.add(key);
            }
        }

        for (const key of Object.keys(metadata)) {
            if (candidates.includes(key)) continue;
            const direct = metadata[key];
            if (typeof direct === 'number' && Number.isFinite(direct)) {
                fields.add(key);
            }
        }
    }

    return Array.from(fields);
}

function buildVarCatalogHtml(entry) {
    const catalog = entry.varCatalog;
    if (!catalog || Object.keys(catalog).length === 0) return '';

    const kindLabel = { f: 'float', i: 'int', u: 'uint', U: 'str', S: 'bytes', b: 'bool', c: 'complex' };

    const coordNames = new Set();
    for (const info of Object.values(catalog)) {
        for (const dim of info.dims) {
            if (catalog[dim]) coordNames.add(dim);
        }
    }

    function varRow(name, info) {
        const dimsStr = info.dims.length ? `(${info.dims.join(', ')})` : '()';
        const shapeStr = info.shape.length ? info.shape.join(' \u00d7 ') : 'scalar';
        const dtype = kindLabel[info.kind] || info.kind;
        return `<tr>
            <td style="padding:2px 8px; font-family:monospace;">${name}</td>
            <td style="padding:2px 8px; color:#666;">${dimsStr}</td>
            <td style="padding:2px 8px;">${shapeStr}</td>
            <td style="padding:2px 8px;">${dtype}</td>
        </tr>`;
    }

    const coordEntries = Object.entries(catalog).filter(([n]) => coordNames.has(n));
    const dataEntries = Object.entries(catalog).filter(([n]) => !coordNames.has(n));

    const thStyle = 'text-align:left; border-bottom:1px solid #ccc; padding:2px 8px; font-size:0.85em; color:#555;';
    const sectionHdr = (label, count) =>
        `<tr><td colspan="4" style="padding:4px 8px; font-weight:bold; background:#f5f5f5; border-top:1px solid #ddd;">${label} (${count})</td></tr>`;

    return `
        <table style="width:100%; border-collapse:collapse; font-size:0.9em; margin-top:8px;">
            <thead><tr>
                <th style="${thStyle}">Name</th>
                <th style="${thStyle}">Dimensions</th>
                <th style="${thStyle}">Shape</th>
                <th style="${thStyle}">Dtype</th>
            </tr></thead>
            <tbody>
                ${coordEntries.length ? sectionHdr('Coordinates', coordEntries.length) + coordEntries.map(([n, v]) => varRow(n, v)).join('') : ''}
                ${dataEntries.length ? sectionHdr('Data variables', dataEntries.length) + dataEntries.map(([n, v]) => varRow(n, v)).join('') : ''}
            </tbody>
        </table>`;
}

function updateDatasetInfoPanel() {
    const info = document.getElementById('data-info-content');
    const firstEntry = AppState.entries[0];
    const isContainer = firstEntry?.structureFamily === 'container';

    const rows = AppState.entries.map(entry => {
        const metadata = entry.metadata || {};
        const task = resolveMeta(metadata, 'task_name') || 'n/a';
        const driver = resolveMeta(metadata, 'driver_name') || 'n/a';
        const sample = resolveMeta(metadata, 'sample_name') || 'n/a';
        const loaded = isContainer
            ? (entry.varCatalog !== null ? `${Object.keys(entry.varCatalog).length} vars` : 'catalog pending')
            : (entry.table !== null ? 'yes' : 'no');
        return `<tr><td>${entry.id}</td><td>${driver}</td><td>${task}</td><td>${sample}</td><td>${loaded}</td></tr>`;
    }).join('');

    const metaTable = `
        <table style="width:100%; border-collapse: collapse;">
            <thead>
                <tr>
                    <th style="text-align:left; border-bottom:1px solid #ccc;">Entry ID</th>
                    <th style="text-align:left; border-bottom:1px solid #ccc;">Driver</th>
                    <th style="text-align:left; border-bottom:1px solid #ccc;">Task</th>
                    <th style="text-align:left; border-bottom:1px solid #ccc;">Sample</th>
                    <th style="text-align:left; border-bottom:1px solid #ccc;">Data Loaded</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>`;

    const varHtml = isContainer && firstEntry?.varCatalog
        ? `<h4 style="margin:12px 0 4px;">Variables (${firstEntry.id})</h4>${buildVarCatalogHtml(firstEntry)}`
        : '';

    info.innerHTML = metaTable + varHtml;
}

async function updateVariableOptions() {
    if (AppState.entries.length === 0) return;

    const firstEntry = AppState.entries[0];
    let numericCols;
    let maxIndex;

    if (firstEntry.structureFamily === 'container') {
        await ensureContainerCatalogLoaded(firstEntry);
        const sampleDim = firstEntry.sampleDim;
        // Scattering data: 2D arrays where the non-sample dim has >= 10 elements
        // (mirrors DatasetWidget.split_vars() — small second dims are composition-like)
        const SCATT_DIM_MIN = 10;
        numericCols = firstEntry.numericColumns.filter(name => {
            const info = firstEntry.varCatalog[name];
            if (info.dims.length !== 2 || !sampleDim || !info.dims.includes(sampleDim)) return false;
            const otherDim = info.dims.find(d => d !== sampleDim);
            const otherIdx = info.dims.indexOf(otherDim);
            return (info.shape[otherIdx] ?? 0) >= SCATT_DIM_MIN;
        });
        AppState.xVariable = null;
        AppState.sampleDim = sampleDim || 'entry';
        maxIndex = firstEntry.numSamples - 1;

        // Fallback: multiple 1D-only containers — each entry IS one sample.
        // This happens when individual datasets are selected (not a pre-concatenated container).
        // Each variable has one dimension (the q-axis), so the 2D filter above finds nothing.
        if (numericCols.length === 0 && AppState.entries.length > 1) {
            numericCols = firstEntry.numericColumns.filter(name => {
                const info = firstEntry.varCatalog[name];
                // Exclude self-referential coordinate arrays (e.g. USAXS_q with dims:["USAXS_q"])
                if (name === info.dims[0]) return false;
                return info.dims.length === 1 && (info.shape[0] ?? 0) >= SCATT_DIM_MIN;
            });
            // Override sampleDim: samples are the entries, not rows within any container
            firstEntry.sampleDim = 'entry';
            AppState.sampleDim = 'entry';
            maxIndex = AppState.entries.length - 1;
        }
    } else {
        await ensureEntryDataLoaded(firstEntry);
        numericCols = firstEntry.numericColumns || [];
        AppState.xVariable = preferredXColumn(numericCols);
        numericCols = numericCols.filter(c => c !== AppState.xVariable);
        maxIndex = Math.max(AppState.entries.length - 1, 0);
    }

    const scatterSelect = document.getElementById('scatter-vars');
    scatterSelect.innerHTML = '';
    numericCols.forEach((name, idx) => {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        if (idx === 0) option.selected = true;
        scatterSelect.appendChild(option);
    });
    AppState.scatterVariables = Array.from(scatterSelect.selectedOptions).map(opt => opt.value);

    const compSelect = document.getElementById('composition-var');
    if (firstEntry.structureFamily === 'container' && firstEntry.sampleDim && firstEntry.varCatalog) {
        const sampleDim = firstEntry.sampleDim;
        // Composition candidates:
        //   1D: indexed solely by sampleDim  (e.g. temperature)
        //   2D: (sampleDim, component_dim) where component_dim has a string coordinate
        //       (e.g. sans_comps with dims ["sans_sample","component"])
        const compCandidates = Object.entries(firstEntry.varCatalog)
            .filter(([_, info]) => {
                if (info.dims[0] !== sampleDim) return false;
                if (info.dims.length === 1) return true;
                if (info.dims.length === 2) {
                    const compDim = info.dims[1];
                    const coord = firstEntry.varCatalog[compDim];
                    return coord && (coord.kind === 'U' || coord.kind === 'S');
                }
                return false;
            })
            .map(([name]) => name);
        compSelect.innerHTML = [
            '<option value="sample_composition">sample_composition (metadata)</option>',
            ...compCandidates.map(name => `<option value="${name}">${name}</option>`)
        ].join('');
        compSelect.value = 'sample_composition';
    } else {
        compSelect.innerHTML = '<option value="sample_composition">sample_composition</option>';
        compSelect.value = 'sample_composition';
    }
    AppState.compositionVariable = compSelect.value;

    const colorSelect = document.getElementById('composition-color');
    colorSelect.innerHTML = '<option value="">None</option>';
    if (firstEntry.structureFamily === 'container' && firstEntry.sampleDim && firstEntry.varCatalog) {
        // sample_vars: 1D numeric variables indexed solely by sampleDim (mirrors DatasetWidget.split_vars)
        const sampleDim = firstEntry.sampleDim;
        Object.entries(firstEntry.varCatalog)
            .filter(([_, info]) => info.dims.length === 1 && info.dims[0] === sampleDim && 'fiu'.includes(info.kind))
            .forEach(([name]) => {
                const option = document.createElement('option');
                option.value = name;
                option.textContent = name;
                colorSelect.appendChild(option);
            });
    } else {
        AppState.metadataNumericFields = collectMetadataNumericFields(AppState.entries);
        AppState.metadataNumericFields.forEach(field => {
            const option = document.createElement('option');
            option.value = field;
            option.textContent = field;
            colorSelect.appendChild(option);
        });
    }
    AppState.compositionColorVariable = colorSelect.value || null;

    const sampleDimSelect = document.getElementById('sample-dim-select');
    if (firstEntry.structureFamily === 'container' && firstEntry.varCatalog) {
        const allDims = new Set();
        for (const info of Object.values(firstEntry.varCatalog)) {
            for (const dim of info.dims) allDims.add(dim);
        }
        // In multi-entry 1D mode the effective sample dim is 'entry' (between entries),
        // not any within-container dimension — add it as a display-only option.
        const effectiveDim = firstEntry.sampleDim;
        if (effectiveDim === 'entry') {
            sampleDimSelect.innerHTML =
                '<option value="entry" selected>entry</option>' +
                Array.from(allDims).map(dim => `<option value="${dim}">${dim}</option>`).join('');
        } else {
            sampleDimSelect.innerHTML = Array.from(allDims).map(dim =>
                `<option value="${dim}"${dim === effectiveDim ? ' selected' : ''}>${dim}</option>`
            ).join('');
        }
    } else {
        sampleDimSelect.innerHTML = '<option value="entry" selected>entry</option>';
    }

    document.getElementById('index-display').textContent = `/ ${maxIndex}`;
    document.getElementById('data-index').max = String(maxIndex);

    updateDatasetInfoPanel();
}

async function buildScatteringTraces() {
    const selected = AppState.scatterVariables;
    if (!selected || selected.length === 0) return [];

    const traces = [];

    // Container branch: use first entry, show only the selected sample row
    const firstEntry = AppState.entries[0];
    if (firstEntry?.structureFamily === 'container') {
        await ensureContainerCatalogLoaded(firstEntry);

        for (const varName of selected) {
            const baseVarInfo = firstEntry.varCatalog[varName];
            if (!baseVarInfo) continue;

            // Multi-entry 1D: each container holds one sample — navigate between entries.
            // Single-container 2D: all samples live in one container — navigate by row.
            const isMultiEntry1D = baseVarInfo.dims.length === 1 && AppState.entries.length > 1;
            const entry = isMultiEntry1D ? AppState.entries[AppState.dataIndex] : firstEntry;
            if (isMultiEntry1D) await ensureContainerCatalogLoaded(entry);

            const varInfo = entry.varCatalog?.[varName];
            if (!varInfo || !'fiu'.includes(varInfo.kind)) continue;

            let yData;
            try {
                yData = await ensureVariableLoaded(entry, varName);
            } catch (err) {
                showError(`Could not load ${varName}: ${err.message}`);
                continue;
            }

            // x-axis: for 1D the single dim IS the q-axis; for 2D find the non-sample dim
            const qDim = isMultiEntry1D
                ? varInfo.dims[0]
                : varInfo.dims.find(d => d !== entry.sampleDim);
            let xData = null;
            if (qDim && entry.varCatalog?.[qDim]) {
                try {
                    xData = await ensureVariableLoaded(entry, qDim);
                } catch (_) {}
            }

            // Show only the selected sample's row (or the whole 1D array for multi-entry)
            const is2D = Array.isArray(yData) && Array.isArray(yData[0]);
            const yRow = is2D ? yData[AppState.dataIndex] : yData;
            if (!yRow) continue;
            const xRow = is2D && Array.isArray(xData) && Array.isArray(xData[0])
                ? xData[AppState.dataIndex]
                : xData;
            traces.push({
                x: xRow || yRow.map((_, j) => j),
                y: yRow,
                type: 'scatter',
                mode: 'markers',
                name: varName,
                marker: { size: 5 },
                visible: true
            });
        }
    } else {
        // Non-container branch: show only the entry at dataIndex
        const entry = AppState.entries[AppState.dataIndex];
        if (!entry || !AppState.xVariable) return traces;
        await ensureEntryDataLoaded(entry);

        const xRaw = entry.table[AppState.xVariable];
        const xData = isNumericArray(xRaw)
            ? toNumericArray(xRaw)
            : Array.from({ length: (entry.table[selected[0]] || []).length }, (_, i) => i);

        for (const varName of selected) {
            const yRaw = entry.table[varName];
            if (!isNumericArray(yRaw)) continue;
            traces.push({
                x: xData,
                y: toNumericArray(yRaw),
                type: 'scatter',
                mode: 'markers',
                name: `${entry.id}:${varName}`,
                marker: { size: 5 },
                visible: true
            });
        }
    }

    return traces;
}

async function renderScatteringPlot() {
    const traces = await buildScatteringTraces();
    if (traces.length === 0) {
        Plotly.purge('scattering-plot');
        return;
    }

    const layout = {
        xaxis: {
            title: AppState.xVariable || 'x',
            type: AppState.logX ? 'log' : 'linear',
            range: AppState.logX ? [Math.log10(AppState.xmin), Math.log10(AppState.xmax)] : [AppState.xmin, AppState.xmax]
        },
        yaxis: {
            title: 'value',
            type: AppState.logY ? 'log' : 'linear'
        },
        autosize: true,
        margin: { t: 10, b: 40, l: 50, r: 10 },
        legend: { yanchor: 'top', xanchor: 'right', y: 0.99, x: 0.99 }
    };

    Plotly.react('scattering-plot', traces, layout, { responsive: true, displayModeBar: true });
}

async function compositionColorArray(points) {
    const field = AppState.compositionColorVariable;
    if (!field) {
        return points.map(() => 0);
    }

    // Container branch: color variable is a 1D catalog variable (sample_var)
    const firstEntry = AppState.entries[0];
    if (firstEntry?.structureFamily === 'container' && firstEntry.varCatalog?.[field]) {
        let colorData;
        try {
            colorData = await ensureVariableLoaded(firstEntry, field);
        } catch (err) {
            showError(`Could not load color variable ${field}: ${err.message}`);
            return points.map(() => 0);
        }
        return points.map(point => {
            const val = Array.isArray(colorData) ? colorData[point.entryIndex] : 0;
            const n = Number(val);
            return Number.isFinite(n) ? n : 0;
        });
    }

    // Non-container / metadata-based path
    const values = points.map(point => {
        const entry = AppState.entries[Math.min(point.entryIndex, AppState.entries.length - 1)];
        const metadata = entry?.metadata || {};
        if (field === 'run_time_minutes') {
            return Number(resolveMeta(metadata, 'run_time_minutes'));
        }
        const raw = metadata[field];
        return Number(raw);
    });

    return values.map(v => (Number.isFinite(v) ? v : 0));
}

async function buildCompositionPoints() {
    const compVar = AppState.compositionVariable;
    const entry = AppState.entries[0];

    // Container branch: composition variable is a dataset array, not metadata
    if (
        entry?.structureFamily === 'container' &&
        compVar !== 'sample_composition' &&
        entry.varCatalog?.[compVar]
    ) {
        const varInfo = entry.varCatalog[compVar];
        const sampleDim = entry.sampleDim;

        if (!sampleDim || varInfo.dims[0] !== sampleDim) {
            return { points: [], xName: 'x', yName: 'y', zName: null, labels: [] };
        }

        // Load composition array (2D: samples × components)
        let compData;
        try {
            compData = await ensureVariableLoaded(entry, compVar);
        } catch (err) {
            showError(`Could not load composition variable ${compVar}: ${err.message}`);
            return { points: [], xName: 'x', yName: 'y', zName: null, labels: [] };
        }

        // Load component name coordinate (e.g. ["benzyl_alcohol", "phenol"])
        const compDimName = varInfo.dims[1];
        let componentNames = null;
        if (compDimName && entry.varCatalog[compDimName]) {
            try {
                componentNames = await ensureVariableLoaded(entry, compDimName);
            } catch (_) {}
        }
        if (!componentNames) {
            componentNames = Array.from({ length: varInfo.shape[1] || 2 }, (_, i) => `comp_${i}`);
        }

        const xName = componentNames[0] || 'x';
        const yName = componentNames[1] || 'y';
        const zName = componentNames[2] || null;

        const points = compData.map((row, sampleIdx) => ({
            entryIndex: sampleIdx,
            x: Number(row[0] ?? 0),
            y: Number(row[1] ?? 0),
            z: zName ? Number(row[2] ?? 0) : null
        }));

        return { points, xName, yName, zName, labels: compData.map((_, i) => `sample ${i}`) };
    }

    // Non-container / metadata-based path (unchanged)
    const points = [];
    const allComponents = new Set();
    const byEntry = AppState.entries.map(e => {
        const composition = getSampleComposition(e);
        Object.keys(composition).forEach(k => allComponents.add(k));
        return composition;
    });

    const components = Array.from(allComponents).sort();
    const xName = components[0] || 'x';
    const yName = components[1] || 'y';
    const zName = components[2] || null;

    byEntry.forEach((composition, entryIndex) => {
        points.push({
            entryIndex,
            x: Number(composition[xName] || 0),
            y: Number(composition[yName] || 0),
            z: zName ? Number(composition[zName] || 0) : null
        });
    });

    return { points, xName, yName, zName, labels: AppState.entries.map(e => e.id) };
}

async function renderCompositionPlot() {
    const { points, xName, yName, zName, labels } = await buildCompositionPoints();
    if (points.length === 0) {
        Plotly.purge('composition-plot');
        return;
    }

    const colors = await compositionColorArray(points);
    const validColors = colors.filter(v => Number.isFinite(v));
    if (validColors.length > 0) {
        AppState.cmin = Math.min(...validColors);
        AppState.cmax = Math.max(...validColors);
        document.getElementById('cmin').value = AppState.cmin.toFixed(2);
        document.getElementById('cmax').value = AppState.cmax.toFixed(2);
    }

    const selectedPoint = points[AppState.dataIndex] || points[0];

    const traces = [];
    if (zName) {
        traces.push({
            type: 'scatter3d',
            mode: 'markers',
            x: points.map(p => p.x),
            y: points.map(p => p.y),
            z: points.map(p => p.z),
            marker: {
                color: colors,
                showscale: true,
                cmin: AppState.cmin,
                cmax: AppState.cmax,
                colorscale: AppState.colorscale,
                size: 5
            },
            text: labels,
            hovertemplate: '<b>%{text}</b><br>x=%{x:.3f}<br>y=%{y:.3f}<br>z=%{z:.3f}<extra></extra>',
            showlegend: false
        });

        traces.push({
            type: 'scatter3d',
            mode: 'markers',
            x: [selectedPoint.x],
            y: [selectedPoint.y],
            z: [selectedPoint.z],
            marker: { color: 'red', size: 10, symbol: 'circle-open', line: { width: 2 } },
            hoverinfo: 'skip',
            showlegend: false
        });

        Plotly.react('composition-plot', traces, {
            scene: {
                xaxis: { title: xName },
                yaxis: { title: yName },
                zaxis: { title: zName },
                aspectmode: 'cube'
            },
            autosize: true,
            margin: { t: 10, b: 10, l: 10, r: 10 }
        }, { responsive: true, displayModeBar: true });
    } else {
        traces.push({
            type: 'scatter',
            mode: 'markers',
            x: points.map(p => p.x),
            y: points.map(p => p.y),
            marker: {
                color: colors,
                showscale: true,
                cmin: AppState.cmin,
                cmax: AppState.cmax,
                colorscale: AppState.colorscale,
                size: 6
            },
            text: labels,
            hovertemplate: '<b>%{text}</b><br>x=%{x:.3f}<br>y=%{y:.3f}<extra></extra>',
            showlegend: false
        });

        traces.push({
            type: 'scatter',
            mode: 'markers',
            x: [selectedPoint.x],
            y: [selectedPoint.y],
            marker: { color: 'red', symbol: 'hexagon-open', size: 12, line: { width: 2 } },
            hoverinfo: 'skip',
            showlegend: false
        });

        Plotly.react('composition-plot', traces, {
            xaxis: { title: xName },
            yaxis: { title: yName },
            autosize: true,
            margin: { t: 10, b: 10, l: 10, r: 10 }
        }, { responsive: true, displayModeBar: true });
    }

    const plotDiv = document.getElementById('composition-plot');
    if (plotDiv.removeAllListeners) {
        plotDiv.removeAllListeners('plotly_click');
    }
    plotDiv.on('plotly_click', data => {
        if (!data.points || data.points.length === 0) return;
        const pointIndex = data.points[0].pointIndex;
        const maxIdx = parseInt(document.getElementById('data-index').max, 10) || 0;
        if (Number.isInteger(pointIndex) && pointIndex >= 0 && pointIndex <= maxIdx) {
            AppState.dataIndex = pointIndex;
            document.getElementById('data-index').value = String(pointIndex);
            renderAllPlots();
        }
    });
}

async function fetchXarrayHtml() {
    const container = document.getElementById('xarray-html-content');
    container.innerHTML = '<em>Loading xarray representation...</em>';

    try {
        const entryIds = JSON.stringify(AppState.entries.map(e => e.id));
        const response = await window.TiledHttpClient.authenticatedFetch(
            `/tiled_get_xarray_html?entry_ids=${encodeURIComponent(entryIds)}`
        );
        const data = await response.json();
        if (data.status === 'success') {
            container.innerHTML = data.html;
            AppState.xarrayHtmlLoaded = true;
            document.getElementById('dataset-info-html').style.display = 'none';
        } else {
            container.innerHTML = `<em>Error: ${data.message}</em>`;
        }
    } catch (err) {
        container.innerHTML = `<em>Failed to load: ${err.message}</em>`;
    }
}

async function renderAllPlots() {
    await renderScatteringPlot();
    await renderCompositionPlot();
}

function switchTab(tabName) {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });

    document.querySelectorAll('.tab-content').forEach(content => {
        const contentId = content.id.replace('-tab', '');
        content.classList.toggle('active', contentId === tabName);
    });

    if (tabName === 'plot') {
        setTimeout(() => {
            Plotly.Plots.resize('scattering-plot');
            Plotly.Plots.resize('composition-plot');
        }, 100);
    }

    if (tabName === 'dataset' && !AppState.xarrayHtmlLoaded && AppState.entries.length > 0) {
        fetchXarrayHtml();
    }
}

function gotoSample(index) {
    const maxIndex = parseInt(document.getElementById('data-index').max, 10) || 0;
    if (index < 0 || index > maxIndex) return;
    AppState.dataIndex = index;
    document.getElementById('data-index').value = String(index);
    renderAllPlots();
}

function downloadDataset() {
    const payload = {
        entry_ids: AppState.entries.map(e => e.id),
        generated_at: new Date().toISOString(),
        entries: AppState.entries.map(entry => ({
            id: entry.id,
            metadata: entry.metadata,
            data: entry.table
        }))
    };

    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `tiled_combined_${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
}

function initializeEventListeners() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    document.getElementById('error-close').addEventListener('click', hideError);

    document.getElementById('download-dataset-btn').addEventListener('click', downloadDataset);

    document.getElementById('scatter-vars').addEventListener('change', (e) => {
        AppState.scatterVariables = Array.from(e.target.selectedOptions).map(opt => opt.value);
        renderScatteringPlot();
    });

    document.getElementById('composition-color').addEventListener('change', (e) => {
        AppState.compositionColorVariable = e.target.value || null;
        renderCompositionPlot();
    });

    document.getElementById('composition-var').addEventListener('change', (e) => {
        AppState.compositionVariable = e.target.value;
        renderCompositionPlot();
    });

    document.getElementById('next-sample').addEventListener('click', () => gotoSample(AppState.dataIndex + 1));
    document.getElementById('prev-sample').addEventListener('click', () => gotoSample(AppState.dataIndex - 1));
    document.getElementById('data-index').addEventListener('change', (e) => {
        gotoSample(parseInt(e.target.value, 10));
    });

    document.getElementById('update-plot').addEventListener('click', async () => {
        AppState.xmin = parseFloat(document.getElementById('xmin-config').value);
        AppState.xmax = parseFloat(document.getElementById('xmax-config').value);
        AppState.logX = document.getElementById('logx-config').checked;
        AppState.logY = document.getElementById('logy-config').checked;
        AppState.colorscale = document.getElementById('colorscale-config').value;
        AppState.cmin = parseFloat(document.getElementById('cmin').value);
        AppState.cmax = parseFloat(document.getElementById('cmax').value);
        await renderAllPlots();
    });

    document.getElementById('reset-dataset').addEventListener('click', async () => {
        for (const entry of AppState.entries) {
            entry.table = null;
            entry.numericColumns = [];
            // Also reset container catalog so sample-dim is re-detected
            entry.varCatalog = null;
            entry.sampleDim = null;
            entry.numSamples = 0;
        }
        AppState.dataIndex = 0;
        AppState.xarrayHtmlLoaded = false;
        document.getElementById('data-index').value = '0';
        document.getElementById('xarray-html-content').innerHTML = '<em>Switch to this tab to load...</em>';
        document.getElementById('dataset-info-html').style.display = '';
        await updateVariableOptions();
        await renderAllPlots();
    });

    document.getElementById('logx-config').addEventListener('change', (e) => {
        AppState.logX = e.target.checked;
        renderScatteringPlot();
    });

    document.getElementById('logy-config').addEventListener('change', (e) => {
        AppState.logY = e.target.checked;
        renderScatteringPlot();
    });

    document.getElementById('xmin-config').addEventListener('input', (e) => {
        AppState.xmin = parseFloat(e.target.value);
        renderScatteringPlot();
    });

    document.getElementById('xmax-config').addEventListener('input', (e) => {
        AppState.xmax = parseFloat(e.target.value);
        renderScatteringPlot();
    });

    document.getElementById('colorscale-config').addEventListener('change', (e) => {
        AppState.colorscale = e.target.value;
        renderCompositionPlot();
    });

    document.getElementById('sample-dim-select').addEventListener('change', async (e) => {
        const newDim = e.target.value;
        const entry = AppState.entries[0];
        if (!entry) return;

        entry.sampleDim = newDim;

        // Recalculate numSamples from the cached catalog shape
        if (entry.varCatalog?.[newDim]) {
            entry.numSamples = entry.varCatalog[newDim].shape?.[0] ?? 1;
        } else {
            entry.numSamples = 1;
        }

        AppState.dataIndex = 0;
        document.getElementById('data-index').value = '0';

        await updateVariableOptions();
        await renderAllPlots();
    });
}

async function initialize() {
    try {
        setLoading(true);
        setStatus('loading', 'Loading configuration...');

        entryIds = parseEntryIds();
        if (!Array.isArray(entryIds) || entryIds.length === 0) {
            throw new Error('No entry IDs specified');
        }
        if (entryIds.length > 25) {
            throw new Error(`Plot selection capped at 25 entries (received ${entryIds.length}).`);
        }

        const config = await window.TiledHttpClient.loadConfig();
        tiledClient = await window.TiledHttpClient.createClientFromConfig(config);

        setStatus('loading', 'Loading metadata...');
        const settled = await Promise.allSettled(entryIds.map(id => loadEntryMetadata(id)));
        AppState.entries = settled
            .filter(item => item.status === 'fulfilled')
            .map(item => item.value);

        if (AppState.entries.length === 0) {
            throw new Error('Failed to load metadata for all selected entries');
        }

        const failed = settled.length - AppState.entries.length;
        if (failed > 0) {
            showError(`Loaded ${AppState.entries.length} entries; ${failed} metadata request(s) failed.`);
        }

        document.getElementById('dataset-count').textContent = `${AppState.entries.length} dataset(s) selected`;
        document.getElementById('download-dataset-btn').disabled = false;

        initializeEventListeners();
        await updateVariableOptions();
        switchTab('plot');

        setStatus('success', `Ready (${AppState.entries.length} entries)`);
        await renderAllPlots();
        hideError();
    } catch (error) {
        setStatus('error', 'Error loading data');
        showError(error.message);
    } finally {
        setLoading(false);
    }
}

document.addEventListener('DOMContentLoaded', initialize);
