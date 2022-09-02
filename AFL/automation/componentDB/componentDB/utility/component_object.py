class ComponentObject:
    name = None
    description = None
    mass = None
    mass_units = None
    density = None
    density_units = None
    formula = None
    sld = None
    passed = True

    def __init__(self, name, description, mass, mass_units, density, density_units, formula, sld, passed):
        self.name = name
        self.description = description
        self.mass = mass
        self.mass_units = mass_units
        self.density = density
        self.density_units = density_units
        self.formula = formula
        self.sld = sld
        self.passed = passed
