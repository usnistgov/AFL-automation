import numpy as np
import copy
import warnings
from typing import Optional, Dict

import pint

from AFL.automation.mixcalc.Solution import Solution

class TargetSolution(Solution):
    """ """
    _stack_name = 'targets'
