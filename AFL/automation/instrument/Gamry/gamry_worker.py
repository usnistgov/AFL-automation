import csv
import datetime
import json
import math
import os
import sys
import time
import traceback

try:
    import rpyc
    from rpyc.utils.server import ThreadedServer
    _RPYC_IMPORT_ERROR = None
except ImportError as exc:
    rpyc = None
    ThreadedServer = None
    _RPYC_IMPORT_ERROR = exc


WORKER_LOG_PATH = os.environ.get('AFL_GAMRY_WORKER_LOG')


def _log_worker_event(event, **details):
    if not WORKER_LOG_PATH:
        return
    payload = {
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'event': event,
        'details': details,
    }
    try:
        with open(WORKER_LOG_PATH, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(payload, default=str) + '\n')
    except Exception:
        pass


def _require_rpyc():
    if rpyc is None:
        raise RuntimeError(
            'RPyC is required in the AFL Python environment to use the Gamry worker bridge.'
        ) from _RPYC_IMPORT_ERROR
    return rpyc, ThreadedServer


def _require_toolkitpy():
    try:
        import toolkitpy as tkp
    except ImportError as exc:
        raise RuntimeError(
            'toolkitpy is required in the AFL Python environment to use the Gamry worker.'
        ) from exc
    return tkp


def _sanitize_filename_component(value):
    text = str(value).strip() or 'unknown'
    return ''.join(character if character.isalnum() or character in ('-', '_') else '_' for character in text)


def _measurement_payload_from_data(measurement_type, data):
    time_values = list(data.get('time', []))
    voltage_values = list(data.get('potential', []))
    current_values = list(data.get('current', []))

    if measurement_type == 'cyclic_voltammetry':
        if not voltage_values:
            voltage_values = list(data.get('vf', []))
        if not current_values:
            current_values = list(data.get('im', []))
        return {
            'x_key': 'potential',
            'y_key': 'current',
            'x_source': 'potential',
            'y_source': 'current',
            'data': {
                'time': time_values,
                'potential': voltage_values,
                'current': current_values,
            },
        }
    if measurement_type == 'chronoamperometry':
        if not voltage_values:
            voltage_values = list(data.get('vf', []))
        if not current_values:
            current_values = list(data.get('im', []))
        return {
            'x_key': 'time',
            'y_key': 'current',
            'x_source': 'time',
            'y_source': 'current',
            'data': {
                'time': time_values,
                'potential': voltage_values,
                'current': current_values,
            },
        }
    if measurement_type == 'sine_wave':
        if not voltage_values:
            voltage_values = list(data.get('vf', []))
        if not current_values:
            current_values = list(data.get('im', []))
        return {
            'x_key': 'time',
            'y_key': 'current',
            'x_source': 'time',
            'y_source': 'current',
            'data': {
                'time': time_values,
                'potential': voltage_values,
                'current': current_values,
                'applied_signal': list(data.get('applied_signal', voltage_values)),
            },
        }
    raise ValueError(f'Unsupported measurement type for payload: {measurement_type}')


def _build_measurement_result_from_data(
    measurement_type,
    instrument_name,
    process_name,
    timestamp,
    parameters,
    data,
):
    payload = _measurement_payload_from_data(measurement_type, data)
    return {
        'mode': 'run_measurement',
        'measurement_type': measurement_type,
        'x_key': payload['x_key'],
        'y_key': payload['y_key'],
        'x_source': payload['x_source'],
        'y_source': payload['y_source'],
        'instrument_name': instrument_name,
        'process_name': process_name,
        'timestamp': timestamp,
        'parameters': parameters,
        'data': payload['data'],
    }


def _calculate_dpv_differential_current(data, cycle_time, pulse_time, points_to_average=3):
    if cycle_time <= 0:
        raise ValueError('DPV cycle time must be positive')
    if pulse_time <= 0:
        raise ValueError('DPV pulse time must be positive')
    if pulse_time >= cycle_time:
        raise ValueError('DPV pulse time must be shorter than the cycle time')
    if points_to_average <= 0:
        raise ValueError('DPV averaging point count must be positive')

    time_values = list(data.get('time', []))
    voltage_values = list(data.get('vf', data.get('potential', [])))
    current_values = list(data.get('im', data.get('current', [])))
    point_total = min(len(time_values), len(voltage_values), len(current_values))
    if point_total <= 0:
        return {
            'voltage_v': [],
            'diff_current_a': [],
            'cycle_index': [],
            'point_count': 0,
            'skipped_cycles': 0,
        }

    base_time = cycle_time - pulse_time
    max_time = max(time_values[:point_total])
    cycle_count = int(math.floor(max_time / cycle_time)) + 1
    differential_voltage = []
    differential_current = []
    cycle_indices = []
    skipped_cycles = 0

    for cycle_index in range(cycle_count):
        cycle_start = cycle_index * cycle_time
        pulse_start = cycle_start + base_time
        cycle_end = (cycle_index + 1) * cycle_time
        base_points = [index for index in range(point_total) if cycle_start <= time_values[index] < pulse_start]
        pulse_points = [index for index in range(point_total) if pulse_start <= time_values[index] <= cycle_end]
        if len(base_points) < points_to_average or len(pulse_points) < points_to_average:
            skipped_cycles += 1
            continue

        base_slice = base_points[-points_to_average:]
        pulse_slice = pulse_points[-points_to_average:]
        base_average = sum(current_values[index] for index in base_slice) / float(points_to_average)
        pulse_average = sum(current_values[index] for index in pulse_slice) / float(points_to_average)
        differential_voltage.append(float(voltage_values[base_points[-1]]))
        differential_current.append(float(pulse_average - base_average))
        cycle_indices.append(cycle_index)

    return {
        'voltage_v': differential_voltage,
        'diff_current_a': differential_current,
        'cycle_index': cycle_indices,
        'point_count': len(differential_voltage),
        'skipped_cycles': skipped_cycles,
    }


