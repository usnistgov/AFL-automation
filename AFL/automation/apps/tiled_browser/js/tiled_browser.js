/**
 * Tiled Database Browser
 *
 * Interactive browser for Tiled database entries with AG Grid integration.
 * Uses Driver proxy endpoints to communicate with Tiled API (avoids CORS issues).
 */

// =============================================================================
// State Management
// =============================================================================

let tiledConfig = null;  // { tiled_server, tiled_api_key }
let tiledClient = null;
let connectionMode = 'unknown'; // 'direct' | 'proxy' | 'unknown'
let currentQueries = [];  // Array of {field, value} query objects
let currentFilters = {};  // Object mapping filter field names to arrays of selected values
let pageSize = 50;
let gridApi = null;
let currentColumns = new Set();
let totalCount = 0;
let multiSelectInstances = {};  // Store multi-select state for each filter
let currentCopyText = '';
let uploadColumnHeaders = [];
let lastUploadFormState = null;
const DEFAULT_SORT_MODEL = [{ colId: 'meta_ended', sort: 'desc' }];
let activeTabName = 'filters';
let tabsCollapsed = false;

// Available search fields (excluding datetime columns)
const SEARCH_FIELDS = [
    'task_name',
    'driver_name',
    'run_time_minutes',
    'sample_uuid',
    'sample_name',
    'AL_campaign_name',
    'AL_uuid',
    'AL_components'
];

const FILTER_FIELDS = [
    'driver_name',
    'sample_name',
    'sample_uuid',
    'AL_campaign_name',
    'AL_uuid'
];

const filterLoadState = {};
const FIELD_CANDIDATES = window.TiledHttpClient.DEFAULT_FIELD_CANDIDATES;
const searchRequestState = {
    sequence: 0,
    controller: null
};
const chronologicalSortCache = {
    key: null,
    rows: [],
    totalCount: 0
};

// =============================================================================
// Utility Functions
// =============================================================================

/**
 * Recursively extract all nested keys from an object with dot notation
 */
function extractNestedKeys(obj, prefix = '') {
    const keys = new Set();

    if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
        for (const [key, value] of Object.entries(obj)) {
            const fullKey = prefix ? `${prefix}.${key}` : key;
            keys.add(fullKey);

            if (value && typeof value === 'object' && !Array.isArray(value)) {
                const nestedKeys = extractNestedKeys(value, fullKey);
                nestedKeys.forEach(k => keys.add(k));
            }
        }
    }

    return keys;
}

/**
 * Get a nested value from an object using dot notation path
 */
function getNestedValue(obj, path) {
    if (!obj || !path) return null;

    const parts = path.split('.');
    let current = obj;

    for (const part of parts) {
        if (current === null || current === undefined) return null;
        current = current[part];
    }

    return current;
}

/**
 * Format a header name from a dot-notation path
 */
