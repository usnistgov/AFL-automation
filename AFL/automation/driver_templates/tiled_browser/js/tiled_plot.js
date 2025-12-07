/**
 * Tiled Plot Viewer
 *
 * Interactive plotting interface for concatenated Tiled database entries using Plotly.js
 */

// =============================================================================
// State Management
// =============================================================================

let plotData = null;  // Cached plot data from server
let entryIds = [];    // List of entry IDs being plotted
let legendMultiSelect = null;  // Slim Select instance for legend variable
let currentPlotType = 'line';
let currentConfig = {
    xVariable: null,
    yVariable: null,
    hueDim: 'index',  // Dimension for separating traces
    legendVar: 'sample_name',  // Variable for trace labels
    selectedLegendValues: [],  // Filter which traces to show
    xLogScale: true,
    yLogScale: true,
    markerSize: 6,
    lineWidth: 2,
    colorscale: 'Viridis',
    showLegend: true,
    showGrid: true,
    plotTitle: ''
};

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
 * Show error message
 */
function showError(message) {
    const errorContainer = document.getElementById('error-container');
    const errorText = document.getElementById('error-text');
    errorText.textContent = message;
    errorContainer.style.display = 'block';
}

/**
 * Hide error message
 */
function hideError() {
    document.getElementById('error-container').style.display = 'none';
}

/**
 * Update status indicator
 */
function setStatus(status, text) {
    const indicator = document.getElementById('status-indicator');
    indicator.className = `status-${status}`;
    indicator.querySelector('.status-text').textContent = text;
}

/**
 * Show/hide loading overlay
 */
function setLoading(isLoading) {
    const overlay = document.getElementById('loading-overlay');
    overlay.style.display = isLoading ? 'flex' : 'none';
}

// =============================================================================
// Data Loading
// =============================================================================

/**
 * Load combined plot data from server
 */
async function loadCombinedPlotData(entryIdsList) {
    try {
        setLoading(true);
        setStatus('loading', 'Loading data...');

        const params = new URLSearchParams({
            entry_ids: JSON.stringify(entryIdsList)
        });

        const response = await authenticatedFetch(`/tiled_get_combined_plot_data?${params}`);

        if (!response.ok) {
            throw new Error(`HTTP error: ${response.status}`);
        }

        const result = await response.json();

        if (result.status === 'error') {
            throw new Error(result.message);
        }

        plotData = result;
        setStatus('success', `Loaded ${result.num_datasets} dataset(s)`);

        // Update dataset count
        document.getElementById('dataset-count').textContent =
            `${result.num_datasets} dataset(s) concatenated`;

        // Enable download button
        document.getElementById('download-dataset-btn').disabled = false;

        return result;

    } catch (error) {
        setStatus('error', 'Error loading data');
        throw error;
    } finally {
        setLoading(false);
    }
}

// =============================================================================
// UI Initialization
// =============================================================================

/**
 * Initialize UI controls based on loaded data
 */
