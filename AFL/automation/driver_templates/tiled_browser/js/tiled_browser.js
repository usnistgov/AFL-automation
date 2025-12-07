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
let currentQueries = [];  // Array of {field, value} query objects
let currentFilters = {};  // Object mapping filter field names to arrays of selected values
let pageSize = 50;
let gridApi = null;
let currentColumns = new Set();
let totalCount = 0;
let multiSelectInstances = {};  // Store multi-select state for each filter

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

// =============================================================================
// Utility Functions
// =============================================================================

/**
 * Get authentication token from cookies for Driver API calls
 */
function getAuthToken() {
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'access_token_cookie') {
            return value;
        }
    }
    return null;
}

/**
 * Wrapper for Driver API calls with JWT token
 */
async function authenticatedFetch(url, options = {}) {
    const token = getAuthToken();
    const headers = { ...options.headers };

    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    return fetch(url, { ...options, headers });
}

/**
 * Wrapper for Tiled API calls with API key header
 */
async function tiledFetch(endpoint, options = {}) {
    if (!tiledConfig) {
        throw new Error('Tiled configuration not loaded');
    }

    const url = tiledConfig.tiled_server + endpoint;
    const headers = {
        'Authorization': `Apikey ${tiledConfig.tiled_api_key}`,
        'Content-Type': 'application/json',
        ...options.headers
    };

    const response = await fetch(url, { ...options, headers });

    if (!response.ok) {
        throw new Error(`Tiled API error: ${response.status} ${response.statusText}`);
    }

    return response.json();
}

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

// =============================================================================
// Configuration Loading
// =============================================================================

/**
 * Load Tiled configuration from Driver backend
 */