function formatHeader(fieldPath) {
    const parts = fieldPath.split('.');
    const lastPart = parts[parts.length - 1];
    return lastPart
        .split('_')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

/**
 * Flatten metadata for grid row data
 */
function flattenMetadata(metadata, prefix = '') {
    const result = {};

    if (metadata && typeof metadata === 'object') {
        for (const [key, value] of Object.entries(metadata)) {
            const fullKey = prefix ? `${prefix}.${key}` : key;

            if (value && typeof value === 'object' && !Array.isArray(value)) {
                Object.assign(result, flattenMetadata(value, fullKey));
            } else {
                result[fullKey] = value;
            }
        }
    }

    return result;
}

function splitCsvLikeLine(line, delimiter) {
    const values = [];
    let current = '';
    let inQuotes = false;

    for (let i = 0; i < line.length; i += 1) {
        const ch = line[i];
        if (ch === '"') {
            // Handle escaped double quote inside quoted field.
            if (inQuotes && i + 1 < line.length && line[i + 1] === '"') {
                current += '"';
                i += 1;
            } else {
                inQuotes = !inQuotes;
            }
            continue;
        }
        if (ch === delimiter && !inQuotes) {
            values.push(current.trim());
            current = '';
            continue;
        }
        current += ch;
    }
    values.push(current.trim());
    return values;
}

function detectTableDelimiter(format, firstLine, userDelimiter = '') {
    const manual = (userDelimiter || '').trim();
    if (manual.length > 0) {
        return manual;
    }
    if (format === 'csv') {
        return ',';
    }
    if (format === 'tsv') {
        if (firstLine.includes('\t')) {
            return '\t';
        }
        const tokens = firstLine.trim().split(/\s+/).filter(Boolean);
        if (tokens.length > 1) {
            return '__whitespace__';
        }
        return '\t';
    }
    if (format === 'dat') {
        if (firstLine.includes('\t')) {
            return '\t';
        }
        const tokens = firstLine.trim().split(/\s+/).filter(Boolean);
        if (tokens.length > 1) {
            return '__whitespace__';
        }
        return '\t';
    }
    return ',';
}

// =============================================================================
// Configuration Loading
// =============================================================================

/**
 * Load Tiled configuration from Driver backend
 */
async function checkConfig() {
    try {
        updateConnectionStatus('loading');

        tiledConfig = await window.TiledHttpClient.loadConfig();
        tiledClient = await window.TiledHttpClient.createClientFromConfig(tiledConfig);
        connectionMode = tiledClient?.mode || 'unknown';

        updateConnectionStatus(connectionMode === 'proxy' ? 'proxy' : 'connected');
        return true;

    } catch (error) {
        connectionMode = 'unknown';
        showError(`Failed to load configuration: ${error.message}`);
        updateConnectionStatus('error');
        return false;
    }
}

// =============================================================================
// Tiled API Functions
// =============================================================================

/**
 * Search Tiled database with pagination
 */
async function performSearch(queries, offset, limit, sortModel = [], signal = null) {
    try {
        const params = window.TiledHttpClient.buildSearchParams({
            offset,
            limit,
            sortModel: sortModel || [],
            queryRows: queries || [],
            quickFilters: currentFilters || {},
            candidatesMap: FIELD_CANDIDATES
        });
        const primaryPayload = await tiledClient.search(params, {
            signal,
            legacyPayload: {
                queryRows: queries || [],
                quickFilters: currentFilters || {},
                sortModel: sortModel || [],
                offset,
                limit
            }
        });
        const primary = window.TiledHttpClient.normalizeSearchResponse(primaryPayload);
        let items = primary.data;
        let totalCount = primary.totalCount;

        const hasConstrainedFields =
            (queries && queries.length > 0) || Object.keys(currentFilters || {}).length > 0;
        if (hasConstrainedFields && primary.data.length === 0) {
            const altParams = window.TiledHttpClient.buildSearchParams({
                offset,
                limit,
                sortModel: sortModel || [],
                queryRows: queries || [],
                quickFilters: currentFilters || {},
                candidatesMap: FIELD_CANDIDATES,
                useAlternate: true
            });
            const secondaryPayload = await tiledClient.search(altParams, {
                signal,
                legacyPayload: {
                    queryRows: queries || [],
                    quickFilters: currentFilters || {},
                    sortModel: sortModel || [],
                    offset,
                    limit
                }
            });
            const secondary = window.TiledHttpClient.normalizeSearchResponse(secondaryPayload);
            items = window.TiledHttpClient.mergeSearchData(primary.data, secondary.data);
            totalCount = Math.max(primary.totalCount, secondary.totalCount, items.length);
        }

        const allKeys = new Set();
        for (const item of items) {
            const metadata = item?.attributes?.metadata || {};
            extractNestedKeys(metadata).forEach(k => allKeys.add(k));
        }

        const finalResult = {
            status: 'success',
            data: items,
            total_count: totalCount,
            columns: Array.from(allKeys).sort()
        };
        return finalResult;

    } catch (error) {
        if (error && error.name === 'AbortError') {
            return { status: 'aborted' };
        }
        return {
            status: 'error',
            message: error.message
        };
    }
}

async function performSearchPaged(queries, offset, limit, sortModel = [], signal = null) {
    const maxPageLimit = Number(window.TiledHttpClient?.MAX_PAGE_LIMIT || 300);
    const requestedLimit = Math.max(Number(limit) || 0, 0);

    if (requestedLimit <= maxPageLimit) {
        return performSearch(queries, offset, requestedLimit, sortModel, signal);
    }

    const mergedData = [];
    let totalCount = 0;
    let currentOffset = Math.max(Number(offset) || 0, 0);
    let remaining = requestedLimit;

    while (remaining > 0) {
        const chunkLimit = Math.min(remaining, maxPageLimit);
        const result = await performSearch(queries, currentOffset, chunkLimit, sortModel, signal);
        if (result.status !== 'success') {
            return result;
        }

        const chunkData = Array.isArray(result.data) ? result.data : [];
        mergedData.push(...chunkData);
        totalCount = Math.max(totalCount, Number(result.total_count || 0), mergedData.length);

        if (chunkData.length < chunkLimit) {
            break;
        }

        currentOffset += chunkLimit;
        remaining -= chunkLimit;
    }

    const allKeys = new Set();
    for (const item of mergedData) {
        const metadata = item?.attributes?.metadata || {};
        extractNestedKeys(metadata).forEach(k => allKeys.add(k));
    }

    return {
        status: 'success',
        data: mergedData,
        total_count: totalCount,
        columns: Array.from(allKeys).sort()
    };
}

/**
 * Load xarray Dataset HTML representation for an entry
 */
async function loadData(entry) {
    try {
        const entryRef = window.TiledHttpClient.toEntryRef(entry);
        const metaResponse = await tiledClient.metadata(entryRef);
        const fullLink = metaResponse?.data?.links?.full || entryRef.fullLink;
        if (!fullLink && !tiledClient.useProxy) {
            throw new Error('Missing links.full on metadata response');
        }

        try {
            const html = await tiledClient.full(fullLink, {
                format: 'text/html',
                responseType: 'text',
                entry: entryRef
            });
            return { status: 'success', html };
        } catch (_htmlError) {
            const jsonData = await tiledClient.full(fullLink, {
                format: 'application/json',
                responseType: 'json',
                entry: entryRef
            });
            return {
                status: 'success',
                html: `<pre>${JSON.stringify(jsonData, null, 2)}</pre>`
            };
        }

    } catch (error) {
        return {
            status: 'error',
            message: error.message
        };
    }
}

/**
 * Load full metadata for an entry
 */
async function loadMetadata(entry) {
    try {
        const result = await tiledClient.metadata(entry);

        return {
            status: 'success',
            metadata: result?.data?.attributes?.metadata || {}
        };

    } catch (error) {
        return {
            status: 'error',
            message: error.message
        };
    }
}

/**
 * Load distinct/unique values for a metadata field
 */
async function loadDistinctValues(field) {
    try {
        const params = window.TiledHttpClient.buildDistinctParams({
            metadataKeys: [field],
            activeFilters: currentFilters || {},
            candidatesMap: FIELD_CANDIDATES
        });
        const result = await tiledClient.distinct(params, { legacyField: field });
        const metadataMap = result?.metadata || {};
        const candidates = window.TiledHttpClient.candidatePathsForField(field, FIELD_CANDIDATES);
        const values = [];
        for (const path of candidates) {
            const items = metadataMap[path] || [];
            for (const item of items) {
                values.push(item?.value);
            }
        }

        return {
            status: 'success',
            values: window.TiledHttpClient.uniqueValues(values).sort((a, b) => String(a).localeCompare(String(b)))
        };

    } catch (error) {
        return {
            status: 'error',
            message: error.message
        };
    }
}

// =============================================================================
// AG Grid Configuration
// =============================================================================

/**
 * Actions cell renderer for View Data and View Metadata buttons
 */
class ActionsRenderer {
    init(params) {
        this.params = params;
        this.eGui = document.createElement('div');
        this.eGui.className = 'action-buttons';

        const viewDataBtn = document.createElement('button');
        viewDataBtn.textContent = 'Data';
        viewDataBtn.className = 'action-btn view-data-btn';
        viewDataBtn.onclick = () => this.onViewData();

        const viewMetadataBtn = document.createElement('button');
        viewMetadataBtn.textContent = 'Metadata';
        viewMetadataBtn.className = 'action-btn view-metadata-btn';
        viewMetadataBtn.onclick = () => this.onViewMetadata();

        this.eGui.appendChild(viewDataBtn);
        this.eGui.appendChild(viewMetadataBtn);
    }

    getGui() {
        return this.eGui;
    }

    async onViewData() {
        const entryRef = this.params.data.entryRef || this.params.data.id;
        showLoadingInModal('data');

        const result = await loadData(entryRef);

        if (result.status === 'success') {
            showDataModal(result.html);
        } else {
            showError(`Failed to load data: ${result.message}`);
            closeModals();
        }
    }

    async onViewMetadata() {
        const entryRef = this.params.data.entryRef || this.params.data.id;
        showLoadingInModal('metadata');

        const result = await loadMetadata(entryRef);

        if (result.status === 'success') {
            showMetadataModal(result.metadata);
        } else {
            showError(`Failed to load metadata: ${result.message}`);
            closeModals();
        }
    }

    refresh() {
        return false;
    }
}

function transformRows(items) {
    return items.map(item => {
        const metadata = item?.attributes?.metadata || {};
        const entryRef = window.TiledHttpClient.entryRefFromItem(item);

        return {
            id: item.id,
            task_name: window.TiledHttpClient.resolveMetadataValue(metadata, 'task_name', FIELD_CANDIDATES),
            driver_name: window.TiledHttpClient.resolveMetadataValue(metadata, 'driver_name', FIELD_CANDIDATES),
            meta_started: window.TiledHttpClient.resolveMetadataValue(metadata, 'meta_started', FIELD_CANDIDATES),
            meta_ended: window.TiledHttpClient.resolveMetadataValue(metadata, 'meta_ended', FIELD_CANDIDATES),
            run_time_minutes: window.TiledHttpClient.resolveMetadataValue(metadata, 'run_time_minutes', FIELD_CANDIDATES),
            sample_uuid: window.TiledHttpClient.resolveMetadataValue(metadata, 'sample_uuid', FIELD_CANDIDATES),
            sample_name: window.TiledHttpClient.resolveMetadataValue(metadata, 'sample_name', FIELD_CANDIDATES),
            AL_campaign_name: window.TiledHttpClient.resolveMetadataValue(metadata, 'AL_campaign_name', FIELD_CANDIDATES),
            AL_uuid: window.TiledHttpClient.resolveMetadataValue(metadata, 'AL_uuid', FIELD_CANDIDATES),
            AL_components: window.TiledHttpClient.resolveMetadataValue(metadata, 'AL_components', FIELD_CANDIDATES),
            entryRef,
            _raw: item
        };
    });
}

/**
 * Parse date string to timestamp for sorting
 * Parses format: MM/DD/YY HH:MM:SS-microseconds TIMEZONE_NAME±TIMEZONE_OFFSET
 * Example: "12/07/25 14:30:45-123456 EST-0500"
 * Returns: Unix timestamp (milliseconds) or 0 if invalid
 */
function parseDateToTimestamp(dateString) {
    if (!dateString) return 0;

    try {
        // QueueDaemon-style: MM/DD/YY HH:MM:SS-ffffff [TZ][+-HHMM]
        // Example: 12/07/25 14:30:45-123456 EST-0500
        let match = dateString.match(
            /^(\d{2})\/(\d{2})\/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})(?:-(\d{1,6}))?(?:\s+[A-Za-z_]+)?(?:([+-]\d{4}))?\s*$/
        );
        if (match) {
            const [_, month, day, year, hours, minutes, seconds, microseconds, tzOffset] = match;
            const fullYear = '20' + year;
            const fractional = microseconds ? `.${microseconds.padEnd(6, '0').slice(0, 6)}` : '';
            const tz = tzOffset ? `${tzOffset.slice(0, 3)}:${tzOffset.slice(3, 5)}` : '';
            const isoString = `${fullYear}-${month}-${day}T${hours}:${minutes}:${seconds}${fractional}${tz}`;
            const date = new Date(isoString);
            if (!isNaN(date.getTime())) {
                return date.getTime();
            }
        }

        // Display-style/legacy: YYYY-MM-DD HH:MM:SS
        match = dateString.match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})/);
        if (match) {
            const [_, year, month, day, hours, minutes, seconds] = match;
            const isoString = `${year}-${month}-${day}T${hours}:${minutes}:${seconds}`;
            const date = new Date(isoString);
            if (!isNaN(date.getTime())) {
                return date.getTime();
            }
        }
        return 0;
    } catch (e) {
        return 0;
    }
}