def _summarize_dpv_timing(data, expected_cycle_count, expected_cycle_time):
    time_values = list(data.get('time', []))
    observed_cycle_count = len(time_values)
    if observed_cycle_count < 2:
        return {
            'expected_cycle_count': int(expected_cycle_count),
            'expected_cycle_time': float(expected_cycle_time),
            'observed_cycle_count': observed_cycle_count,
            'observed_duration': None,
            'observed_cycle_time': None,
            'observed_cycles_per_second': None,
            'cycle_completion_ratio': (
                float(observed_cycle_count) / float(expected_cycle_count)
                if expected_cycle_count else None
            ),
        }

    observed_duration = float(time_values[-1]) - float(time_values[0])
    observed_cycle_time = observed_duration / float(observed_cycle_count - 1) if observed_cycle_count > 1 else None
    observed_cycles_per_second = (
        1.0 / observed_cycle_time if observed_cycle_time and observed_cycle_time > 0 else None
    )
    return {
        'expected_cycle_count': int(expected_cycle_count),
        'expected_cycle_time': float(expected_cycle_time),
        'observed_cycle_count': observed_cycle_count,
        'observed_duration': observed_duration,
        'observed_cycle_time': observed_cycle_time,
        'observed_cycles_per_second': observed_cycles_per_second,
        'cycle_completion_ratio': (
            float(observed_cycle_count) / float(expected_cycle_count)
            if expected_cycle_count else None
        ),
    }


def point_count(value):
    return int(math.ceil(abs(value)))


def initialize_pstat(tkp, pstat, current_range_mode='auto', current_range_limit=None):
    pstat.set_ach_select(tkp.ACHSELECT_GND)
    pstat.set_ie_stability(tkp.STABILITY_NORM)
    pstat.set_ca_speed(tkp.CASPEED_NORM)
    pstat.set_ground(tkp.FLOAT)
    pstat.set_ich_range(3.0)
    pstat.set_ich_range_mode(False)
    pstat.set_ich_offset_enable(False)
    pstat.set_vch_range(10.0)
    pstat.set_vch_range_mode(True)
    pstat.set_vch_offset_enable(False)
    pstat.set_ach_range(3.0)
    pstat.set_ie_range_lower_limit(0)
    pstat.set_pos_feed_enable(False)
    pstat.set_analog_out(0.0)
    pstat.set_voltage(0.0)
    pstat.set_pos_feed_resistance(0.0)
    if current_range_mode == 'auto':
        if hasattr(pstat, 'set_ierange_mode'):
            pstat.set_ierange_mode(True)
        elif hasattr(pstat, 'set_ie_range_mode'):
            pstat.set_ie_range_mode(True)
    else:
        if hasattr(pstat, 'set_ierange_mode'):
            pstat.set_ierange_mode(False)
        elif hasattr(pstat, 'set_ie_range_mode'):
            pstat.set_ie_range_mode(False)
        if current_range_limit is not None:
            if hasattr(pstat, 'set_ie_range'):
                pstat.set_ie_range(float(current_range_limit))
            elif hasattr(pstat, 'set_ierange'):
                pstat.set_ierange(float(current_range_limit))


def list_instruments(tkp):
    instruments = []
    if hasattr(tkp, 'enumerate_instruments'):
        for instrument in tkp.enumerate_instruments():
            instruments.append(str(instrument))
    return instruments


def release_pstat(tkp, pstat):
    if pstat is None:
        return
    try:
        pstat.set_cell(False)
    except Exception:
        pass
    try:
        pstat.close()
    except Exception:
        pass


def validate_connection(tkp, instrument_name):
    pstat = tkp.Pstat(instrument_name)
    try:
        return {
            'instrument_name': instrument_name,
            'model': getattr(pstat, 'modelname', lambda: None)() if hasattr(pstat, 'modelname') else None,
            'serial_number': getattr(pstat, 'serialno', lambda: None)() if hasattr(pstat, 'serialno') else None,
            'label': getattr(pstat, 'label', lambda: None)() if hasattr(pstat, 'label') else None,
        }
    finally:
        release_pstat(tkp, pstat)
        del pstat


def _curve_data_to_lists(data):
    names = getattr(getattr(data, 'dtype', None), 'names', None) or []
    return {
        name: data[name].tolist()
        for name in names
    }


