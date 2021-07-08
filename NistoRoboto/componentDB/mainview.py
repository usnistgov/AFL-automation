import os
from os.path import *

from flask import *
from werkzeug.utils import secure_filename

bp = Blueprint("mainview", __name__)

@bp.route("/")
def index():
    return render_template("/mainview.html")
