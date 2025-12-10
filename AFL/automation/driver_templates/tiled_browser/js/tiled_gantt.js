// ============================================================================
// Tiled Gantt Chart Application
// ============================================================================

// ============= State Management =============
let entryIds = [];

const AppState = {
    rawData: null,              // Combined plot data from backend
    currentColorScheme: 'driver_name',
    ganttData: null             // Processed Gantt traces
};

// ============= Utility Functions =============

/**
 * Get JWT auth token from localStorage
 */
function getAuthToken() {
    return localStorage.getItem('tiled_auth_token');
}

/**
 * Authenticated fetch wrapper
 */
async function authenticatedFetch(url, options = {}) {
    const token = getAuthToken();
    if (token) {
        options.headers = options.headers || {};
        options.headers['Authorization'] = `Bearer ${token}`;
    }
    const response = await fetch(url, options);
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    return response;
}

/**
 * Show error message
 */
function showError(message) {
    const container = document.getElementById('error-container');
    const textEl = document.getElementById('error-text');
    textEl.textContent = message;
    container.style.display = 'block';
    hideLoading();
}

/**
 * Show/hide loading overlay
 */
function showLoading() {
    document.getElementById('loading-overlay').style.display = 'flex';
}

function hideLoading() {
    document.getElementById('loading-overlay').style.display = 'none';
}

// ============= Data Loading =============

/**
 * Load Gantt metadata from backend
 */
async function loadGanttMetadata(entryIdsList) {
    console.log('=== LOADING GANTT METADATA ===');
    console.log('Entry IDs:', entryIdsList);

    const params = new URLSearchParams({
        entry_ids: JSON.stringify(entryIdsList)
    });

    console.log('Request URL:', `/tiled_get_gantt_metadata?${params}`);

    const response = await authenticatedFetch(
        `/tiled_get_gantt_metadata?${params}`
    );

    const text = await response.text();
    console.log('Response text (first 1000 chars):', text.substring(0, 1000));

    const result = JSON.parse(text);
    console.log('Parsed result:', result);
    console.log('Result status:', result.status);
    console.log('Result metadata:', result.metadata);

    if (result.status === 'error') {
        throw new Error(result.message || 'Failed to load metadata');
    }

    return result;
}

// ============= Date Parsing =============

/**
 * Parse custom date format: "MM/DD/YY HH:MM:SS-microseconds TIMEZONE±OFFSET"
 * Returns Unix timestamp in milliseconds
 */
function parseCustomDate(dateString) {
    if (!dateString || typeof dateString !== 'string') return 0;

    // Trim whitespace from the date string
    dateString = dateString.trim();

    try {
        const regex = /^(\d{2})\/(\d{2})\/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})(?:-(\d+))?\s*([A-Z]+)?([+-]\d{4})?/;
        const match = dateString.match(regex);

        if (!match) {
            console.warn('Invalid date format:', dateString);
            return 0;
        }

        const [_, month, day, year, hours, minutes, seconds, microseconds, tzName, tzOffset] = match;

        // Convert 2-digit year to 4-digit
        const fullYear = 2000 + parseInt(year, 10);

        // Create Date in UTC
        const date = new Date(Date.UTC(
            fullYear,
            parseInt(month, 10) - 1,
            parseInt(day, 10),
            parseInt(hours, 10),
            parseInt(minutes, 10),
            parseInt(seconds, 10)
        ));

        // Add microseconds (first 3 digits as milliseconds)
        if (microseconds) {
            const ms = parseInt(microseconds.substring(0, 3), 10);
            date.setUTCMilliseconds(ms);
        }

        // Adjust for timezone offset
        if (tzOffset) {
            const sign = tzOffset[0] === '+' ? 1 : -1;
            const offsetHours = parseInt(tzOffset.substring(1, 3), 10);
            const offsetMinutes = parseInt(tzOffset.substring(3, 5), 10);
            const totalOffsetMs = sign * (offsetHours * 60 + offsetMinutes) * 60 * 1000;
            return date.getTime() - totalOffsetMs;
        }

        return date.getTime();
    } catch (error) {
        console.error('Error parsing date:', dateString, error);
        return 0;
    }
}

/**
 * Format date for display in hover text
 */