def _validate_voltage_limit(*voltages, limit=2.0):
    for voltage in voltages:
        if abs(float(voltage)) > limit:
            raise ValueError(f'Voltage {float(voltage):.6g} V exceeds the hard limit of {limit:.6g} V')



def _predict_dpv_point_count(initial_voltage, final_voltage, step_size, sample_period, pulse_time, timer_resolution=0.001):
    if step_size == 0:
        raise ValueError('DPV step size must be non-zero')
    if sample_period <= 0:
        raise ValueError('DPV sample period must be positive')
    if pulse_time <= 0:
        raise ValueError('DPV pulse time must be positive')
    if pulse_time >= sample_period:
        raise ValueError('DPV pulse time must be shorter than the sample period')

    span = final_voltage - initial_voltage
    cycle_count = int(abs(round(span / step_size)))
    if cycle_count <= 0:
        raise ValueError('DPV initial and final voltages must span at least one step')

    samples_per_cycle = max(2, int(math.ceil(sample_period / timer_resolution)))
    predicted_raw_points = cycle_count * samples_per_cycle
    return {
        'cycle_count': cycle_count,
        'samples_per_cycle': samples_per_cycle,
        'predicted_raw_points': predicted_raw_points,
    }


def _derive_dpv_trace(data, sample_period, pulse_time):
    del sample_period, pulse_time

    time_values = list(data.get('time', []))
    if not time_values:
        time_values = list(data.get('T', []))

    forward_potential = list(data.get('vfwd', []))
    if not forward_potential:
        forward_potential = list(data.get('Vfwd', []))

    reverse_potential = list(data.get('vrev', []))
    if not reverse_potential:
        reverse_potential = list(data.get('Vrev', []))

    step_potential = list(data.get('vstep', []))
    if not step_potential:
        step_potential = list(data.get('Vstep', []))

    forward_current = list(data.get('ifwd', []))
    if not forward_current:
        forward_current = list(data.get('Ifwd', []))

    reverse_current = list(data.get('irev', []))
    if not reverse_current:
        reverse_current = list(data.get('Irev', []))

    differential_current = list(data.get('idif', []))
    if not differential_current:
        differential_current = list(data.get('Idif', []))

    applied_signal_values = list(data.get('sig', []))
    if not applied_signal_values:
        applied_signal_values = list(data.get('Sig', []))
    if not applied_signal_values:
        applied_signal_values = list(data.get('vu', []))

    if forward_potential and reverse_potential and forward_current and reverse_current:
        point_count = min(len(forward_potential), len(reverse_potential), len(forward_current), len(reverse_current))
        if time_values:
            point_count = min(point_count, len(time_values))
        if step_potential:
            point_count = min(point_count, len(step_potential))
        if differential_current:
            point_count = min(point_count, len(differential_current))
        if applied_signal_values:
            point_count = min(point_count, len(applied_signal_values))
        if point_count <= 0:
            return None

        derived = {
            'cycle_index': list(range(point_count)),
            'potential': forward_potential[:point_count],
            'current': (differential_current[:point_count] if differential_current else [
                forward_current[index] - reverse_current[index]
                for index in range(point_count)
            ]),
            'base_current': reverse_current[:point_count],
            'pulse_current': forward_current[:point_count],
            'base_potential': reverse_potential[:point_count],
            'pulse_potential': forward_potential[:point_count],
        }
        if time_values:
            derived['time'] = time_values[:point_count]
            derived['base_time'] = time_values[:point_count]
        if step_potential:
            derived['step_potential'] = step_potential[:point_count]
        if applied_signal_values:
            derived['applied_signal'] = applied_signal_values[:point_count]
        return derived

    current_values = list(data.get('im', []))
    potential_values = list(data.get('vf', []))
    if not time_values or not current_values or not potential_values:
        return None

    point_count = min(len(time_values), len(current_values), len(potential_values))
    if point_count < 2:
        return None

    time_values = time_values[:point_count]
    current_values = current_values[:point_count]
    potential_values = potential_values[:point_count]
    if applied_signal_values:
        applied_signal_values = applied_signal_values[:point_count]

    potential_tolerance = max(1e-6, max(abs(value) for value in potential_values) * 1e-6)
    cycle_index = []
    base_potential = []
    base_current = []
    base_time = []
    pulse_potential = []
    pulse_current = []
    pulse_end_time = []
    differential_current = []
    applied_signal = []

    pulse_start_indices = []
    for index in range(1, point_count):
        delta = potential_values[index] - potential_values[index - 1]
        if abs(delta) <= potential_tolerance:
            continue
        if index > 1:
            previous_delta = potential_values[index - 1] - potential_values[index - 2]
            if abs(previous_delta) > potential_tolerance and (previous_delta > 0) != (delta > 0):
                continue
        pulse_start_indices.append(index)

    for cycle_id, pulse_start_index in enumerate(pulse_start_indices):
        next_pulse_start = pulse_start_indices[cycle_id + 1] if cycle_id + 1 < len(pulse_start_indices) else point_count
        base_index_value = pulse_start_index - 1
        pulse_index_value = pulse_start_index
        for candidate_index in range(pulse_start_index + 1, next_pulse_start):
            delta = potential_values[candidate_index] - potential_values[candidate_index - 1]
            if abs(delta) > potential_tolerance and (delta > 0) != ((potential_values[pulse_start_index] - potential_values[base_index_value]) > 0):
                break
            pulse_index_value = candidate_index
        if pulse_index_value <= base_index_value:
            continue

        cycle_index.append(cycle_id)
        base_potential.append(potential_values[base_index_value])
        base_current.append(current_values[base_index_value])
        base_time.append(time_values[base_index_value])
        pulse_potential.append(potential_values[pulse_start_index])
        pulse_current.append(current_values[pulse_index_value])
        pulse_end_time.append(time_values[pulse_index_value])
        differential_current.append(current_values[pulse_index_value] - current_values[base_index_value])
        if applied_signal_values:
            applied_signal.append(applied_signal_values[pulse_index_value])

    if not differential_current:
        return None

    derived = {
        'cycle_index': cycle_index,
        'potential': pulse_potential,
        'current': differential_current,
        'base_current': base_current,
        'pulse_current': pulse_current,
        'base_potential': base_potential,
        'pulse_potential': pulse_potential,
        'base_time': base_time,
        'time': pulse_end_time,
    }
    if applied_signal:
        derived['applied_signal'] = applied_signal
    return derived


