// ============================================================================
// Tiled Plot Viewer (Direct Tiled HTTP)
// ============================================================================

let entryIds = [];
let tiledClient = null;
const FIELD_CANDIDATES = window.TiledHttpClient.DEFAULT_FIELD_CANDIDATES;

const AppState = {
    entries: [],               // [{id, metadata, fullLink, table, numericColumns}]
    plotManifest: null,
    plotVariableCache: {},
    dataIndex: 0,
    xarrayHtmlLoaded: false,
    sampleDim: 'entry',
    scatterVariables: [],
    xVariable: null,
    currentDataMode: 'line',
    compositionVariable: 'sample_composition',
    compositionColorVariable: null,
    metadataNumericFields: [],
    _lastAutoRangedColorVar: undefined,  // sentinel: auto-range only when color variable changes
    _lastAutoRangedImageVar: undefined,
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
    const entryRef = window.TiledHttpClient.toEntryRef(entryId);
    const payload = await tiledClient.metadata(entryRef);
    const data = payload?.data;
    if (!data) {
        throw new Error(`Metadata missing for ${entryRef.id || entryId}`);
    }
    return {
        id: entryRef.id || data.id || '',
        entryRef: {
            ...entryRef,
            metadataLink: entryRef.metadataLink || data.links?.self || null,
            fullLink: entryRef.fullLink || data.links?.full || null,
            searchLink: entryRef.searchLink || data.links?.search || null
        },
        metadata: data.attributes?.metadata || {},
        structureFamily: data.attributes?.structure_family || 'unknown',
        fullLink: data.links?.full || entryRef.fullLink || null,
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
    if (!entry.fullLink && !tiledClient.useProxy) {
        entry.table = {};
        entry.numericColumns = [];
        return entry.table;
    }

    const fullData = await tiledClient.full(entry.fullLink, {
        format: 'application/json',
        responseType: 'json',
        entry: entry.entryRef || entry.id
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

function classifyCatalogItem(info, catalog, sampleDim) {
    if (!info) return 'unknown';
    const dims = info.dims || [];
    const kind = info.kind || 'O';
    if (info.is_coord) {
        if (sampleDim && dims.length === 1 && dims[0] === sampleDim) return 'sample_coord';
        if ('USO'.includes(kind)) return 'coord_string';
        if ('fiu'.includes(kind)) return 'coord_numeric';
        return 'coord_other';
    }
    if (!'fiu'.includes(kind)) return 'meta';
    if (dims.length === 0) return 'scalar';
    if (dims.length === 1) {
        if (sampleDim && dims[0] === sampleDim) return 'sample_1d';
        return 'line_1d';
    }
    if (dims.length === 2) {
        if (sampleDim && dims[0] === sampleDim) {
            const compDim = dims[1];
            const coord = catalog?.[compDim];
            if (coord && 'USO'.includes(coord.kind || '')) return 'composition_2d';
            return 'stacked_2d';
        }
        return 'image_2d';
    }
    if (dims.length === 3) {
        if (sampleDim && dims[0] === sampleDim) return 'image_stack_3d';
        return 'volume_3d';
    }
    return 'nd';
}

function getPlotCatalog() {
    return AppState.plotManifest?.catalog || AppState.entries[0]?.varCatalog || null;
}

function getEffectiveSampleDim() {
    return AppState.entries[0]?.sampleDim || AppState.plotManifest?.sample_dim || 'entry';
}

function getVariableMode(info, sampleDim, catalog) {
    const classification = classifyCatalogItem(info, catalog, sampleDim);
    if (classification === 'image_2d' || classification === 'image_stack_3d') return 'image';
    if (classification === 'line_1d' || classification === 'stacked_2d') return 'line';
    return 'other';
}

async function ensurePlotManifestLoaded() {
    if (AppState.entries.length <= 1 || AppState.plotManifest !== null) return;
    const entryIds = JSON.stringify(AppState.entries.map(e => e.id));
    const response = await window.TiledHttpClient.authenticatedFetch(
        `/tiled_get_plot_manifest?entry_ids=${encodeURIComponent(entryIds)}`
    );
    const payload = await response.json();
    if (!response.ok || payload.status === 'error') {
        throw new Error(payload.message || `Failed to load plot manifest (${response.status})`);
    }
    AppState.plotManifest = payload.manifest || null;
    if (AppState.plotManifest?.sample_dim) {
        AppState.sampleDim = AppState.plotManifest.sample_dim;
        if (AppState.entries[0]) {
            AppState.entries[0].sampleDim = AppState.plotManifest.sample_dim;
            AppState.entries[0].numSamples = AppState.plotManifest.sample_count || 1;
        }
    }
}

async function ensureManifestVariableLoaded(varName) {
    if (!AppState.plotManifest || AppState.entries.length <= 1) {
        throw new Error(`Combined plot manifest not available for ${varName}`);
    }
    if (Object.prototype.hasOwnProperty.call(AppState.plotVariableCache, varName)) {
        return AppState.plotVariableCache[varName];
    }
    const entryIds = JSON.stringify(AppState.entries.map(e => e.id));
    const params = new URLSearchParams({
        entry_ids: entryIds,
        var_name: varName
    });
    const response = await window.TiledHttpClient.authenticatedFetch(
        `/tiled_get_plot_variable?${params.toString()}`
    );
    const payload = await response.json();
    if (!response.ok || payload.status === 'error') {
        throw new Error(payload.message || `Failed to load combined variable ${varName}`);
    }
    const variable = payload.variable || {};
    AppState.plotVariableCache[varName] = variable.data;
    return variable.data;
}

async function ensureContainerCatalogLoaded(entry) {
    if (entry.varCatalog !== null) return;

    const params = window.TiledHttpClient.buildSearchParams({ limit: 100, fields: ['structure_family', 'structure'] });
    const result = await tiledClient.search(params, { entry });
    const items = result?.data || [];

    const catalog = {};
    for (const item of items) {
        const s = item.attributes?.structure || {};
        catalog[item.id] = {
            entryRef: window.TiledHttpClient.entryRefFromItem(item),
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

    varInfo.data = await tiledClient.full(varInfo.fullLink, {
        format: 'application/json',
        entry: varInfo.entryRef || varName
    });
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

function getCatalogCoordNames(catalog) {
    const coordNames = new Set();
    for (const [name, info] of Object.entries(catalog || {})) {
        for (const dim of info.dims || []) {
            if (catalog?.[dim]) coordNames.add(dim);
        }
        if (info.is_coord) coordNames.add(name);
    }
    return coordNames;
}

function buildVarCatalogHtml(catalog, sampleDim = null) {
    if (!catalog || Object.keys(catalog).length === 0) return '';

    const kindLabel = { f: 'float', i: 'int', u: 'uint', U: 'str', S: 'bytes', b: 'bool', c: 'complex' };

    const coordNames = getCatalogCoordNames(catalog);

    function varRow(name, info) {
        const dimsStr = info.dims.length ? `(${info.dims.join(', ')})` : '()';
        const shapeStr = info.shape.length ? info.shape.join(' \u00d7 ') : 'scalar';
        const dtype = kindLabel[info.kind] || info.kind;
        const classification = classifyCatalogItem(info, catalog, sampleDim);
        return `<tr>
            <td style="padding:2px 8px; font-family:monospace;">${name}</td>
            <td style="padding:2px 8px; color:#666;">${dimsStr}</td>
            <td style="padding:2px 8px;">${shapeStr}</td>
            <td style="padding:2px 8px;">${dtype}</td>
            <td style="padding:2px 8px;">${classification}</td>
        </tr>`;
    }

    const coordEntries = Object.entries(catalog).filter(([n]) => coordNames.has(n));
    const dataEntries = Object.entries(catalog).filter(([n]) => !coordNames.has(n));

    const thStyle = 'text-align:left; border-bottom:1px solid #ccc; padding:2px 8px; font-size:0.85em; color:#555;';
    const sectionHdr = (label, count) =>
        `<tr><td colspan="5" style="padding:4px 8px; font-weight:bold; background:#f5f5f5; border-top:1px solid #ddd;">${label} (${count})</td></tr>`;

    return `
        <table style="width:100%; border-collapse:collapse; font-size:0.9em; margin-top:8px;">
            <thead><tr>
                <th style="${thStyle}">Name</th>
                <th style="${thStyle}">Dimensions</th>
                <th style="${thStyle}">Shape</th>
                <th style="${thStyle}">Dtype</th>
                <th style="${thStyle}">Class</th>
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
    const isContainer = firstEntry?.structureFamily === 'container' || Boolean(AppState.plotManifest);

    const rows = AppState.entries.map(entry => {
        const metadata = entry.metadata || {};
        const task = resolveMeta(metadata, 'task_name') || 'n/a';
        const driver = resolveMeta(metadata, 'driver_name') || 'n/a';
        const sample = resolveMeta(metadata, 'sample_name') || 'n/a';
        const loaded = AppState.plotManifest
            ? `${Object.keys(AppState.plotManifest.catalog || {}).length} vars`
            : (isContainer
            ? (entry.varCatalog !== null ? `${Object.keys(entry.varCatalog).length} vars` : 'catalog pending')
            : (entry.table !== null ? 'yes' : 'no'));
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

    const catalog = AppState.plotManifest?.catalog || firstEntry?.varCatalog || null;
    const label = AppState.plotManifest ? 'Combined dataset' : firstEntry?.id;
    const varHtml = isContainer && catalog
        ? `<h4 style="margin:12px 0 4px;">Variables (${label})</h4>${buildVarCatalogHtml(catalog, getEffectiveSampleDim())}`
        : '';

    info.innerHTML = metaTable + varHtml;
}

async function updateVariableOptions() {
    if (AppState.entries.length === 0) return;

    const firstEntry = AppState.entries[0];
    const useManifest = AppState.entries.length > 1 && Boolean(AppState.plotManifest?.catalog);
    let variableOptions = [];
    let maxIndex;

    if (useManifest) {
        const catalog = AppState.plotManifest.catalog;
        const sampleDim = AppState.plotManifest.sample_dim || 'index';
        firstEntry.sampleDim = sampleDim;
        firstEntry.numSamples = AppState.plotManifest.sample_count || 1;
        AppState.sampleDim = sampleDim;
        AppState.xVariable = null;
        maxIndex = Math.max((AppState.plotManifest.dims?.[sampleDim] ?? AppState.plotManifest.sample_count ?? 1) - 1, 0);
        variableOptions = Object.entries(catalog)
            .filter(([name, info]) => {
                if (getCatalogCoordNames(catalog).has(name)) return false;
                return ['line', 'image'].includes(getVariableMode(info, sampleDim, catalog));
            })
            .map(([name, info]) => ({
                name,
                mode: getVariableMode(info, sampleDim, catalog),
                classification: classifyCatalogItem(info, catalog, sampleDim)
            }));
    } else if (firstEntry.structureFamily === 'container') {
        await ensureContainerCatalogLoaded(firstEntry);
        const sampleDim = firstEntry.sampleDim;
        const catalog = firstEntry.varCatalog;
        variableOptions = Object.entries(catalog)
            .filter(([name]) => !getCatalogCoordNames(catalog).has(name))
            .map(([name, info]) => ({
                name,
                mode: getVariableMode(info, sampleDim, catalog),
                classification: classifyCatalogItem(info, catalog, sampleDim)
            }))
            .filter(option => option.mode === 'line' || option.mode === 'image');
        AppState.xVariable = null;
        AppState.sampleDim = sampleDim || 'entry';
        maxIndex = firstEntry.numSamples - 1;
    } else {
        await ensureEntryDataLoaded(firstEntry);
        const numericCols = firstEntry.numericColumns || [];
        AppState.xVariable = preferredXColumn(numericCols);
        variableOptions = numericCols
            .filter(c => c !== AppState.xVariable)
            .map(name => ({ name, mode: 'line', classification: 'line_1d' }));
        maxIndex = Math.max(AppState.entries.length - 1, 0);
    }

    const scatterSelect = document.getElementById('scatter-vars');
    scatterSelect.innerHTML = '';
    variableOptions.forEach((optionInfo, idx) => {
        const option = document.createElement('option');
        option.value = optionInfo.name;
        option.textContent = optionInfo.mode === 'image'
            ? `${optionInfo.name} [image]`
            : optionInfo.name;
        option.dataset.mode = optionInfo.mode;
        option.dataset.classification = optionInfo.classification;
        if (idx === 0) option.selected = true;
        scatterSelect.appendChild(option);
    });
    AppState.scatterVariables = Array.from(scatterSelect.selectedOptions).map(opt => opt.value);

    const compSelect = document.getElementById('composition-var');
    if (!useManifest && firstEntry.structureFamily === 'container' && firstEntry.sampleDim && firstEntry.varCatalog) {
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
    if (!useManifest && firstEntry.structureFamily === 'container' && firstEntry.sampleDim && firstEntry.varCatalog) {
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
    if (useManifest) {
        const sampleDim = AppState.plotManifest.sample_dim || 'index';
        sampleDimSelect.innerHTML = `<option value="${sampleDim}" selected>${sampleDim}</option>`;
    } else if (firstEntry.structureFamily === 'container' && firstEntry.varCatalog) {
        const allDims = new Set();
        for (const info of Object.values(firstEntry.varCatalog)) {
            for (const dim of info.dims) allDims.add(dim);
        }
        const effectiveDim = firstEntry.sampleDim;
        sampleDimSelect.innerHTML = Array.from(allDims).map(dim =>
            `<option value="${dim}"${dim === effectiveDim ? ' selected' : ''}>${dim}</option>`
        ).join('');
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
    const useManifest = AppState.entries.length > 1 && Boolean(AppState.plotManifest?.catalog);
    const sampleDim = getEffectiveSampleDim();
    const manifestCatalog = AppState.plotManifest?.catalog || {};

    const firstEntry = AppState.entries[0];
    if (useManifest) {
        for (const varName of selected) {
            const varInfo = manifestCatalog[varName];
            if (!varInfo || !'fiu'.includes(varInfo.kind)) continue;

            let yData;
            try {
                yData = await ensureManifestVariableLoaded(varName);
            } catch (err) {
                showError(`Could not load ${varName}: ${err.message}`);
                continue;
            }

            const qDim = varInfo.dims.find(d => d !== sampleDim) || varInfo.dims[0];
            let xData = null;
            if (qDim && manifestCatalog[qDim]) {
                try {
                    xData = await ensureManifestVariableLoaded(qDim);
                } catch (_) {}
            }

            const is2D = Array.isArray(yData) && Array.isArray(yData[0]);
            const yRow = is2D ? yData[Math.min(AppState.dataIndex, yData.length - 1)] : yData;
            if (!yRow) continue;
            const xRow = is2D && Array.isArray(xData) && Array.isArray(xData[0])
                ? xData[Math.min(AppState.dataIndex, xData.length - 1)]
                : xData;
            traces.push({
                x: Array.isArray(xRow) ? toNumericArray(xRow) : yRow.map((_, j) => j),
                y: toNumericArray(yRow),
                type: 'scatter',
                mode: 'markers',
                name: varName,
                marker: { size: 5 },
                visible: true
            });
        }
        return traces;
    }

    // Container branch: use first entry, show only the selected sample row
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

function updatePrimaryPlotTitle(mode) {
    const title = document.getElementById('primary-plot-title');
    if (!title) return;
    title.textContent = mode === 'image' ? 'Image Data' : '1D Data';
}

async function buildImagePlot(varName) {
    const useManifest = AppState.entries.length > 1 && Boolean(AppState.plotManifest?.catalog);
    const sampleDim = getEffectiveSampleDim();
    const manifestCatalog = AppState.plotManifest?.catalog || {};
    let varInfo;
    let zData;
    let xData = null;
    let yData = null;
    let yDim = null;
    let xDim = null;

    if (useManifest) {
        varInfo = manifestCatalog[varName];
        if (!varInfo) {
            throw new Error(`Variable ${varName} not in combined manifest`);
        }

        zData = await ensureManifestVariableLoaded(varName);
        if (Array.isArray(zData) && Array.isArray(zData[0]) && Array.isArray(zData[0][0]) && varInfo.dims.includes(sampleDim)) {
            zData = zData[Math.min(AppState.dataIndex, zData.length - 1)];
        }

        const imageDims = (varInfo.dims || []).filter(d => d !== sampleDim).slice(-2);
        yDim = imageDims[0];
        xDim = imageDims[1];

        if (xDim && manifestCatalog[xDim]) {
            try {
                xData = await ensureManifestVariableLoaded(xDim);
            } catch (_) {}
        }
        if (yDim && manifestCatalog[yDim]) {
            try {
                yData = await ensureManifestVariableLoaded(yDim);
            } catch (_) {}
        }

        if (Array.isArray(xData) && Array.isArray(xData[0]) && manifestCatalog[xDim]?.dims?.includes(sampleDim)) {
            xData = xData[Math.min(AppState.dataIndex, xData.length - 1)];
        }
        if (Array.isArray(yData) && Array.isArray(yData[0]) && manifestCatalog[yDim]?.dims?.includes(sampleDim)) {
            yData = yData[Math.min(AppState.dataIndex, yData.length - 1)];
        }
    } else {
        const entry = AppState.entries[0];
        if (!entry || entry.structureFamily !== 'container') {
            throw new Error(`Image rendering requires container-style array access for ${varName}`);
        }

        await ensureContainerCatalogLoaded(entry);
        varInfo = entry.varCatalog?.[varName];
        if (!varInfo) {
            throw new Error(`Variable ${varName} not in catalog`);
        }

        zData = await ensureVariableLoaded(entry, varName);
        if (Array.isArray(zData) && Array.isArray(zData[0]) && Array.isArray(zData[0][0])) {
            zData = zData[Math.min(AppState.dataIndex, zData.length - 1)];
        }

        const imageDims = (varInfo.dims || []).length >= 2
            ? varInfo.dims.slice(-2)
            : [];
        yDim = imageDims[0];
        xDim = imageDims[1];

        if (xDim && entry.varCatalog?.[xDim]) {
            try {
                xData = await ensureVariableLoaded(entry, xDim);
            } catch (_) {}
        }
        if (yDim && entry.varCatalog?.[yDim]) {
            try {
                yData = await ensureVariableLoaded(entry, yDim);
            } catch (_) {}
        }

        if (Array.isArray(xData) && Array.isArray(xData[0])) {
            xData = xData[Math.min(AppState.dataIndex, xData.length - 1)];
        }
        if (Array.isArray(yData) && Array.isArray(yData[0])) {
            yData = yData[Math.min(AppState.dataIndex, yData.length - 1)];
        }
    }

    if (!(Array.isArray(zData) && Array.isArray(zData[0]))) {
        throw new Error(`Variable ${varName} is not a 2D image payload`);
    }

    const flat = zData.flat().map(Number).filter(Number.isFinite);
    if (flat.length > 0 && AppState._lastAutoRangedImageVar !== varName) {
        AppState._lastAutoRangedImageVar = varName;
        AppState.cmin = Math.min(...flat);
        AppState.cmax = Math.max(...flat);
        document.getElementById('cmin').value = AppState.cmin.toFixed(2);
        document.getElementById('cmax').value = AppState.cmax.toFixed(2);
    }

    return {
        traces: [{
            type: 'heatmap',
            z: zData,
            x: Array.isArray(xData) ? xData : undefined,
            y: Array.isArray(yData) ? yData : undefined,
            colorscale: AppState.colorscale,
            zmin: AppState.cmin,
            zmax: AppState.cmax,
            colorbar: { title: varName },
            hovertemplate: 'x=%{x}<br>y=%{y}<br>z=%{z}<extra></extra>'
        }],
        layout: {
            xaxis: { title: xDim || 'x' },
            yaxis: { title: yDim || 'y', autorange: 'reversed' },
            autosize: true,
            margin: { t: 10, b: 40, l: 50, r: 10 }
        }
    };
}

async function renderScatteringPlot() {
    const selected = AppState.scatterVariables || [];
    if (selected.length === 0) {
        updatePrimaryPlotTitle('line');
        Plotly.purge('scattering-plot');
        return;
    }

    const catalog = getPlotCatalog();
    const sampleDim = getEffectiveSampleDim();
    const imageSelections = selected.filter(name => {
        const info = catalog?.[name];
        if (!info) return false;
        return getVariableMode(info, sampleDim, catalog) === 'image';
    });

    if (imageSelections.length > 0) {
        updatePrimaryPlotTitle('image');
        if (selected.length > 1) {
            showError('Select exactly one image variable at a time.');
            Plotly.purge('scattering-plot');
            return;
        }
        try {
            const imagePlot = await buildImagePlot(imageSelections[0]);
            Plotly.react('scattering-plot', imagePlot.traces, imagePlot.layout, {
                responsive: true,
                displayModeBar: true
            });
            hideError();
        } catch (err) {
            showError(`Could not render image ${imageSelections[0]}: ${err.message}`);
            Plotly.purge('scattering-plot');
        }
        return;
    }

    updatePrimaryPlotTitle('line');
    const traces = await buildScatteringTraces();
    if (traces.length === 0) {
        Plotly.purge('scattering-plot');
        return;
    }

    Plotly.react('scattering-plot', traces, {
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
    }, { responsive: true, displayModeBar: true });
    hideError();
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
    if (validColors.length > 0 && AppState.compositionColorVariable !== AppState._lastAutoRangedColorVar) {
        AppState._lastAutoRangedColorVar = AppState.compositionColorVariable;
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

    document.getElementById('reset-dataset')?.addEventListener('click', async () => {
        for (const entry of AppState.entries) {
            entry.table = null;
            entry.numericColumns = [];
            // Also reset container catalog so sample-dim is re-detected
            entry.varCatalog = null;
            entry.sampleDim = null;
            entry.numSamples = 0;
        }
        AppState.plotManifest = null;
        AppState.plotVariableCache = {};
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
        renderAllPlots();
    });

    document.getElementById('sample-dim-select').addEventListener('change', async (e) => {
        const newDim = e.target.value;
        const entry = AppState.entries[0];
        if (!entry) return;

        entry.sampleDim = newDim;
        AppState.sampleDim = newDim;

        // Recalculate numSamples from the cached catalog shape
        if (AppState.plotManifest?.dims?.[newDim] !== undefined) {
            entry.numSamples = AppState.plotManifest.dims[newDim] ?? 1;
        } else if (entry.varCatalog?.[newDim]) {
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
        AppState.plotManifest = null;
        AppState.plotVariableCache = {};

        entryIds = parseEntryIds().map(entry => window.TiledHttpClient.toEntryRef(entry));
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

        if (AppState.entries.length > 1) {
            setStatus('loading', 'Loading combined dataset structure...');
            await ensurePlotManifestLoaded();
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
