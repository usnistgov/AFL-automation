import warnings

import numpy as np
import pytest
from AFL.automation.mixing.Solution import Solution
from AFL.automation.mixing.Component import Component
from AFL.automation.shared.units import units
from AFL.automation.shared.exceptions import EmptyException

from AFL.automation.shared.warnings import MixWarning


@pytest.mark.usefixtures("mixdb")
def test_solution_initialization():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        solution = Solution(name="TestSolution")
    assert solution.name == "TestSolution"
    assert solution.size == 0


@pytest.mark.usefixtures("mixdb")
def test_add_component_from_name():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        solution = Solution(name="TestSolution")
    solution.add_component("H2O")
    assert "H2O" in solution.components
    assert solution.components["H2O"].mass == None


@pytest.mark.usefixtures("mixdb")
def test_set_properties_from_dict():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        solution = Solution(name="TestSolution")
    solution.add_component("H2O")
    solution["H2O"].mass = 10 * units.g  # need to initialize the mass
    properties = {"mass": "20 g"}
    solution.set_properties_from_dict(properties, inplace=True)
    assert solution.mass == 20 * units.g
    assert solution.volume == 20 * units.ml


@pytest.mark.usefixtures("mixdb")
def test_rename_component():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        solution = Solution(name="TestSolution")
    solution.add_component("H2O")
    solution.rename_component("H2O", "D2O", inplace=True)
    assert "D2O" in solution.components
    assert "H2O" not in solution.components


@pytest.mark.usefixtures("mixdb")
def test_contains():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        solution = Solution(name="TestSolution")
    solution.add_component("H2O")
    assert solution.contains("H2O")
    assert not solution.contains("Ethanol")


@pytest.mark.usefixtures("mixdb")
def test_mass_property():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        solution = Solution(name="TestSolution", masses={"H2O": "10 g"})
    assert solution.mass == 10 * units.g
    solution.mass = "20 g"
    assert solution.mass == 20 * units.g


@pytest.mark.usefixtures("mixdb")
def test_volume_property():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        solution = Solution(name="TestSolution", volumes={"H2O": "10 ml"})
    assert solution.volume == 10 * units.ml
    solution.volume = "20 ml"
    assert solution.volume == 20 * units.ml


@pytest.mark.usefixtures("mixdb")
def test_mass_fraction_property():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        solution = Solution(
            name="TestSolution",
            masses={"H2O": "10 g", "NaCl": "10 g"},
            solutes=["NaCl"],
        )
    assert solution.mass_fraction["H2O"] == 0.5
    assert solution.mass_fraction["NaCl"] == 0.5


@pytest.mark.usefixtures("mixdb")
def test_volume_fraction_property():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        solution = Solution(
            name="TestSolution", volumes={"H2O": "10 ml", "Hexanes": "10 ml"}
        )
    assert solution.volume_fraction["H2O"] == 0.5
    assert solution.volume_fraction["Hexanes"] == 0.5


@pytest.mark.usefixtures("mixdb")
def test_concentration_property():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        solution = Solution(
            name="TestSolution",
            masses={"H2O": "10 g", "NaCl": "20 mg"},
            total_volume="10 ml",
            solutes=["NaCl"],
        )

    assert solution.concentration["NaCl"] == 2 * units("mg/ml")


@pytest.mark.usefixtures("mixdb")
def test_molarity_property():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        solution = Solution(
            name="TestSolution",
            masses={"H2O": "10 g", "NaCl": "20 mg"},
            total_volume="10 ml",
            solutes=["NaCl"],
        )
    np.testing.assert_allclose(
        solution.molarity["NaCl"], 34.2215 * units("mM"), rtol=1e-3
    )


@pytest.mark.usefixtures("mixdb")
def test_measure_out():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        solution = Solution(name="TestSolution", masses={"H2O": "10 g"})
    new_solution = solution.measure_out("5 g")
    assert new_solution.mass.to('g') == 5 * units.g
    assert solution.mass.to('g') == 10 * units.g


