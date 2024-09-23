import periodictable  # type: ignore
import copy
from pyparsing import ParseException
from typing import Optional, Dict, Iterator, Tuple, Union

from AFL.automation.shared.units import units, AVOGADROS_NUMBER, enforce_units  # type: ignore


class Component:
    """ Component of a mixture

    This class defines the basic properties of a component within a mixture. It
    includes attributes for mass, volume, density, formula, and scattering length
    density (SLD). It also enforces unit specifications for these attributes.

    Parameters
    ----------
    name : str
        The name of the component.
    mass : str | units.Quantity | None
        The mass of the component, by default None.
    volume : str | units.Quantity | None
        The volume of the component, by default None.
    density : str | units.Quantity | None
        The density of the component, by default None.
    formula : Optional[str], optional
        The chemical formula of the component, by default None.
    sld : str | units.Quantity | None
        The scattering length density of the component, by default None.
    """

    def __init__(self, name: str, mass: Optional[units.Quantity] = None, volume: Optional[units.Quantity] = None,
                 density: Optional[units.Quantity] = None, formula: Optional[str] = None, sld: Optional[units.Quantity] = None,
                 uid: Optional[str] = None) -> None:
        self.name: str = name

        self._mass: Optional[units.Quantity] = enforce_units(mass, 'mass')
        self._volume: Optional[units.Quantity] = enforce_units(volume, 'volume')
        self._density: Optional[units.Quantity] = enforce_units(density, 'density')
        self._sld: Optional[units.Quantity] = sld #need to add sld units
        if formula is None:
            self.formula = name
        else:
            self.formula = formula
        self.uid = uid

    def emit(self) -> Dict[str, Union[str, units.Quantity]]:
        return {
            'name': self.name,
            'density': self.density,
            'formula': self.formula,
            'sld': self.sld,
        }

    def __str__(self) -> str:
        out_str = '<Component '
        out_str += f' M={self.mass:4.3f}' if self.has_mass else ' M=None'
        out_str += f' V={self.volume:4.3f}' if self.has_volume else ' V=None'
        out_str += f' D={self.density:4.3f}' if self.has_density else ' D=None'
        out_str += '>'
        return out_str

    def __repr__(self) -> str:
        return self.__str__()

    def __hash__(self) -> int:
        """Needed so Components can be dictionary keys"""
        return id(self)

    def copy(self) -> 'Component':
        return copy.deepcopy(self)

    def __iter__(self) -> Iterator[Tuple[str, 'Component']]:
        """Dummy iterator to mimic behavior of Mixture."""
        for name, component in [(self.name, self)]:
            yield name, component

    @property
    def mass(self) -> Optional[units.Quantity]:
        return self._mass

    @mass.setter
    def mass(self, value: units.Quantity) -> None:
        value = enforce_units(value, 'mass')
        self._mass = value

    def set_mass(self, value: units.Quantity) -> 'Component':
        """Setter for inline mass changes"""
        component = self.copy()
        component.mass = value
        return component

    @property
    def volume(self) -> Optional[units.Quantity]:
        if self.has_mass and self.has_density:
            return enforce_units(self._mass / self._density, 'volume')  # type: ignore
        else:
            return None

    @volume.setter
    def volume(self, value: units.Quantity) -> None:
        value = enforce_units(value, 'volume')
        if not self.has_density:
            raise ValueError('Can\'t set volume without specifying density')
        else:
            self.mass = enforce_units(value * self._density, 'mass')

    def set_volume(self, value: units.Quantity) -> 'Component':
        """Setter for inline volume changes"""
        component = self.copy()
        component.volume = value
        return component

    @property
    def density(self) -> Optional[units.Quantity]:
        return self._density

    @density.setter
    def density(self, value: units.Quantity) -> None:
        value = enforce_units(value, 'density')
        self._density = value

    @property
    def formula(self) -> Optional[periodictable.formula]:
        return self._formula

    @formula.setter
    def formula(self, value: Optional[str]) :
        if value is None:
            self._formula = None
        else:
            try:
                self._formula = periodictable.formula(value)
            except (ValueError, ParseException):
                self._formula = None

    @property
    def moles(self) -> Optional[units.Quantity]:
        if self.has_formula:
            return self._mass / (self.formula.molecular_mass * units('g')) / AVOGADROS_NUMBER  # type: ignore
        else:
            return None

    @property
    def sld(self) -> Optional[units.Quantity]:
        if self._sld is not None:
            return self._sld
        elif self.has_formula and self.has_density:
            self.formula.density = self.density.to('g/ml').magnitude  # type: ignore
            sld = self.formula.neutron_sld(wavelength=5.0)[0]  # type: ignore
            return sld * 1e-6 * units('angstrom^(-2)')
        else:
            return None

    @sld.setter
    def sld(self, value: units.Quantity) -> None:
        self._sld = value

    @property
    def is_solute(self) -> bool:
        return not self.has_volume

    @property
    def is_solvent(self) -> bool:
        return self.has_volume

    @property
    def has_mass(self) -> bool:
        return self._mass is not None

    @property
    def has_volume(self) -> bool:
        if self._volume is not None or (self.has_mass and self.has_density):
            return True

    @property
    def has_density(self) -> bool:
        return self._density is not None

    @property
    def has_formula(self) -> bool:
        return self._formula is not None

    @property
    def has_sld(self) -> bool:
        return self._sld is not None or (self.has_formula and self.has_density)

    def __add__(self, other: 'Component') -> 'Component':

        if not (self.name == other.name):
            raise ValueError(f'Can only add components of the same name. Not {self.name} and {other.name}')

        if not (self.density == other.density):
            raise ValueError(f'Density mismatch in component.__add__: {self.density} and {other.density}')

        component = self.copy()
        component.mass = enforce_units(component._mass + other._mass, 'mass')  # type: ignore
        return component
