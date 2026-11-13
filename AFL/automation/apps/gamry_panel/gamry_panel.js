(function () {
    const form = document.getElementById('cv-form');
    const serviceOutput = document.getElementById('service-output');
    const resultOutput = document.getElementById('result-output');
    const resultSummary = document.getElementById('result-summary');
    const resultSource = document.getElementById('result-source');
    const bridgeStatus = document.getElementById('bridge-status');
    const bridgeEndpoint = document.getElementById('bridge-endpoint');
    const instrumentSelect = document.getElementById('instrument-select');
    const measurementMode = document.getElementById('measurement-mode');
    const primaryCanvas = document.getElementById('cv-plot');
    const primaryContext = primaryCanvas.getContext('2d');
    const voltageTimeCanvas = document.getElementById('voltage-time-plot');
    const voltageTimeContext = voltageTimeCanvas.getContext('2d');

    function setOutput(element, payload) {
        if (typeof payload === 'string') {
            element.textContent = payload;
            return;
        }
        element.textContent = JSON.stringify(payload, null, 2);
    }

    function updateModeVisibility() {
        const mode = measurementMode.value || 'cv';
        document.querySelectorAll('.mode-section').forEach((section) => {
            section.hidden = section.getAttribute('data-mode') !== mode;
        });
    }

    function getFormPayload() {
        const data = new FormData(form);
        const payload = {};
        data.forEach((value, key) => {
            if (value === '') {
                return;
            }
            if (key === 'instrument_name' || key === 'current_range_mode' || key === 'measurement_mode') {
                payload[key] = value;
                return;
            }
            if (value === 'on') {
                payload[key] = true;
                return;
            }
            payload[key] = Number(value);
        });
        form.querySelectorAll('input[type="checkbox"]').forEach((input) => {
            if (!(input.name in payload)) {
                payload[input.name] = input.checked;
            }
        });
        return payload;
    }

    let authToken = null;

    async function callDriver(route, payload) {
        const params = new URLSearchParams(Object.assign({ r: route }, payload || {}));
        const response = await fetch('/query_driver?' + params.toString(), {
            method: 'GET',
            headers: { Accept: 'application/json' },
        });
        const text = await response.text();
        let parsed;
        try {
            parsed = JSON.parse(text);
        } catch (error) {
            parsed = { status: response.ok ? 'ok' : 'error', raw: text };
        }
        if (!response.ok || (parsed && parsed.status === 'error')) {
            const message = parsed && (parsed.message || parsed.raw) ? (parsed.message || parsed.raw) : ('Request failed with status ' + response.status);
            throw new Error(message);
        }
        return parsed;
    }

    async function ensureAuthToken() {
        if (authToken) {
            return authToken;
        }
        const response = await fetch('/login', {
            method: 'POST',
            headers: {
                Accept: 'application/json',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ username: 'gamry_panel', password: 'domo_arigato' }),
        });
        const payload = await response.json();
        if (!response.ok || !payload.token) {
            throw new Error(payload.msg || 'Unable to authenticate panel queue request');
        }
        authToken = payload.token;
        return authToken;
    }

    async function enqueueDriver(task) {
        const token = await ensureAuthToken();
        const response = await fetch('/enqueue', {
            method: 'POST',
            headers: {
                Accept: 'application/json',
                'Content-Type': 'application/json',
                Authorization: 'Bearer ' + token,
            },
            body: JSON.stringify(task),
        });
        const text = await response.text();
        if (!response.ok) {
            throw new Error(text || ('Enqueue failed with status ' + response.status));
        }
        return { status: 'ok', task_uuid: text.trim() };
    }

    function updateStatus(service) {
        if (!service) {
            bridgeStatus.textContent = 'Unknown';
            bridgeStatus.className = 'status-pill';
            bridgeEndpoint.textContent = 'Endpoint unavailable';
            return;
        }
        const ready = Boolean(service.bridge_ready || service.bridge_usable);
        bridgeStatus.textContent = ready ? 'Bridge Ready' : 'Bridge Offline';
        bridgeStatus.className = ready ? 'status-pill ready' : 'status-pill error';
        bridgeEndpoint.textContent = service.host + ':' + service.port + ' | instrument=' + service.instrument_name;
    }

    function populateForm(config) {
        if (!config) {
            return;
        }
        Object.keys(config).forEach((key) => {
            const input = form.elements.namedItem(key);
            if (!input) {
                return;
            }
            if (input instanceof RadioNodeList) {
                Array.from(input).forEach((node) => {
                    if (node.type === 'checkbox') {
                        node.checked = Boolean(config[key]);
                    } else {
                        node.checked = String(node.value) === String(config[key]);
                    }
                });
                return;
            }
            if (input.type === 'checkbox') {
                input.checked = Boolean(config[key]);
                return;
            }
            input.value = config[key];
        });
        updateModeVisibility();
    }

    function populateInstrumentList(payload, selectedInstrument) {
        const instruments = payload && Array.isArray(payload.instruments) ? payload.instruments : [];
        instrumentSelect.innerHTML = '';

        const selectedValue = selectedInstrument || form.elements.namedItem('instrument_name').value || '';
        if (!instruments.length) {
            const option = document.createElement('option');
            option.value = selectedValue;
            option.textContent = selectedValue || 'No instruments detected';
            instrumentSelect.appendChild(option);
            instrumentSelect.value = selectedValue;
            return;
        }

        instruments.forEach((instrumentName) => {
            const option = document.createElement('option');
            option.value = instrumentName;
            option.textContent = instrumentName;
            instrumentSelect.appendChild(option);
        });

        if (selectedValue && instruments.indexOf(selectedValue) !== -1) {
            instrumentSelect.value = selectedValue;
        } else {
            instrumentSelect.value = instruments[0];
            form.elements.namedItem('instrument_name').value = instruments[0];
        }
    }

    function drawSeriesPlot(plotCanvas, plotContext, x, y, xLabel, yLabel, emptyMessage, lineColor) {
        plotContext.clearRect(0, 0, plotCanvas.width, plotCanvas.height);
        plotContext.fillStyle = '#f8f7f3';
        plotContext.fillRect(0, 0, plotCanvas.width, plotCanvas.height);

        if (!x.length || !y.length) {
            plotContext.fillStyle = '#5f6b73';
            plotContext.font = '18px Georgia';
            plotContext.fillText(emptyMessage, 24, 40);
            return;
        }

        const paddingLeft = 72;
        const paddingRight = 28;
        const paddingTop = 24;
        const paddingBottom = 52;
        const width = plotCanvas.width - paddingLeft - paddingRight;
        const height = plotCanvas.height - paddingTop - paddingBottom;
        const minX = Math.min.apply(null, x);
        const maxX = Math.max.apply(null, x);
        const minY = Math.min.apply(null, y);
        const maxY = Math.max.apply(null, y);
        const spanX = maxX - minX || 1;
        const spanY = maxY - minY || 1;
        const tickCount = 5;

        function formatTick(value) {
            if (!Number.isFinite(value)) {
                return '';
            }
            if (Math.abs(value) >= 1000 || (Math.abs(value) > 0 && Math.abs(value) < 0.001)) {
                return value.toExponential(2);
            }
            return value.toFixed(3).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1');
        }

        plotContext.strokeStyle = '#e2d8c7';
        plotContext.lineWidth = 1;
        for (let index = 0; index <= tickCount; index += 1) {
            const xRatio = index / tickCount;
            const xPixel = paddingLeft + width * xRatio;
            plotContext.beginPath();
            plotContext.moveTo(xPixel, paddingTop);
            plotContext.lineTo(xPixel, plotCanvas.height - paddingBottom);
            plotContext.stroke();

            const yRatio = index / tickCount;
            const yPixel = paddingTop + height * yRatio;
            plotContext.beginPath();
            plotContext.moveTo(paddingLeft, yPixel);
            plotContext.lineTo(plotCanvas.width - paddingRight, yPixel);
            plotContext.stroke();
        }

        plotContext.strokeStyle = '#8b7d6b';
        plotContext.lineWidth = 1.25;
        plotContext.beginPath();
        plotContext.moveTo(paddingLeft, paddingTop);
        plotContext.lineTo(paddingLeft, plotCanvas.height - paddingBottom);
        plotContext.lineTo(plotCanvas.width - paddingRight, plotCanvas.height - paddingBottom);
        plotContext.stroke();

        plotContext.fillStyle = '#5f6b73';
        plotContext.font = '12px Georgia';
        for (let index = 0; index <= tickCount; index += 1) {
            const xRatio = index / tickCount;
            const xValue = minX + spanX * xRatio;
            const xPixel = paddingLeft + width * xRatio;
            plotContext.beginPath();
            plotContext.moveTo(xPixel, plotCanvas.height - paddingBottom);
            plotContext.lineTo(xPixel, plotCanvas.height - paddingBottom + 6);
            plotContext.stroke();
            plotContext.fillText(formatTick(xValue), xPixel - 18, plotCanvas.height - paddingBottom + 20);

            const yRatio = index / tickCount;
            const yValue = maxY - spanY * yRatio;
            const yPixel = paddingTop + height * yRatio;
            plotContext.beginPath();
            plotContext.moveTo(paddingLeft - 6, yPixel);
            plotContext.lineTo(paddingLeft, yPixel);
            plotContext.stroke();
            plotContext.fillText(formatTick(yValue), 8, yPixel + 4);
        }

        plotContext.strokeStyle = lineColor;
        plotContext.lineWidth = 2;
        plotContext.beginPath();
        x.forEach((xValue, index) => {
            const px = paddingLeft + ((xValue - minX) / spanX) * width;
            const py = plotCanvas.height - paddingBottom - ((y[index] - minY) / spanY) * height;
            if (index === 0) {
                plotContext.moveTo(px, py);
            } else {
                plotContext.lineTo(px, py);
            }
        });
        plotContext.stroke();

        plotContext.fillStyle = '#1f2a30';
        plotContext.font = '14px Georgia';
        plotContext.fillText(xLabel, plotCanvas.width / 2 - 42, plotCanvas.height - 14);
        plotContext.save();
        plotContext.translate(18, plotCanvas.height / 2 + 42);
        plotContext.rotate(-Math.PI / 2);
        plotContext.fillText(yLabel, 0, 0);
        plotContext.restore();
    }

    function drawPlot(result) {
        const attrs = result && result.attrs ? result.attrs : {};
        const plotData = result && result.plot_data ? result.plot_data : null;
        if (plotData) {
            const voltage = Array.isArray(plotData.voltage_v) ? plotData.voltage_v : [];
            const current = Array.isArray(plotData.current_a) ? plotData.current_a : [];
            const time = Array.isArray(plotData.time_s) ? plotData.time_s : [];
            const differentialCurrent = Array.isArray(plotData.diff_current_a) ? plotData.diff_current_a : [];
            const measurementType = attrs.measurement_type || '';
            if (measurementType === 'differential_pulse_voltammetry') {
                drawSeriesPlot(primaryCanvas, primaryContext, voltage, differentialCurrent, 'Voltage (V)', 'Differential Current (A)', 'No differential-current data to plot yet.', '#0f766e');
                drawSeriesPlot(voltageTimeCanvas, voltageTimeContext, [], [], 'Time (s)', 'Voltage (V)', 'DPV voltage-vs-time plot disabled.', '#b45309');
                return;
            }
            const primaryX = measurementType === 'chronoamperometry' ? time : voltage;
            const primaryXLabel = measurementType === 'chronoamperometry' ? 'Time (s)' : 'Voltage (V)';
            drawSeriesPlot(primaryCanvas, primaryContext, primaryX, current, primaryXLabel, 'Current (A)', 'No measurement data to plot yet.', '#0f766e');
            drawSeriesPlot(voltageTimeCanvas, voltageTimeContext, time, voltage, 'Time (s)', 'Voltage (V)', 'No voltage-vs-time data to plot yet.', '#b45309');
            return;
        }

        drawSeriesPlot(primaryCanvas, primaryContext, [], [], 'Voltage (V)', 'Current (A)', 'No measurement data to plot yet.', '#0f766e');
        drawSeriesPlot(voltageTimeCanvas, voltageTimeContext, [], [], 'Time (s)', 'Voltage (V)', 'No voltage-vs-time data to plot yet.', '#b45309');
    }

    function renderResult(result) {
        if (!result) {
            resultSummary.textContent = 'No run yet.';
            resultSource.textContent = 'Plot source: none';
            setOutput(resultOutput, 'No result yet.');
            drawPlot(null);
            return;
        }
        const attrs = result.attrs || {};
        const measurementType = attrs.measurement_type || 'measurement';
        resultSummary.textContent = measurementType + ' | ' + (attrs.instrument_name || 'Unknown instrument') + ' | ' + (attrs.point_count || 0) + ' points';
        resultSource.textContent = 'Plot source: ' + (attrs.plot_source || 'dataset');
        setOutput(resultOutput, {
            measurement_type: measurementType,
            instrument_name: attrs.instrument_name || 'Unknown instrument',
            point_count: attrs.point_count || 0,
            plot_source: attrs.plot_source || 'dataset',
            plot_variant: attrs.plot_variant || null,
        });
        drawPlot(result);
    }

    async function refreshState() {
        const state = await callDriver('getPanelState');
        updateStatus(state.service);
        populateForm(state.config);
        populateInstrumentList(state.available_instruments, state.config && state.config.instrument_name);
        renderResult(state.last_result);
        setOutput(serviceOutput, state.last_connection || state);
    }

    async function runAction(route, payload, outputElement) {
        outputElement.textContent = 'Working...';
        try {
            const result = await callDriver(route, payload);
            setOutput(outputElement, result.connection || result);
            if (result.service) {
                updateStatus(result.service);
            }
            if (result.config) {
                populateForm(result.config);
            }
            if (result.available_instruments) {
                populateInstrumentList(result.available_instruments, result.config && result.config.instrument_name);
            }
            if (result.result) {
                renderResult(result.result);
            }
        } catch (error) {
            setOutput(outputElement, { status: 'error', message: String(error) });
        }
    }

    async function enqueueMeasurement(payload, outputElement) {
        outputElement.textContent = 'Queueing...';
        try {
            const result = await enqueueDriver(Object.assign({ task_name: 'enqueuePanelMeasurement' }, payload));
            setOutput(outputElement, result);
            await refreshState();
        } catch (error) {
            setOutput(outputElement, { status: 'error', message: String(error) });
        }
    }

    document.getElementById('refresh-state').addEventListener('click', function () {
        refreshState();
    });
    document.getElementById('start-service').addEventListener('click', function () {
        runAction('startService', {}, serviceOutput);
    });
    document.getElementById('connect-instrument').addEventListener('click', function () {
        const selectedInstrument = instrumentSelect.value || form.elements.namedItem('instrument_name').value;
        form.elements.namedItem('instrument_name').value = selectedInstrument;
        runAction('connectInstrument', { instrument_name: selectedInstrument }, serviceOutput);
    });
    document.getElementById('stop-service').addEventListener('click', function () {
        runAction('shutdownService', {}, serviceOutput);
    });
    document.getElementById('list-instruments').addEventListener('click', function () {
        runAction('listInstruments', {}, serviceOutput);
    });
    document.getElementById('validate-connection').addEventListener('click', function () {
        runAction('validateConnection', {}, serviceOutput);
    });
    document.getElementById('diagnose-connection').addEventListener('click', function () {
        runAction('diagnoseConnection', { instrument_name: form.elements.namedItem('instrument_name').value }, serviceOutput);
    });
    instrumentSelect.addEventListener('change', function () {
        form.elements.namedItem('instrument_name').value = instrumentSelect.value;
    });
    measurementMode.addEventListener('change', function () {
        updateModeVisibility();
    });
    document.getElementById('save-config').addEventListener('click', function () {
        runAction('updatePanelConfig', getFormPayload(), serviceOutput);
    });
    document.getElementById('run-measurement').addEventListener('click', function () {
        enqueueMeasurement(getFormPayload(), resultOutput);
    });

    updateModeVisibility();
    refreshState();
})();