def _normalize_parameters(parameters, expected_keys):
    if isinstance(parameters, dict):
        return {key: parameters[key] for key in expected_keys if key in parameters}

    try:
        keys = list(parameters.keys())
    except Exception:
        keys = None
    if keys is not None:
        normalized = {}
        for key in expected_keys:
            if key in keys:
                try:
                    normalized[key] = parameters[key]
                    continue
                except Exception:
                    pass
            try:
                normalized[key] = getattr(parameters, key)
            except Exception:
                pass
        return normalized

    normalized = {}
    for key in expected_keys:
        try:
            normalized[key] = parameters[key]
            continue
        except Exception:
            pass
        try:
            normalized[key] = getattr(parameters, key)
        except Exception:
            pass
    return normalized


def collect_cv(
    tkp,
    instrument_name,
    process_name,
    initial_voltage,
    apex1_voltage,
    apex2_voltage,
    final_voltage,
    apex1_hold,
    apex2_hold,
    final_hold,
    scan_rate,
    step_size,
    cycles,
    scan_delay,
    current_range_mode,
):
    parameters = {
        'initial_voltage': float(initial_voltage),
        'apex1_voltage': float(apex1_voltage),
        'apex2_voltage': float(apex2_voltage),
        'final_voltage': float(final_voltage),
        'apex1_hold': float(apex1_hold),
        'apex2_hold': float(apex2_hold),
        'final_hold': float(final_hold),
        'scan_rate': float(scan_rate),
        'step_size': float(step_size),
        'cycles': int(cycles),
        'scan_delay': float(scan_delay),
        'current_range_mode': str(current_range_mode),
    }
    pstat = tkp.Pstat(instrument_name)
    curve = None
    signal = None
    try:
        pstat.set_ctrl_mode(tkp.PSTATMODE)
        initialize_pstat(tkp, pstat, parameters['current_range_mode'])

        initial_voltage = parameters['initial_voltage']
        apex1_voltage = parameters['apex1_voltage']
        apex2_voltage = parameters['apex2_voltage']
        final_voltage = parameters['final_voltage']
        apex1_hold = parameters['apex1_hold']
        apex2_hold = parameters['apex2_hold']
        final_hold = parameters['final_hold']
        scan_rate = parameters['scan_rate']
        step_size = parameters['step_size']
        cycles = parameters['cycles']
        scan_delay = parameters['scan_delay']

        curve = tkp.RcvCurve(pstat, 100000)
        curve.sample_time = step_size / scan_rate
        signal = pstat.signal_r_up_dn_new(
            [initial_voltage, apex1_voltage, apex2_voltage, final_voltage],
            [scan_rate, scan_rate, scan_rate],
            [apex1_hold, apex2_hold, final_hold],
            curve.sample_time,
            cycles,
            tkp.PSTATMODE,
        )
        pstat.set_signal_r_up_dn(signal)
        pstat.init_signal()
        pstat.set_cell(True)
        time.sleep(0.25)
        curve.run(True)
        while tkp.pstat_is_valid(pstat) and curve.running():
            time.sleep(0.1)
        if scan_delay > 0:
            time.sleep(scan_delay)
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        raw_data = _curve_data_to_lists(curve.acq_data())
        return _build_measurement_result_from_data(
            measurement_type='cyclic_voltammetry',
            instrument_name=instrument_name,
            process_name=process_name,
            timestamp=timestamp,
            parameters=parameters,
            data=raw_data,
        )
    finally:
        if signal is not None:
            del signal
        if curve is not None:
            del curve
        release_pstat(tkp, pstat)
        del pstat