/**
 * Format date/time string for display
 * Parses format: MM/DD/YY HH:MM:SS-microseconds TIMEZONE_NAME±TIMEZONE_OFFSET
 * Example: "12/07/25 14:30:45-123456 EST-0500"
 */
function formatDateTime(dateString) {
    if (!dateString) return '';

    try {
        // Extract date/time portion before the microseconds
        const match = dateString.match(/^(\d{2})\/(\d{2})\/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})/);

        if (!match) {
            return dateString; // Return original if format doesn't match
        }

        const [_, month, day, year, hours, minutes, seconds] = match;

        // Convert 2-digit year to 4-digit year (assuming 20xx)
        const fullYear = '20' + year;

        // Format as ISO string for Date parsing: YYYY-MM-DDTHH:MM:SS
        const isoString = `${fullYear}-${month}-${day}T${hours}:${minutes}:${seconds}`;
        const date = new Date(isoString);

        // Validate the date is valid
        if (isNaN(date.getTime())) {
            return dateString;
        }

        // Format output as YYYY-MM-DD HH:MM:SS
        const outYear = date.getFullYear();
        const outMonth = String(date.getMonth() + 1).padStart(2, '0');
        const outDay = String(date.getDate()).padStart(2, '0');
        const outHours = String(date.getHours()).padStart(2, '0');
        const outMinutes = String(date.getMinutes()).padStart(2, '0');
        const outSeconds = String(date.getSeconds()).padStart(2, '0');

        return `${outYear}-${outMonth}-${outDay} ${outHours}:${outMinutes}:${outSeconds}`;
    } catch (e) {
        return dateString;
    }
}

/**
 * Initialize AG Grid with infinite row model backed by server-side paging.
 */
async function initializeGrid() {
    const gridDiv = document.getElementById('grid-container');

    const gridOptions = {
        columnDefs: [
            {
                field: 'id',
                headerName: 'Entry ID',
                pinned: 'left',
                width: 100
            },
            { field: 'task_name', headerName: 'Task Name', width: 200 },
            { field: 'driver_name', headerName: 'Driver Name', width: 150 },
            {
                field: 'meta_started',
                headerName: 'Started',
                width: 180,
                valueFormatter: params => formatDateTime(params.value),
                comparator: (valueA, valueB) => {
                    // Parse custom date format for sorting
                    const timestampA = parseDateToTimestamp(valueA);
                    const timestampB = parseDateToTimestamp(valueB);
                    return timestampA - timestampB;
                }
            },
            {
                field: 'meta_ended',
                headerName: 'Ended',
                width: 180,
                sort: 'desc',  // Default sort: most recent first
                valueFormatter: params => formatDateTime(params.value),
                comparator: (valueA, valueB) => {
                    // Parse custom date format for sorting
                    const timestampA = parseDateToTimestamp(valueA);
                    const timestampB = parseDateToTimestamp(valueB);
                    return timestampA - timestampB;
                }
            },
            { field: 'run_time_minutes', headerName: 'Runtime (min)', width: 130 },
            { field: 'sample_uuid', headerName: 'Sample UUID', width: 250 },
            { field: 'sample_name', headerName: 'Sample Name', width: 200 },
            { field: 'AL_campaign_name', headerName: 'AL Campaign', width: 200 },
            { field: 'AL_uuid', headerName: 'AL UUID', width: 250 },
            { field: 'AL_components', headerName: 'AL Components', width: 200 },
            {
                field: 'actions',
                headerName: 'Actions',
                pinned: 'right',
                width: 150,
                cellRenderer: ActionsRenderer,
                lockPosition: true,
                sortable: false
            }
        ],
        defaultColDef: {
            sortable: true,
            filter: false,
            resizable: true
        },
        rowModelType: 'infinite',
        pagination: true,
        paginationPageSize: pageSize,
        paginationPageSizeSelector: [25, 50, 100, 200],
        animateRows: true,
        rowSelection: {
            mode: 'multiRow',
            checkboxes: true,
            headerCheckbox: false,
            enableClickSelection: true,
            enableSelectionWithoutKeys: true
        },
        cacheBlockSize: pageSize,
        maxBlocksInCache: 10,
        onGridReady: (params) => {
            gridApi = params.api;
            gridApi.setGridOption('datasource', createDatasource());
        },
        onPaginationChanged: () => {
            updateInfoBar();
        },
        onSelectionChanged: () => {
            updateSelectionButtons();
        }
    };

    gridApi = agGrid.createGrid(gridDiv, gridOptions);
}

// =============================================================================
// UI Functions
// =============================================================================

/**
 * Update connection status indicator
 */
function updateConnectionStatus(status) {
    const statusEl = document.getElementById('connection-status');
    const textEl = statusEl.querySelector('.status-text');

    statusEl.className = '';

    switch (status) {
        case 'connected':
            statusEl.classList.add('status-connected');
            textEl.textContent = 'Connected';
            break;
        case 'proxy':
            statusEl.classList.add('status-proxy');
            textEl.textContent = 'Connected via same-origin proxy (reduced performance)';
            break;
        case 'loading':
            statusEl.classList.add('status-loading');
            textEl.textContent = connectionMode === 'proxy'
                ? 'Loading via same-origin proxy...'
                : 'Loading...';
            break;
        case 'error':
            statusEl.classList.add('status-disconnected');
            textEl.textContent = 'Connection Error';
            break;
        default:
            statusEl.classList.add('status-disconnected');
            textEl.textContent = 'Not Connected';
    }
}

function showOperationalConnectionStatus() {
    updateConnectionStatus(connectionMode === 'proxy' ? 'proxy' : 'connected');
}

/**
 * Update info bar with counts
 */
function updateInfoBar() {
    document.getElementById('total-count').textContent = `Total: ${totalCount} entries`;
    // Note: page-info element removed since AG Grid handles pagination display
}

/**
 * Show error banner
 */
function showError(message) {
    const container = document.getElementById('error-container');
    const text = document.getElementById('error-text');

    text.textContent = message;
    container.style.display = 'block';

    // Auto-hide after 10 seconds
    setTimeout(() => hideError(), 10000);
}

/**
 * Hide error banner
 */
function hideError() {
    document.getElementById('error-container').style.display = 'none';
}

/**
 * Show success message
 */
