"""Stock components are made here. Stocks are also made here based off the stock ID you give the stock component"""

from flask import *
from werkzeug.exceptions import abort
from flaskr.db import get_db

bp = Blueprint("stock_component", __name__)

@bp.route("/stock_component")
def index():
    db = get_db()
    posts = db.execute(
        "SELECT * FROM stock_component ORDER BY created DESC, stock_id"
    ).fetchall()
    return render_template("stock_component/view_stock_component.html", posts=posts)

def get_post(id, check_author=True):
    """
    :raise 404: if a post with the given id doesn't exist
    :raise 403: if the current user isn't the author
    """
    post = (
        get_db()
        .execute(
            "SELECT * FROM stock_component WHERE id = ?",
            (id,),
        )
        .fetchone()
    )

    if post is None:
        abort(404, f"Stock Component ID {id} doesn't exist.")

    return post

@bp.route("/stock_component/create", methods=("GET", "POST"))
def create():

    if request.method == "POST":

        passed = True

        """Stock name, for creating a stock entry."""
        stock_name = request.form['stock_name']
        """"""

        stock_id = request.form['stock_id']
        component_id = request.form['component_id']
        amount = request.form['amount']
        units = request.form['units']

        if not(stock_id.isdecimal() and component_id.isdecimal()):
            flash("Stock and component ID must be valid numbers")
            passed=False

        if units.isdecimal():
            flash("Input valid units")
            passed=False

        if passed:
            db = get_db()
            db.execute(
                "INSERT INTO stock_component (stock_id, component_id, amount, units) VALUES (?, ?, ?, ?)",
                (stock_id, component_id, amount, units),
            )
            db.commit()

            db.execute("INSERT INTO stock (name, id) VALUES (?, ?)", (stock_name, stock_id)) #SQL does a check so you'll get a error if the id isn't unique
            db.commit()

            return redirect(url_for("stock_component.index"))

    return render_template("stock_component/create_stock_component.html")


@bp.route("/stock_component/<int:id>/update", methods=("GET", "POST"))
def update(id):

    post = get_post(id)

    if request.method == "POST":

        passed = True

        stock_id = request.form['stock_id']
        component_id = request.form['component_id']
        amount = request.form['amount']
        units = request.form['units']

        if not (stock_id.isdecimal() and component_id.isdecimal()):
            flash("Stock and component ID must be valid numbers")
            passed = False

        if units.isdecimal():
            flash("Input valid units")
            passed = False

        if passed:
            db = get_db()
            db.execute(
                "UPDATE stock_component SET stock_id = ?, component_id = ?, amount = ?, units = ? WHERE id = ?",
                (stock_id, component_id, amount, units, id)
            ) #update stock_component table

            db.commit()
            return redirect(url_for("stock_component.index"))

    return render_template("stock_component/update_stock_component.html", post=post)


@bp.route("/stock_component/<int:id>/delete", methods=("GET", "POST"))
def delete(id):

    get_post(id)
    db = get_db()
    db.execute("DELETE FROM stock_component WHERE id = ?", (id,))
    db.commit()
    return redirect(url_for("stock_component.index"))