def collect_chronoamperometry(tkp, instrument_name, process_name, parameters):
    normalized = {
        'initial_voltage': float(parameters['initial_voltage']),
        'step1_voltage': float(parameters['step1_voltage']),
        'step2_voltage': float(parameters['step2_voltage']),
        'initial_time': float(parameters['initial_time']),
        'step1_time': float(parameters['step1_time']),
        'step2_time': float(parameters['step2_time']),
        'sample_time': float(parameters['sample_time']),
        'expected_max_v': float(parameters['expected_max_v']),
        'current_range_mode': str(parameters.get('current_range_mode', 'auto')),
    }
    pstat = tkp.Pstat(instrument_name)
    curve = None
    signal = None
    try:
        initialize_pstat(tkp, pstat, normalized['current_range_mode'])
        tkp.check_hve(pstat, normalized['expected_max_v'])
        if tkp.hve(pstat):
            pstat.set_electrometer(tkp.ELECTROMETER_HIGH_V)
            pstat.set_ctrl_mode(tkp.ZRAX4MODE)
            scale = 0.25
        else:
            pstat.set_ctrl_mode(tkp.PSTATMODE)
            scale = 1.0
        curve = tkp.ChronoCurve(pstat, 100000)
        signal = pstat.signal_d_step_new(
            normalized['initial_voltage'] * scale,
            normalized['initial_time'],
            normalized['step1_voltage'] * scale,
            normalized['step1_time'],
            normalized['step2_voltage'] * scale,
            normalized['step2_time'],
            normalized['sample_time'],
            tkp.PSTATMODE,
        )
        pstat.set_signal_d_step(signal)
        pstat.init_signal()
        pstat.set_cell(True)
        time.sleep(0.25)
        curve.run(True)
        while tkp.pstat_is_valid(pstat) and curve.running():
            time.sleep(0.1)
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        raw_data = _curve_data_to_lists(curve.acq_data())
        return _build_measurement_result_from_data(
            measurement_type='chronoamperometry',
            instrument_name=instrument_name,
            process_name=process_name,
            timestamp=timestamp,
            parameters=normalized,
            data=raw_data,
        )
    finally:
        try:
            tkp.reset_hve(pstat)
        except Exception:
            pass
        if signal is not None:
            del signal
        if curve is not None:
            del curve
        release_pstat(tkp, pstat)
        del pstat


def collect_sine(tkp, instrument_name, process_name, parameters):
    normalized = {
        'dc_offset': float(parameters['dc_offset']),
        'amplitude': float(parameters['amplitude']),
        'signal_frequency': float(parameters['signal_frequency']),
        'acq_frequency': float(parameters['acq_frequency']),
        'total_time': float(parameters['total_time']),
        'phase_offset': float(parameters['phase_offset']),
        'current_range_mode': str(parameters.get('current_range_mode', 'auto')),
    }
    pstat = tkp.Pstat(instrument_name)
    curve = None
    signal = None
    try:
        pstat.set_ctrl_mode(tkp.PSTATMODE)
        initialize_pstat(tkp, pstat, normalized['current_range_mode'])
        if normalized['signal_frequency'] <= 0:
            raise ValueError('Signal frequency must be positive for sine mode')
        if normalized['acq_frequency'] <= 0:
            raise ValueError('Acquisition frequency must be positive for sine mode')
        if normalized['total_time'] <= 0:
            raise ValueError('Total time must be positive for sine mode')

        cycles = int(normalized['signal_frequency'] * normalized['total_time'])
        if cycles <= 0:
            raise ValueError('Total time must span at least one full sine cycle')

        points_per_cycle = int(round(normalized['acq_frequency'] / normalized['signal_frequency']))
        if points_per_cycle <= 2:
            raise ValueError('Acquisition frequency must provide more than two points per cycle for sine mode')

        total_points = int(normalized['acq_frequency'] * normalized['total_time'] + 1000)
        sample_period = 1.0 / normalized['acq_frequency']
        points = []
        sections = []
        rates = []
        for index in range(points_per_cycle):
            phase = (2.0 * math.pi * index / points_per_cycle) + normalized['phase_offset']
            points.append((normalized['amplitude'] * math.sin(phase)) + normalized['dc_offset'])
            sections.append(0)
            rates.append(0xC0000001)
        signal = pstat.signal_univ_new(
            0.0,
            cycles,
            sample_period,
            1,
            points,
            sections,
            [0.0],
            rates,
            [0],
            tkp.PSTATMODE,
            tkp.SIG_UNIV_TYPE_ARRAY_ONLY,
        )
        curve = tkp.RcvCurve(pstat, total_points)
        pstat.set_signal_univ(signal)
        pstat.init_signal()
        pstat.set_cell(True)
        curve.run(True)
        while tkp.pstat_is_valid(pstat) and curve.running():
            time.sleep(0.05)
        pstat.set_cell(False)
        normalized['cycles'] = cycles
        normalized['total_points'] = total_points
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        raw_data = _curve_data_to_lists(curve.acq_data())
        return _build_measurement_result_from_data(
            measurement_type='sine_wave',
            instrument_name=instrument_name,
            process_name=process_name,
            timestamp=timestamp,
            parameters=normalized,
            data=raw_data,
        )
    finally:
        if signal is not None:
            del signal
        if curve is not None:
            del curve
        release_pstat(tkp, pstat)
        del pstat


