import pint

units = pint.UnitRegistry()
units.default_system = 'cgs'
AVOGADROS_NUMBER = 6.0221409e+23 * units('1/mol')

DEFAULT_UNITS = {}
DEFAULT_UNITS['volume'] = 'ml'
DEFAULT_UNITS['mass'] = 'mg'
DEFAULT_UNITS['concentration'] = 'g/ml'
DEFAULT_UNITS['density'] = 'g/ml'
DEFAULT_UNITS['molarity'] = 'millimolar'

SUPPORTED_TYPES = ['volume', 'mass', 'density', 'molarity', 'concentration']


def has_units(value):
    return hasattr(value, 'units')


def is_volume(value):
    return (len(value.dimensionality) == 1) and (value.dimensionality['[length]'] == 3)


def is_molarity(value):
    return ((len(value.dimensionality) == 2) and (value.dimensionality['[length]'] == -3) and (
            value.dimensionality['[substance]'] == 1))


def is_mass(value):
    return (len(value.dimensionality) == 1) and (value.dimensionality['[mass]'] == 1)


def is_density(value):
    return ((len(value.dimensionality) == 2) and (value.dimensionality['[mass]'] == 1) and (
            value.dimensionality['[length]'] == -3))


def is_concentration(value):
    return ((len(value.dimensionality) == 2) and (value.dimensionality['[mass]'] == 1) and (
            value.dimensionality['[length]'] == -3))


def get_unit_type(value):
    if is_volume(value):
        return 'volume'
    elif is_molarity(value):
        return 'molarity'
    elif is_mass(value):
        return 'mass'
    elif is_density(value):
        return 'density'
    elif is_concentration(value):
        return 'concentration'
    else:
        raise ValueError(f'Unit system ({value}) not recognized as one of: {SUPPORTED_TYPES}')


def enforce_units(value, unit_type):
    """Ensure that a number has units and convert to the default_units"""
    # None bypasses all unit testing
    if value is None:
        return

    if unit_type.lower() not in SUPPORTED_TYPES:
        raise ValueError(f'Not configured to enforce unit_type: {unit_type}')

    if not has_units(value):
        raise ValueError('Supplied value must have units!')

    if unit_type.lower() == 'volume':
        if not is_volume(value):
            raise ValueError(f'Supplied value must be a volume not {value.dimensionality}')
        else:
            value = value.to(DEFAULT_UNITS['volume'])

    elif unit_type.lower() == 'mass':
        if not is_mass(value):
            raise ValueError(f'Supplied value must be a mass not {value.dimensionality}')
        else:
            value = value.to(DEFAULT_UNITS['mass'])

    elif unit_type.lower() == 'density':
        if not is_density(value):
            raise ValueError(f'Supplied value must be a density not {value.dimensionality}')
        else:
            value = value.to(DEFAULT_UNITS['density'])

    elif unit_type.lower() == 'concentration':
        if not is_concentration(value):
            raise ValueError(f'Supplied value must be a concentration not {value.dimensionality}')
        else:
            value = value.to(DEFAULT_UNITS['concentration'])

    elif unit_type.lower() == 'molarity':
        if not is_molarity(value):
            raise ValueError(f'Supplied value must be a molarity not {value.dimensionality}')
        else:
            value = value.to(DEFAULT_UNITS['molarity'])

    return value