function showSuccess(message) {
    // Reuse error container but with success styling
    const container = document.getElementById('error-container');
    const text = document.getElementById('error-text');
    const errorMsg = container.querySelector('.error-message');

    text.textContent = message;
    errorMsg.style.backgroundColor = '#d4edda';
    errorMsg.style.borderColor = '#28a745';
    errorMsg.style.color = '#155724';
    container.style.display = 'block';

    // Auto-hide after 3 seconds and reset styling
    setTimeout(() => {
        hideError();
        errorMsg.style.backgroundColor = '';
        errorMsg.style.borderColor = '';
        errorMsg.style.color = '';
    }, 3000);
}

/**
 * Show loading overlay on grid
 */
function showLoadingOverlay() {
    const overlay = document.getElementById('loading-overlay');
    overlay.classList.remove('hidden');
}

/**
 * Hide loading overlay
 */
function hideLoadingOverlay() {
    const overlay = document.getElementById('loading-overlay');
    overlay.classList.add('hidden');
}

/**
 * Show loading state in modal
 */
function showLoadingInModal(type) {
    const modalId = type === 'data' ? 'data-modal' : 'metadata-modal';
    const bodyId = type === 'data' ? 'data-modal-body' : 'metadata-modal-body';

    document.getElementById(modalId).style.display = 'block';
    document.getElementById(bodyId).innerHTML = '<div class="loading-spinner"></div><p>Loading...</p>';
    document.body.style.overflow = 'hidden';
}

/**
 * Show data modal with HTML content
 */
function showDataModal(html) {
    document.getElementById('data-modal').style.display = 'block';
    document.getElementById('data-modal-body').innerHTML = html;
    document.body.style.overflow = 'hidden';
}

/**
 * Show metadata modal with JSON content
 */
function showMetadataModal(metadata) {
    document.getElementById('metadata-modal').style.display = 'block';
    document.getElementById('metadata-modal-body').textContent = JSON.stringify(metadata, null, 2);
    document.body.style.overflow = 'hidden';
}

/**
 * Show copy modal with provided text
 */
function showCopyModal(title, text) {
    const modal = document.getElementById('copy-modal');
    const titleEl = document.getElementById('copy-modal-title');
    const textEl = document.getElementById('copy-modal-text');
    const statusEl = document.getElementById('copy-modal-status');

    currentCopyText = text;
    titleEl.textContent = title;
    textEl.value = text;
    statusEl.textContent = '';
    statusEl.classList.remove('copy-status--success', 'copy-status--error');

    modal.style.display = 'block';
    document.body.style.overflow = 'hidden';
}

/**
 * Update copy modal status message
 */
function setCopyModalStatus(message, isSuccess) {
    const statusEl = document.getElementById('copy-modal-status');
    statusEl.textContent = message;
    statusEl.classList.remove('copy-status--success', 'copy-status--error');
    statusEl.classList.add(isSuccess ? 'copy-status--success' : 'copy-status--error');
}

/**
 * Close all modals
 */
function closeModals() {
    document.getElementById('data-modal').style.display = 'none';
    document.getElementById('metadata-modal').style.display = 'none';
    document.getElementById('copy-modal').style.display = 'none';
    document.body.style.overflow = '';
}

// =============================================================================
// Event Handlers
// =============================================================================

/**
 * Add a new query row to the search builder
 */
function addQueryRow() {
    const container = document.getElementById('query-rows');
    const queryRow = document.createElement('div');
    queryRow.className = 'query-row';

    const fieldSelect = document.createElement('select');
    fieldSelect.className = 'query-field';
    fieldSelect.innerHTML = '<option value="">Select field...</option>' +
        SEARCH_FIELDS.map(f => `<option value="${f}">${f}</option>`).join('');
    fieldSelect.value = 'task_name';

    const valueInput = document.createElement('input');
    valueInput.type = 'text';
    valueInput.className = 'query-value';
    valueInput.placeholder = 'Search value...';

    const removeBtn = document.createElement('button');
    removeBtn.className = 'remove-query-btn';
    removeBtn.textContent = '×';
    removeBtn.onclick = () => {
        container.removeChild(queryRow);
        performSearchAction();
    };

    queryRow.appendChild(fieldSelect);
    queryRow.appendChild(valueInput);
    queryRow.appendChild(removeBtn);
    container.appendChild(queryRow);
}

/**
 * Perform search action - combines filters and queries
 */
async function performSearchAction() {
    // Collect all queries from the query rows
    const queryRows = document.querySelectorAll('.query-row');
    currentQueries = [];

    queryRows.forEach(row => {
        const field = row.querySelector('.query-field').value;
        const value = row.querySelector('.query-value').value;
        if (field && value) {
            currentQueries.push({ field, value });
        }
    });

    refreshDatasource();
}

/**
 * Clear all searches
 */
async function clearSearch() {
    // Remove all query rows
    const container = document.getElementById('query-rows');
    container.innerHTML = '';

    // Add one empty row
    addQueryRow();

    // Clear current queries
    currentQueries = [];

    refreshDatasource();
}

/**
 * Select all currently filtered/visible rows
 */
function selectAllRows() {
    if (!gridApi) {
        console.error('Grid API not available');
        return;
    }

    // For infinite row model, we need to select all loaded nodes
    // Get all currently loaded row nodes
    const nodesToSelect = [];
    gridApi.forEachNode(node => {
        if (node.data) {
            nodesToSelect.push(node);
        }
    });

    // Select all nodes
    nodesToSelect.forEach(node => {
        node.setSelected(true);
    });
}

/**
 * Update selection button states based on selected rows
 */
function updateSelectionButtons() {
    const selectedRows = gridApi.getSelectedRows();
    const copyEntryBtn = document.getElementById('copy-entry-id-button');
    const copySampleBtn = document.getElementById('copy-sample-uuid-button');
    const plotSelectedBtn = document.getElementById('plot-selected-btn');

    const hasSelection = selectedRows.length > 0;

    if (copyEntryBtn && copySampleBtn) {
        copyEntryBtn.disabled = !hasSelection;
        copySampleBtn.disabled = !hasSelection;

        // Update button text with count
        copyEntryBtn.textContent = hasSelection
            ? `Copy Entry ID (${selectedRows.length})`
            : 'Copy Entry ID';
        copySampleBtn.textContent = hasSelection
            ? `Copy Sample UUID (${selectedRows.length})`
            : 'Copy Sample UUID';
    }

    // Enable/disable Plot Selected button
    if (plotSelectedBtn) {
        plotSelectedBtn.disabled = !hasSelection;
    }

    // Enable/disable Gantt Selected button
    const ganttSelectedBtn = document.getElementById('gantt-selected-btn');
    if (ganttSelectedBtn) {
        ganttSelectedBtn.disabled = !hasSelection;
    }
}

/**
 * Copy selected entry IDs to clipboard
 */
function copyEntryIds() {
    const selectedRows = gridApi.getSelectedRows();
    if (selectedRows.length === 0) {
        showError('No rows selected');
        return;
    }

    const ids = selectedRows.map(row => row.id).join(', ');
    showCopyModal(`Copy Entry ID (${selectedRows.length})`, ids);
}

/**
 * Copy selected sample UUIDs to clipboard
 */
function copySampleUuids() {
    const selectedRows = gridApi.getSelectedRows();
    if (selectedRows.length === 0) {
        showError('No rows selected');
        return;
    }

    const uuids = selectedRows
        .map(row => row.sample_uuid)
        .filter(uuid => uuid !== null && uuid !== undefined)
        .join(', ');

    if (uuids.length === 0) {
        showError('No sample UUIDs found in selected rows');
        return;
    }

    const count = selectedRows.filter(row => row.sample_uuid).length;
    showCopyModal(`Copy Sample UUID (${count})`, uuids);
}

/**
 * Attempt to copy text from modal to clipboard
 */
