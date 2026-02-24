import pytest

from AFL.automation.mixing.MassBalance import MassBalance
from AFL.automation.mixing.Solution import Solution
from AFL.automation.mixing.TargetSolution import TargetSolution
from AFL.automation.mixing.BalanceDiagnosis import BalanceDiagnosis, FailureCode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_standard_stocks(mb_context):
    """Add the three standard test stocks inside an active MassBalance context."""
    Solution(name="Stock1", masses={"H2O": "20 g"}, location='1A1')
    Solution(name="Stock2", masses={"Hexanes": "20 g"}, location='1A2')
    Solution(
        name="Stock3",
        masses={"H2O": "20 g"},
        concentrations={"NaCl": "200 mg/ml"},
        solutes=["NaCl"],
        location='1A3',
    )


# ---------------------------------------------------------------------------
# Basic structure tests
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("mixdb")
def test_diagnosis_key_present_for_all_results():
    """Every balanced entry must have a 'diagnosis' key."""
    with MassBalance() as mb:
        _make_standard_stocks(mb)
        for ratio in [0.0, 0.5, 1.0]:
            TargetSolution(
                name=f"T{ratio}",
                mass_fractions={"H2O": ratio, "Hexanes": 1.0 - ratio},
                concentrations={"NaCl": "25 mg/ml"},
                total_mass="500 mg",
                solutes=["NaCl"],
            )
    mb.balance()

    for result in mb.balanced:
        assert 'diagnosis' in result
        assert isinstance(result['diagnosis'], BalanceDiagnosis)


@pytest.mark.usefixtures("mixdb")
def test_diagnosis_success():
    """A successful balance produces diagnosis.success=True and no details."""
    with MassBalance() as mb:
        _make_standard_stocks(mb)
        TargetSolution(
            name="Mid",
            mass_fractions={"H2O": 0.5, "Hexanes": 0.5},
            concentrations={"NaCl": "25 mg/ml"},
            total_mass="500 mg",
            solutes=["NaCl"],
        )
    mb.balance()

    result = mb.balanced[0]
    assert result['success'] is True
    diag = result['diagnosis']
    assert diag.success is True
    assert diag.details == []


@pytest.mark.usefixtures("mixdb")
def test_diagnosis_tolerance_exceeded_always_present_on_failure():
    """TOLERANCE_EXCEEDED is always present when success=False."""
    with MassBalance() as mb:
        _make_standard_stocks(mb)
        TargetSolution(
            name="PureHexanes",
            mass_fractions={"H2O": 0.0, "Hexanes": 1.0},
            concentrations={"NaCl": "25 mg/ml"},
            total_mass="500 mg",
            solutes=["NaCl"],
        )
    mb.balance()

    result = mb.balanced[0]
    assert result['success'] is False
    codes = [d.code for d in result['diagnosis'].details]
    assert FailureCode.TOLERANCE_EXCEEDED in codes


@pytest.mark.usefixtures("mixdb")
def test_diagnosis_component_errors_populated():
    """component_errors maps every component name to its signed relative error."""
    with MassBalance() as mb:
        _make_standard_stocks(mb)
        TargetSolution(
            name="PureHexanes",
            mass_fractions={"H2O": 0.0, "Hexanes": 1.0},
            concentrations={"NaCl": "25 mg/ml"},
            total_mass="500 mg",
            solutes=["NaCl"],
        )
    mb.balance()

    diag = mb.balanced[0]['diagnosis']
    # All components should appear in component_errors
    assert len(diag.component_errors) > 0
    for comp, err in diag.component_errors.items():
        assert isinstance(comp, str)
        assert isinstance(err, float)


# ---------------------------------------------------------------------------
# MISSING_STOCK_COMPONENT
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("mixdb")
def test_diagnosis_missing_stock_component():
    """MISSING_STOCK_COMPONENT fires when a target component is absent from all stocks."""
    with MassBalance() as mb:
        # Stocks contain only H2O and Hexanes — no Mystery_Solvent
        Solution(name="Stock1", masses={"H2O": "20 g"}, location='1A1')
        Solution(name="Stock2", masses={"Hexanes": "20 g"}, location='1A2')
        # Target requests Mystery_Solvent which is not in any stock
        TargetSolution(
            name="MysteryTarget",
            mass_fractions={"H2O": 0.5, "Hexanes": 0.3, "Mystery_Solvent": 0.2},
            total_mass="500 mg",
        )
    mb.balance()

    diag = mb.balanced[0]['diagnosis']
    codes = [d.code for d in diag.details]
    assert FailureCode.MISSING_STOCK_COMPONENT in codes

    detail = next(d for d in diag.details if d.code == FailureCode.MISSING_STOCK_COMPONENT)
    assert "Mystery_Solvent" in detail.affected_components


