/**
 * Tiled Plot Viewer
 *
 * Interactive plotting interface for concatenated Tiled database entries using Plotly.js
 */

// =============================================================================
// State Management
// =============================================================================

let entryIds = [];    // List of entry IDs being plotted

// Enhanced state management for DatasetWidget functionality
const AppState = {
    // Dataset management
    originalDataset: null,       // Immutable reference for reset
    workingDataset: null,         // Current filtered/modified state
    dataIndex: 0,                 // Current sample index (0-based)
    sampleDim: 'index',           // Active sample dimension name
    currentTab: 'plot',           // Active tab (dataset|plot|config)

    // Variable categorization (auto-computed)
    sampleVars: [],               // 1D with sample_dim only
    compVars: [],                 // Multi-D, non-sample dim < 10
    scattVars: [],                // Multi-D, non-sample dim >= 10

    // Plot selections
    scatteringVariables: [],      // Multi-select for overlay
    compositionVariable: null,
    compositionColorVariable: null,

    // Settings
    cmin: 0.0,
    cmax: 1.0,
    colorscale: 'Bluered',
    xmin: 0.001,
    xmax: 1.0,
    logX: true,
    logY: true
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
    if (overlay) {
        overlay.style.display = isLoading ? 'flex' : 'none';
    }
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

        console.log('=== FETCHING DATA ===');
        console.log('URL:', `/tiled_get_combined_plot_data?${params}`);

        const response = await authenticatedFetch(`/tiled_get_combined_plot_data?${params}`);

        console.log('Response status:', response.status);
        console.log('Response headers:', [...response.headers.entries()]);

        if (!response.ok) {
            throw new Error(`HTTP error: ${response.status}`);
        }

        // Get the raw text first to see what we're trying to parse
        const responseText = await response.text();
        console.log('Response length:', responseText.length, 'chars');
        console.log('Response preview:', responseText.substring(0, 500));

        let result;
        try {
            result = JSON.parse(responseText);
            console.log('✓ JSON parse successful');
            console.log('Result keys:', Object.keys(result));
        } catch (parseError) {
            console.error('✗ JSON parse FAILED:', parseError);
            console.error('Error at position:', parseError.message);
            // Try to find the problematic area
            const errorMatch = parseError.message.match(/position (\d+)/);
            if (errorMatch) {
                const pos = parseInt(errorMatch[1]);
                console.error('Context around error:', responseText.substring(Math.max(0, pos - 100), Math.min(responseText.length, pos + 100)));
            }
            throw parseError;
        }

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
// DatasetWidget Functions (Variable Categorization & Data Extraction)
// =============================================================================

/**
 * Categorize variables into sample/composition/scattering based on dimensionality
 * Port of DatasetWidget_Model.split_vars()
 */
function categorizeVariables(dataset, sampleDim) {
    const sampleVars = [];
    const compVars = [];
    const scattVars = [];

    if (!dataset || !dataset.variables) {
        return { sampleVars, compVars, scattVars };
    }

    for (const varName of dataset.variables) {
        const varData = dataset.data[varName];
        if (!varData || varData.error) continue;

        const dims = varData.dims || [];

        // 1D variable with only sample dimension
        if (dims.length === 1 && dims[0] === sampleDim) {
            sampleVars.push(varName);
        }
        // Multi-dimensional
        else if (dims.length >= 2 && dims.includes(sampleDim)) {
            // Find non-sample dimension
            const otherDims = dims.filter(d => d !== sampleDim);
            if (otherDims.length > 0) {
                const otherDimSize = dataset.dim_sizes[otherDims[0]] || 0;
                // Heuristic: <10 = composition, >=10 = scattering
                if (otherDimSize < 10) {
                    compVars.push(varName);
                } else {
                    scattVars.push(varName);
                }
            }
        }
    }

    return { sampleVars, compVars, scattVars };
}

/**
 * Extract scattering data for a specific sample index
 * Port of DatasetWidget_Model.get_scattering()
 */
function getScattering(dataset, varName, index, sampleDim) {
    if (!dataset || !dataset.data || !dataset.data[varName]) {
        return { x: [], y: [] };
    }

    const varData = dataset.data[varName];
    if (varData.error) {
        return { x: [], y: [] };
    }

    const dims = varData.dims || [];
    const values = varData.values;

    if (!Array.isArray(values) || values.length === 0) {
        return { x: [], y: [] };
    }

    // Find sample dimension index
    const sampleDimIdx = dims.indexOf(sampleDim);
    const otherDim = dims.filter(d => d !== sampleDim)[0];

    if (sampleDimIdx === -1) {
        return { x: [], y: [] };
    }

    // Extract slice at index
    let ySlice;
    if (sampleDimIdx === 0) {
        ySlice = values[index] || [];
    } else {
        // Transpose case
        ySlice = values.map(row => Array.isArray(row) ? row[index] : row);
    }

    // Get x coordinate (q-values)
    let xCoord;
    if (otherDim && dataset.coords && dataset.coords[otherDim] && !dataset.coords[otherDim].error) {
        xCoord = dataset.coords[otherDim];
    } else {
        // Fallback to indices
        xCoord = Array.from({ length: ySlice.length }, (_, i) => i);
    }

    return { x: xCoord, y: ySlice };
}

/**
 * Extract composition data for all samples
 * Port of DatasetWidget_Model.get_composition()
 */
function getComposition(dataset, varName, sampleDim) {
    const emptyResult = { x: [], y: [], z: null, xname: 'x', yname: 'y', zname: null };

    if (!dataset || !dataset.data || !dataset.data[varName]) {
        return emptyResult;
    }

    const varData = dataset.data[varName];
    if (varData.error || !Array.isArray(varData.values)) {
        return emptyResult;
    }

    const dims = varData.dims || [];
    const values = varData.values;
    const componentDim = dims.filter(d => d !== sampleDim)[0];

    if (!componentDim) {
        return emptyResult;
    }

    // Get component coordinate names
    let componentCoord = ['x', 'y', 'z'];
    if (dataset.coords && dataset.coords[componentDim] && !dataset.coords[componentDim].error) {
        componentCoord = dataset.coords[componentDim];
    }

    // Assume shape is [sample_dim, component]
    const sampleDimIdx = dims.indexOf(sampleDim);

    // Extract x, y, z columns
    let x, y, z;
    if (sampleDimIdx === 0) {
        // Standard layout [samples, components]
        x = values.map(row => Array.isArray(row) ? row[0] : row);
        y = values.map(row => Array.isArray(row) ? row[1] : 0);
        z = values[0] && values[0].length > 2
            ? values.map(row => Array.isArray(row) ? row[2] : 0)
            : null;
    } else {
        // Transposed layout - less common
        x = Array.isArray(values[0]) ? values[0] : [];
        y = Array.isArray(values[1]) ? values[1] : [];
        z = values.length > 2 && Array.isArray(values[2]) ? values[2] : null;
    }

    return {
        x,
        y,
        z,
        xname: componentCoord[0] || 'x',
        yname: componentCoord[1] || 'y',
        zname: z ? (componentCoord[2] || 'z') : null
    };
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
// DatasetWidget Plotting Functions
// =============================================================================

/**
 * Render scattering plot with multi-trace overlay
 */
function renderScatteringPlot() {
    const scatterVarsSelect = document.getElementById('scatter-vars');
    const selectedVars = Array.from(scatterVarsSelect.selectedOptions).map(opt => opt.value);
    const dataset = AppState.workingDataset;
    const index = AppState.dataIndex;

    if (!dataset || selectedVars.length === 0 || selectedVars[0] === '') {
        Plotly.purge('scattering-plot');
        return;
    }

    const traces = [];

    for (const varName of selectedVars) {
        const { x, y } = getScattering(dataset, varName, index, AppState.sampleDim);

        if (x.length > 0 && y.length > 0) {
            traces.push({
                x: x,
                y: y,
                name: varName,
                type: 'scatter',
                mode: 'markers',
                marker: { size: 4 }
            });
        }
    }

    if (traces.length === 0) {
        Plotly.purge('scattering-plot');
        return;
    }

    const layout = {
        xaxis: {
            title: 'q',
            type: AppState.logX ? 'log' : 'linear',
            range: AppState.logX
                ? [Math.log10(AppState.xmin), Math.log10(AppState.xmax)]
                : [AppState.xmin, AppState.xmax]
        },
        yaxis: {
            title: 'I',
            type: AppState.logY ? 'log' : 'linear'
        },
        autosize: true,
        margin: { t: 10, b: 40, l: 50, r: 10 },
        legend: { yanchor: 'top', xanchor: 'right', y: 0.99, x: 0.99 }
    };

    const config = { responsive: true, displayModeBar: true };
    Plotly.react('scattering-plot', traces, layout, config);
}

/**
 * Render composition plot (2D or 3D) with color mapping
 */
function renderCompositionPlot() {
    const compVar = AppState.compositionVariable;
    const colorVar = AppState.compositionColorVariable;
    const dataset = AppState.workingDataset;

    if (!dataset || !compVar) {
        Plotly.purge('composition-plot');
        return;
    }

    const { x, y, z, xname, yname, zname } = getComposition(dataset, compVar, AppState.sampleDim);

    if (x.length === 0) {
        Plotly.purge('composition-plot');
        return;
    }

    // Get color data
    let colors = null;
    if (colorVar && colorVar !== '' && dataset.data[colorVar] && !dataset.data[colorVar].error) {
        colors = dataset.data[colorVar].values;
        // Auto-set color range
        const validColors = colors.filter(c => c !== null && c !== undefined && !isNaN(c));
        if (validColors.length > 0) {
            AppState.cmin = Math.min(...validColors);
            AppState.cmax = Math.max(...validColors);
            // Update UI
            document.getElementById('cmin').value = AppState.cmin.toFixed(2);
            document.getElementById('cmax').value = AppState.cmax.toFixed(2);
        }
    }
    if (!colors) {
        colors = Array(x.length).fill(0);
    }

    const traces = [];

    if (z) {
        // 3D scatter plot
        traces.push({
            type: 'scatter3d',
            mode: 'markers',
            x: x,
            y: y,
            z: z,
            marker: {
                color: colors,
                showscale: true,
                cmin: AppState.cmin,
                cmax: AppState.cmax,
                colorscale: AppState.colorscale,
                colorbar: { thickness: 15, outlinewidth: 0 },
                size: 4
            },
            customdata: colors,
            hovertemplate: `${xname}: %{x:.2f}<br>${yname}: %{y:.2f}<br>${zname}: %{z:.2f}<br>color: %{customdata:.2f}<extra></extra>`,
            showlegend: false
        });

        // Selected point (highlighted)
        traces.push({
            type: 'scatter3d',
            mode: 'markers',
            x: [x[AppState.dataIndex]],
            y: [y[AppState.dataIndex]],
            z: [z[AppState.dataIndex]],
            marker: {
                color: 'red',
                symbol: 'circle-open',
                size: 10,
                line: { width: 2 }
            },
            hoverinfo: 'skip',
            showlegend: false
        });

        const layout = {
            scene: {
                xaxis: { title: xname },
                yaxis: { title: yname },
                zaxis: { title: zname },
                aspectmode: 'cube'
            },
            autosize: true,
            margin: { t: 10, b: 10, l: 10, r: 10 }
        };

        const config = { responsive: true, displayModeBar: true };
        Plotly.react('composition-plot', traces, layout, config);
    } else {
        // 2D scatter plot
        traces.push({
            type: 'scatter',
            mode: 'markers',
            x: x,
            y: y,
            marker: {
                color: colors,
                showscale: true,
                cmin: AppState.cmin,
                cmax: AppState.cmax,
                colorscale: AppState.colorscale,
                colorbar: { thickness: 15, outlinewidth: 0 },
                size: 6
            },
            customdata: colors,
            hovertemplate: `${xname}: %{x:.2f}<br>${yname}: %{y:.2f}<br>color: %{customdata:.2f}<extra></extra>`,
            showlegend: false
        });

        // Selected point (highlighted)
        traces.push({
            type: 'scatter',
            mode: 'markers',
            x: [x[AppState.dataIndex]],
            y: [y[AppState.dataIndex]],
            marker: {
                color: 'red',
                symbol: 'hexagon-open',
                size: 12,
                line: { width: 2 }
            },
            hoverinfo: 'skip',
            showlegend: false
        });

        const layout = {
            xaxis: { title: xname },
            yaxis: { title: yname },
            autosize: true,
            margin: { t: 10, b: 10, l: 10, r: 10 }
        };

        const config = { responsive: true, displayModeBar: true };
        Plotly.react('composition-plot', traces, layout, config);
    }

    // Attach click handler
    const plotDiv = document.getElementById('composition-plot');
    plotDiv.removeAllListeners && plotDiv.removeAllListeners('plotly_click');
    plotDiv.on('plotly_click', handleCompositionClick);
}

/**
 * Update only the selected point marker (efficient update)
 */
function updateSelectedPoint() {
    const compVar = AppState.compositionVariable;
    const dataset = AppState.workingDataset;

    if (!dataset || !compVar) return;

    const { x, y, z } = getComposition(dataset, compVar, AppState.sampleDim);

    if (x.length === 0) return;

    const update = z ? {
        x: [[x[AppState.dataIndex]]],
        y: [[y[AppState.dataIndex]]],
        z: [[z[AppState.dataIndex]]]
    } : {
        x: [[x[AppState.dataIndex]]],
        y: [[y[AppState.dataIndex]]]
    };

    // Update trace 1 (the selected point marker)
    Plotly.restyle('composition-plot', update, [1]);
}

/**
 * Update color scale in real-time
 */
function updateColorScale() {
    const update = {
        'marker.cmin': AppState.cmin,
        'marker.cmax': AppState.cmax
    };
    Plotly.restyle('composition-plot', update, [0]);
}

/**
 * Update both plots
 */
function updatePlots() {
    renderScatteringPlot();
    updateSelectedPoint();
}

/**
 * Handle click on composition plot to select sample
 */
function handleCompositionClick(data) {
    if (data.points && data.points.length > 0) {
        const pointIndex = data.points[0].pointIndex;
        AppState.dataIndex = pointIndex;

        // Update UI
        document.getElementById('data-index').value = pointIndex;

        // Update both plots
        updatePlots();
    }
}

// =============================================================================
// Tab Navigation
// =============================================================================

/**
 * Switch between tabs
 */
function switchTab(tabName) {
    // Update buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });

    // Update content
    document.querySelectorAll('.tab-content').forEach(content => {
        const contentId = content.id.replace('-tab', '');
        content.classList.toggle('active', contentId === tabName);
    });

    AppState.currentTab = tabName;

    // Resize plots if switching to plot tab
    if (tabName === 'plot') {
        setTimeout(() => {
            Plotly.Plots.resize('scattering-plot');
            Plotly.Plots.resize('composition-plot');
        }, 100);
    }
}

/**
 * Initialize tab navigation
 */
function initializeTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const targetTab = e.target.dataset.tab;
            switchTab(targetTab);
        });
    });

    // Default to 'plot' tab
    switchTab('plot');
}