function formatDateForDisplay(dateString) {
    if (!dateString) return 'N/A';

    const timestamp = parseCustomDate(dateString);
    if (timestamp === 0) return dateString;

    const date = new Date(timestamp);
    return date.toISOString().replace('T', ' ').substring(0, 19);
}

// ============= Color Generation =============

/**
 * Generate color map for categorical values
 */
function generateColorMap(rows, colorScheme) {
    const uniqueValues = [...new Set(rows.map(row => row[colorScheme] || 'Unknown'))].sort();

    const colorPalette = [
        'rgb(31, 119, 180)',   'rgb(255, 127, 14)',  'rgb(44, 160, 44)',
        'rgb(214, 39, 40)',    'rgb(148, 103, 189)', 'rgb(140, 86, 75)',
        'rgb(227, 119, 194)',  'rgb(127, 127, 127)', 'rgb(188, 189, 34)',
        'rgb(23, 190, 207)',   'rgb(174, 199, 232)', 'rgb(255, 187, 120)',
        'rgb(152, 223, 138)',  'rgb(255, 152, 150)', 'rgb(197, 176, 213)'
    ];

    const colorMap = {};

    uniqueValues.forEach((value, index) => {
        if (index < colorPalette.length) {
            colorMap[value] = colorPalette[index];
        } else {
            const hue = (index * 137.5) % 360;
            colorMap[value] = `hsl(${hue}, 70%, 50%)`;
        }
    });

    return colorMap;
}

// ============= Gantt Data Processing =============

/**
 * Extract task data from Gantt metadata response
 */
function extractTaskData(ganttData) {
    const tasks = [];

    console.log('=== EXTRACTING TASK DATA ===');
    console.log('Gantt data structure:', ganttData);
    console.log('Metadata array:', ganttData.metadata);

    // Get metadata array directly
    const metadata = ganttData.metadata || [];

    if (!metadata || metadata.length === 0) {
        console.error('No metadata found in ganttData');
        console.log('Available keys in ganttData:', Object.keys(ganttData));
        return tasks;
    }

    metadata.forEach((entryMeta, index) => {
        console.log(`\n--- Processing entry ${index} ---`);
        console.log('Entry metadata:', entryMeta);

        // The backend returns:
        // - Top level: driver_name, task_name, sample_name, etc.
        // - Nested meta object: started, ended, run_time_minutes
        const meta = entryMeta.meta || {};
        console.log('Meta object:', meta);
        console.log('Meta keys:', Object.keys(meta));

        // Extract timing data from nested meta object
        const metaStarted = meta.started || null;
        const metaEnded = meta.ended || null;
        const runTimeMinutes = meta.run_time_minutes || 0;

        console.log('Extracted fields:', {
            driver_name: entryMeta.driver_name,
            task_name: entryMeta.task_name,
            meta_started: metaStarted,
            meta_ended: metaEnded,
            run_time_minutes: runTimeMinutes
        });

        const task = {
            entry_id: entryMeta.entry_id || `entry_${index}`,
            driver_name: entryMeta.driver_name || 'Unknown',  // Top level
            task_name: entryMeta.task_name || 'Unknown',      // Top level
            sample_name: entryMeta.sample_name || 'N/A',
            sample_uuid: entryMeta.sample_uuid || 'N/A',
            AL_campaign_name: entryMeta.AL_campaign_name || 'N/A',
            meta_started: metaStarted,      // From nested meta
            meta_ended: metaEnded,          // From nested meta
            run_time_minutes: runTimeMinutes  // From nested meta
        };

        console.log('Created task:', task);
        tasks.push(task);
    });

    console.log('\n=== FINAL TASKS ARRAY ===');
    console.log('Total tasks:', tasks.length);
    console.log('Tasks:', tasks);

    return tasks;
}

/**
 * Prepare Gantt chart data structure
 */
