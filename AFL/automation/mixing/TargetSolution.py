import numpy as np
import copy
import warnings
from typing import Optional, Dict

import pint

from AFL.automation.mixing.Solution import Solution

class TargetSolution(Solution):
    """ """
    _stack_name = 'targets'