// =============================================================================
// Sample Navigation
// =============================================================================

/**
 * Navigate to next sample
 */
function nextSample() {
    const maxIndex = (AppState.workingDataset?.dim_sizes[AppState.sampleDim] || 1) - 1;
    if (AppState.dataIndex < maxIndex) {
        AppState.dataIndex++;
        document.getElementById('data-index').value = AppState.dataIndex;
        updatePlots();
    }
}

/**
 * Navigate to previous sample
 */
function prevSample() {
    if (AppState.dataIndex > 0) {
        AppState.dataIndex--;
        document.getElementById('data-index').value = AppState.dataIndex;
        updatePlots();
    }
}

/**
 * Go to specific sample index
 */
function gotoSample() {
    const input = document.getElementById('data-index');
    const index = parseInt(input.value);
    const maxIndex = (AppState.workingDataset?.dim_sizes[AppState.sampleDim] || 1) - 1;

    if (!isNaN(index) && index >= 0 && index <= maxIndex) {
        AppState.dataIndex = index;
        updatePlots();
    } else {
        // Reset to current valid index
        input.value = AppState.dataIndex;
    }
}

/**
 * Initialize navigation controls
 */
function initializeNavigation() {
    document.getElementById('next-sample').addEventListener('click', nextSample);
    document.getElementById('prev-sample').addEventListener('click', prevSample);
    document.getElementById('data-index').addEventListener('change', gotoSample);
}

