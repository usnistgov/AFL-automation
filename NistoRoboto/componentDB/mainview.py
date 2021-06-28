from flask import *

from flaskr.db import get_db

bp = Blueprint("mainview", __name__)

@bp.route("/")
def index():
    return render_template("/mainview.html")