function copyModalTextToClipboard() {
    if (!currentCopyText) {
        setCopyModalStatus('Nothing to copy.', false);
        return;
    }

    if (!navigator.clipboard || !navigator.clipboard.writeText) {
        setCopyModalStatus('Copy failed: clipboard API unavailable.', false);
        return;
    }

    navigator.clipboard.writeText(currentCopyText).then(() => {
        setCopyModalStatus('Copied to clipboard successfully.', true);
    }).catch(err => {
        const message = err && err.message ? err.message : 'Unknown error';
        setCopyModalStatus(`Copy failed: ${message}`, false);
    });
}

/**
 * Open plot page with selected entries
 */
function plotSelected() {
    const selectedRows = gridApi.getSelectedRows();

    if (selectedRows.length === 0) {
        showError('Please select at least one row to plot');
        return;
    }
    if (selectedRows.length > 25) {
        showError(`Plot selection capped at 25 entries (selected ${selectedRows.length}).`);
        return;
    }

    const entryIds = selectedRows.map(row => row.entryRef || row.id);

    // Open plot page and pass entry IDs
    // Use URL params for short lists, sessionStorage for long lists
    if (entryIds.length <= 10) {
        // Short list: use URL params
        const idsParam = encodeURIComponent(JSON.stringify(entryIds));
        window.open(`/tiled_plot?entry_ids=${idsParam}`, '_blank');
    } else {
        // Long list: use sessionStorage to pass data
        sessionStorage.setItem('plotEntryIds', JSON.stringify(entryIds));
        window.open('/tiled_plot', '_blank');
    }
}

/**
 * Open Gantt chart for selected rows
 */
function ganttSelected() {
    const selectedRows = gridApi.getSelectedRows();

    if (selectedRows.length === 0) {
        showError('Please select at least one row for Gantt chart');
        return;
    }
    if (selectedRows.length > 200) {
        showError(`Gantt selection capped at 200 entries (selected ${selectedRows.length}).`);
        return;
    }

    const entryIds = selectedRows.map(row => row.entryRef || row.id);

    // Open gantt page and pass entry IDs
    if (entryIds.length <= 10) {
        // Short list: use URL params
        const idsParam = encodeURIComponent(JSON.stringify(entryIds));
        window.open(`/tiled_gantt?entry_ids=${idsParam}`, '_blank');
    } else {
        // Long list: use sessionStorage
        sessionStorage.setItem('ganttEntryIds', JSON.stringify(entryIds));
        window.open('/tiled_gantt', '_blank');
    }
}

/**
 * Handle page size change
 */
function handlePageSizeChange(newSize) {
    pageSize = parseInt(newSize);

    if (gridApi) {
        gridApi.updateGridOptions({
            paginationPageSize: pageSize,
            cacheBlockSize: pageSize,
            datasource: createDatasource()
        });
        gridApi.purgeInfiniteCache();
    }
}

/**
 * Initialize a multi-select component
 */
function initMultiSelect(container, fieldName, values) {
    const searchBox = container.querySelector('.multiselect-search-box');
    const searchInput = container.querySelector('.multiselect-search');
    const tagsContainer = container.querySelector('.multiselect-tags');
    const dropdown = container.querySelector('.multiselect-dropdown');
    const optionsContainer = container.querySelector('.multiselect-options');

    // Store state
    const state = {
        allValues: values,
        selectedValues: [],
        isOpen: false
    };
    multiSelectInstances[fieldName] = state;

    // Populate options
    optionsContainer.innerHTML = '';
    values.forEach(value => {
        const option = document.createElement('div');
        option.className = 'multiselect-option';
        option.textContent = value;
        option.dataset.value = value;
        option.addEventListener('click', () => toggleOption(fieldName, value));
        optionsContainer.appendChild(option);
    });

    // Search input handler
    searchInput.addEventListener('input', (e) => {
        const searchTerm = e.target.value.toLowerCase();
        const options = optionsContainer.querySelectorAll('.multiselect-option');
        options.forEach(option => {
            const text = option.textContent.toLowerCase();
            if (text.includes(searchTerm)) {
                option.classList.remove('hidden');
            } else {
                option.classList.add('hidden');
            }
        });
    });

    // Focus/blur handlers for dropdown
    searchInput.addEventListener('focus', () => {
        dropdown.style.display = 'block';
        state.isOpen = true;
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (!container.contains(e.target)) {
            dropdown.style.display = 'none';
            state.isOpen = false;
        }
    });
}

/**
 * Toggle option selection in multi-select
 */
function toggleOption(fieldName, value) {
    const state = multiSelectInstances[fieldName];
    const index = state.selectedValues.indexOf(value);

    if (index === -1) {
        // Add selection
        state.selectedValues.push(value);
    } else {
        // Remove selection
        state.selectedValues.splice(index, 1);
    }

    updateMultiSelectUI(fieldName);
}

/**
 * Remove a tag from multi-select
 */
function removeTag(fieldName, value) {
    const state = multiSelectInstances[fieldName];
    const index = state.selectedValues.indexOf(value);
    if (index !== -1) {
        state.selectedValues.splice(index, 1);
        updateMultiSelectUI(fieldName);
    }
}

/**
 * Update multi-select UI (tags and option highlighting)
 */
function updateMultiSelectUI(fieldName) {
    const state = multiSelectInstances[fieldName];
    const container = document.querySelector(`.multiselect-search-box[data-filter="${fieldName}"]`).parentElement;
    const tagsContainer = container.querySelector('.multiselect-tags');
    const optionsContainer = container.querySelector('.multiselect-options');

    // Update tags
    tagsContainer.innerHTML = '';
    state.selectedValues.forEach(value => {
        const tag = document.createElement('div');
        tag.className = 'multiselect-tag';
        tag.innerHTML = `
            <span>${value}</span>
            <span class="multiselect-tag-remove" data-value="${value}">&times;</span>
        `;
        tag.querySelector('.multiselect-tag-remove').addEventListener('click', (e) => {
            e.stopPropagation();
            removeTag(fieldName, value);
        });
        tagsContainer.appendChild(tag);
    });

    // Update option highlighting
    const options = optionsContainer.querySelectorAll('.multiselect-option');
    options.forEach(option => {
        const value = option.dataset.value;
        if (state.selectedValues.includes(value)) {
            option.classList.add('selected');
        } else {
            option.classList.remove('selected');
        }
    });
}

/**
 * Load unique values into multi-select components
 */
async function loadFilterDropdowns() {
    FILTER_FIELDS.forEach(field => {
        const container = document.querySelector(`.multiselect-search-box[data-filter="${field}"]`).parentElement;
        const searchBox = container.querySelector('.multiselect-search-box');
        const searchInput = container.querySelector('.multiselect-search');
        const trigger = () => ensureFilterLoaded(field, container);
        searchBox.addEventListener('click', trigger);
        searchInput.addEventListener('focus', trigger);
    });
}

async function ensureFilterLoaded(field, container) {
    if (filterLoadState[field] === 'loading' || filterLoadState[field] === 'loaded') {
        return;
    }
    filterLoadState[field] = 'loading';

    const dropdown = container.querySelector('.multiselect-dropdown');
    const optionsContainer = container.querySelector('.multiselect-options');
    if (dropdown) {
        dropdown.style.display = 'block';
    }
    optionsContainer.innerHTML = '<div class="multiselect-loading"><div class="loading-spinner"></div><div class="multiselect-loading-text">Loading...</div></div>';

    const result = await loadDistinctValues(field);
    if (result.status === 'success') {
        initMultiSelect(container, field, result.values);
        filterLoadState[field] = 'loaded';
    } else {
        optionsContainer.innerHTML = '<div class="multiselect-empty">Error loading values</div>';
        console.error(`Failed to load distinct values for ${field}:`, result.message);
        filterLoadState[field] = 'error';
    }
}

/**
 * Apply filter selections
 */
