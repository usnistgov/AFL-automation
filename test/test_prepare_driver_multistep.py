import pytest

from AFL.automation.prepare.PrepareDriver import PrepareDriver, capture_task_video


class DummyPrepare(PrepareDriver):
    defaults = {
        'prep_targets': [],
        'stocks': [],
        'fixed_compositions': {},
        'minimum_volume': '100 ul',
        'tol': 1e-3,
        'enable_multistep_dilution': True,
        'multistep_max_steps': 2,
        'multistep_diluent_policy': 'primary_solvent',
    }

    def __init__(self):
        super().__init__(driver_name='DummyPrepare')
        self.data = {}
        self.last_plan = None
        self.raise_on_plan = False
        self.raise_on_protocol_validation = False
        self.last_validated_protocol = None

    def resolve_destination(self, dest):
        if dest is not None:
            return dest
        if not self.config.get('prep_targets'):
            raise ValueError('No prep targets configured')
        queue = self.config['prep_targets']
        out = queue.pop(0)
        self.config['prep_targets'] = queue
        return out

    def execute_preparation(self, target, balanced_target, destination):
        self.last_plan = {
            'mode': 'single',
            'destination': destination,
            'protocol': [
                {
                    'source': step.source,
                    'dest': step.dest,
                    'volume': step.volume,
                }
                for step in getattr(balanced_target, 'protocol', [])
            ],
        }
        return True

    def execute_preparation_plan(self, target, balanced_target, destination, procedure_plan, intermediate_destinations):
        self.last_plan = {
            'mode': 'multistep',
            'destination': destination,
            'intermediate_destinations': list(intermediate_destinations),
            'procedure_plan': procedure_plan,
        }
        if self.raise_on_plan:
            raise RuntimeError('planned failure')
        return True

    def _validate_pipette_action_plan(self, protocol):
        self.last_validated_protocol = [
            {
                'source': step.source,
                'dest': step.dest,
                'volume': step.volume,
            }
            for step in protocol
        ]
        if self.raise_on_protocol_validation:
            raise ValueError('protocol contains infeasible transfer volume')


def test_capture_task_video_decorator_is_opt_in_and_finalizes_on_failure():
    class VideoDriver:
        def __init__(self):
            self.events = []

        def _start_task_video(self, task_name, output_filename):
            self.events.append(("start", task_name, output_filename))

        def _finish_task_video(self):
            self.events.append(("finish",))

        @capture_task_video("example.mp4")
        def operation(self, capture_task_video=False, fail=False):
            if fail:
                raise RuntimeError("planned failure")
            return "complete"

    driver = VideoDriver()

    assert driver.operation() == "complete"
    assert driver.events == []

    assert driver.operation(capture_task_video=True) == "complete"
    assert driver.events == [("start", "operation", "example.mp4"), ("finish",)]

    with pytest.raises(RuntimeError, match="planned failure"):
        driver.operation(capture_task_video=True, fail=True)
    assert driver.events[-2:] == [("start", "operation", "example.mp4"), ("finish",)]



def _seed_stocks(driver: DummyPrepare):
    driver.reset_stocks()
    driver.reset_targets()
    driver.add_stock({'name': 'Stock1', 'masses': {'H2O': '20 g'}, 'location': '1A1'})
    driver.add_stock({'name': 'Stock2', 'masses': {'Hexanes': '20 g'}, 'location': '1A2'})
    driver.add_stock({
        'name': 'Stock3',
        'masses': {'H2O': '20 g'},
        'concentrations': {'NaCl': '200 mg/ml'},
        'solutes': ['NaCl'],
        'location': '1A3',
    })


def _tiny_nacl_target():
    return {
        'name': 'TinyNaCl',
        'masses': {'H2O': '249.75 mg', 'Hexanes': '249.75 mg', 'NaCl': '0.5 mg'},
    }


def _binary_target():
    return {
        'name': 'BinaryBlend',
        'masses': {'H2O': '250 mg', 'Hexanes': '250 mg'},
    }


def _stock_fraction_target():
    return {
        'name': 'ColorSample',
        'location': '1A4',
        'stock_volume_fractions': {
            'Stock1': 0.3,
            'Stock2': 0.7,
        },
        'total_volume': '1000 ul',
    }


