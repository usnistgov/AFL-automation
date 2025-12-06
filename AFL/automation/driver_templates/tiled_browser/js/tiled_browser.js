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
let currentQuery = '';
let pageSize = 50;
let gridApi = null;
let currentColumns = new Set();
let totalCount = 0;

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
async function performSearch(query, offset, limit) {
    try {
        // Use proxy endpoint to avoid CORS issues
        const params = new URLSearchParams({
            query: query || '',
            offset: offset,
            limit: limit
        });

        console.log('Calling /tiled_search with params:', { query, offset, limit });

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
        viewDataBtn.textContent = 'View Data';
        viewDataBtn.className = 'action-btn view-data-btn';
        viewDataBtn.onclick = () => this.onViewData();

        const viewMetadataBtn = document.createElement('button');
        viewMetadataBtn.textContent = 'View Metadata';
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

            const result = await performSearch(currentQuery, offset, limit);

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

                // Update columns if needed
                if (result.columns && result.columns.length > 0) {
                    updateColumns(result.columns);
                }

                // Transform data for grid
                const rows = result.data.map(item => ({
                    id: item.id,
                    ...flattenMetadata(item.attributes?.metadata || {}),
                    _raw: item
                }));

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
            { field: 'id', headerName: 'Entry ID', pinned: 'left', width: 200 },
            { field: 'actions', headerName: 'Actions', pinned: 'right', width: 220, cellRenderer: ActionsRenderer }
        ],
        defaultColDef: {
            sortable: false,
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
        animateRows: true,
        rowSelection: 'single',
        onGridReady: (params) => {
            gridApi = params.api;
            hideLoadingOverlay();
        },
        onPaginationChanged: () => {
            updateInfoBar();
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

    if (gridApi) {
        const currentPage = gridApi.paginationGetCurrentPage() + 1;
        const totalPages = gridApi.paginationGetTotalPages();
        document.getElementById('page-info').textContent = `Page ${currentPage} of ${totalPages}`;
    }
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
 * Perform search action
 */
function performSearchAction() {
    currentQuery = document.getElementById('search-input').value;

    if (gridApi) {
        gridApi.setDatasource(createDatasource());
    }
}

/**
 * Clear search
 */
function clearSearch() {
    document.getElementById('search-input').value = '';
    currentQuery = '';

    if (gridApi) {
        gridApi.setDatasource(createDatasource());
    }
}

/**
 * Handle page size change
 */
function handlePageSizeChange(newSize) {
    pageSize = parseInt(newSize);

    if (gridApi) {
        gridApi.setGridOption('paginationPageSize', pageSize);
        gridApi.setGridOption('cacheBlockSize', pageSize);
        gridApi.setDatasource(createDatasource());
    }
}

/**
 * Set up all event listeners
 */
function setupEventListeners() {
    // Search button
    document.getElementById('search-button').addEventListener('click', performSearchAction);

    // Clear button
    document.getElementById('clear-search-button').addEventListener('click', clearSearch);

    // Search on Enter key
    document.getElementById('search-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            performSearchAction();
        }
    });

    // Page size change
    document.getElementById('page-size').addEventListener('change', (e) => {
        handlePageSizeChange(e.target.value);
    });

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

    // Set up event listeners
    setupEventListeners();

    // Initialize AG Grid
    initializeGrid();
});
