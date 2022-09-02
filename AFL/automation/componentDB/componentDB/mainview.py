from flask import *

bp = Blueprint("mainview", __name__)

@bp.route("/")
def index():
    return render_template("mainview.html")


@bp.route("/graph")
def graph():
    legend = 'Monthly Data'
    labels = ["January", "February", "March", "April", "May", "June", "July", "August"]
    values = [10, 9, 8, 7, 6, 5, 4, 3]
    return render_template('graph.html', values=values, labels=labels, legend=legend)