function initializeControls(data) {
    const xSelect = document.getElementById('x-variable');
    const ySelect = document.getElementById('y-variable');
    const legendSelect = document.getElementById('legend-variable');
    const hueDimSelect = document.getElementById('hue-dim');

    // Clear existing options (except first placeholder)
    xSelect.innerHTML = '<option value="">Select variable...</option>';
    ySelect.innerHTML = '<option value="">Select variable...</option>';
    legendSelect.innerHTML = '';

    // Populate with dataset variables and coordinates
    const allOptions = new Set();

    // Add coordinates and dimensions as options
    if (data.coords) {
        Object.keys(data.coords).forEach(coord => {
            // Only add if not an error object
            if (!data.coords[coord].error) {
                allOptions.add(coord);
            }
        });
    }

    // Add data variables as options
    if (data.variables) {
        data.variables.forEach(variable => {
            const varData = data.data[variable];
            // Only add if accessible (not error or too large)
            if (varData && !varData.error) {
                allOptions.add(variable);
            }
        });
    }

    // Sort and populate dropdowns
    const sortedOptions = Array.from(allOptions).sort();
    sortedOptions.forEach(option => {
        // X axis
        const xOpt = document.createElement('option');
        xOpt.value = option;
        xOpt.textContent = option;
        xSelect.appendChild(xOpt);

        // Y axis
        const yOpt = document.createElement('option');
        yOpt.value = option;
        yOpt.textContent = option;
        ySelect.appendChild(yOpt);
    });

    // Populate legend variable multi-select with variables that have hue dimension
    const legendOptions = [];

    // Always add 'index' first as the default
    legendOptions.push({
        text: 'index',
        value: 'index',
        selected: true
    });

    // Add other variables that have the hue dimension
    if (data.available_legend_vars) {
        data.available_legend_vars.forEach(varName => {
            // Skip 'index' since we already added it first
            if (varName !== 'index') {
                legendOptions.push({
                    text: varName,
                    value: varName
                });
            }
        });
    }

    // Initialize Slim Select for legend variable
    if (legendMultiSelect) {
        legendMultiSelect.destroy();
    }

    legendMultiSelect = new SlimSelect({
        select: '#legend-variable',
        settings: {
            placeholderText: 'Select legend labels...',
            searchText: 'No results',
            searchPlaceholder: 'Search...',
            searchHighlight: true,
            allowDeselect: false  // Always require at least one selection
        },
        data: legendOptions
    });

    // Auto-select default legend variable
    autoSelectDefaults(data, xSelect, ySelect);

    // Populate hue dimension select
    if (data.dims) {
        hueDimSelect.innerHTML = '';
        data.dims.forEach(dim => {
            const opt = document.createElement('option');
            opt.value = dim;
            opt.textContent = dim;
            if (dim === 'index') {
                opt.selected = true;
            }
            hueDimSelect.appendChild(opt);
        });
    }

    // Update data info panel
    updateDataInfo(data);
}

/**
 * Auto-select sensible default variables
 */
function autoSelectDefaults(data, xSelect, ySelect) {
    // Common x-axis names (prioritized)
    const xPreferences = ['q', 'Q', 'SAXS_q', 'USAXS_q', 'x', 'time', 'wavelength', 'energy'];
    // Common y-axis names (prioritized)
    const yPreferences = ['I', 'intensity', 'SAXS_I', 'USAXS_I', 'y', 'counts', 'signal'];

    // Try to find preferred x variable
    for (const pref of xPreferences) {
        if (data.coords && data.coords[pref] && !data.coords[pref].error) {
            xSelect.value = pref;
            currentConfig.xVariable = pref;
            break;
        }
    }

    // Try to find preferred y variable
    for (const pref of yPreferences) {
        if (data.data && data.data[pref] && !data.data[pref].error) {
            ySelect.value = pref;
            currentConfig.yVariable = pref;
            break;
        }
    }

    // If nothing selected, use first available options
    if (!currentConfig.xVariable && xSelect.options.length > 1) {
        xSelect.selectedIndex = 1;
        currentConfig.xVariable = xSelect.value;
    }
    if (!currentConfig.yVariable && ySelect.options.length > 1) {
        ySelect.selectedIndex = 1;
        currentConfig.yVariable = ySelect.value;
    }

    // Use integer indices for legend
    currentConfig.legendVar = 'index';
}

/**
 * Update data information panel
 */
function updateDataInfo(data) {
    const infoContent = document.getElementById('data-info-content');

    // Display the interactive HTML representation from xarray
    if (data.dataset_html) {
        infoContent.innerHTML = data.dataset_html;
    } else {
        infoContent.innerHTML = '<p class="info-loading">No dataset information available.</p>';
    }
}

// =============================================================================
// Plotting Functions
// =============================================================================

/**
 * Extract data for plotting
 */
