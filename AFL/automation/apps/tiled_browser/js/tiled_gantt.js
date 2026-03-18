// ============================================================================
// Tiled Gantt Chart Application (Direct Tiled HTTP)
// ============================================================================

let entryIds = [];
let tiledClient = null;
const FIELD_CANDIDATES = window.TiledHttpClient.DEFAULT_FIELD_CANDIDATES;

const AppState = {
    rawData: null,
    currentColorScheme: 'driver_name',
    ganttData: null
};

function showError(message) {
    const container = document.getElementById('error-container');
    const textEl = document.getElementById('error-text');
    textEl.textContent = message;
    container.style.display = 'block';
    hideLoading();
}

function showLoading() {
    document.getElementById('loading-overlay').style.display = 'flex';
}

function hideLoading() {
    document.getElementById('loading-overlay').style.display = 'none';
}

function parseCustomDate(dateString) {
    if (!dateString || typeof dateString !== 'string') return 0;
    const value = dateString.trim();

    try {
        const regex = /^(\d{2})\/(\d{2})\/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})(?:-(\d+))?\s*([A-Z]+)?([+-]\d{4})?/;
        const match = value.match(regex);
        if (!match) return 0;

        const [_, month, day, year, hours, minutes, seconds, microseconds, _tzName, tzOffset] = match;
        const fullYear = 2000 + parseInt(year, 10);
        const date = new Date(Date.UTC(
            fullYear,
            parseInt(month, 10) - 1,
            parseInt(day, 10),
            parseInt(hours, 10),
            parseInt(minutes, 10),
            parseInt(seconds, 10)
        ));

        if (microseconds) {
            date.setUTCMilliseconds(parseInt(microseconds.substring(0, 3), 10));
        }

        if (tzOffset) {
            const sign = tzOffset[0] === '+' ? 1 : -1;
            const offsetHours = parseInt(tzOffset.substring(1, 3), 10);
            const offsetMinutes = parseInt(tzOffset.substring(3, 5), 10);
            const totalOffsetMs = sign * (offsetHours * 60 + offsetMinutes) * 60 * 1000;
            return date.getTime() - totalOffsetMs;
        }

        return date.getTime();
    } catch (_error) {
        return 0;
    }
}

function formatDateForDisplay(dateString) {
    if (!dateString) return 'N/A';
    const timestamp = parseCustomDate(dateString);
    if (timestamp === 0) return dateString;
    return new Date(timestamp).toISOString().replace('T', ' ').substring(0, 19);
}

function resolve(meta, field) {
    return window.TiledHttpClient.resolveMetadataValue(meta, field, FIELD_CANDIDATES);
}

async function loadGanttMetadata(entryIdsList) {
    const settled = await Promise.allSettled(
        entryIdsList.map(async (entryId) => {
            const entryRef = window.TiledHttpClient.toEntryRef(entryId);
            const payload = await tiledClient.metadata(entryRef);
            const metadata = payload?.data?.attributes?.metadata || {};
            return {
                entry_id: entryRef.id || entryId,
                driver_name: resolve(metadata, 'driver_name') || 'Unknown',
                task_name: resolve(metadata, 'task_name') || 'Unknown',
                sample_name: resolve(metadata, 'sample_name') || 'N/A',
                sample_uuid: resolve(metadata, 'sample_uuid') || 'N/A',
                AL_campaign_name: resolve(metadata, 'AL_campaign_name') || 'N/A',
                meta_started: resolve(metadata, 'meta_started'),
                meta_ended: resolve(metadata, 'meta_ended'),
                run_time_minutes: resolve(metadata, 'run_time_minutes') || 0
            };
        })
    );

    const metadata = [];
    const failed = [];

    for (const result of settled) {
        if (result.status === 'fulfilled') {
            metadata.push(result.value);
        } else {
            failed.push(result.reason?.message || 'Unknown metadata fetch error');
        }
    }

    if (metadata.length === 0) {
        throw new Error(failed[0] || 'Failed to load metadata');
    }

    return { metadata, failed };
}

function generateColorMap(rows, colorScheme) {
    const uniqueValues = [...new Set(rows.map(row => row[colorScheme] || 'Unknown'))].sort();
    const palette = [
        'rgb(31, 119, 180)', 'rgb(255, 127, 14)', 'rgb(44, 160, 44)',
        'rgb(214, 39, 40)', 'rgb(148, 103, 189)', 'rgb(140, 86, 75)',
        'rgb(227, 119, 194)', 'rgb(127, 127, 127)', 'rgb(188, 189, 34)',
        'rgb(23, 190, 207)', 'rgb(174, 199, 232)', 'rgb(255, 187, 120)',
        'rgb(152, 223, 138)', 'rgb(255, 152, 150)', 'rgb(197, 176, 213)'
    ];

    const colorMap = {};
    uniqueValues.forEach((value, index) => {
        if (index < palette.length) {
            colorMap[value] = palette[index];
        } else {
            const hue = (index * 137.5) % 360;
            colorMap[value] = `hsl(${hue}, 70%, 50%)`;
        }
    });
    return colorMap;
}