@pytest.mark.usefixtures('mixdb')
def test_prepare_multistep_consumes_multiple_prep_targets():
    driver = DummyPrepare()
    driver.config.write = False
    _seed_stocks(driver)
    driver.config['prep_targets'] = ['5A1', '5A2', '5A3']

    _, destination = driver.prepare(_tiny_nacl_target(), enable_multistep_dilution=True)

    assert destination == '5A2'
    assert driver.last_plan is not None
    assert driver.last_plan['mode'] == 'multistep'
    assert driver.last_plan['intermediate_destinations'] == ['5A1']
    assert driver.config['prep_targets'] == ['5A3']


@pytest.mark.usefixtures('mixdb')
def test_prepare_multistep_insufficient_targets_raises_without_consuming_queue():
    driver = DummyPrepare()
    driver.config.write = False
    _seed_stocks(driver)
    original = ['5A1']
    driver.config['prep_targets'] = list(original)

    with pytest.raises(ValueError, match='Not enough prep_targets entries'):
        driver.prepare(_tiny_nacl_target(), enable_multistep_dilution=True)

    assert driver.config['prep_targets'] == original


@pytest.mark.usefixtures('mixdb')
def test_prepare_multistep_restores_queue_on_execution_exception():
    driver = DummyPrepare()
    driver.config.write = False
    _seed_stocks(driver)
    original = ['5A1', '5A2', '5A3']
    driver.config['prep_targets'] = list(original)
    driver.raise_on_plan = True

    with pytest.raises(RuntimeError, match='planned failure'):
        driver.prepare(_tiny_nacl_target(), enable_multistep_dilution=True)

    assert driver.config['prep_targets'] == original


@pytest.mark.usefixtures('mixdb')
def test_prepare_records_metadata_for_single_step_prepare():
    driver = DummyPrepare()
    driver.config.write = False
    _seed_stocks(driver)
    driver.config['prep_targets'] = ['5A1']

    result, destination = driver.prepare(_binary_target(), enable_multistep_dilution=False)

    assert destination == '5A1'
    assert result['destination'] == '5A1'
    assert result['intermediate_destinations'] == []
    assert result['planned_mass_transfers'] is not None
    assert result['procedure_plan']['required_intermediate_targets'] == 0

    prepare_data = driver.data['prepare']
    assert prepare_data['requested_target']['name'] == 'BinaryBlend'
    assert prepare_data['applied_target']['name'] == 'BinaryBlend'
    assert prepare_data['destination'] == '5A1'
    assert prepare_data['intermediate_destinations'] == []
    assert prepare_data['execution_success'] is True
    assert prepare_data['planned_mass_transfers'] == result['planned_mass_transfers']
    assert prepare_data['executed_transfers'] == []


@pytest.mark.usefixtures('mixdb')
def test_prepare_records_metadata_for_multistep_prepare():
    driver = DummyPrepare()
    driver.config.write = False
    _seed_stocks(driver)
    driver.config['prep_targets'] = ['5A1', '5A2', '5A3']

    result, destination = driver.prepare(_tiny_nacl_target(), enable_multistep_dilution=True)

    assert destination == '5A2'
    assert result['destination'] == '5A2'
    assert result['intermediate_destinations'] == ['5A1']
    assert result['procedure_plan']['required_intermediate_targets'] == 1

    prepare_data = driver.data['prepare']
    assert prepare_data['destination'] == '5A2'
    assert prepare_data['intermediate_destinations'] == ['5A1']
    assert prepare_data['procedure_plan']['required_intermediate_targets'] == 1
    assert prepare_data['execution_success'] is True


def test_prepare_driver_default_composition_format_is_masses():
    driver = DummyPrepare()
    driver.config.write = False

    assert driver.config['composition_format'] == 'masses'


@pytest.mark.usefixtures('mixdb')
def test_is_feasible_accepts_stock_volume_fraction_targets():
    driver = DummyPrepare()
    driver.config.write = False
    _seed_stocks(driver)

    feasible = driver.is_feasible(_stock_fraction_target(), enable_multistep_dilution=False)

    assert feasible == [{
        'name': 'ColorSample',
        'location': '1A4',
        'total_volume': '1000.0 ul',
        'stock_volume_fractions': {'Stock1': 0.3, 'Stock2': 0.7},
        'stock_transfer_volumes_ul': {'Stock1': 300.0, 'Stock2': 700.0},
    }]