function extractPlotData(xVar, yVar, hueDim, legendVar, selectedLegendValues) {
    if (!plotData) {
        console.error('No plot data available');
        return null;
    }

    // Get x data (coordinate or data variable)
    let xData;
    if (plotData.coords && plotData.coords[xVar] && !plotData.coords[xVar].error) {
        xData = plotData.coords[xVar];
    } else if (plotData.data && plotData.data[xVar] && !plotData.data[xVar].error) {
        xData = plotData.data[xVar].values;
    } else {
        console.error(`Could not find x variable: ${xVar}`, plotData);
        return null;
    }

    // Get y data (data variable)
    let yData, yDims;
    if (plotData.data && plotData.data[yVar] && !plotData.data[yVar].error) {
        yData = plotData.data[yVar].values;
        yDims = plotData.data[yVar].dims;
    } else {
        console.error(`Could not find y variable: ${yVar}`, plotData);
        return null;
    }

    // Get legend data if specified
    let legendData = null;
    if (legendVar) {
        // Special case: 'index' means use integer indices
        if (legendVar === 'index') {
            legendData = null;  // Will use integer indices below
        } else if (plotData.data && plotData.data[legendVar] && !plotData.data[legendVar].error) {
            legendData = plotData.data[legendVar].values;
        } else if (plotData.coords && plotData.coords[legendVar] && !plotData.coords[legendVar].error) {
            // Also check coordinates
            legendData = plotData.coords[legendVar];
        }
    }

    // If y data has multiple dimensions, need to separate by hue dimension
    if (yDims && yDims.includes(hueDim)) {
        // Split into traces based on hue dimension
        const hueDimIndex = yDims.indexOf(hueDim);
        const numTraces = plotData.dim_sizes[hueDim] || 1;

        const traces = [];
        for (let i = 0; i < numTraces; i++) {
            // Extract slice for this trace
            let ySlice;
            if (hueDimIndex === 0) {
                ySlice = yData[i];
            } else if (hueDimIndex === 1 && Array.isArray(yData[0])) {
                ySlice = yData.map(row => row[i]);
            } else {
                // More complex indexing - flatten if needed
                ySlice = yData;
            }

            // Get legend label
            let traceName;
            if (legendData) {
                if (Array.isArray(legendData)) {
                    traceName = String(legendData[i] || `Trace ${i}`);
                } else {
                    traceName = String(legendData);
                }
            } else {
                // Use integer index as the label
                traceName = String(i);
            }

            // Filter by selected legend values if any
            if (selectedLegendValues.length > 0 && !selectedLegendValues.includes(traceName)) {
                console.log(`Filtering out trace ${traceName}, not in selected values:`, selectedLegendValues);
                continue;
            }

            traces.push({
                x: xData,
                y: ySlice,
                name: traceName
            });
        }

        if (traces.length === 0) {
            console.error('All traces were filtered out. Selected legend values:', selectedLegendValues, 'Available trace names:',
                Array.from({length: numTraces}, (_, i) => {
                    if (legendData && Array.isArray(legendData)) {
                        return String(legendData[i] || `Trace ${i}`);
                    } else if (legendData) {
                        return String(legendData);
                    } else {
                        return String(i);
                    }
                }));
        }

        return traces;
    } else {
        // Single trace
        const traceName = legendVar && legendData ? String(legendData) : 'Data';
        return [{
            x: xData,
            y: yData,
            name: traceName
        }];
    }
}

/**
 * Create Plotly traces based on plot type
 */
function createTraces(plotType, dataGroups, config) {
    const traces = [];

    if (plotType === 'heatmap') {
        // For heatmap, use first data group and create 2D trace
        if (dataGroups.length > 0) {
            const data = dataGroups[0];
            traces.push({
                x: data.x,
                y: data.y,
                z: Array.isArray(data.y[0]) ? data.y : [data.y],
                type: 'heatmap',
                colorscale: config.colorscale,
                colorbar: {
                    title: config.yVariable || 'Intensity'
                }
            });
        }
    } else {
        // Line or scatter plots - multiple traces
        dataGroups.forEach((data, idx) => {
            const trace = {
                x: data.x,
                y: data.y,
                name: data.name,
                type: 'scatter'
            };

            if (plotType === 'line') {
                trace.mode = 'lines';
                trace.line = {
                    width: config.lineWidth
                };
            } else if (plotType === 'scatter') {
                trace.mode = 'markers';
                trace.marker = {
                    size: config.markerSize
                };
            }

            traces.push(trace);
        });
    }

    return traces;
}