function prepareGanttData(tasks, colorScheme) {
    console.log('\n=== PREPARING GANTT DATA ===');
    console.log('Input tasks count:', tasks.length);
    console.log('Color scheme:', colorScheme);

    // Filter valid tasks with detailed logging
    const validTasks = tasks.filter((task, index) => {
        const isValid = task.meta_started && task.meta_ended && task.driver_name;

        if (!isValid) {
            console.warn(`Task ${index} filtered out:`, {
                entry_id: task.entry_id,
                has_meta_started: !!task.meta_started,
                has_meta_ended: !!task.meta_ended,
                has_driver_name: !!task.driver_name,
                meta_started: task.meta_started,
                meta_ended: task.meta_ended,
                driver_name: task.driver_name
            });
        }

        return isValid;
    });

    console.log('Valid tasks count:', validTasks.length);
    console.log('Valid tasks:', validTasks);

    if (validTasks.length === 0) {
        console.error('No valid tasks found!');
        console.error('Original tasks:', tasks);
        throw new Error('No valid tasks with timing data found. Check console for details.');
    }

    // Group by driver_name
    const driverGroups = {};
    validTasks.forEach(task => {
        const driver = task.driver_name;
        if (!driverGroups[driver]) {
            driverGroups[driver] = [];
        }
        driverGroups[driver].push(task);
    });

    // Sort drivers chronologically
    const sortedDrivers = Object.keys(driverGroups).sort((a, b) => {
        const aMin = Math.min(...driverGroups[a].map(t => parseCustomDate(t.meta_started)));
        const bMin = Math.min(...driverGroups[b].map(t => parseCustomDate(t.meta_started)));
        return aMin - bMin;
    });

    // Generate color map
    const colorMap = generateColorMap(validTasks, colorScheme);

    // Create traces
    const traces = [];

    sortedDrivers.forEach(driver => {
        const driverTasks = driverGroups[driver];

        // Group by color scheme value
        const colorGroups = {};
        driverTasks.forEach(task => {
            const colorKey = task[colorScheme] || 'Unknown';
            if (!colorGroups[colorKey]) {
                colorGroups[colorKey] = [];
            }
            colorGroups[colorKey].push(task);
        });

        // Create one trace per color group
        Object.entries(colorGroups).forEach(([colorKey, groupTasks]) => {
            const baseValues = [];
            const durations = [];
            const yValues = [];
            const customData = [];

            groupTasks.forEach(task => {
                const startTime = parseCustomDate(task.meta_started);
                const endTime = parseCustomDate(task.meta_ended);
                const duration = endTime - startTime;

                console.log(`  Task ${task.entry_id}:`, {
                    meta_started: task.meta_started,
                    meta_ended: task.meta_ended,
                    startTime: startTime,
                    endTime: endTime,
                    duration: duration,
                    isValid: startTime > 0 && endTime > 0 && duration > 0
                });

                if (startTime > 0 && endTime > 0 && duration > 0) {
                    baseValues.push(new Date(startTime));
                    durations.push(duration);
                    yValues.push(driver);
                    customData.push({
                        driver_name: task.driver_name,
                        task_name: task.task_name,
                        sample_name: task.sample_name,
                        entry_id: task.entry_id,
                        start_time: formatDateForDisplay(task.meta_started),
                        end_time: formatDateForDisplay(task.meta_ended),
                        duration: task.run_time_minutes
                    });
                }
            });

            if (baseValues.length > 0) {
                const trace = {
                    type: 'bar',
                    orientation: 'h',
                    base: baseValues,
                    x: durations,
                    y: yValues,
                    name: colorKey,
                    marker: {
                        color: colorMap[colorKey],
                        line: { width: 1, color: 'white' }
                    },
                    customdata: customData,
                    hovertemplate:
                        '<b>Driver:</b> %{customdata.driver_name}<br>' +
                        '<b>Task:</b> %{customdata.task_name}<br>' +
                        '<b>Sample:</b> %{customdata.sample_name}<br>' +
                        '<b>Entry ID:</b> %{customdata.entry_id}<br>' +
                        '<b>Started:</b> %{customdata.start_time}<br>' +
                        '<b>Ended:</b> %{customdata.end_time}<br>' +
                        '<b>Duration:</b> %{customdata.duration} min<extra></extra>',
                    showlegend: true,
                    legendgroup: colorKey
                };

                console.log(`Adding trace for driver="${driver}", color="${colorKey}":`, {
                    numBars: baseValues.length,
                    baseValues: baseValues,
                    durations: durations,
                    yValues: yValues
                });

                traces.push(trace);
            }
        });
    });

    console.log(`\n=== FINAL TRACES ===`);
    console.log(`Total traces: ${traces.length}`);
    console.log(`Sorted drivers: ${sortedDrivers}`);
    traces.forEach((trace, idx) => {
        console.log(`Trace ${idx}: name="${trace.name}", bars=${trace.x.length}`);
    });

    return { traces, sortedDrivers };
}

