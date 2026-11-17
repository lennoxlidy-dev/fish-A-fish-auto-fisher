import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                    # for "from fakes import ..."
sys.path.insert(0, os.path.dirname(HERE))   # for "import autofisher"