# ---------------------------------------------------------------------------
# STOCK_CONCENTRATION_TOO_LOW
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("mixdb")
def test_diagnosis_stock_concentration_too_low():
    """STOCK_CONCENTRATION_TOO_LOW fires when the target fraction exceeds the max stock fraction."""
    with MassBalance() as mb:
        # Stock with very dilute NaCl: ~1 mg/ml in 20 g H2O → NaCl fraction ≈ 0.001
        Solution(
            name="DiluteSaline",
            masses={"H2O": "20 g"},
            concentrations={"NaCl": "1 mg/ml"},
            solutes=["NaCl"],
            location='1A1',
        )
        Solution(name="HexanesStock", masses={"Hexanes": "20 g"}, location='1A2')
        # Target: NaCl mass fraction = 200/(200+300) = 0.40 >> 0.001
        TargetSolution(
            name="HighNaCl",
            masses={"NaCl": "200 mg", "H2O": "300 mg"},
        )
    mb.targets[0].location = None
    mb.balance()

    diag = mb.balanced[0]['diagnosis']
    codes = [d.code for d in diag.details]
    assert FailureCode.STOCK_CONCENTRATION_TOO_LOW in codes

    detail = next(d for d in diag.details if d.code == FailureCode.STOCK_CONCENTRATION_TOO_LOW)
    assert "NaCl" in detail.affected_components
    assert detail.data["target_mass_fraction"] > detail.data["max_achievable_mass_fraction"]


# ---------------------------------------------------------------------------
# TARGET_OUTSIDE_REACHABLE_COMPOSITIONS
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("mixdb")
def test_diagnosis_target_outside_reachable_compositions():
    """TARGET_OUTSIDE_REACHABLE_COMPOSITIONS fires when the target lies outside the stock hull.

    Classic coupled-component scenario:
      Stock A provides H2O + NaCl.
      Stock B provides Mystery_Solvent + NaCl.
      Target wants H2O + Mystery_Solvent but ZERO NaCl.
    Any non-negative combination of A and B introduces NaCl, so the target is
    geometrically unreachable regardless of volume constraints.
    """
    with MassBalance(minimum_volume='5 ul') as mb:
        # Stock A: equal masses H2O and NaCl
        Solution(
            name="StockA",
            masses={"H2O": "10 g", "NaCl": "10 g"},
            location='1A1',
        )
        # Stock B: equal masses Mystery_Solvent and NaCl
        Solution(
            name="StockB",
            masses={"Mystery_Solvent": "10 g", "NaCl": "10 g"},
            location='1A2',
        )
        # Target wants H2O + Mystery_Solvent, no NaCl
        TargetSolution(
            name="NoNaCl",
            masses={"H2O": "250 mg", "Mystery_Solvent": "250 mg"},
        )
    mb.targets[0].location = None
    mb.balance()

    diag = mb.balanced[0]['diagnosis']
    codes = [d.code for d in diag.details]
    assert FailureCode.TARGET_OUTSIDE_REACHABLE_COMPOSITIONS in codes


# ---------------------------------------------------------------------------
# BELOW_MINIMUM_PIPETTE_VOLUME
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("mixdb")
def test_diagnosis_below_minimum_pipette_volume():
    """BELOW_MINIMUM_PIPETTE_VOLUME fires when a stock is excluded due to min-volume constraint."""
    # Use a large minimum_volume so that Stock3's minimum contribution of NaCl far
    # exceeds what the target needs, causing the solver to zero out Stock3.
    # Target wants only 0.5 mg NaCl but 100 ul of Stock3 (200 mg/ml) delivers ~20 mg.
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
        # Tiny NaCl requirement: 0.5 mg in 500 mg total (fraction ≈ 0.001)
        TargetSolution(
            name="TinyNaCl",
            masses={"H2O": "249.75 mg", "Hexanes": "249.75 mg", "NaCl": "0.5 mg"},
        )
    mb.targets[0].location = None
    mb.balance()

    diag = mb.balanced[0]['diagnosis']
    codes = [d.code for d in diag.details]
    assert FailureCode.BELOW_MINIMUM_PIPETTE_VOLUME in codes

    detail = next(d for d in diag.details if d.code == FailureCode.BELOW_MINIMUM_PIPETTE_VOLUME)
    assert "Stock3" in detail.affected_stocks