function extractTaskData(ganttData) {
    return (ganttData.metadata || []).map(entry => ({
        entry_id: entry.entry_id,
        driver_name: entry.driver_name || 'Unknown',
        task_name: entry.task_name || 'Unknown',
        sample_name: entry.sample_name || 'N/A',
        sample_uuid: entry.sample_uuid || 'N/A',
        AL_campaign_name: entry.AL_campaign_name || 'N/A',
        meta_started: entry.meta_started,
        meta_ended: entry.meta_ended,
        run_time_minutes: entry.run_time_minutes || 0
    }));
}

function prepareGanttData(tasks, colorScheme) {
    const validTasks = tasks.filter(task => task.meta_started && task.meta_ended && task.driver_name);
    if (validTasks.length === 0) {
        throw new Error('No valid tasks with timing data found.');
    }

    const driverGroups = {};
    validTasks.forEach(task => {
        if (!driverGroups[task.driver_name]) {
            driverGroups[task.driver_name] = [];
        }
        driverGroups[task.driver_name].push(task);
    });

    const sortedDrivers = Object.keys(driverGroups).sort((a, b) => {
        const aMin = Math.min(...driverGroups[a].map(t => parseCustomDate(t.meta_started)));
        const bMin = Math.min(...driverGroups[b].map(t => parseCustomDate(t.meta_started)));
        return aMin - bMin;
    });

    const colorMap = generateColorMap(validTasks, colorScheme);
    const traces = [];

    sortedDrivers.forEach(driver => {
        const driverTasks = driverGroups[driver];
        const colorGroups = {};

        driverTasks.forEach(task => {
            const key = task[colorScheme] || 'Unknown';
            if (!colorGroups[key]) colorGroups[key] = [];
            colorGroups[key].push(task);
        });

        Object.entries(colorGroups).forEach(([colorKey, groupTasks]) => {
            const baseValues = [];
            const durations = [];
            const yValues = [];
            const customData = [];

            groupTasks.forEach(task => {
                const startTime = parseCustomDate(task.meta_started);
                const endTime = parseCustomDate(task.meta_ended);
                const duration = endTime - startTime;
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
                traces.push({
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
                });
            }
        });
    });

    return { traces, sortedDrivers };
}

function calculateChartHeight(numDrivers) {
    const minHeight = 400;
    const maxHeight = 1200;
    const pixelsPerDriver = 60;
    const headerFooterSpace = 150;
    const calculatedHeight = (numDrivers * pixelsPerDriver) + headerFooterSpace;
    return Math.max(minHeight, Math.min(maxHeight, calculatedHeight));
}

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
            rangeslider: { visible: true, thickness: 0.1 }
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
        height,
        margin: { l: 150, r: 200, t: 80, b: 150 }
    };
}

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
            setTimeout(() => {
                Plotly.Plots.resize('gantt-chart-container');
            }, 100);
        });

        hideLoading();
    } catch (error) {
        showError(`Failed to render chart: ${error.message}`);
    }
}

function updateColorScheme(newScheme) {
    AppState.currentColorScheme = newScheme;
    renderGanttChart();
}

function initializeEventListeners() {
    document.getElementById('color-scheme-select').addEventListener('change', (e) => {
        updateColorScheme(e.target.value);
    });

    document.getElementById('error-close').addEventListener('click', () => {
        document.getElementById('error-container').style.display = 'none';
    });
}

function parseEntryIds() {
    const urlParams = new URLSearchParams(window.location.search);
    const urlEntryIds = urlParams.get('entry_ids');

    if (urlEntryIds) {
        return JSON.parse(decodeURIComponent(urlEntryIds));
    }

    const storedIds = sessionStorage.getItem('ganttEntryIds');
    if (storedIds) {
        sessionStorage.removeItem('ganttEntryIds');
        return JSON.parse(storedIds);
    }

    throw new Error('No entry IDs provided');
}

async function initialize() {
    try {
        showLoading();
        entryIds = parseEntryIds().map(entry => window.TiledHttpClient.toEntryRef(entry));

        if (!Array.isArray(entryIds) || entryIds.length === 0) {
            throw new Error('No entries selected');
        }
        if (entryIds.length > 200) {
            throw new Error(`Gantt selection capped at 200 entries (received ${entryIds.length}).`);
        }

        const config = await window.TiledHttpClient.loadConfig();
        tiledClient = await window.TiledHttpClient.createClientFromConfig(config);

        initializeEventListeners();

        const data = await loadGanttMetadata(entryIds);
        AppState.rawData = data;

        if ((data.failed || []).length > 0) {
            const failedCount = data.failed.length;
            showError(`Loaded ${data.metadata.length} entries; ${failedCount} metadata request(s) failed.`);
        }

        renderGanttChart();
    } catch (error) {
        showError(error.message);
    }
}

document.addEventListener('DOMContentLoaded', initialize);
