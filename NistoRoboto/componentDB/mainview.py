from flask import *

from flaskr.db import get_db

bp = Blueprint("mainview", __name__)

@bp.route("/")
def index():

    db = get_db()
    posts = db.execute(
        "SELECT * FROM component ORDER BY created DESC"
    ).fetchall()
    return render_template("/mainview.html", posts=posts)