def collect_dpv(tkp, instrument_name, process_name, parameters):
    normalized = {
        'initial_voltage': float(parameters['initial_voltage']),
        'final_voltage': float(parameters['final_voltage']),
        'step_size': float(parameters['step_size']),
        'pulse_size': float(parameters['pulse_size']),
        'sample_period': float(parameters['sample_period']),
        'pulse_time': float(parameters['pulse_time']),
        'noise_rejection': bool(parameters.get('noise_rejection', True)),
        'irange_mode': str(parameters.get('irange_mode', 'fixed')).lower(),
        'max_current': float(parameters.get('max_current', 0.0003)),
        'current_range_mode': str(parameters.get('current_range_mode', 'auto')),
    }

    _validate_voltage_limit(
        normalized['initial_voltage'],
        normalized['final_voltage'],
        normalized['initial_voltage'] + normalized['pulse_size'],
        normalized['final_voltage'] + normalized['pulse_size'],
    )

    timer_resolution = 0.001
    prediction = _predict_dpv_point_count(
        normalized['initial_voltage'],
        normalized['final_voltage'],
        normalized['step_size'],
        normalized['sample_period'],
        normalized['pulse_time'],
        timer_resolution=timer_resolution,
    )
    max_cycles = prediction['cycle_count']
    predicted_raw_points = prediction['predicted_raw_points']
    max_curve_points = 262144
    if predicted_raw_points > max_curve_points:
        raise ValueError(
            'DPV experiment would exceed the acquisition buffer size '
            f'({predicted_raw_points} predicted points > {max_curve_points} max). '
            'Increase step size, reduce sample period, or reduce voltage span.'
        )

    cycle_time = normalized['sample_period']
    integration_period = min(normalized['pulse_time'], max(timer_resolution, normalized['pulse_time'] * 0.5))
    enable_override_a = False
    override_a = 0.0
    enable_override_b = False
    override_b = 0.0
    drop_knock_enabled = not normalized['noise_rejection']
    drop_knock_duration = normalized['pulse_time'] if drop_knock_enabled else 0.0
    drop_knock_polarity = False
    dpv_current_range_limit = normalized['max_current'] if normalized['irange_mode'] == 'fixed' else None
    dpv_current_range_mode = 'auto' if normalized['irange_mode'] == 'auto' else 'fixed'

    pstat = tkp.Pstat(instrument_name)
    curve = None
    signal = None
    try:
        _log_worker_event('dpv_start', instrument_name=instrument_name, process_name=process_name, parameters=normalized)
        pstat.set_ctrl_mode(tkp.PSTATMODE)
        initialize_pstat(tkp, pstat, dpv_current_range_mode, dpv_current_range_limit)
        _log_worker_event(
            'dpv_initialized',
            current_range_mode=normalized['current_range_mode'],
            dpv_irange_mode=normalized['irange_mode'],
            dpv_current_range_mode=dpv_current_range_mode,
            dpv_current_range_limit=dpv_current_range_limit,
        )
        signal = pstat.signal_pv_new(
            normalized['initial_voltage'],
            normalized['step_size'],
            normalized['pulse_size'],
            enable_override_a,
            override_a,
            enable_override_b,
            override_b,
            max_cycles,
            timer_resolution,
            normalized['pulse_time'],
            cycle_time,
            integration_period,
            drop_knock_enabled,
            drop_knock_duration,
            drop_knock_polarity,
            tkp.PSTATMODE,
        )
        _log_worker_event(
            'dpv_signal_created',
            max_cycles=max_cycles,
            cycle_time=cycle_time,
            integration_period=integration_period,
            predicted_raw_points=predicted_raw_points,
            samples_per_cycle=prediction['samples_per_cycle'],
            initial_voltage=normalized['initial_voltage'],
            step_size=normalized['step_size'],
            pulse_size=normalized['pulse_size'],
        )
        curve = tkp.CpivCurve(pstat, predicted_raw_points + 1000)
        pstat.set_signal_pv(signal)
        pstat.init_signal()
        pstat.set_cell(True)
        time.sleep(0.25)
        _log_worker_event('dpv_curve_run_begin')
        curve.run(True)
        expected_duration = max_cycles * cycle_time
        deadline = time.monotonic() + max(30.0, expected_duration * 3.0 + 5.0)
        loop_iterations = 0
        while tkp.pstat_is_valid(pstat) and curve.running():
            if time.monotonic() > deadline:
                raise TimeoutError(
                    'DPV acquisition did not complete within the expected time '
                    f'(max_cycles={max_cycles}, cycle_time={cycle_time}, pulse_time={normalized["pulse_time"]})'
                )
            loop_iterations += 1
            time.sleep(0.1)
        _log_worker_event('dpv_curve_run_complete', loop_iterations=loop_iterations, pstat_valid=tkp.pstat_is_valid(pstat))
        normalized['max_cycles'] = max_cycles
        normalized['timer_resolution'] = timer_resolution
        normalized['cycle_time'] = cycle_time
        normalized['integration_period'] = integration_period
        normalized['predicted_raw_points'] = predicted_raw_points
        normalized['samples_per_cycle'] = prediction['samples_per_cycle']
        normalized['max_curve_points'] = max_curve_points
        normalized['enable_override_a'] = enable_override_a
        normalized['override_a'] = override_a
        normalized['enable_override_b'] = enable_override_b
        normalized['override_b'] = override_b
        normalized['drop_knock_enabled'] = drop_knock_enabled
        normalized['drop_knock_duration'] = drop_knock_duration
        normalized['drop_knock_polarity'] = drop_knock_polarity
        raw_data = _curve_data_to_lists(curve.acq_data())
        _log_worker_event(
            'dpv_raw_data',
            keys=sorted(raw_data.keys()),
            lengths={key: len(value) for key, value in raw_data.items() if hasattr(value, '__len__')},
        )
        derived_trace = _derive_dpv_trace(raw_data, cycle_time, normalized['pulse_time'])
        if derived_trace is not None:
            _log_worker_event('dpv_derived_trace', point_count=len(derived_trace.get('current', [])))
            timing_summary = _summarize_dpv_timing(derived_trace, max_cycles, cycle_time)
            normalized.update(timing_summary)
            _log_worker_event('dpv_timing_summary', **timing_summary)
        else:
            _log_worker_event('dpv_derived_trace_empty')

        differential_trace = _calculate_dpv_differential_current(raw_data, normalized['sample_period'], normalized['pulse_time'])
        normalized['dpv_diff_point_count'] = int(differential_trace['point_count'])
        normalized['dpv_diff_skipped_cycles'] = int(differential_trace['skipped_cycles'])
        dpv_data = {
            'potential': differential_trace['voltage_v'],
            'current': differential_trace['diff_current_a'],
        }
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return {
            'mode': 'run_measurement',
            'measurement_type': 'differential_pulse_voltammetry',
            'x_key': 'potential',
            'y_key': 'current',
            'x_source': 'potential',
            'y_source': 'current',
            'instrument_name': instrument_name,
            'process_name': process_name,
            'timestamp': timestamp,
            'parameters': normalized,
            'data': dpv_data,
        }
    except Exception as exc:
        _log_worker_event('dpv_exception', error_type=exc.__class__.__name__, message=str(exc), traceback=traceback.format_exc())
        raise
    finally:
        _log_worker_event('dpv_cleanup_begin', has_signal=signal is not None, has_curve=curve is not None)
        if signal is not None:
            del signal
        if curve is not None:
            del curve
        release_pstat(tkp, pstat)
        del pstat
        _log_worker_event('dpv_cleanup_complete')