/**
 * Create Plotly layout
 */
function createLayout(config) {
    const layout = {
        title: config.plotTitle || `${config.yVariable} vs ${config.xVariable}`,
        xaxis: {
            title: config.xVariable || 'X',
            type: config.xLogScale ? 'log' : 'linear',
            showgrid: config.showGrid
        },
        yaxis: {
            title: config.yVariable || 'Y',
            type: config.yLogScale ? 'log' : 'linear',
            showgrid: config.showGrid
        },
        showlegend: config.showLegend,
        hovermode: 'closest',
        autosize: true,
        margin: { l: 60, r: 40, t: 60, b: 60 }
    };

    return layout;
}

/**
 * Render the plot
 */
function renderPlot() {
    if (!currentConfig.xVariable || !currentConfig.yVariable) {
        showError('Please select both X and Y variables');
        return;
    }

    hideError();

    const extracted = extractPlotData(
        currentConfig.xVariable,
        currentConfig.yVariable,
        currentConfig.hueDim,
        currentConfig.legendVar,
        currentConfig.selectedLegendValues
    );

    if (!extracted || extracted.length === 0) {
        showError('Could not extract plot data. Check variable selections.');
        return;
    }

    const traces = createTraces(
        currentPlotType,
        extracted,
        currentConfig
    );

    const layout = createLayout(currentConfig);

    const plotConfig = {
        responsive: true,
        displayModeBar: true,
        modeBarButtonsToRemove: ['lasso2d', 'select2d'],
        toImageButtonOptions: {
            format: 'png',
            filename: `tiled_plot_${new Date().toISOString().slice(0,10)}`,
            height: 1000,
            width: 1400,
            scale: 2
        }
    };

    Plotly.newPlot('plot', traces, layout, plotConfig);
}

// =============================================================================
// Event Handlers
// =============================================================================

/**
 * Update current config from UI controls
 */
function updateConfigFromUI() {
    currentConfig.xVariable = document.getElementById('x-variable').value;
    currentConfig.yVariable = document.getElementById('y-variable').value;
    currentConfig.hueDim = document.getElementById('hue-dim').value;
    currentConfig.xLogScale = document.getElementById('x-log-scale').checked;
    currentConfig.yLogScale = document.getElementById('y-log-scale').checked;
    currentConfig.markerSize = parseInt(document.getElementById('marker-size').value);
    currentConfig.lineWidth = parseFloat(document.getElementById('line-width').value);
    currentConfig.colorscale = document.getElementById('colorscale').value;
    currentConfig.showLegend = document.getElementById('show-legend').checked;
    currentConfig.showGrid = document.getElementById('show-grid').checked;
    currentConfig.plotTitle = document.getElementById('plot-title').value;

    currentPlotType = document.getElementById('plot-type').value;

    // Get selected legend variable from Slim Select
    if (legendMultiSelect) {
        const selected = legendMultiSelect.getSelected();
        // Use the selected variable name as the legend variable
        if (selected.length > 0) {
            currentConfig.legendVar = selected[0];
        }
    }

    // For now, don't filter traces - show all
    currentConfig.selectedLegendValues = [];
}

/**
 * Download concatenated dataset
 */