async function applyFilters() {
    // Clear existing filters
    currentFilters = {};

    // Collect selected filter values from multi-select instances
    for (const [fieldName, state] of Object.entries(multiSelectInstances)) {
        if (state.selectedValues.length > 0) {
            currentFilters[fieldName] = state.selectedValues;
        }
    }

    refreshDatasource();
}

/**
 * Clear all filter selections
 */
async function clearFilters() {
    // Clear all multi-select instances
    for (const [fieldName, state] of Object.entries(multiSelectInstances)) {
        state.selectedValues = [];
        updateMultiSelectUI(fieldName);
    }

    // Clear filter state
    currentFilters = {};

    // Refresh grid
    refreshDatasource();
}

/**
 * Refresh data while keeping current filters and search
 */
async function refreshData() {
    if (!gridApi) {
        console.error('Grid API not available');
        return;
    }

    // Show brief loading indication
    const refreshBtn = document.getElementById('refresh-button');
    const originalText = refreshBtn.textContent;
    refreshBtn.disabled = true;
    refreshBtn.textContent = '⟳ Refreshing...';

    refreshDatasource();

    // Reset button
    refreshBtn.disabled = false;
    refreshBtn.textContent = originalText;
    showSuccess('Data refreshed');
}

function inferUploadFormat(filename) {
    if (!filename) return '';
    const lower = filename.toLowerCase();
    if (lower.endsWith('.nc')) return 'nc';
    if (lower.endsWith('.csv')) return 'csv';
    if (lower.endsWith('.tsv')) return 'tsv';
    if (lower.endsWith('.dat')) return 'dat';
    return '';
}

function getUploadCommentPrefix() {
    const input = document.getElementById('upload-comment-prefix');
    return input ? input.value : '';
}

function useLastCommentAsHeader() {
    const input = document.getElementById('upload-last-comment-header');
    return !!(input && input.checked);
}

function extractUploadHeaderLine(fileText, commentPrefix = '', headerFromLastComment = false) {
    const lines = fileText.split(/\r?\n/).filter(line => line.trim().length > 0);
    if (lines.length === 0) {
        return '';
    }

    const prefix = (commentPrefix || '').trim();
    if (!prefix) {
        return lines[0];
    }

    const commentLines = [];
    const dataLines = [];
    lines.forEach(line => {
        const trimmedStart = line.trimStart();
        if (trimmedStart.startsWith(prefix)) {
            commentLines.push(trimmedStart.slice(prefix.length).trim());
        } else {
            dataLines.push(line);
        }
    });

    if (headerFromLastComment) {
        const header = commentLines.length > 0 ? commentLines[commentLines.length - 1] : '';
        if (header) {
            return header;
        }
    }

    return dataLines.length > 0 ? dataLines[0] : '';
}

function resetUploadCoordinateSelector() {
    uploadColumnHeaders = [];
    const selectEl = document.getElementById('upload-coordinate-column');
    selectEl.innerHTML = '<option value="">None (row index)</option>';
    selectEl.disabled = true;
}

function populateUploadCoordinateSelector(columns) {
    const selectEl = document.getElementById('upload-coordinate-column');
    selectEl.innerHTML = '<option value="">None (row index)</option>';
    columns.forEach(column => {
        const option = document.createElement('option');
        option.value = column;
        option.textContent = column;
        selectEl.appendChild(option);
    });
    selectEl.disabled = columns.length === 0;
}

async function handleUploadFileSelection() {
    const fileInput = document.getElementById('upload-file-input');
    const formatEl = document.getElementById('upload-file-format');
    const delimiterEl = document.getElementById('upload-delimiter');
    const commentPrefix = getUploadCommentPrefix();
    const headerFromLastComment = useLastCommentAsHeader();

    resetUploadCoordinateSelector();

    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
        formatEl.value = 'Auto-detect from file extension';
        return;
    }

    const file = fileInput.files[0];
    const format = inferUploadFormat(file.name);
    formatEl.value = format || 'Unsupported format';

    if (!format || format === 'nc') {
        return;
    }

    try {
        const text = await file.text();
        const headerLine = extractUploadHeaderLine(text, commentPrefix, headerFromLastComment);
        if (!headerLine) {
            showError('Uploaded table appears empty.');
            return;
        }
        const delimiter = detectTableDelimiter(format, headerLine, delimiterEl.value);
        const columns = delimiter === '__whitespace__'
            ? headerLine.trim().split(/\s+/).filter(name => name.length > 0)
            : splitCsvLikeLine(headerLine, delimiter).filter(name => name.length > 0);
        uploadColumnHeaders = columns;
        populateUploadCoordinateSelector(columns);
    } catch (error) {
        showError(`Failed to read file headers: ${error.message}`);
    }
}

function isNumericUploadCompositionValue(value) {
    return /^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$/.test(value);
}

function createUploadCompositionRow(component = '', value = '') {
    const row = document.createElement('div');
    row.className = 'upload-composition-row';

    const componentInput = document.createElement('input');
    componentInput.type = 'text';
    componentInput.className = 'upload-composition-component';
    componentInput.placeholder = 'Component name (e.g. PEG)';
    componentInput.value = component;

    const valueInput = document.createElement('input');
    valueInput.type = 'text';
    valueInput.className = 'upload-composition-value';
    valueInput.placeholder = 'Value (e.g. 0.35)';
    valueInput.value = value;

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'upload-composition-remove';
    removeBtn.textContent = 'x';
    removeBtn.title = 'Remove component row';
    removeBtn.addEventListener('click', () => {
        row.remove();
    });

    row.appendChild(componentInput);
    row.appendChild(valueInput);
    row.appendChild(removeBtn);
    return row;
}

function initializeUploadCompositionEditor() {
    const rowsContainer = document.getElementById('upload-composition-rows');
    const addButton = document.getElementById('upload-add-composition-button');
    if (!rowsContainer || !addButton) {
        return;
    }

    addButton.addEventListener('click', () => {
        rowsContainer.appendChild(createUploadCompositionRow());
    });

    if (!rowsContainer.children.length) {
        rowsContainer.appendChild(createUploadCompositionRow());
    }
}

function getUploadCompositionRows() {
    return Array.from(document.querySelectorAll('#upload-composition-rows .upload-composition-row'));
}

function gatherSampleComposition() {
    const composition = {};
    const rows = getUploadCompositionRows();

    for (const row of rows) {
        const compInput = row.querySelector('.upload-composition-component');
        const valueInput = row.querySelector('.upload-composition-value');
        const compName = compInput ? compInput.value.trim() : '';
        const rawValue = valueInput ? valueInput.value.trim() : '';

        if (!compName && !rawValue) {
            continue;
        }
        if (!compName || !rawValue) {
            throw new Error('Each sample composition row needs both component name and value.');
        }

        composition[compName] = isNumericUploadCompositionValue(rawValue) ? Number(rawValue) : rawValue;
    }

    return composition;
}

function getUploadFormState() {
    const rows = getUploadCompositionRows().map(row => ({
        component: (row.querySelector('.upload-composition-component')?.value || '').trim(),
        value: (row.querySelector('.upload-composition-value')?.value || '').trim()
    }));

    return {
        delimiter: document.getElementById('upload-delimiter').value,
        comment_prefix: getUploadCommentPrefix(),
        last_comment_as_header: useLastCommentAsHeader(),
        coordinate_column: document.getElementById('upload-coordinate-column').value,
        sample_name: document.getElementById('upload-sample-name').value,
        sample_uuid: document.getElementById('upload-sample-uuid').value,
        AL_campaign_name: document.getElementById('upload-al-campaign-name').value,
        AL_uuid: document.getElementById('upload-al-uuid').value,
        task_name: document.getElementById('upload-task-name').value,
        driver_name: document.getElementById('upload-driver-name').value,
        composition_rows: rows
    };
}

