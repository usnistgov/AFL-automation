import pytest

from AFL.automation.mixcalc.MassBalance import MassBalance
from AFL.automation.mixcalc.Solution import Solution
from AFL.automation.mixcalc.TargetSolution import TargetSolution


@pytest.mark.usefixtures("mixdb")
def test_multistep_dilution_can_recover_minimum_volume_failure():
    with MassBalance(minimum_volume='100 ul') as mb:
        Solution(name="Stock1", masses={"H2O": "20 g"}, location='1A1')
        Solution(name="Stock2", masses={"Hexanes": "20 g"}, location='1A2')
        Solution(
            name="Stock3",
            masses={"H2O": "20 g"},
            concentrations={"NaCl": "200 mg/ml"},
            solutes=["NaCl"],
            location='1A3',
        )
        TargetSolution(
            name="TinyNaCl",
            masses={"H2O": "249.75 mg", "Hexanes": "249.75 mg", "NaCl": "0.5 mg"},
        )

    mb.targets[0].location = '9A1'
    mb.balance(enable_multistep_dilution=True, multistep_max_steps=2)

    assert mb.balanced
    result = mb.balanced[0]
    assert result['success'] is True
    procedure_plan = result.get('procedure_plan')
    assert procedure_plan is not None
    assert procedure_plan['enabled'] is True
    assert procedure_plan['required_intermediate_targets'] >= 1
    stage_types = [s.get('stage_type') for s in procedure_plan.get('stages', [])]
    assert 'dilution' in stage_types
    assert 'final_mix' in stage_types


@pytest.mark.usefixtures("mixdb")
def test_multistep_disabled_keeps_single_step_failure_behavior():
    with MassBalance(minimum_volume='100 ul') as mb:
        Solution(name="Stock1", masses={"H2O": "20 g"}, location='1A1')
        Solution(name="Stock2", masses={"Hexanes": "20 g"}, location='1A2')
        Solution(
            name="Stock3",
            masses={"H2O": "20 g"},
            concentrations={"NaCl": "200 mg/ml"},
            solutes=["NaCl"],
            location='1A3',
        )
        TargetSolution(
            name="TinyNaCl",
            masses={"H2O": "249.75 mg", "Hexanes": "249.75 mg", "NaCl": "0.5 mg"},
        )

    mb.targets[0].location = '9A1'
    mb.balance(enable_multistep_dilution=False)

    assert mb.balanced
    result = mb.balanced[0]
    assert result['success'] is False