@pytest.mark.usefixtures("mixdb")
def test_measure_out_deplete():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        solution = Solution(name="TestSolution", masses={"H2O": "10 g"})
    new_solution = solution.measure_out("5 g", deplete=True)
    assert new_solution.mass.to('g') == 5 * units.g
    assert solution.mass.to('g') == 5 * units.g


@pytest.mark.usefixtures("mixdb")
def test_measure_out_empty_exception():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        solution = Solution(
            name="TestSolution", masses={"H2O": "10 g"}, total_volume="10 ml"
        )
    with pytest.raises(EmptyException):
        solution.measure_out("15 g", deplete=True)


@pytest.mark.usefixtures("mixdb")
def test_mixed_solvents_volume():
    with pytest.warns(MixWarning):
        solution = Solution(
            name="TestSolution",
            volumes={"H2O": "10 ml", "Hexanes": "2 ml"},
            concentrations={"NaCl": "200 mg/ml"},
            total_volume="10 ml",
            solutes=["NaCl"],
        )
    assert solution.volume == 10 * units.ml
    assert solution.volume_fraction["H2O"].magnitude == pytest.approx((10.0 / 12.0))
    assert solution.volume_fraction["Hexanes"].magnitude == pytest.approx((2.0 / 12.0))
    assert solution.concentration["NaCl"].to("mg/ml").magnitude == pytest.approx(200)
    assert [s.name for n, s in solution.solvents] == ["H2O", "Hexanes"]
    assert [s.name for n, s in solution.solutes] == ["NaCl"]


@pytest.mark.usefixtures("mixdb")
def test_mixed_solvents_mass():
    mass_H2O = 10.0  # g
    mass_Hexanes = 2  # g
    conc_NaCl = 200  # mg/ml
    rho_H2O = 1.0  # g/ml
    rho_Hexanes = 0.661  # g/ml

    total_volume = mass_H2O / rho_H2O + mass_Hexanes / rho_Hexanes
    mass_NaCl = conc_NaCl * total_volume / 1000  # mg ->g
    total_mass = (
        mass_H2O + mass_Hexanes + mass_NaCl
    )  # mass before volume scaling, mass fraction should be preserved

    with pytest.warns(MixWarning):
        solution = Solution(
            name="TestSolution",
            masses={"H2O": f"{mass_H2O} g", "Hexanes": f"{mass_Hexanes} g"},
            concentrations={"NaCl": f"{conc_NaCl} mg/ml"},
            total_volume="10 ml",
            solutes=["NaCl"],
        )

    assert solution.volume == 10 * units.ml
    assert solution.mass_fraction["H2O"].magnitude == pytest.approx(
        (mass_H2O / total_mass)
    )
    assert solution.mass_fraction["Hexanes"].magnitude == pytest.approx(
        (mass_Hexanes / total_mass)
    )
    assert solution.mass_fraction["NaCl"].magnitude == pytest.approx(
        (mass_NaCl / total_mass)
    )
    assert solution.concentration["NaCl"].to("mg/ml").magnitude == pytest.approx(
        conc_NaCl
    )
    assert [s.name for n, s in solution.solvents] == ["H2O", "Hexanes"]
    assert [s.name for n, s in solution.solutes] == ["NaCl"]


@pytest.mark.usefixtures("mixdb")
def test_mixed_solvents_error():
    with pytest.raises(ValueError):
        solution = Solution(
            name="TestSolution",
            concentrations={"NaCl": "200 mg/ml"},
            total_volume="10 ml",
        )


