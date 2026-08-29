import warnings

import pytest
from AFL.automation.mixcalc.BalanceDiagnosis import BalanceDiagnosis, FailureCode
from AFL.automation.mixcalc.MassBalanceDriver import MassBalanceDriver
from AFL.automation.mixcalc.Solution import Solution
from AFL.automation.shared.units import units
from AFL.automation.shared.warnings import MixWarning


def _build_balanced_massbalance_driver():
    mb = MassBalanceDriver()
    mb.config.write = False
    mb.config['minimum_volume'] = '20 ul'
    mb.config['tol'] = 1e-3
    mb.reset_stocks()
    mb.reset_targets()
    mb.add_stock({
        'name': 'WaterStock',
        'masses': {'H2O': '20 g'},
        'location': '1A1'
    })
    mb.add_stock({
        'name': 'SaltStock',
        'masses': {'H2O': '20 g'},
        'concentrations': {'NaCl': '200 mg/ml'},
        'solutes': ['NaCl'],
        'location': '1A2'
    })
    mb.add_target({
        'name': 'Target',
        'concentrations': {'NaCl': '25 mg/ml'},
        'mass_fractions': {'H2O': 1.0},
        'total_volume': '1 ml',
        'solutes': ['NaCl']
    })
    mb.balance()
    assert mb.balanced
    assert mb.balanced[0]['success'] is True
    return mb


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
        # Integer-ul aliquots can differ slightly from the continuous ideal
        # mass balance; the reported solution is built from those executable
        # aliquots and must remain within one microlitre-scale increment.
        assert balanced.mass.to('mg').magnitude == pytest.approx(500, abs=1.0)
        assert balanced.concentration['NaCl'].to('mg/ml').magnitude == pytest.approx(25, abs=0.2)
        assert all(float(action.volume).is_integer() for action in balanced.protocol)

        sub_balanced = balanced.copy()
        sub_target = Solution(**mb.config['targets'][i])
        del sub_balanced.components['NaCl']
        del sub_target.components['NaCl']

        assert sub_balanced.mass_fraction['H2O'] == pytest.approx(
            sub_target.mass_fraction['H2O'], abs=0.002
        )
        assert sub_balanced.mass_fraction['Hexanes'] == pytest.approx(
            sub_target.mass_fraction['Hexanes'], abs=0.002
        )

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
def test_add_stock_normalizes_legacy_single_source_payload():
    mb = MassBalanceDriver()
    mb.config.write = False
    mb.reset_stocks()

    mb.add_stock(
        {
            'name': 'WaterStock',
            'masses': {'H2O': '20 g'},
            'location': '1a1',
            'total_volume': '10 ml',
            'tip_location': ['2A1', '2A2'],
        }
    )

    assert mb.config['stocks'] == [
        {
            'name': 'WaterStock',
            'masses': {'H2O': '20 g'},
            'tip_location': ['2A1', '2A2'],
            'sources': [{'location': '1A1', 'initial_volume': '10 ml'}],
        }
    ]
    assert mb.config['stock_inventory'] == {
        'WaterStock@1A1': {'remaining_volume': '10 ml'}
    }


@pytest.mark.usefixtures("mixdb")
def test_upload_stocks_preserves_multi_source_schema_and_list_stocks_reports_remaining_volume():
    mb = MassBalanceDriver()
    mb.config.write = False
    mb.reset_stocks()

    result = mb.upload_stocks(
        stocks=[
            {
                'name': 'BufferA',
                'masses': {'H2O': '20 g'},
                'tip_location': ['6A1', '6A2'],
                'sources': [
                    {'location': '1A1', 'initial_volume': '700 ul'},
                    {'location': '1A2', 'initial_volume': '1000 ul'},
                ],
            }
        ],
        reset=True,
    )

    assert result['success'] is True
    assert len(mb.stocks) == 2
    listed = mb.list_stocks()
    assert listed == [
        {
            'name': 'BufferA',
            'masses': {'H2O': '20 g'},
            'tip_location': ['6A1', '6A2'],
            'sources': [
                {'location': '1A1', 'initial_volume': '700 ul', 'stock_id': 'BufferA@1A1', 'remaining_volume': '700 ul'},
                {'location': '1A2', 'initial_volume': '1000 ul', 'stock_id': 'BufferA@1A2', 'remaining_volume': '1000 ul'},
            ],
            'remaining_volume': '1700.0 ul',
        }
    ]