function restoreUploadFormState(state) {
    if (!state || typeof state !== 'object') {
        return;
    }

    const byId = {
        'upload-delimiter': state.delimiter,
        'upload-comment-prefix': state.comment_prefix,
        'upload-sample-name': state.sample_name,
        'upload-sample-uuid': state.sample_uuid,
        'upload-al-campaign-name': state.AL_campaign_name,
        'upload-al-uuid': state.AL_uuid,
        'upload-task-name': state.task_name,
        'upload-driver-name': state.driver_name
    };

    Object.entries(byId).forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el && value !== undefined && value !== null) {
            el.value = value;
        }
    });

    const lastCommentHeaderEl = document.getElementById('upload-last-comment-header');
    if (lastCommentHeaderEl && state.last_comment_as_header !== undefined) {
        lastCommentHeaderEl.checked = !!state.last_comment_as_header;
    }

    const coordEl = document.getElementById('upload-coordinate-column');
    if (coordEl && state.coordinate_column) {
        const option = Array.from(coordEl.options).find(opt => opt.value === state.coordinate_column);
        if (option) {
            coordEl.value = state.coordinate_column;
        }
    }

    const rowsContainer = document.getElementById('upload-composition-rows');
    if (rowsContainer) {
        rowsContainer.innerHTML = '';
        const rows = Array.isArray(state.composition_rows) ? state.composition_rows : [];
        if (rows.length) {
            rows.forEach(row => {
                rowsContainer.appendChild(createUploadCompositionRow(row.component || '', row.value || ''));
            });
        } else {
            rowsContainer.appendChild(createUploadCompositionRow());
        }
    }
}

function gatherUploadMetadata() {
    const metadata = {
        sample_name: document.getElementById('upload-sample-name').value.trim(),
        sample_uuid: document.getElementById('upload-sample-uuid').value.trim(),
        AL_campaign_name: document.getElementById('upload-al-campaign-name').value.trim(),
        AL_uuid: document.getElementById('upload-al-uuid').value.trim(),
        task_name: document.getElementById('upload-task-name').value.trim(),
        driver_name: document.getElementById('upload-driver-name').value.trim()
    };

    const sampleComposition = gatherSampleComposition();
    if (Object.keys(sampleComposition).length > 0) {
        metadata.sample_composition = sampleComposition;
    }

    return metadata;
}

async function submitDatasetUpload() {
    const fileInput = document.getElementById('upload-file-input');
    const uploadBtn = document.getElementById('upload-submit-button');
    const delimiterEl = document.getElementById('upload-delimiter');
    const commentPrefix = getUploadCommentPrefix();
    const headerFromLastComment = useLastCommentAsHeader();
    const coordEl = document.getElementById('upload-coordinate-column');
    lastUploadFormState = getUploadFormState();

    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
        showError('Please choose a file to upload.');
        return;
    }

    const file = fileInput.files[0];
    const format = inferUploadFormat(file.name);
    if (!format) {
        showError('Unsupported file extension. Use .nc, .csv, .tsv, or .dat.');
        return;
    }

    if ((format === 'csv' || format === 'tsv' || format === 'dat') && coordEl.value && uploadColumnHeaders.length > 0 && !uploadColumnHeaders.includes(coordEl.value)) {
        showError('Selected coordinate column is not present in the table headers.');
        return;
    }

    let metadata;
    try {
        metadata = gatherUploadMetadata();
    } catch (error) {
        showError(error.message);
        return;
    }
    const payload = new FormData();
    payload.append('file', file);
    payload.append('file_format', format);
    payload.append('metadata', JSON.stringify(metadata));

    const coordValue = coordEl.value || '';
    if (coordValue) {
        payload.append('coordinate_column', coordValue);
    }

    if (format === 'csv' || format === 'tsv' || format === 'dat') {
        const delimiter = delimiterEl.value || '';
        if (delimiter) {
            payload.append('delimiter', delimiter);
        }
        payload.append('comment_prefix', commentPrefix);
        payload.append('last_comment_as_header', headerFromLastComment ? 'true' : 'false');
    }

    const originalText = uploadBtn.textContent;
    uploadBtn.disabled = true;
    uploadBtn.textContent = 'Uploading...';

    try {
        const response = await window.TiledHttpClient.authenticatedFetch('/tiled_upload_data', {
            method: 'POST',
            body: payload
        });
        const result = await response.json();
        if (!response.ok || result.status === 'error') {
            const message = result.message || `Upload failed with HTTP ${response.status}`;
            showError(message);
            return;
        }

        const summaryVars = result.dataset_summary?.data_vars?.length || 0;
        const entryMsg = result.entry_id ? ` Entry: ${result.entry_id}.` : '';
        showSuccess(`Upload complete (${summaryVars} variables).${entryMsg}`);
        refreshDatasource();
    } catch (error) {
        showError(`Upload failed: ${error.message}`);
    } finally {
        uploadBtn.disabled = false;
        uploadBtn.textContent = originalText;
        restoreUploadFormState(lastUploadFormState);
    }
}

/**
 * Switch between tabs
 */
function switchTab(tabName) {
    const tabContainer = document.querySelector('.tab-container');
    const isActiveTab = tabName === activeTabName;

    if (isActiveTab) {
        tabsCollapsed = !tabsCollapsed;
        tabContainer.classList.toggle('collapsed', tabsCollapsed);
        return;
    }

    activeTabName = tabName;
    tabsCollapsed = false;
    tabContainer.classList.remove('collapsed');

    // Update tab buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        if (btn.dataset.tab === tabName) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    // Update tab content
    document.querySelectorAll('.tab-content').forEach(content => {
        if (content.id === `${tabName}-tab`) {
            content.classList.add('active');
        } else {
            content.classList.remove('active');
        }
    });
}

/**
 * Set up all event listeners
 */
function setupEventListeners() {
    const initialActiveButton = document.querySelector('.tab-button.active');
    if (initialActiveButton && initialActiveButton.dataset.tab) {
        activeTabName = initialActiveButton.dataset.tab;
    }

    // Tab buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    // Filter buttons
    document.getElementById('apply-filters-button').addEventListener('click', applyFilters);
    document.getElementById('clear-filters-button').addEventListener('click', clearFilters);

    // Refresh button
    const refreshBtn = document.getElementById('refresh-button');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', refreshData);
    }

    // Search button
    document.getElementById('search-button').addEventListener('click', performSearchAction);

    // Clear button
    document.getElementById('clear-search-button').addEventListener('click', clearSearch);

    // Add query button
    document.getElementById('add-query-button').addEventListener('click', addQueryRow);

    // Search on Enter key in query rows (delegate event)
    document.getElementById('query-rows').addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && (e.target.classList.contains('query-value') || e.target.classList.contains('query-field'))) {
            performSearchAction();
        }
    });

    // Page size change (may not exist if using AG Grid's built-in pagination)
    const pageSizeEl = document.getElementById('page-size');
    if (pageSizeEl) {
        pageSizeEl.addEventListener('change', (e) => {
            handlePageSizeChange(e.target.value);
        });
    }

    // Select All button
    const selectAllBtn = document.getElementById('select-all-button');
    if (selectAllBtn) {
        selectAllBtn.addEventListener('click', selectAllRows);
    }

    // Clipboard buttons
    const copyEntryBtn = document.getElementById('copy-entry-id-button');
    const copySampleBtn = document.getElementById('copy-sample-uuid-button');
    if (copyEntryBtn) {
        copyEntryBtn.addEventListener('click', copyEntryIds);
    }
    if (copySampleBtn) {
        copySampleBtn.addEventListener('click', copySampleUuids);
    }

    // Plot Selected button
    const plotSelectedBtn = document.getElementById('plot-selected-btn');
    if (plotSelectedBtn) {
        plotSelectedBtn.addEventListener('click', plotSelected);
    }

    // Gantt Selected button
    const ganttSelectedBtn = document.getElementById('gantt-selected-btn');
    if (ganttSelectedBtn) {
        ganttSelectedBtn.addEventListener('click', ganttSelected);
    }

    // Upload controls
    const uploadFileInput = document.getElementById('upload-file-input');
    const uploadDelimiter = document.getElementById('upload-delimiter');
    const uploadCommentPrefix = document.getElementById('upload-comment-prefix');
    const uploadLastCommentHeader = document.getElementById('upload-last-comment-header');
    const uploadSubmitButton = document.getElementById('upload-submit-button');
    initializeUploadCompositionEditor();

    if (uploadFileInput) {
        uploadFileInput.addEventListener('change', handleUploadFileSelection);
    }
    if (uploadDelimiter) {
        uploadDelimiter.addEventListener('input', handleUploadFileSelection);
    }
    if (uploadCommentPrefix) {
        uploadCommentPrefix.addEventListener('input', handleUploadFileSelection);
    }
    if (uploadLastCommentHeader) {
        uploadLastCommentHeader.addEventListener('change', handleUploadFileSelection);
    }
    if (uploadSubmitButton) {
        uploadSubmitButton.addEventListener('click', submitDatasetUpload);
    }

    // Error close button
    document.getElementById('error-close').addEventListener('click', hideError);

    // Modal close buttons
    document.getElementById('data-modal-close').addEventListener('click', closeModals);
    document.getElementById('metadata-modal-close').addEventListener('click', closeModals);
    document.getElementById('copy-modal-close').addEventListener('click', closeModals);

    // Copy modal button
    document.getElementById('copy-modal-copy-button').addEventListener('click', copyModalTextToClipboard);

    // Close modal on overlay click
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', closeModals);
    });

    // Close modal on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeModals();
        }
    });
}

