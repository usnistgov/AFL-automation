import pytest
from AFL.automation.mixcalc.BalanceDiagnosis import BalanceDiagnosis, FailureCode
from AFL.automation.mixcalc.MassBalanceDriver import MassBalanceDriver
from AFL.automation.mixcalc.Solution import Solution
from AFL.automation.shared.units import units

@pytest.mark.usefixtures("mixdb")
def test_massbalance_driver_mixed_solvents_mass():
    mb = MassBalanceDriver()
    mb.config.write = False # need to disable writing to config file for testing
    # Isolate test behavior from any persisted user config in ~/.afl.
    mb.config['minimum_volume'] = '20 ul'
    mb.config['tol'] = 1e-3
    # Ensure prior user config does not leak into test expectations
    mb.reset_stocks()
    mb.reset_targets()
    # Add stocks
    mb.add_stock({
        'name': "Stock1",
        'masses': {"H2O": f"20 g"},
        'location': '1A1'
    })
    mb.add_stock({
        'name': "Stock2",
        'masses': {"Hexanes": f"20 g"},
        'location': '1A2'
    })
    mb.add_stock({
        'name': "Stock3",
        'masses': {"H2O": f"20 g"},
        'concentrations': {"NaCl": f"200 mg/ml"},
        'solutes': ["NaCl"],
        'location': '1A3'
    })
    # Add targets
    for ratio in [0.0, 0.25, 0.5, 0.75, 1.0]:
        mb.add_target({
            'name': "TestSolution",
            'mass_fractions': {"H2O": ratio, "Hexanes": 1.0 - ratio},
            'concentrations': {"NaCl": f"25 mg/ml"},
            'total_mass': "500 mg",
            'solutes': ["NaCl"]
        })
    mb.balance()
    assert len(mb.targets) == 5
    assert len(mb.stocks) == 3

    none_count = 0
    for i, result in enumerate(mb.balanced):
        balanced = result['balanced_target']

        if not result['success']:
            none_count += 1
            continue
        assert balanced.mass.to('mg').magnitude == pytest.approx(500)
        assert balanced.concentration['NaCl'].to('mg/ml').magnitude == pytest.approx(25)

        sub_balanced = balanced.copy()
        sub_target = Solution(**mb.config['targets'][i])
        del sub_balanced.components['NaCl']
        del sub_target.components['NaCl']

        assert sub_balanced.mass_fraction['H2O'] == pytest.approx(sub_target.mass_fraction['H2O'])
        assert sub_balanced.mass_fraction['Hexanes'] == pytest.approx(sub_target.mass_fraction['Hexanes'])

    assert none_count == 1


@pytest.mark.usefixtures("mixdb")
def test_massbalance_driver_balance_settings_and_progress():
    mb = MassBalanceDriver()
    mb.config.write = False
    # Isolate test behavior from any persisted user config in ~/.afl.
    mb.config['minimum_volume'] = '20 ul'
    mb.config['tol'] = 1e-3
    mb.reset_stocks()
    mb.reset_targets()

    mb.set_config(tol=2e-3)
    settings = mb.get_balance_settings()
    assert settings['tol'] == pytest.approx(2e-3)

    progress = mb.get_balance_progress()
    assert progress['active'] is False
    assert 'completed' in progress
    assert 'total' in progress

    mb.add_stock({
        'name': "Stock1",
        'masses': {"H2O": "20 g"},
        'location': '1A1'
    })
    mb.add_stock({
        'name': "Stock2",
        'masses': {"Hexanes": "20 g"},
        'location': '1A2'
    })
    mb.add_target({
        'name': "SimpleTarget",
        'mass_fractions': {"H2O": 0.5, "Hexanes": 0.5},
        'total_mass': "500 mg",
    })

    mb.balance()
    post = mb.get_balance_progress()
    assert post['active'] is False
    assert post['total'] == 1
    assert post['completed'] == 1


@pytest.mark.usefixtures("mixdb")
def test_massbalance_driver_rejects_zero_target_component_contamination():
    mb = MassBalanceDriver()
    mb.config.write = False
    mb.config['minimum_volume'] = '20 ul'
    mb.config['tol'] = 1e-3
    mb.reset_stocks()
    mb.reset_targets()

    mb.add_stock({
        'name': 'WaterStock',
        'masses': {'H2O': '20 g'},
        'location': '1A1',
    })
    mb.add_stock({
        'name': 'HexanesTraceSalt',
        'masses': {'Hexanes': '20 g', 'NaCl': '20 mg'},
        'solutes': ['NaCl'],
        'location': '1A2',
    })
    mb.add_target({
        'name': 'ZeroNaCl',
        'masses': {'H2O': '250 mg', 'Hexanes': '250 mg'},
    })

    mb.balance()

    result = mb.balanced[0]
    codes = [d.code for d in result['diagnosis'].details]
    assert result['success'] is False
    assert result['balanced_target'] is None
    assert FailureCode.UNWANTED_STOCK_COMPONENT in codes