@pytest.mark.usefixtures('mixdb')
def test_prepare_accepts_stock_volume_fraction_targets():
    driver = DummyPrepare()
    driver.config.write = False
    _seed_stocks(driver)
    driver.config['prep_targets'] = ['5A1']

    result, destination = driver.prepare(_stock_fraction_target(), enable_multistep_dilution=False)

    assert destination == '5A1'
    assert result['destination'] == '5A1'
    assert result['intermediate_destinations'] == []
    assert result['planned_mass_transfers'] is None
    assert result['procedure_plan']['mode'] == 'stock_volume_fractions'
    assert result['stock_volume_fractions'] == {'Stock1': 0.3, 'Stock2': 0.7}
    assert result['stock_transfer_volumes_ul'] == {'Stock1': 300.0, 'Stock2': 700.0}
    assert driver.last_plan['mode'] == 'single'
    assert driver.last_plan['destination'] == '5A1'
    assert driver.last_plan['protocol'] == [
        {'source': '1A1', 'dest': '1A4', 'volume': 300.0},
        {'source': '1A2', 'dest': '1A4', 'volume': 700.0},
    ]
    assert driver.last_validated_protocol == [
        {'source': '1A1', 'dest': '1A4', 'volume': 300.0},
        {'source': '1A2', 'dest': '1A4', 'volume': 700.0},
    ]

    prepare_data = driver.data['prepare']
    assert prepare_data['requested_target']['stock_volume_fractions'] == {'Stock1': 0.3, 'Stock2': 0.7}
    assert prepare_data['balanced_target']['stock_transfer_volumes_ul'] == {'Stock1': 300.0, 'Stock2': 700.0}
    assert prepare_data['execution_success'] is True


@pytest.mark.usefixtures('mixdb')
def test_is_feasible_rejects_stock_volume_fraction_targets_with_invalid_protocol_volumes():
    driver = DummyPrepare()
    driver.config.write = False
    driver.raise_on_protocol_validation = True
    _seed_stocks(driver)

    feasible = driver.is_feasible(_stock_fraction_target(), enable_multistep_dilution=False)

    assert feasible == [None]
    assert driver.last_validated_protocol == [
        {'source': '1A1', 'dest': '1A4', 'volume': 300.0},
        {'source': '1A2', 'dest': '1A4', 'volume': 700.0},
    ]


@pytest.mark.usefixtures('mixdb')
def test_is_feasible_reports_missing_direct_recipe_stocks():
    driver = DummyPrepare()
    driver.config.write = False

    target = {
        'name': 'MissingStockRecipe',
        'location': '1A4',
        'stock_volume_fractions': {'stock_Red': 1.0},
        'total_volume': '1000 ul',
    }

    with pytest.warns(UserWarning, match='configured stock.*stock_Red'):
        assert driver.is_feasible(target, enable_multistep_dilution=False) == [None]

    assert 'stock_Red' in driver.last_feasibility_errors[0]
    assert 'Currently configured stocks: none' in driver.last_feasibility_errors[0]


@pytest.mark.usefixtures('mixdb')
def test_prepare_rejects_stock_volume_fraction_targets_with_invalid_protocol_volumes():
    driver = DummyPrepare()
    driver.config.write = False
    driver.raise_on_protocol_validation = True
    _seed_stocks(driver)
    driver.config['prep_targets'] = ['5A1']

    with pytest.raises(ValueError, match='not feasible.*protocol.*volume'):
        driver.prepare(_stock_fraction_target(), enable_multistep_dilution=False)

    assert driver.last_validated_protocol == [
        {'source': '1A1', 'dest': '1A4', 'volume': 300.0},
        {'source': '1A2', 'dest': '1A4', 'volume': 700.0},
    ]


@pytest.mark.usefixtures('mixdb')
def test_prepare_rejects_stock_volume_fraction_targets_that_do_not_sum_to_one():
    driver = DummyPrepare()
    driver.config.write = False
    _seed_stocks(driver)
    driver.config['prep_targets'] = ['5A1']
    bad_target = _stock_fraction_target()
    bad_target['stock_volume_fractions'] = {'Stock1': 0.3, 'Stock2': 0.6}

    with pytest.raises(ValueError, match='not feasible.*must sum to 1.0'):
        driver.prepare(bad_target, enable_multistep_dilution=False)