def run_measurement(tkp, instrument_name, process_name, measurement_mode, parameters):
    mode = str(measurement_mode).lower()
    expected_keys_by_mode = {
        'cv': [
            'initial_voltage', 'apex1_voltage', 'apex2_voltage', 'final_voltage',
            'apex1_hold', 'apex2_hold', 'final_hold', 'scan_rate', 'step_size',
            'cycles', 'scan_delay', 'current_range_mode',
        ],
        'ca': [
            'initial_voltage', 'step1_voltage', 'step2_voltage', 'initial_time',
            'step1_time', 'step2_time', 'sample_time', 'expected_max_v', 'current_range_mode',
        ],
        'sine': [
            'dc_offset', 'amplitude', 'signal_frequency', 'acq_frequency',
            'total_time', 'phase_offset', 'current_range_mode',
        ],
        'dpv': [
            'initial_voltage', 'final_voltage', 'step_size', 'pulse_size',
            'sample_period', 'pulse_time', 'noise_rejection', 'irange_mode',
            'max_current', 'current_range_mode',
        ],
    }
    if mode not in expected_keys_by_mode:
        raise ValueError(f'Unsupported measurement mode: {measurement_mode}')

    normalized_parameters = _normalize_parameters(parameters, expected_keys_by_mode[mode])
    if mode == 'cv':
        return collect_cv(
            tkp,
            instrument_name,
            process_name,
            normalized_parameters['initial_voltage'],
            normalized_parameters['apex1_voltage'],
            normalized_parameters['apex2_voltage'],
            normalized_parameters['final_voltage'],
            normalized_parameters['apex1_hold'],
            normalized_parameters['apex2_hold'],
            normalized_parameters['final_hold'],
            normalized_parameters['scan_rate'],
            normalized_parameters['step_size'],
            normalized_parameters['cycles'],
            normalized_parameters['scan_delay'],
            normalized_parameters['current_range_mode'],
        )
    try:
        if mode == 'ca':
            return collect_chronoamperometry(tkp, instrument_name, process_name, normalized_parameters)
        if mode == 'sine':
            return collect_sine(tkp, instrument_name, process_name, normalized_parameters)
        return collect_dpv(tkp, instrument_name, process_name, normalized_parameters)
    except Exception as exc:
        return {
            'mode': 'run_measurement',
            'measurement_type': mode,
            'instrument_name': instrument_name,
            'process_name': process_name,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'error': {
                'type': exc.__class__.__name__,
                'message': str(exc),
                'traceback': traceback.format_exc(),
            },
        }


_RpycServiceBase = rpyc.Service if rpyc is not None else object