@pytest.mark.usefixtures("mixdb")
def test_massbalance_driver_transfer_report_omits_zero_mass_transfers():
    mb = MassBalanceDriver()
    mb.config.write = False
    mb.config['minimum_volume'] = '20 ul'
    mb.config['tol'] = 1e-3
    mb.reset_stocks()
    mb.reset_targets()

    mb.add_stock({
        'name': 'WaterStock',
        'masses': {'H2O': '20 g'},
        'location': '1A1',
    })
    mb.add_stock({
        'name': 'HexanesStock',
        'masses': {'Hexanes': '20 g'},
        'location': '1A2',
    })
    mb.add_stock({
        'name': 'MysteryStock',
        'masses': {'Mystery_Solvent': '20 g'},
        'location': '1A3',
    })
    mb.add_target({
        'name': 'BinaryTarget',
        'masses': {'H2O': '250 mg', 'Hexanes': '250 mg'},
    })

    mb.balance()

    transfers = mb.balanced[0]['transfers']
    assert mb.balanced[0]['success'] is True
    assert transfers is not None
    assert set(stock.name for stock in transfers.keys()) == {'WaterStock', 'HexanesStock'}
    assert all(mass != '0.0 g' for mass in transfers.values())


def test_massbalance_driver_balance_status_metadata_exact_success():
    entry = {
        'success': True,
        'diagnosis': BalanceDiagnosis(
            success=True,
            component_errors={'H2O': 1e-16, 'NaCl': 0.0},
        ),
    }

    meta = MassBalanceDriver._balance_status_metadata(entry)

    assert meta['balance_status'] == 'succeeded'
    assert meta['max_component_error'] == pytest.approx(1e-16)


def test_massbalance_driver_balance_status_metadata_within_tolerance():
    entry = {
        'success': True,
        'diagnosis': BalanceDiagnosis(
            success=True,
            component_errors={'H2O': 0.02, 'NaCl': 0.0},
        ),
    }

    meta = MassBalanceDriver._balance_status_metadata(entry)

    assert meta['balance_status'] == 'within_tolerance'
    assert meta['max_component_error'] == pytest.approx(0.02)


def test_massbalance_driver_balance_status_metadata_failed():
    entry = {
        'success': False,
        'diagnosis': BalanceDiagnosis(
            success=False,
            component_errors={'H2O': 0.01, 'NaCl': 0.0},
        ),
    }

    meta = MassBalanceDriver._balance_status_metadata(entry)

    assert meta['balance_status'] == 'failed'
    assert meta['max_component_error'] == pytest.approx(0.01)


@pytest.mark.usefixtures("mixdb")
def test_massbalance_driver_balance_report_includes_status_metadata():
    mb = _build_balanced_massbalance_driver()

    report = mb.balance_report()

    assert report
    assert report[0]['balance_status'] == 'succeeded'
    assert 'max_component_error' in report[0]
    assert report[0]['max_component_error'] is not None


@pytest.mark.usefixtures("mixdb")
def test_massbalance_driver_collect_balanced_targets_includes_status_metadata():
    mb = _build_balanced_massbalance_driver()
    mb.balanced[0]['diagnosis'] = BalanceDiagnosis(
        success=True,
        component_errors={'H2O': 0.02, 'NaCl': 0.0},
    )
    mb.balanced[0]['success'] = True

    targets = mb._collect_balanced_targets()

    assert len(targets) == 1
    assert targets[0]['balance_success'] is True
    assert targets[0]['balance_status'] == 'within_tolerance'
    assert targets[0]['max_component_error'] == pytest.approx(0.02)


@pytest.mark.usefixtures("mixdb")
def test_massbalance_stock_history_local_fallback(monkeypatch):
    mb = MassBalanceDriver()
    mb.config.write = False
    mb.reset_stocks()
    mb.config['stock_history'] = []

    monkeypatch.setattr(
        mb,
        '_get_tiled_client',
        lambda: {'status': 'error', 'message': 'tiled unavailable for test'},
    )

    upload_result = mb.upload_stocks(
        stocks=[{'name': 'StockA', 'masses': {'H2O': '1 g'}}],
        reset=True,
        tags=['campaign-a', 'seed'],
    )
    assert upload_result['success'] is True
    assert upload_result['history_source'] == 'local'

    history = mb.list_stock_history()
    assert history['source'] == 'local'
    assert len(history['history']) == 1
    assert history['history'][0]['tags'] == ['campaign-a', 'seed']

    snapshot_id = history['history'][0]['id']
    loaded = mb.load_stock_history(snapshot_id=snapshot_id)
    assert loaded['success'] is True
    assert loaded['source'] == 'local'
    assert len(loaded['stocks']) == 1
    assert loaded['stocks'][0]['name'] == 'StockA'