@pytest.mark.usefixtures("mixdb")
def test_multi_source_stock_preserves_recipe_volume_and_uses_source_inventory():
    mb = MassBalanceDriver()
    mb.config.write = False
    mb.reset_stocks()

    mb.add_stock(
        {
            "name": "stock_NaCl",
            "total_volume": "20 ml",
            "volumes": {"H2O": "20 ml"},
            "concentrations": {"NaCl": "1 mg/ml"},
            "solutes": ["NaCl"],
            "sources": [
                {"location": "2A1", "initial_volume": "350 ul"},
                {"location": "2A2", "initial_volume": "100 ul"},
                {"location": "2B1", "initial_volume": "100 ul"},
            ],
        }
    )

    assert mb.config["stocks"][0]["total_volume"] == "20 ml"
    assert [float(stock.volume.to("ul").magnitude) for stock in mb.stocks] == pytest.approx(
        [350.0, 100.0, 100.0]
    )
    assert all(
        float(stock.concentration["NaCl"].to("mg/ml").magnitude) == pytest.approx(1.0)
        for stock in mb.stocks
    )


@pytest.mark.usefixtures("mixdb")
def test_multi_source_inventory_does_not_rescale_recipe_during_construction():
    mb = MassBalanceDriver()
    mb.config.write = False
    mb.reset_stocks()

    stock_definition = {
        "name": "stock_NaCl",
        "volumes": {"H2O": "20 ml"},
        "concentrations": {"NaCl": "1 mg/ml"},
        "solutes": ["NaCl"],
        "sources": [
            {"location": "2A1", "initial_volume": "20 ml"},
            {"location": "2B1", "initial_volume": "20 ml"},
        ],
    }

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        mb.add_stock(stock_definition)

    assert not [warning for warning in caught if issubclass(warning.category, MixWarning)]
    assert [float(stock.volume.to("ml").magnitude) for stock in mb.stocks] == [20.0, 20.0]

    mb.config["stock_inventory"]["stock_NaCl@2A1"] = {
        "remaining_volume": "10 ml"
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        mb.process_stocks()

    assert not [warning for warning in caught if issubclass(warning.category, MixWarning)]
    assert [float(stock.volume.to("ml").magnitude) for stock in mb.stocks] == [10.0, 20.0]
    assert [
        float(stock.concentration["NaCl"].to("mg/ml").magnitude)
        for stock in mb.stocks
    ] == pytest.approx([1.0, 1.0])


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


@pytest.mark.usefixtures("mixdb")
def test_get_sample_composition_supports_masses():
    mb = _build_balanced_massbalance_driver()

    composition = mb.get_sample_composition('masses')
    balanced_target = mb.balanced[-1]['balanced_target']

    assert composition['H2O'] == pytest.approx(
        balanced_target['H2O'].mass.to('mg').magnitude
    )
    assert composition['NaCl'] == pytest.approx(
        balanced_target['NaCl'].mass.to('mg').magnitude
    )


@pytest.mark.usefixtures("mixdb")
def test_get_sample_composition_dict_requires_all_components():
    mb = _build_balanced_massbalance_driver()

    with pytest.raises(ValueError, match='must specify every component'):
        mb.get_sample_composition({'H2O': 'masses'})


@pytest.mark.usefixtures("mixdb")
def test_get_sample_composition_dict_accepts_mixed_formats():
    mb = _build_balanced_massbalance_driver()

    composition = mb.get_sample_composition({
        'H2O': 'masses',
        'NaCl': 'concentration',
    })
    balanced_target = mb.balanced[-1]['balanced_target']

    assert composition['H2O'] == pytest.approx(
        balanced_target['H2O'].mass.to('mg').magnitude
    )
    assert composition['NaCl'] == pytest.approx(
        balanced_target.concentration['NaCl'].to('mg/ml').magnitude
    )