@pytest.mark.usefixtures("mixdb")
def test_solute_override():
    mass_H2O = 10.0  # g
    mass_Hexanes = 2  # g
    conc_NaCl = 200  # mg/ml
    rho_H2O = 1.0  # g/ml

    total_volume = mass_H2O / rho_H2O
    mass_NaCl = conc_NaCl * total_volume / 1000  # mg ->g
    total_mass = (
        mass_H2O + mass_Hexanes + mass_NaCl
    )  # mass before volume scaling, mass fraction should be preserved

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        solution = Solution(
            name="TestSolution",
            masses={"H2O": f"{mass_H2O} g", "Hexanes": f"{mass_Hexanes} g"},
            concentrations={"NaCl": f"{conc_NaCl} mg/ml"},
            solutes=["NaCl", "Hexanes"],
            total_volume="10 ml",
        )

    assert solution.volume.to("ml").magnitude == pytest.approx(10.0)
    assert solution.mass_fraction["H2O"].magnitude == pytest.approx(
        (mass_H2O / total_mass)
    )
    assert solution.mass_fraction["Hexanes"].magnitude == pytest.approx(
        (mass_Hexanes / total_mass)
    )
    assert solution.mass_fraction["NaCl"].magnitude == pytest.approx(
        (mass_NaCl / total_mass)
    )
    assert solution.concentration["NaCl"].to("mg/ml").magnitude == pytest.approx(
        conc_NaCl
    )
    assert [s.name for n, s in solution.solvents] == ["H2O"]
    assert [s.name for n, s in solution.solutes] == ["Hexanes", "NaCl"]


@pytest.mark.usefixtures("mixdb")
def test_solute_warning():
    with pytest.warns(MixWarning):
        Solution(name="TestSolution", masses={"H2O": "10 g", "NaCl": "10 mg"})


@pytest.mark.usefixtures("mixdb")
def test_solution_sanity_check_warning_mass():
    with pytest.warns(MixWarning):
        Solution(name="TestSolution", masses={"H2O": "10 g"}, total_volume="1 ml")


@pytest.mark.usefixtures("mixdb")
def test_solution_sanity_check_warning_volume():
    with pytest.warns(MixWarning):
        Solution(name="TestSolution", volumes={"H2O": "10 l"}, total_volume="1 l")


@pytest.mark.usefixtures("mixdb")
def test_solution_sanity_check():
    mass_H2O = 10.0  # g
    mass_Hexanes = 2  # g
    conc_NaCl = 200  # mg/ml
    with pytest.warns(MixWarning):
        Solution(
            name="TestSolution",
            masses={"H2O": f"{mass_H2O} g", "Hexanes": f"{mass_Hexanes} g"},
            volumes={"H2O": f"20 ml"},
            concentrations={"NaCl": f"{conc_NaCl} mg/ml"},
            solutes=["NaCl", "Hexanes"],
            total_volume="10 ml",
        )


@pytest.mark.usefixtures("mixdb")
def test_solution_with_mass_fractions():
    with pytest.warns(MixWarning):
        solution = Solution(
            name="TestSolution",
            mass_fractions={"H2O": "0.8", "Hexanes": "0.2"},
            concentrations={"NaCl": "50 mg/ml"},
            total_mass="10 g",
            solutes=["NaCl"],
        )
    assert solution.mass == 10 * units.g
    assert (
        solution["H2O"].mass / (solution["H2O"].mass + solution["Hexanes"].mass)
    ).magnitude == 0.8
    assert (
        solution["Hexanes"].mass / (solution["H2O"].mass + solution["Hexanes"].mass)
    ).magnitude == 0.2
    assert solution.concentration["NaCl"] == 50 * units("mg/ml")


@pytest.mark.usefixtures("mixdb")
def test_solvent_volume_property():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        solution = Solution(
            name="TestSolution",
            volumes={"H2O": "10 ml", "Hexanes": "5 ml"},
            masses={"NaCl": "10 mg"},
            solutes=["NaCl"],
        )
    assert (
        solution.solvent_volume == solution["H2O"].volume + solution["Hexanes"].volume
    )


@pytest.mark.usefixtures("mixdb")
def test_solvent_mass_property():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        solution = Solution(
            name="TestSolution",
            masses={"H2O": "10 g", "Hexanes": "5 g", "NaCl": "10 mg"},
            solutes=["NaCl"],
        )
    assert solution.solvent_mass == 15 * units.g