async function downloadDataset() {
    try {
        const btn = document.getElementById('download-dataset-btn');
        btn.disabled = true;
        btn.textContent = 'Downloading...';

        const params = new URLSearchParams({
            entry_ids: JSON.stringify(entryIds)
        });

        const response = await authenticatedFetch(`/tiled_download_combined_dataset?${params}`);

        if (!response.ok) {
            throw new Error(`HTTP error: ${response.status}`);
        }

        // Get filename from Content-Disposition header if available
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = 'combined_dataset.nc';
        if (contentDisposition) {
            const matches = /filename="(.+)"/.exec(contentDisposition);
            if (matches) {
                filename = matches[1];
            }
        }

        // Download the file
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

    } catch (error) {
        console.error('Download error:', error);
        showError(`Failed to download dataset: ${error.message}`);
    } finally {
        const btn = document.getElementById('download-dataset-btn');
        btn.disabled = false;
        btn.textContent = 'Download Dataset';
    }
}

/**
 * Initialize event listeners
 */
function initializeEventListeners() {
    // Update plot button
    document.getElementById('update-plot-btn').addEventListener('click', () => {
        updateConfigFromUI();
        renderPlot();
    });

    // Download dataset button
    document.getElementById('download-dataset-btn').addEventListener('click', downloadDataset);

    // Advanced controls toggle
    document.getElementById('advanced-controls-header').addEventListener('click', () => {
        const advancedSection = document.getElementById('advanced-controls');
        const expandIcon = document.querySelector('.expand-icon');

        if (advancedSection.style.display === 'none') {
            advancedSection.style.display = 'flex';
            expandIcon.textContent = '▼';
        } else {
            advancedSection.style.display = 'none';
            expandIcon.textContent = '►';
        }
    });

    // Error close button
    document.getElementById('error-close').addEventListener('click', hideError);

    // Plot type change - update relevant controls
    document.getElementById('plot-type').addEventListener('change', (e) => {
        const plotType = e.target.value;
        const legendGroup = document.getElementById('legend-variable').closest('.control-group');
        const markerGroup = document.getElementById('marker-size').closest('.control-group');
        const lineGroup = document.getElementById('line-width').closest('.control-group');

        if (plotType === 'heatmap') {
            // Hide marker and line controls for heatmap
            if (markerGroup) markerGroup.style.display = 'none';
            if (lineGroup) lineGroup.style.display = 'none';
            if (legendGroup) legendGroup.style.display = 'none';
        } else if (plotType === 'scatter') {
            if (markerGroup) markerGroup.style.display = 'flex';
            if (lineGroup) lineGroup.style.display = 'none';
            if (legendGroup) legendGroup.style.display = 'flex';
        } else if (plotType === 'line') {
            if (markerGroup) markerGroup.style.display = 'none';
            if (lineGroup) lineGroup.style.display = 'flex';
            if (legendGroup) legendGroup.style.display = 'flex';
        }
    });
}

// =============================================================================
// Initialization
// =============================================================================

/**
 * Main initialization function
 */
async function initialize() {
    try {
        // Get entry IDs from URL params or sessionStorage
        const urlParams = new URLSearchParams(window.location.search);
        const urlEntryIds = urlParams.get('entry_ids');

        if (urlEntryIds) {
            try {
                entryIds = JSON.parse(decodeURIComponent(urlEntryIds));
            } catch (e) {
                throw new Error('Invalid entry_ids in URL');
            }
        } else {
            // Try sessionStorage
            const storedIds = sessionStorage.getItem('plotEntryIds');
            if (storedIds) {
                entryIds = JSON.parse(storedIds);
                // Clear from sessionStorage
                sessionStorage.removeItem('plotEntryIds');
            } else {
                throw new Error('No entry IDs provided');
            }
        }

        if (!entryIds || entryIds.length === 0) {
            throw new Error('No entry IDs specified');
        }

        // Initialize event listeners
        initializeEventListeners();

        // Load data from server
        const data = await loadCombinedPlotData(entryIds);

        // Initialize controls with loaded data
        initializeControls(data);

        // Render initial plot if we have defaults
        if (currentConfig.xVariable && currentConfig.yVariable) {
            renderPlot();
        }

    } catch (error) {
        console.error('Initialization error:', error);
        showError(`Failed to initialize: ${error.message}`);
        setStatus('error', 'Initialization failed');
    }
}

// Run initialization when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize);
} else {
    initialize();
}