class GamryBridgeService(_RpycServiceBase):
    tkp = None
    process_name = 'AFL_GamryDriver'
    active_pstat = None
    active_instrument_name = None

    @classmethod
    def release_active_pstat(cls):
        pstat = cls.active_pstat
        cls.active_pstat = None
        cls.active_instrument_name = None
        if pstat is None:
            return False
        release_pstat(cls.tkp, pstat)
        try:
            del pstat
        except Exception:
            pass
        return True

    def exposed_ping(self):
        return {
            'status': 'ok',
            'result': {
                'service': 'gamry_worker',
                'process_name': self.process_name,
                'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
        }

    def exposed_list_instruments(self):
        return {'status': 'ok', 'result': {'instruments': list_instruments(self.tkp)}}

    def exposed_validate_connection(self, instrument_name):
        self.release_active_pstat()
        pstat = self.tkp.Pstat(instrument_name)
        self.__class__.active_pstat = pstat
        self.__class__.active_instrument_name = instrument_name
        try:
            result = {
                'instrument_name': instrument_name,
                'model': getattr(pstat, 'modelname', lambda: None)() if hasattr(pstat, 'modelname') else None,
                'serial_number': getattr(pstat, 'serialno', lambda: None)() if hasattr(pstat, 'serialno') else None,
                'label': getattr(pstat, 'label', lambda: None)() if hasattr(pstat, 'label') else None,
            }
            return {'status': 'ok', 'result': result}
        except Exception:
            self.release_active_pstat()
            raise

    def exposed_release_connection(self):
        released = self.release_active_pstat()
        return {'status': 'ok', 'result': {'released': released}}

    def exposed_collect_cv(
        self,
        instrument_name,
        process_name,
        initial_voltage,
        apex1_voltage,
        apex2_voltage,
        final_voltage,
        apex1_hold,
        apex2_hold,
        final_hold,
        scan_rate,
        step_size,
        cycles,
        scan_delay,
        current_range_mode,
    ):
        if self.__class__.active_pstat is not None:
            active_name = self.__class__.active_instrument_name
            if active_name is None or active_name == instrument_name:
                self.release_active_pstat()
        return {
            'status': 'ok',
            'result': collect_cv(
                self.tkp,
                instrument_name,
                process_name,
                initial_voltage,
                apex1_voltage,
                apex2_voltage,
                final_voltage,
                apex1_hold,
                apex2_hold,
                final_hold,
                scan_rate,
                step_size,
                cycles,
                scan_delay,
                current_range_mode,
            ),
        }

    def exposed_run_measurement(self, instrument_name, process_name, measurement_mode, parameters):
        if self.__class__.active_pstat is not None:
            active_name = self.__class__.active_instrument_name
            if active_name is None or active_name == instrument_name:
                self.release_active_pstat()
        return {
            'status': 'ok',
            'result': run_measurement(
                self.tkp,
                instrument_name,
                process_name,
                measurement_mode,
                parameters,
            ),
        }


def serve(host, port, process_name):
    _, threaded_server_cls = _require_rpyc()
    tkp = _require_toolkitpy()

    _log_worker_event('worker_serve_start', host=host, port=port, process_name=process_name, python_executable=sys.executable)
    tkp.toolkitpy_init(process_name)
    GamryBridgeService.tkp = tkp
    GamryBridgeService.process_name = process_name
    server = threaded_server_cls(
        GamryBridgeService,
        hostname=host,
        port=port,
        protocol_config={
            'allow_public_attrs': True,
            'allow_all_attrs': True,
            'allow_pickle': False,
        },
    )
    try:
        print('RPYC_READY {} {}'.format(host, port), flush=True)
        _log_worker_event('worker_ready', host=host, port=port)
        server.start()
    finally:
        _log_worker_event('worker_shutdown')
        try:
            tkp.toolkitpy_close()
        except Exception:
            pass


def diagnose(process_name, instrument_name=None):
    tkp = _require_toolkitpy()

    report = {
        'status': 'ok',
        'process_name': process_name,
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'toolkit_module': getattr(tkp, '__file__', None),
        'python_executable': sys.executable,
        'python_version': sys.version,
        'instrument_name': instrument_name,
    }

    tkp.toolkitpy_init(process_name)
    try:
        instruments = list_instruments(tkp)
        report['enumerated_instruments'] = instruments
        report['instrument_count'] = len(instruments)

        if instrument_name:
            try:
                report['validate_connection'] = validate_connection(tkp, instrument_name)
            except Exception as exc:
                report['status'] = 'error'
                report['validate_connection_error'] = {
                    'type': exc.__class__.__name__,
                    'message': str(exc),
                    'traceback': traceback.format_exc(),
                }
        return report
    finally:
        try:
            tkp.toolkitpy_close()
        except Exception:
            pass


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == 'serve':
        process_name = sys.argv[4] if len(sys.argv) > 4 else 'AFL_GamryDriver'
        serve(sys.argv[2], int(sys.argv[3]), process_name)
        return

    if len(sys.argv) >= 2 and sys.argv[1] == 'diagnose':
        instrument_name = sys.argv[2] if len(sys.argv) > 2 else None
        process_name = sys.argv[3] if len(sys.argv) > 3 else 'AFL_GamryDriver'
        print(json.dumps(diagnose(process_name, instrument_name), indent=2))
        return

    raise SystemExit('Use: gamry_worker.py serve <host> <port> [process_name] or gamry_worker.py diagnose [instrument_name] [process_name]')


if __name__ == '__main__':
    main()