function refreshDatasource() {
    if (!gridApi) return;
    chronologicalSortCache.key = null;
    chronologicalSortCache.rows = [];
    chronologicalSortCache.totalCount = 0;
    gridApi.setGridOption('datasource', createDatasource());
    gridApi.purgeInfiniteCache();
}

function shouldUseChronologicalEndedSort(sortModel) {
    return Array.isArray(sortModel)
        && sortModel.length === 1
        && sortModel[0]
        && sortModel[0].colId === 'meta_ended'
        && (sortModel[0].sort === 'desc' || sortModel[0].sort === 'asc')
        && (!currentQueries || currentQueries.length === 0)
        && Object.keys(currentFilters || {}).length === 0;
}

function chronologicalCacheKey() {
    return JSON.stringify({
        queries: currentQueries || [],
        filters: currentFilters || {}
    });
}

async function getChronologicallySortedRows(sortModel, signal) {
    const direction = sortModel[0].sort;
    const key = chronologicalCacheKey();
    if (chronologicalSortCache.key === key) {
        const rows = direction === 'asc'
            ? chronologicalSortCache.rows.slice().reverse()
            : chronologicalSortCache.rows;
        return {
            status: 'success',
            rows,
            total_count: chronologicalSortCache.totalCount
        };
    }

    const countResult = await performSearch(currentQueries, 0, 1, [], signal);
    if (countResult.status !== 'success') {
        return countResult;
    }

    const allCount = Number(countResult.total_count || 0);
    if (allCount === 0) {
        chronologicalSortCache.key = key;
        chronologicalSortCache.rows = [];
        chronologicalSortCache.totalCount = 0;
        return {
            status: 'success',
            rows: [],
            total_count: 0
        };
    }

    const descResult = await performSearchPaged(
        currentQueries,
        0,
        allCount,
        [{ colId: 'meta_ended', sort: 'desc' }],
        signal
    );
    if (descResult.status !== 'success') {
        return descResult;
    }

    const ascResult = await performSearchPaged(
        currentQueries,
        0,
        allCount,
        [{ colId: 'meta_ended', sort: 'asc' }],
        signal
    );
    if (ascResult.status !== 'success') {
        return ascResult;
    }

    const mergedById = new Map();
    for (const item of (descResult.data || [])) {
        if (item && item.id) mergedById.set(item.id, item);
    }
    for (const item of (ascResult.data || [])) {
        if (item && item.id && !mergedById.has(item.id)) {
            mergedById.set(item.id, item);
        }
    }

    const rows = transformRows(Array.from(mergedById.values()));
    rows.sort((a, b) => parseDateToTimestamp(b.meta_ended) - parseDateToTimestamp(a.meta_ended));

    chronologicalSortCache.key = key;
    chronologicalSortCache.rows = rows;  // always stored sorted desc
    chronologicalSortCache.totalCount = Math.max(
        Number(descResult.total_count || 0),
        Number(ascResult.total_count || 0),
        rows.length
    );

    const returnRows = direction === 'asc' ? rows.slice().reverse() : rows;
    return {
        status: 'success',
        rows: returnRows,
        total_count: chronologicalSortCache.totalCount
    };
}

function createDatasource() {
    return {
        getRows: async (params) => {
            const sequence = ++searchRequestState.sequence;
            if (searchRequestState.controller) {
                searchRequestState.controller.abort();
            }
            searchRequestState.controller = new AbortController();
            try {
                updateConnectionStatus('loading');
                showLoadingOverlay();
                const effectiveSortModel = (params.sortModel && params.sortModel.length > 0)
                    ? params.sortModel
                    : DEFAULT_SORT_MODEL;

                if (shouldUseChronologicalEndedSort(effectiveSortModel)) {
                    const chronResult = await getChronologicallySortedRows(
                        effectiveSortModel,
                        searchRequestState.controller.signal
                    );
                    if (sequence !== searchRequestState.sequence) {
                        return;
                    }

                    if (chronResult.status === 'success') {
                        showOperationalConnectionStatus();
                        totalCount = chronResult.total_count || 0;
                        updateInfoBar();

                        const start = params.startRow || 0;
                        const end = params.endRow || (start + pageSize);
                        const pagedRows = (chronResult.rows || []).slice(start, end);

                        hideLoadingOverlay();
                        params.successCallback(pagedRows, totalCount);
                    } else if (chronResult.status === 'aborted') {
                        return;
                    } else {
                        updateConnectionStatus('error');
                        showError(chronResult.message || 'Unknown error occurred');
                        hideLoadingOverlay();
                        params.failCallback();
                    }
                    return;
                }

                const result = await performSearch(
                    currentQueries,
                    params.startRow,
                    params.endRow - params.startRow,
                    effectiveSortModel,
                    searchRequestState.controller.signal
                );
                if (sequence !== searchRequestState.sequence) {
                    return;
                }

                if (result.status === 'success') {
                    showOperationalConnectionStatus();
                    const rows = transformRows(result.data || []);
                    totalCount = result.total_count || 0;
                    updateInfoBar();

                    hideLoadingOverlay();
                    params.successCallback(rows, totalCount);
                } else if (result.status === 'aborted') {
                    // Newer request superseded this one.
                    return;
                } else {
                    updateConnectionStatus('error');
                    showError(result.message || 'Unknown error occurred');
                    hideLoadingOverlay();
                    params.failCallback();
                }
            } catch (error) {
                updateConnectionStatus('error');
                showError(`Error loading data: ${error.message}`);
                hideLoadingOverlay();
                params.failCallback();
            }
        }
    };
}

// =============================================================================
// Initialization
// =============================================================================

document.addEventListener('DOMContentLoaded', async () => {
    // Check Tiled configuration
    const configOk = await checkConfig();

    if (!configOk) {
        hideLoadingOverlay();
        return;
    }

    // Lazy-load unique values for filter dropdowns
    loadFilterDropdowns();

    // Add initial query row
    addQueryRow();

    // Set up event listeners
    setupEventListeners();

    // Initialize AG Grid
    initializeGrid();
});