// =============================================================================
// Data Manipulation Operations
// =============================================================================

/**
 * Update dropdowns after dataset changes
 * Mirrors Python DatasetWidget_View.update_dropdowns()
 */
function updateDropdowns() {
    const dataset = AppState.workingDataset;
    if (!dataset) return;

    // Update scatter vars (1D data variables)
    const scatterSelect = document.getElementById('scatter-vars');
    const prevScatterSelection = Array.from(scatterSelect.selectedOptions).map(o => o.value);
    scatterSelect.innerHTML = AppState.scattVars.map(v =>
        `<option value="${v}">${v}</option>`
    ).join('');
    // Try to restore previous selection, otherwise auto-select first
    if (AppState.scattVars.length > 0) {
        const validPrevSelection = prevScatterSelection.filter(v => AppState.scattVars.includes(v));
        if (validPrevSelection.length > 0) {
            validPrevSelection.forEach(v => {
                const opt = scatterSelect.querySelector(`option[value="${v}"]`);
                if (opt) opt.selected = true;
            });
        } else {
            scatterSelect.selectedIndex = 0;
        }
    }

    // Update composition var dropdown
    const compSelect = document.getElementById('composition-var');
    compSelect.innerHTML = ['<option value="">Select composition...</option>']
        .concat(AppState.compVars.map(v => `<option value="${v}">${v}</option>`))
        .join('');
    
    // Check if current selection is still valid, otherwise pick first available
    if (AppState.compositionVariable && AppState.compVars.includes(AppState.compositionVariable)) {
        compSelect.value = AppState.compositionVariable;
    } else if (AppState.compVars.length > 0) {
        AppState.compositionVariable = AppState.compVars[0];
        compSelect.value = AppState.compositionVariable;
    } else {
        AppState.compositionVariable = null;
        compSelect.value = '';
    }

    // Update composition color dropdown (populated with sample_vars - 1D variables)
    const colorSelect = document.getElementById('composition-color');
    colorSelect.innerHTML = ['<option value="">None</option>']
        .concat(AppState.sampleVars.map(v => `<option value="${v}">${v}</option>`))
        .join('');
    
    // Restore color selection if still valid
    if (AppState.compositionColorVariable && AppState.sampleVars.includes(AppState.compositionColorVariable)) {
        colorSelect.value = AppState.compositionColorVariable;
    } else {
        AppState.compositionColorVariable = null;
        colorSelect.value = '';
    }

    // Update sel dimension dropdown (for filtering operations)
    const selDimSelect = document.getElementById('sel-dim');
    if (dataset.dims) {
        selDimSelect.innerHTML = ['<option value="">Select dimension...</option>']
            .concat(dataset.dims.map(d => `<option value="${d}">${d}</option>`))
            .join('');
    }

    // Update extract from var dropdown
    const extractVarSelect = document.getElementById('extract-from-var');
    extractVarSelect.innerHTML = ['<option value="">Select variable...</option>']
        .concat(AppState.compVars.concat(AppState.scattVars).map(v =>
            `<option value="${v}">${v}</option>`
        )).join('');

    // Update sample dimension selector
    const sampleDimSelect = document.getElementById('sample-dim-select');
    if (dataset.dims) {
        sampleDimSelect.innerHTML = dataset.dims.map(d =>
            `<option value="${d}" ${d === AppState.sampleDim ? 'selected' : ''}>${d}</option>`
        ).join('');
    }

    // Update index display with max index for current sample dimension
    const maxIndex = (dataset.dim_sizes[AppState.sampleDim] || 1) - 1;
    document.getElementById('index-display').textContent = `/ ${maxIndex}`;
    
    console.log('Updated dropdowns:', {
        sampleVars: AppState.sampleVars,
        compVars: AppState.compVars,
        scattVars: AppState.scattVars,
        compositionVariable: AppState.compositionVariable,
        compositionColorVariable: AppState.compositionColorVariable
    });
}