/**
 * Calculate chart height based on number of drivers
 */
function calculateChartHeight(numDrivers) {
    const minHeight = 400;
    const maxHeight = 1200;
    const pixelsPerDriver = 60;
    const headerFooterSpace = 150;

    const calculatedHeight = (numDrivers * pixelsPerDriver) + headerFooterSpace;
    return Math.max(minHeight, Math.min(maxHeight, calculatedHeight));
}

/**
 * Create Gantt chart layout
 */
function createGanttLayout(sortedDrivers) {
    const height = calculateChartHeight(sortedDrivers.length);

    return {
        title: 'Task Timeline Gantt Chart',
        barmode: 'overlay',
        bargap: 0.2,
        bargroupgap: 0,

        xaxis: {
            type: 'date',
            title: 'Timeline',
            rangeslider: {
                visible: true,
                thickness: 0.1
            }
        },

        yaxis: {
            type: 'category',
            title: 'Driver Name',
            automargin: true,
            categoryorder: 'array',
            categoryarray: sortedDrivers,
            fixedrange: false
        },

        hovermode: 'closest',
        showlegend: true,
        legend: {
            orientation: 'v',
            x: 1.02,
            y: 1,
            xanchor: 'left',
            yanchor: 'top'
        },

        height: height,
        margin: {
            l: 150,
            r: 200,
            t: 80,
            b: 150
        }
    };
}

// ============= Rendering =============

/**
 * Render Gantt chart
 */
function renderGanttChart() {
    try {
        const tasks = extractTaskData(AppState.rawData);
        const { traces, sortedDrivers } = prepareGanttData(tasks, AppState.currentColorScheme);
        const layout = createGanttLayout(sortedDrivers);

        AppState.ganttData = { traces, sortedDrivers };

        Plotly.newPlot('gantt-chart-container', traces, layout, {
            responsive: true,
            displayModeBar: true,
            modeBarButtonsToRemove: ['lasso2d', 'select2d'],
            scrollZoom: true
        }).then(() => {
            // Force resize after plot is created to ensure correct dimensions
            setTimeout(() => {
                Plotly.Plots.resize('gantt-chart-container');
            }, 100);
        });

        hideLoading();
    } catch (error) {
        console.error('Error rendering Gantt chart:', error);
        showError(`Failed to render chart: ${error.message}`);
    }
}

/**
 * Update color scheme
 */
function updateColorScheme(newScheme) {
    AppState.currentColorScheme = newScheme;
    renderGanttChart();
}

// ============= Event Handlers =============

function initializeEventListeners() {
    // Color scheme dropdown
    document.getElementById('color-scheme-select').addEventListener('change', (e) => {
        updateColorScheme(e.target.value);
    });

    // Error close button
    document.getElementById('error-close').addEventListener('click', () => {
        document.getElementById('error-container').style.display = 'none';
    });
}

// ============= Initialization =============

async function initialize() {
    try {
        showLoading();

        // 1. Get entry IDs from URL params or sessionStorage
        const urlParams = new URLSearchParams(window.location.search);
        const urlEntryIds = urlParams.get('entry_ids');

        if (urlEntryIds) {
            try {
                entryIds = JSON.parse(decodeURIComponent(urlEntryIds));
            } catch (e) {
                throw new Error('Invalid entry_ids in URL');
            }
        } else {
            const storedIds = sessionStorage.getItem('ganttEntryIds');
            if (storedIds) {
                entryIds = JSON.parse(storedIds);
                sessionStorage.removeItem('ganttEntryIds');
            } else {
                throw new Error('No entry IDs provided');
            }
        }

        if (!entryIds || entryIds.length === 0) {
            throw new Error('No entries selected');
        }

        // 2. Initialize event listeners
        initializeEventListeners();

        // 3. Load metadata from backend (lightweight, no dataset loading)
        const data = await loadGanttMetadata(entryIds);
        AppState.rawData = data;

        // 4. Render chart
        renderGanttChart();

    } catch (error) {
        console.error('Initialization error:', error);
        showError(error.message);
    }
}

// Run on DOM ready
document.addEventListener('DOMContentLoaded', initialize);
