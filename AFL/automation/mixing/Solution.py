import copy
import warnings
from itertools import chain
from typing import Optional, Dict, List

import numpy as np
import pint

from AFL.automation.mixing.Component import Component
from AFL.automation.mixing.Context import Context
from AFL.automation.mixing.MixDB import MixDB
from AFL.automation.shared.exceptions import EmptyException, NotFoundError
from AFL.automation.shared.units import (
    units,
    enforce_units,
    has_units,
    is_volume,
    is_mass,
    AVOGADROS_NUMBER,
)
from AFL.automation.shared.warnings import MixWarning

SANITY_MSG = """
Solution Check:
---------------
{results}
Potential Reasons:
------------------
{reasons}
"""


class Solution(Context):
    _stack_name = "stocks"

    def __init__(
        self,
        name: str,
        total_mass: Optional[str | pint.Quantity] = None,
        total_volume: Optional[str | pint.Quantity] = None,
        masses: Optional[Dict] = None,
        volumes: Optional[Dict] = None,
        concentrations: Optional[Dict] = None,
        mass_fractions: Optional[Dict] = None,
        location: Optional[str] = None,
        solutes: Optional[List[str]] = None,
        sanity_check: Optional[bool] = True,
    ):
        """
        Initialize a Solution object.

        Parameters
        ----------
        name : str
            The name of the solution.
        total_mass : str or pint.Quantity, optional
            The total mass of the solution.
        total_volume : str or pint.Quantity, optional
            The total volume of the solution.
        masses : dict, optional
            A dictionary of component masses.
        volumes : dict, optional
            A dictionary of component volumes.
        concentrations : dict, optional
            A dictionary of component concentrations.
        mass_fractions : dict, optional
            A dictionary of component mass fractions.
        location : str, optional
            The location of the solution on the robot. Usually a deck location e.g., '1A1'.
        solutes : list of str, optional
            A list of solute names. If set, the components will be initialized as solutes and they won't contribute
            to the volume of the solution
        sanity_check : bool, optional
            Whether to perform a sanity check on the solution.

        Raises
        ------
        ValueError
            If concentrations are set without specifying a component with volume.
            If mass fractions are set without specifying a component with mass or the total mass.
        """

        super().__init__(name=name)
        self.context_type = "Solution"
        self.location = location
        self.protocol = None
        self.components: Dict = {}
        self.add_self_to_context()

        # Handle initialization of non-specific properties
        if masses is None:
            masses = {}
        if volumes is None:
            volumes = {}
        if concentrations is None:
            concentrations = {}
        if mass_fractions is None:
            mass_fractions = {}
        if solutes is None:
            solutes = []

        # Initialize components
        for name in chain(masses, volumes, concentrations, mass_fractions, solutes):
            self.add_component(name, solutes)

        for name, mass in masses.items():
            self.components[name].mass = mass
        for name, volume in volumes.items():
            self.components[name].volume = volume

        if len(mass_fractions) > 0:
            if (total_mass is None) and (
                    (self.mass is None) or (self.mass.magnitude == 0)
            ):
                raise ValueError(
                    "Cannot set mass_fraction without setting a component with mass or specifying the total_mass."
                )
            else:
                # need to initialize all components with a mass
                for name in mass_fractions.keys():
                    self.components[name].mass = '1.0 mg'
                if total_mass is not None:
                    self.mass = total_mass
            self.mass_fraction = mass_fractions

        if len(concentrations) > 0 and (
            (self.volume is None) or (self.volume.magnitude == 0)
        ):
            raise ValueError(
                "Cannot set concentrations without setting a component with volume."
            )
        self.concentration = concentrations

        if total_mass is not None:
            self.mass = total_mass

        if total_volume is not None:
            self.volume = total_volume

        if sanity_check:
            self._sanity_check(masses, volumes, concentrations, mass_fractions, total_mass, total_volume)

    def _sanity_check(self, masses, volumes, concentrations, mass_fractions, total_mass, total_volume):
        """
        Perform a sanity check on the solution to ensure consistency of requested and final properties.

        Parameters
        ----------
        masses : dict
            A dictionary of component masses.
        volumes : dict
            A dictionary of component volumes.
        concentrations : dict
            A dictionary of component concentrations.
        mass_fractions : dict
            A dictionary of component mass fractions.
        total_mass : str or pint.Quantity, optional
            The total mass of the solution.
        total_volume : str or pint.Quantity, optional
            The total volume of the solution.

        Raises
        ------
        MixWarning
            If any inconsistencies are found in the solution properties.
        """
        msg = ""
        for name, mass in masses.items():
            mass = enforce_units(mass, "mass")
            if not np.isclose(self.components[name].mass, mass):
                msg += f"Mass of {name} was specified to be {mass} but is now to {self[name].mass}.\n"

        for name, volume in volumes.items():
            volume = enforce_units(volume, "volume")
            if not np.isclose(self.components[name].volume, volume):
                msg += f"Volume of {name} was specified to be {volume} but is now {self[name].volume}.\n"

        for name, concentration in concentrations.items():
            concentration = enforce_units(concentration, "concentration")
            if not np.isclose(self.concentration[name], concentration):
                msg += f"Concentration of {name} was specified to be {concentration} but is now {self.concentration[name]}.\n"

        for name, mass_fraction in mass_fractions.items():
            if not np.isclose(self.mass_fraction[name], mass_fraction):
                msg += f"Mass fraction of {name} was specified to be {mass_fraction} but is now {self.mass_fraction[name]}.\n"

        if total_mass is not None:
            if not np.isclose(self.mass, enforce_units(total_mass, "mass")):
                msg += f"Total mass was specified to be {total_mass} but is now {self.mass}.\n"

        if total_volume is not None:
            if not np.isclose(self.volume, enforce_units(total_volume, "volume")):
                msg += f"Total volume was specified to be {total_volume} but is now {self.volume}.\n"

        if msg:
            reasons = ""
            if any(
                [
                    ((name in masses) and (name in volumes))
                    for name, component in self
                ]
            ):
                reasons += "- You have specified the same component(s) in both masses and volumes.\n"

            if any(
                [
                    ((name in masses) and (name in concentrations))
                    for name, component in self
                ]
            ):
                reasons += "- You have specified the same component(s) in both masses and concentrations.\n"

            if any(
                [
                    ((name in volumes) and (name in concentrations))
                    for name, component in self
                ]
            ):
                reasons += "- You have specified the same component(s) in both volumes and concentrations.\n"

            if any(
                [
                    ((name in masses) and (name in mass_fractions))
                    for name, component in self
                ]
            ):
                reasons += "- You have specified the same component(s) in both masses and mass fractions.\n"

            if any(
                [
                    ((name in volumes) and (name in mass_fractions))
                    for name, component in self
                ]
            ):
                reasons += "- You have specified the same component(s) in both volumes and mass fractions.\n"

            if any(
                [
                    ((name in concentrations) and (name in mass_fractions))
                    for name, component in self
                ]
            ):
                reasons += "- You have specified the same component(s) in both concentrations and mass fractions.\n"

            if (total_mass is not None) or (total_volume is not None):
                reasons += (
                    "- You specified total_mass and/or total_volume. These transforms happen at the end of the\n "
                    "solution creation and, while they conserve mass_fractions, they do not conserve other\n "
                    "quantities."
                )
            if not reasons:
                reasons = f"- No clear reasons. This may be the sign of a bug, please report!\n"

            msg = SANITY_MSG.format(results=msg, reasons=reasons)
            warnings.warn(msg, MixWarning, stacklevel=2)

    def __call__(self, reset=False):
        if reset:
            self.components.clear()
        return self

    def __str__(self):
        out_str = f'<Solution name:"{self.name}" size:{self.size}>'
        return out_str

    def __repr__(self):
        return self.__str__()

    def __getitem__(self, name):
        try:
            return self.components[name]
        except KeyError:
            raise KeyError(
                f"The component '{name}' is not in this solution which contains: {list(self.components.keys())}"
            )

    def __iter__(self):
        for name, component in self.components.items():
            yield name, component

    def __hash__(self):
        """Needed so Solutions can be dictionary keys"""
        return id(self)

    def to_dict(self):
        out_dict = {
            "name": self.name,
            "components": list(self.components.keys()),
            "masses": {},
        }
        for k, v in self:
            out_dict["masses"][k] = {"value": v.mass.to("mg").magnitude, "units": "mg"}
        return out_dict

    def add_component(self, name, solutes: Optional[List[str]] = None):
        if name not in self.components:
            try:
                mixdb = MixDB.get_db()
            except ValueError:
                # attempt to instantiate from default location
                mixdb = MixDB()

            if solutes and (name in solutes):
                solute = True
            else:
                solute = False

            try:
                self.components[name] = Component(
                    solute=solute, **mixdb.get_component(name)
                )
            except NotFoundError:
                raise

    def set_properties_from_dict(self, properties=None, inplace=False):
        if properties is not None:
            if inplace:
                solution = self
            else:
                solution = self.copy()

            for name, props in properties.items():
                if name in ["mass", "volume", "density"]:
                    setattr(solution, name, props)
                else:  # assume setting component properties
                    for prop_name, value in props.items():
                        setattr(solution.components[name], prop_name, value)
            return solution
        else:
            return self

    def rename_component(self, old_name, new_name, inplace=False):
        if inplace:
            solution = self
        else:
            solution = self.copy()
        solution.components[new_name] = solution.components[old_name].copy()
        del solution.components[old_name]
        return solution

    def copy(self, name=None):
        # Create a new instance without copying the context
        solution = Solution(name=name if name is not None else self.name)
        solution.context_type = self.context_type
        solution.location = self.location
        solution.protocol = self.protocol
        solution.components = {name: component.copy() for name, component in self.components.items()}
        return solution

    def contains(self, name: str) -> bool:
        return name in self.components

    @property
    def size(self):
        return len(self.components)

    @property
    def solutes(self):
        return [(name, component) for name, component in self if component.is_solute]

    @property
    def solvents(self):
        return [(name, component) for name, component in self if component.is_solvent]

    def __add__(self, other):
        mixture = self.copy()
        mixture.name = self.name + " + " + other.name
        for name, component in other:
            if mixture.contains(name):
                mixture.components[name] = mixture.components[name] + component.copy()
            else:
                mixture.components[name] = component.copy()
        return mixture

    def __eq__(self, other):
        """Compare the mass,volume, and composition of two mixtures"""

        # list of true/false values that represent equality checks
        checks = [
            np.isclose(self.mass, other.mass),
            np.isclose(self.volume, other.volume),
        ]

        for name, component in self:
            checks.append(np.isclose(self[name].mass, other[name].mass))
            checks.append(
                np.isclose(self.mass_fraction[name], other.mass_fraction[name])
            )

        return all(checks)

    def all_components_have_mass(self):
        return all([component.has_mass for name, component in self])

    @property
    def mass(self) -> pint.Quantity:
        """Total mass of mixture."""
        masses = [component.mass for name, component in self if component.has_mass]
        if len(masses) == 0:
            return 0 * units("mg")
        return sum(masses)

    @mass.setter
    def mass(self, value: str | pint.Quantity):
        """Set total mass of mixture."""
        # assert self.all_components_have_mass(), (
        #     f"Cannot set mass of solution with components lacking mass. Current "
        #     f"solution has: { {k:v.mass for k,v in self.components.items()} }"
        # )
        value = enforce_units(value, "mass")
        scale_factor = value / self.mass
        for name, component in self:
            if component.has_mass:
                component.mass = enforce_units((component.mass * scale_factor), "mass")

    def set_mass(self, value: str | pint.Quantity):
        """Setter for inline mass changes"""
        value = enforce_units(value, "mass")
        solution = self.copy()
        solution.mass = value
        return solution

    @property
    def volume(self) -> pint.Quantity:
        """Total volume of mixture. Only solvents are included in volume calculation"""
        volumes = [component.volume for name, component in self.solvents]
        if len(volumes) == 0:
            return 0 * units("ml")
        else:
            return sum(volumes)

    @volume.setter
    def volume(self, value: str | pint.Quantity):
        """Set total volume of mixture. Mass composition will be preserved"""
        if len(self.solvents) == 0:
            raise ValueError("Cannot set Solution volume without any Solvents")

        total_volume = enforce_units(value, "volume")

        w = self.mass_fraction

        # grab the density of the first solvent
        rho_1 = self.solvents[0][1].density

        denominator = [1.0]
        # skip the first solvent
        for name, component in self.solvents[1:]:
            rho_2 = component.density
            denominator.append(-w[name] * (1 - rho_1 / rho_2))

        for name, component in self.solutes:
            denominator.append(-w[name])

        total_mass = enforce_units(total_volume * rho_1 / sum(denominator), "mass")
        self.mass = total_mass

    def set_volume(self, value: str | pint.Quantity):
        """Setter for inline volume changes"""
        solution = self.copy()
        solution.volume = value
        return solution

    @property
    def solvent_sld(self) -> pint.Quantity:
        sld = []
        vfracs = []
        for name, vfrac in self.volume_fraction.items():
            component_sld = self.components[name].sld
            if component_sld is None:
                warnings.warn(f"SLD for solvent {name} is None. Check db", stacklevel=2)
                continue
            sld.append(component_sld)
            vfracs.append(vfrac)
        sld = [v * s / sum(vfracs) for v, s in zip(vfracs, sld)]
        return sum(sld)

    @property
    def solvent_density(self):
        m = self.solvent_mass
        v = self.solvent_volume
        return enforce_units(m / v, "density")

    @property
    def solvent_volume(self):
        return sum(
            [component.mass / component.density for name, component in self.solvents]
        )

    @property
    def solvent_mass(self):
        return sum([component.mass for name, component in self.solvents])

    @property
    def mass_fraction(self):
        """Mass fraction of components in mixture

        Returns
        -------
        mass_fraction: dict
        Component mass fractions
        """
        total_mass = self.mass
        mass_fraction = {}
        for name, component in self:
            mass_fraction[name] = component.mass / total_mass
        return {name: component.mass / total_mass for name, component in self}

    @mass_fraction.setter
    def mass_fraction(self, target_mass_fractions):
        """Mass fraction of components in mixture

        Returns
        -------
        mass_fraction: dict
        Component mass fractions
        """
        if len(target_mass_fractions) < len(self.components):
            warnings.warn(
                "Setting mass fractions for less than all components. This will set a partial mass fraction for those components",
                MixWarning,
                stacklevel=2,
            )
        total_mass = sum(
            [self.components[name].mass for name in target_mass_fractions.keys()]
        )

        for name, fraction in target_mass_fractions.items():
            self.components[name].mass = enforce_units(fraction,'dimensionless') * total_mass

    @property
    def volume_fraction(self):
        """Volume fraction of solvents in mixture

        Returns
        -------
        solvent_fraction: dict
        Component mass fractions
        """
        total_volume = self.volume
        return {
            name: component.volume / total_volume for name, component in self.solvents
        }

    @volume_fraction.setter
    def volume_fraction(self, target_volume_fractions):
        """Volume fraction of components in mixture

        Returns
        -------
        volume_fraction: dict
        Component volume fractions
        """
        if len(target_volume_fractions) < len(self.components):
            warnings.warn(
                "Setting volume fractions for less than all components. This will set a partial volume fraction for those components",
                MixWarning,
                stacklevel=2,
            )
        total_volume = sum(
            [self.components[name].volume for name in target_volume_fractions.keys()]
        )

        for name, fraction in target_volume_fractions.items():
            self.components[name].volume = enforce_units(fraction,'dimensionless') * total_volume

    @property
    def concentration(self):
        total_volume = self.volume
        return {name: component.mass / total_volume for name, component in self}

    @concentration.setter
    def concentration(self, concentration_dict):
        total_volume = self.volume
        for name, concentration in concentration_dict.items():
            concentration = enforce_units(concentration, "concentration")
            self.components[name].mass = enforce_units(
                concentration * total_volume, "mass"
            )

    @property
    def molarity(self):
        total_volume = self.volume
        result = {}
        for name, component in self:
            if component.has_formula:
                result[name] = enforce_units(component.moles / total_volume, "molarity")
        return result

    @molarity.setter
    def molarity(self, molarity_dict):
        total_volume = self.volume
        for name, molarity in molarity_dict.items():
            if not self.components[name].has_formula:
                raise ValueError(
                    f"Attempting to set molarity of component without formula: {name}"
                )
            else:
                molar_mass = (
                    self.components[name].formula.molecular_mass
                    * AVOGADROS_NUMBER
                    * units("g")
                )
                self.components[name].mass = enforce_units(
                    molarity * molar_mass * total_volume, "mass"
                )

    def measure_out(
        self, amount: str | pint.Quantity, deplete: object = False
    ) -> "Solution":
        """Create solution with identical composition at new total mass/volume"""

        if not has_units(amount):
            amount = units(amount)

        if is_volume(amount):
            solution = self.copy()
            solution.volume = amount
        elif is_mass(amount):
            solution = self.copy()
            solution.mass = amount
        else:
            raise ValueError(
                f"Must supply measure_out with a volume or mass not {amount.dimensionality}"
            )

        if deplete:
            if self.volume >= solution.volume:
                self.volume = self.volume - solution.volume
            else:
                raise EmptyException(f"Cannot measure out {solution.volume} from a solution with volume {self.volume}")
        return solution