/**
 * Update dataset info HTML display
 */
function updateDatasetHTML() {
    const dataset = AppState.workingDataset;
    const infoContent = document.getElementById('data-info-content');

    if (dataset && dataset.dataset_html) {
        infoContent.innerHTML = dataset.dataset_html;
    } else {
        infoContent.innerHTML = '<p class="info-loading">No dataset information available.</p>';
    }
}

/**
 * Update after dataset changes (re-categorize, update UI)
 */
function updateAfterDataChange() {
    const dataset = AppState.workingDataset;
    if (!dataset) return;

    // Re-categorize variables
    const { sampleVars, compVars, scattVars } = categorizeVariables(dataset, AppState.sampleDim);
    AppState.sampleVars = sampleVars;
    AppState.compVars = compVars;
    AppState.scattVars = scattVars;

    // Update all dropdowns
    updateDropdowns();

    // Update dataset HTML display
    updateDatasetHTML();

    // Reset data index if out of bounds
    const newSize = dataset.dim_sizes[AppState.sampleDim] || 1;
    if (AppState.dataIndex >= newSize) {
        AppState.dataIndex = 0;
        document.getElementById('data-index').value = 0;
    }

    // Update plots
    renderScatteringPlot();
    renderCompositionPlot();
}

/**
 * Reset dataset to original state
 */