# ---------------------------------------------------------------------------
# UNWANTED_STOCK_COMPONENT
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("mixdb")
def test_diagnosis_unwanted_stock_component():
    """UNWANTED_STOCK_COMPONENT is tolerance-gated for unwanted contamination.

    Stock B provides NaCl (needed) but also H2O (unwanted, target=0).
    With a small minimum_volume the solver includes Stock B for NaCl, bringing
    H2O contamination, but in this setup the computed zero-target relative error
    is below the 5% tolerance so UNWANTED_STOCK_COMPONENT is not emitted.
    """
    with MassBalance(minimum_volume='5 ul') as mb:
        # Stock A: pure Hexanes
        Solution(name="StockA", masses={"Hexanes": "20 g"}, location='1A1')
        # Stock B: 80% H2O + 20% NaCl (by mass)
        Solution(name="StockB", masses={"H2O": "16 g", "NaCl": "4 g"}, location='1A2')
        # Target: 80% Hexanes + 20% NaCl, ZERO H2O.
        # NaCl target fraction (0.20) == max NaCl stock fraction (0.20 in StockB), so
        # STOCK_CONCENTRATION_TOO_LOW does not fire.  The solver must use ~29mg of StockB
        # to partially satisfy NaCl, delivering ~23mg of unwanted H2O.
        # Zero-target relative error is computed against total target mass (500 mg),
        # so this is ~4.7%, below the 5% tolerance gate for UNWANTED_STOCK_COMPONENT.
        TargetSolution(
            name="HexanesNaCl",
            masses={"Hexanes": "400 mg", "NaCl": "100 mg"},
        )
    mb.targets[0].location = None
    mb.balance()

    diag = mb.balanced[0]['diagnosis']
    codes = [d.code for d in diag.details]
    assert FailureCode.UNWANTED_STOCK_COMPONENT not in codes
    assert FailureCode.TARGET_OUTSIDE_REACHABLE_COMPOSITIONS in codes
    assert FailureCode.TOLERANCE_EXCEEDED in codes


# ---------------------------------------------------------------------------
# failure_summary() and balance_report()
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("mixdb")
def test_failure_summary_string():
    """failure_summary() returns a non-empty string for failed balances."""
    with MassBalance() as mb:
        _make_standard_stocks(mb)
        TargetSolution(
            name="PureHexanes",
            mass_fractions={"H2O": 0.0, "Hexanes": 1.0},
            concentrations={"NaCl": "25 mg/ml"},
            total_mass="500 mg",
            solutes=["NaCl"],
        )
    mb.balance()

    summary = mb.failure_summary()
    assert isinstance(summary, str)
    assert len(summary) > 0
    assert "PureHexanes" in summary
    # At least one failure code name should appear
    code_values = [c.value for c in FailureCode]
    assert any(v in summary for v in code_values)


@pytest.mark.usefixtures("mixdb")
def test_failure_summary_empty_on_all_success():
    """failure_summary() returns an empty string when all balances succeed."""
    with MassBalance() as mb:
        _make_standard_stocks(mb)
        TargetSolution(
            name="Mid",
            mass_fractions={"H2O": 0.5, "Hexanes": 0.5},
            concentrations={"NaCl": "25 mg/ml"},
            total_mass="500 mg",
            solutes=["NaCl"],
        )
    mb.balance()

    assert mb.balanced[0]['success'] is True
    assert mb.failure_summary() == ""


@pytest.mark.usefixtures("mixdb")
def test_balance_report_includes_diagnosis():
    """balance_report() includes a 'diagnosis' key for every entry."""
    with MassBalance() as mb:
        _make_standard_stocks(mb)
        for ratio in [0.0, 0.5, 1.0]:
            TargetSolution(
                name=f"T{ratio}",
                mass_fractions={"H2O": ratio, "Hexanes": 1.0 - ratio},
                concentrations={"NaCl": "25 mg/ml"},
                total_mass="500 mg",
                solutes=["NaCl"],
            )
    report = mb.balance(return_report=True)

    for entry in report:
        assert 'diagnosis' in entry
        assert entry['diagnosis'] is not None
        assert 'success' in entry['diagnosis']
        assert 'details' in entry['diagnosis']
        assert 'component_errors' in entry['diagnosis']
        assert isinstance(entry['diagnosis']['details'], list)

    # Failing entries must have details
    failing = [e for e in report if not e['success']]
    assert len(failing) > 0
    for entry in failing:
        assert entry['diagnosis']['success'] is False
        assert len(entry['diagnosis']['details']) > 0


@pytest.mark.usefixtures("mixdb")
def test_balance_report_diagnosis_json_serialisable():
    """Diagnosis data in balance_report() must be JSON-serialisable."""
    import json

    with MassBalance() as mb:
        _make_standard_stocks(mb)
        TargetSolution(
            name="PureHexanes",
            mass_fractions={"H2O": 0.0, "Hexanes": 1.0},
            concentrations={"NaCl": "25 mg/ml"},
            total_mass="500 mg",
            solutes=["NaCl"],
        )
    report = mb.balance(return_report=True)
    # Should not raise
    json.dumps(report)
