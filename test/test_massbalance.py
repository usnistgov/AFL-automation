import pytest
from AFL.automation.mixcalc.MassBalance import MassBalance
from AFL.automation.mixcalc.Solution import Solution
from AFL.automation.mixcalc.TargetSolution import TargetSolution
from AFL.automation.shared.units import units


@pytest.mark.usefixtures("mixdb")
def test_mixed_solvents_mass():
    with MassBalance() as mb:
        Solution(
            name="Stock1",
            masses={"H2O": f"20 g"},
            location='1A1'
        )

        Solution(
            name="Stock2",
            masses={"Hexanes": f"20 g"},
            location = '1A2'
        )

        Solution(
            name="Stock3",
            masses={"H2O": f"20 g"},
            concentrations={"NaCl": f"200 mg/ml"},
            solutes= ["NaCl"],
            location = '1A3'
        )

        for ratio in [0.0,0.25,0.5,0.75,1.0]:
           TargetSolution(
                name="TestSolution",
                mass_fractions={"H2O": ratio, "Hexanes": 1.0-ratio},
                concentrations={"NaCl": f"25 mg/ml"},
                total_mass="500 mg",
                solutes=["NaCl"],
            )
    mb.balance()
    assert len(mb.targets) == 5
    assert len(mb.stocks) == 3

    none_count = 0
    for result in mb.balanced:
        target = result['target']
        balanced = result['balanced_target']


        if not result['success']:
            none_count += 1
            continue
        # Balancing now produces executable whole-microlitre aliquots.  At this
        # scale, rounding each stock transfer can shift the final composition
        # slightly from the continuous solver result.
        assert balanced.mass.to('mg').magnitude == pytest.approx(500, abs=1)
        assert balanced.concentration['NaCl'].to('mg/ml').magnitude == pytest.approx(25, abs=0.2)
        assert all(action.volume == int(action.volume) for action in balanced.protocol)

        sub_balanced = balanced.copy()
        sub_target = target.copy()
        del sub_balanced.components['NaCl']
        del sub_target.components['NaCl']

        assert sub_balanced.mass_fraction['H2O'].to('').magnitude == pytest.approx(
            sub_target.mass_fraction['H2O'].to('').magnitude, abs=2e-3
        )
        assert sub_balanced.mass_fraction['Hexanes'].to('').magnitude == pytest.approx(
            sub_target.mass_fraction['Hexanes'].to('').magnitude, abs=2e-3
        )

    assert none_count == 1


@pytest.mark.usefixtures("mixdb")
def test_balanced_protocol_inherits_stock_tip_location():
    with MassBalance() as mb:
        Solution(
            name="TipStock",
            masses={"H2O": "20 g"},
            location="1A1",
            tip="6A4",
        )
        TargetSolution(
            name="TipTarget",
            masses={"H2O": "500 mg"},
            location="5A1",
        )

    mb.balance()

    result = mb.balanced[0]
    assert result["success"] is True
    assert result["balanced_target"] is not None
    assert len(result["balanced_target"].protocol) == 1
    assert result["balanced_target"].protocol[0].tip_location == "6A4"


@pytest.mark.usefixtures("mixdb")
def test_balanced_protocol_inherits_stock_tip_location_list():
    with MassBalance() as mb:
        Solution(
            name="TipStockList",
            masses={"H2O": "20 g"},
            location="1A1",
            tip=["6A4", "9A4"],
        )
        TargetSolution(
            name="TipTargetList",
            masses={"H2O": "500 mg"},
            location="5A1",
        )

    mb.balance()

    result = mb.balanced[0]
    assert result["success"] is True
    assert result["balanced_target"] is not None
    assert len(result["balanced_target"].protocol) == 1
    assert result["balanced_target"].protocol[0].tip_location == ["6A4", "9A4"]
