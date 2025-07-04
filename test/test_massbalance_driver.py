import pytest
from AFL.automation.mixing.MassBalance import MassBalanceDriver
from AFL.automation.mixing.Solution import Solution
from AFL.automation.shared.units import units

@pytest.mark.usefixtures("mixdb")
def test_massbalance_driver_mixed_solvents_mass():
    mb = MassBalanceDriver()
    mb.config.write = False # need to disable writing to config file for testing
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

        if balanced is None:
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

    assert none_count == 2 