function resetDataset() {
    if (!AppState.originalDataset) return;

    // Deep clone original dataset
    AppState.workingDataset = JSON.parse(JSON.stringify(AppState.originalDataset));

    updateAfterDataChange();
}

/**
 * Initialize DatasetWidget event listeners
 */
function initializeDatasetWidgetListeners() {
    // Tab navigation
    initializeTabs();

    // Sample navigation
    initializeNavigation();

    // Plot update button - mirrors Python initialize_plots()
    document.getElementById('update-plot').addEventListener('click', () => {
        // Update settings from config inputs
        AppState.xmin = parseFloat(document.getElementById('xmin-config').value);
        AppState.xmax = parseFloat(document.getElementById('xmax-config').value);
        AppState.logX = document.getElementById('logx-config').checked;
        AppState.logY = document.getElementById('logy-config').checked;
        AppState.colorscale = document.getElementById('colorscale-config').value;

        // Sync dropdown values to AppState before rendering
        AppState.compositionVariable = document.getElementById('composition-var').value || null;
        AppState.compositionColorVariable = document.getElementById('composition-color').value || null;

        console.log('Update Plot clicked:', {
            compositionVariable: AppState.compositionVariable,
            compositionColorVariable: AppState.compositionColorVariable,
            sampleDim: AppState.sampleDim,
            dataIndex: AppState.dataIndex
        });

        renderScatteringPlot();
        renderCompositionPlot();
    });

    // Color range inputs
    document.getElementById('cmin').addEventListener('input', (e) => {
        AppState.cmin = parseFloat(e.target.value);
        updateColorScale();
    });
    document.getElementById('cmax').addEventListener('input', (e) => {
        AppState.cmax = parseFloat(e.target.value);
        updateColorScale();
    });

    // Log scale toggles - instant update
    document.getElementById('logx-config').addEventListener('change', (e) => {
        AppState.logX = e.target.checked;
        renderScatteringPlot();
    });
    document.getElementById('logy-config').addEventListener('change', (e) => {
        AppState.logY = e.target.checked;
        renderScatteringPlot();
    });

    // X-axis range inputs - instant update
    document.getElementById('xmin-config').addEventListener('input', (e) => {
        AppState.xmin = parseFloat(e.target.value);
        renderScatteringPlot();
    });
    document.getElementById('xmax-config').addEventListener('input', (e) => {
        AppState.xmax = parseFloat(e.target.value);
        renderScatteringPlot();
    });

    // Colorscale select - instant update
    document.getElementById('colorscale-config').addEventListener('change', (e) => {
        AppState.colorscale = e.target.value;
        renderCompositionPlot();
    });

    // Composition variable selection
    document.getElementById('composition-var').addEventListener('change', (e) => {
        AppState.compositionVariable = e.target.value;
        renderCompositionPlot();
    });

    // Composition color variable selection
    document.getElementById('composition-color').addEventListener('change', (e) => {
        AppState.compositionColorVariable = e.target.value;
        renderCompositionPlot();
    });

    // Scattering variables selection
    document.getElementById('scatter-vars').addEventListener('change', () => {
        renderScatteringPlot();
    });

    // Sample dimension change - mirrors Python update_sample_dim()
    document.getElementById('sample-dim-select').addEventListener('change', (e) => {
        console.log('Sample dimension changed to:', e.target.value);
        AppState.sampleDim = e.target.value;
        
        // Reset composition selections so new defaults get picked (like Python does)
        AppState.compositionVariable = null;
        AppState.compositionColorVariable = null;
        
        // Reset data index
        AppState.dataIndex = 0;
        document.getElementById('data-index').value = 0;
        
        // Re-categorize variables and update dropdowns
        updateAfterDataChange();
    });

    // Reset dataset button
    document.getElementById('reset-dataset').addEventListener('click', resetDataset);
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
 * Initialize event listeners (for backward compatibility - only elements that still exist)
 */
function initializeEventListeners() {
    // Download dataset button (still exists)
    const downloadBtn = document.getElementById('download-dataset-btn');
    if (downloadBtn) {
        downloadBtn.addEventListener('click', downloadDataset);
    }

    // Error close button (still exists)
    const errorClose = document.getElementById('error-close');
    if (errorClose) {
        errorClose.addEventListener('click', hideError);
    }

    // Old controls are removed in new UI, so skip those event listeners
    // The new DatasetWidget controls are handled in initializeDatasetWidgetListeners()
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
        initializeDatasetWidgetListeners();

        // Load data from server
        const data = await loadCombinedPlotData(entryIds);

        // Initialize AppState with dataset
        AppState.originalDataset = JSON.parse(JSON.stringify(data)); // Deep clone
        AppState.workingDataset = data;

        // Use server-provided sample_dim if available, otherwise detect
        if (data.sample_dim) {
            AppState.sampleDim = data.sample_dim;
            console.log(`Using server-provided sample dimension: ${data.sample_dim}`);
        } else if (data.dims && !data.dims.includes('index')) {
            // Fallback: Auto-detect sample dimension if 'index' doesn't exist
            // Look for dimensions matching *_sample pattern
            const samplePattern = /_sample$/;
            for (const dim of data.dims) {
                if (samplePattern.test(dim)) {
                    AppState.sampleDim = dim;
                    console.log(`Auto-detected sample dimension: ${dim}`);
                    break;
                }
            }
            // If no *_sample pattern found, use first dimension with size > 1
            if (AppState.sampleDim === 'index' && data.dim_sizes) {
                for (const dim of data.dims) {
                    if (data.dim_sizes[dim] > 1) {
                        AppState.sampleDim = dim;
                        console.log(`Using first multi-valued dimension as sample dim: ${dim}`);
                        break;
                    }
                }
            }
        }

        // Categorize variables based on sample dimension
        const { sampleVars, compVars, scattVars } = categorizeVariables(data, AppState.sampleDim);
        AppState.sampleVars = sampleVars;
        AppState.compVars = compVars;
        AppState.scattVars = scattVars;

        console.log('Sample dimension:', AppState.sampleDim);
        console.log('Categorized variables:', { sampleVars, compVars, scattVars });

        // Update dropdowns with categorized variables
        updateDropdowns();

        // Update dataset HTML display
        updateDatasetHTML();

        // Auto-select defaults for composition plot
        if (compVars.length > 0) {
            AppState.compositionVariable = compVars[0];
            document.getElementById('composition-var').value = compVars[0];
        }
        if (sampleVars.length > 0) {
            AppState.compositionColorVariable = sampleVars[0];
            document.getElementById('composition-color').value = sampleVars[0];
        }

        // Render initial plots
        renderScatteringPlot();
        renderCompositionPlot();

        // Also initialize old controls for backward compatibility (commented out for now)
        // initializeControls(data);
        // if (currentConfig.xVariable && currentConfig.yVariable) {
        //     renderPlot();
        // }

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

// Add window resize handler to resize Plotly plots
let resizeTimeout;
window.addEventListener('resize', () => {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(() => {
        // Only resize if plot tab is active
        if (AppState.currentTab === 'plot') {
            const scatteringPlot = document.getElementById('scattering-plot');
            const compositionPlot = document.getElementById('composition-plot');

            if (scatteringPlot && scatteringPlot.data) {
                Plotly.Plots.resize('scattering-plot');
            }
            if (compositionPlot && compositionPlot.data) {
                Plotly.Plots.resize('composition-plot');
            }
        }
    }, 100); // Debounce resize events
});
