import pint

units = pint.UnitRegistry()
units.default_system = 'cgs'
AVOGADROS = 6.0221409e+23*units('1/mol')

