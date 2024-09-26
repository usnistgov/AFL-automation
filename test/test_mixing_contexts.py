import pytest
from AFL.automation.mixing.MassBalance import MassBalance
from AFL.automation.mixing.Solution import Solution

@pytest.mark.usefixtures('mixdb')
def test_massbalance_context_add_solution():
    with MassBalance() as mb:
        solution1 = Solution(
            name='Solution1',
            volumes={'H2O': '10 ml', 'Hexanes': '2 ml'},
            concentrations={'NaCl': '200 mg/ml'},
            total_volume='10 ml'
        )
        solution2 = Solution(
            name='Solution1',
            volumes={'H2O': '10 ml', 'Hexanes': '2 ml'},
            concentrations={'NaCl': '0 mg/ml'},
            total_volume='10 ml'
        )

    assert solution1 in mb.stocks
    assert solution2 in mb.stocks

@pytest.mark.usefixtures('mixdb')
def test_massbalance_context_reset():
    with MassBalance() as mb:
        solution1 = Solution(
            name='Solution1',
            volumes={'H2O': '10 ml', 'Hexanes': '2 ml'},
            concentrations={'NaCl': '200 mg/ml'},
            total_volume='10 ml'
        )
        solution2 = Solution(
            name='Solution1',
            volumes={'H2O': '10 ml', 'Hexanes': '2 ml'},
            concentrations={'NaCl': '100 mg/ml'},
            total_volume='10 ml'
        )

    with mb(reset=True):
        solution3 = Solution(
            name='Solution1',
            volumes={'H2O': '20 ml', 'Hexanes':'0 ml' },
            concentrations={'NaCl': '0 mg/ml'},
            total_volume='10 ml'
        )

    assert solution1 not in mb.stocks
    assert solution2 not in mb.stocks
    assert solution3 in mb.stocks

@pytest.mark.usefixtures('mixdb')
def test_nested_massbalance_contexts():
    with MassBalance() as mb_outer:
        solution_outer = Solution(
            name='OuterSolution',
            volumes={'H2O': '10 ml'},
            concentrations={'NaCl': '100 mg/ml'},
            total_volume='10 ml'
        )

        with MassBalance() as mb_inner:
            solution_inner = Solution(
                name='InnerSolution',
                volumes={'H2O': '5 ml'},
                concentrations={'NaCl': '50 mg/ml'},
                total_volume='5 ml'
            )

    assert solution_inner in mb_inner.stocks
    assert solution_outer not in mb_inner.stocks

    assert solution_outer in mb_outer.stocks
    assert solution_inner not in mb_outer.stocks