import pytest

from AFL.automation.prepare.PrepareDriver import PrepareDriver


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