async function checkConfig() {
    try {
        updateConnectionStatus('loading');

        const response = await authenticatedFetch('/tiled_config');
        const data = await response.json();

        if (data.status === 'error') {
            showError(data.message);
            updateConnectionStatus('error');
            return false;
        }

        tiledConfig = {
            tiled_server: data.tiled_server,
            tiled_api_key: data.tiled_api_key
        };

        updateConnectionStatus('connected');
        return true;

    } catch (error) {
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
async function performSearch(queries, offset, limit) {
    try {
        // Combine filters and queries
        const allQueries = [...queries];

        // Add filters - for multi-value filters, add each value as a separate query
        // Multiple values for the same field will be OR'd together on the backend
        for (const [field, values] of Object.entries(currentFilters)) {
            if (Array.isArray(values)) {
                // Multi-select: add each value
                values.forEach(value => {
                    if (value) {
                        allQueries.push({ field, value });
                    }
                });
            } else if (values) {
                // Single value
                allQueries.push({ field, value: values });
            }
        }

        // Use proxy endpoint to avoid CORS issues
        const params = new URLSearchParams({
            queries: JSON.stringify(allQueries),
            offset: offset,
            limit: limit
        });

        console.log('Calling /tiled_search with params:', { queries: allQueries, offset, limit });

        const response = await authenticatedFetch(`/tiled_search?${params}`);

        if (!response.ok) {
            console.error('HTTP error response:', response.status, response.statusText);
            throw new Error(`HTTP error: ${response.status}`);
        }

        const result = await response.json();
        console.log('Raw response from /tiled_search:', result);

        if (result.status === 'error') {
            console.error('Error status in response:', result.message);
            return result;
        }

        // Defensive check for data
        if (!result.data) {
            console.error('No data field in response:', result);
            return {
                status: 'error',
                message: 'No data field in server response'
            };
        }

        if (!Array.isArray(result.data)) {
            console.error('Data field is not an array:', typeof result.data, result.data);
            return {
                status: 'error',
                message: `Invalid data format: expected array, got ${typeof result.data}`
            };
        }

        // Extract all unique metadata keys from response
        const allKeys = new Set();
        const items = result.data;

        for (const item of items) {
            const metadata = item.attributes?.metadata || {};
            const keys = extractNestedKeys(metadata);
            keys.forEach(k => allKeys.add(k));
        }

        const finalResult = {
            status: 'success',
            data: items,
            total_count: result.total_count || 0,
            columns: Array.from(allKeys).sort()
        };

        console.log('Returning from performSearch:', finalResult);
        return finalResult;

    } catch (error) {
        console.error('Exception in performSearch:', error);
        return {
            status: 'error',
            message: error.message
        };
    }
}

/**
 * Load xarray Dataset HTML representation for an entry
 */
async function loadData(entryId) {
    try {
        // Use proxy endpoint to avoid CORS issues
        const params = new URLSearchParams({ entry_id: entryId });
        const response = await authenticatedFetch(`/tiled_get_data?${params}`);

        if (!response.ok) {
            throw new Error(`HTTP error: ${response.status}`);
        }

        const result = await response.json();

        if (result.status === 'error') {
            return result;
        }

        return {
            status: 'success',
            html: result.html
        };

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
async function loadMetadata(entryId) {
    try {
        // Use proxy endpoint to avoid CORS issues
        const params = new URLSearchParams({ entry_id: entryId });
        const response = await authenticatedFetch(`/tiled_get_metadata?${params}`);

        if (!response.ok) {
            throw new Error(`HTTP error: ${response.status}`);
        }

        const result = await response.json();

        if (result.status === 'error') {
            return result;
        }

        return {
            status: 'success',
            metadata: result.metadata
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
        const params = new URLSearchParams({ field });
        const response = await authenticatedFetch(`/tiled_get_distinct_values?${params}`);

        if (!response.ok) {
            throw new Error(`HTTP error: ${response.status}`);
        }

        const result = await response.json();

        if (result.status === 'error') {
            return result;
        }

        return {
            status: 'success',
            values: result.values || []
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
        const entryId = this.params.data.id;
        showLoadingInModal('data');

        const result = await loadData(entryId);

        if (result.status === 'success') {
            showDataModal(result.html);
        } else {
            showError(`Failed to load data: ${result.message}`);
            closeModals();
        }
    }

    async onViewMetadata() {
        const entryId = this.params.data.id;
        showLoadingInModal('metadata');

        const result = await loadMetadata(entryId);

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

/**
 * Check if columns have changed and need updating
 */
function columnsChanged(newColumns) {
    if (newColumns.length !== currentColumns.size) return true;

    for (const col of newColumns) {
        if (!currentColumns.has(col)) return true;
    }

    return false;
}

/**
 * Update grid column definitions
 */
function updateColumns(apiColumns) {
    if (!columnsChanged(apiColumns)) return;

    currentColumns = new Set(apiColumns);

    const columnDefs = [
        {
            field: 'id',
            headerName: 'Entry ID',
            pinned: 'left',
            width: 200,
            sortable: false,
            filter: false
        }
    ];

    // Add metadata columns
    for (const col of apiColumns) {
        columnDefs.push({
            field: col,
            headerName: formatHeader(col),
            valueGetter: params => {
                const value = getNestedValue(params.data, col);
                if (value === null || value === undefined) return '-';
                if (typeof value === 'object') return JSON.stringify(value);
                return value;
            },
            sortable: false,
            filter: false,
            width: 150,
            resizable: true
        });
    }

    // Add actions column
    columnDefs.push({
        field: 'actions',
        headerName: 'Actions',
        pinned: 'right',
        width: 220,
        cellRenderer: ActionsRenderer,
        sortable: false,
        filter: false
    });

    gridApi.setGridOption('columnDefs', columnDefs);
}

/**
 * Create infinite datasource for AG Grid (Community edition)
 */
function createDatasource() {
    return {
        getRows: async (params) => {
            const offset = params.startRow;
            const limit = params.endRow - params.startRow;

            updateConnectionStatus('loading');

            const result = await performSearch(currentQueries, offset, limit);

            console.log('performSearch result:', result);

            if (result.status === 'success') {
                updateConnectionStatus('connected');

                // Defensive check for data array
                if (!result.data || !Array.isArray(result.data)) {
                    console.error('Invalid data format:', result);
                    updateConnectionStatus('error');
                    showError('Invalid data format received from server');
                    params.failCallback();
                    hideLoadingOverlay();
                    return;
                }

                // Transform data for grid with specific columns
                const rows = result.data.map(item => {
                    const metadata = item.attributes?.metadata || {};
                    // Check both direct metadata and attrs (Tiled may nest in attrs)
                    const attrs = metadata.attrs || metadata;
                    const meta = attrs.meta || {};

                    return {
                        id: item.id,
                        task_name: attrs.task_name || null,
                        driver_name: attrs.driver_name || null,
                        meta_started: meta.started || null,
                        meta_ended: meta.ended || null,
                        run_time_minutes: meta.run_time_minutes || null,
                        sample_uuid: attrs.sample_uuid || null,
                        sample_name: attrs.sample_name || null,
                        AL_campaign_name: attrs.AL_campaign_name || null,
                        AL_uuid: attrs.AL_uuid || null,
                        AL_components: attrs.AL_components || null,
                        _raw: item
                    };
                });

                // Update total count display
                totalCount = result.total_count || 0;
                updateInfoBar();

                // For infinite row model: lastRow is the total count, or -1 if unknown
                const lastRow = result.total_count <= params.endRow ? result.total_count : -1;
                params.successCallback(rows, lastRow);

            } else {
                updateConnectionStatus('error');
                showError(result.message || 'Unknown error occurred');
                params.failCallback();
            }

            hideLoadingOverlay();
        }
    };
}

/**
 * Initialize AG Grid
 */
function initializeGrid() {
    const gridDiv = document.getElementById('grid-container');

    const gridOptions = {
        columnDefs: [
            {
                field: 'id',
                headerName: 'Entry ID',
                pinned: 'left',
                width: 100,
                checkboxSelection: true
                // Note: headerCheckboxSelection not supported with infinite row model
            },
            { field: 'task_name', headerName: 'Task Name', width: 200 },
            { field: 'driver_name', headerName: 'Driver Name', width: 150 },
            { field: 'meta_started', headerName: 'Started', width: 180 },
            { field: 'meta_ended', headerName: 'Ended', width: 180 },
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
                lockPosition: true
            }
        ],
        defaultColDef: {
            sortable: true,
            filter: false,
            resizable: true
        },
        rowModelType: 'infinite',
        datasource: createDatasource(),
        cacheBlockSize: pageSize,
        maxBlocksInCache: 10,
        cacheOverflowSize: 2,
        maxConcurrentDatasourceRequests: 2,
        infiniteInitialRowCount: 100,
        pagination: true,
        paginationPageSize: pageSize,
        paginationPageSizeSelector: [25, 50, 100, 200],
        animateRows: true,
        rowSelection: 'multiple',
        suppressRowClickSelection: true,
        onGridReady: (params) => {
            gridApi = params.api;
            hideLoadingOverlay();
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
        case 'loading':
            statusEl.classList.add('status-loading');
            textEl.textContent = 'Loading...';
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
 * Close all modals
 */
function closeModals() {
    document.getElementById('data-modal').style.display = 'none';
    document.getElementById('metadata-modal').style.display = 'none';
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
function performSearchAction() {
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

    // Combine filters and queries for search
    if (gridApi) {
        gridApi.updateGridOptions({ datasource: createDatasource() });
    }
}

/**
 * Clear all searches
 */
function clearSearch() {
    // Remove all query rows
    const container = document.getElementById('query-rows');
    container.innerHTML = '';

    // Add one empty row
    addQueryRow();

    // Clear current queries
    currentQueries = [];

    if (gridApi) {
        gridApi.updateGridOptions({ datasource: createDatasource() });
    }
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
    navigator.clipboard.writeText(ids).then(() => {
        showSuccess(`Copied ${selectedRows.length} entry ID(s) to clipboard`);
    }).catch(err => {
        showError(`Failed to copy to clipboard: ${err.message}`);
    });
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

    navigator.clipboard.writeText(uuids).then(() => {
        const count = selectedRows.filter(row => row.sample_uuid).length;
        showSuccess(`Copied ${count} sample UUID(s) to clipboard`);
    }).catch(err => {
        showError(`Failed to copy to clipboard: ${err.message}`);
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

    // Extract entry IDs
    const entryIds = selectedRows.map(row => row.id);

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
    const filterFields = [
        { field: 'driver_name' },
        { field: 'sample_name' },
        { field: 'sample_uuid' },
        { field: 'AL_campaign_name' },
        { field: 'AL_uuid' }
    ];

    for (const { field } of filterFields) {
        const container = document.querySelector(`.multiselect-search-box[data-filter="${field}"]`).parentElement;
        const optionsContainer = container.querySelector('.multiselect-options');

        // Show loading state
        optionsContainer.innerHTML = '<div class="multiselect-loading">Loading...</div>';

        // Load distinct values
        const result = await loadDistinctValues(field);

        if (result.status === 'success') {
            // Initialize multi-select with values
            initMultiSelect(container, field, result.values);
        } else {
            // Show error state
            optionsContainer.innerHTML = '<div class="multiselect-empty">Error loading values</div>';
            console.error(`Failed to load distinct values for ${field}:`, result.message);
        }
    }
}

/**
 * Apply filter selections
 */
function applyFilters() {
    // Clear existing filters
    currentFilters = {};

    // Collect selected filter values from multi-select instances
    for (const [fieldName, state] of Object.entries(multiSelectInstances)) {
        if (state.selectedValues.length > 0) {
            currentFilters[fieldName] = state.selectedValues;
        }
    }

    // Refresh grid with new filters
    if (gridApi) {
        gridApi.updateGridOptions({ datasource: createDatasource() });
    }
}

/**
 * Clear all filter selections
 */
function clearFilters() {
    // Clear all multi-select instances
    for (const [fieldName, state] of Object.entries(multiSelectInstances)) {
        state.selectedValues = [];
        updateMultiSelectUI(fieldName);
    }

    // Clear filter state
    currentFilters = {};

    // Refresh grid
    if (gridApi) {
        gridApi.updateGridOptions({ datasource: createDatasource() });
    }
}

/**
 * Switch between tabs
 */
function switchTab(tabName) {
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
    // Tab buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    // Filter buttons
    document.getElementById('apply-filters-button').addEventListener('click', applyFilters);
    document.getElementById('clear-filters-button').addEventListener('click', clearFilters);

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

    // Error close button
    document.getElementById('error-close').addEventListener('click', hideError);

    // Modal close buttons
    document.getElementById('data-modal-close').addEventListener('click', closeModals);
    document.getElementById('metadata-modal-close').addEventListener('click', closeModals);

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

    // Load unique values for filter dropdowns
    loadFilterDropdowns();

    // Add initial query row
    addQueryRow();

    // Set up event listeners
    setupEventListeners();

    // Initialize AG Grid
    initializeGrid();
});
