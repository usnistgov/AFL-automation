"""Stock components are made here. Stocks are also made here based off the stock ID you give the stock component"""
from math import ceil

from flask import *
from werkzeug.exceptions import abort
from flaskr.db import get_db

bp = Blueprint("stock_component", __name__)


@bp.route("/stock_component/<int:page>/<int:per_page>", methods=("GET", "POST"))
def index(page, per_page):
    db = get_db()
    posts = db.execute(
        "SELECT * FROM stock_component ORDER BY created DESC"
    ).fetchall()

    per_page = int(request.form.get("number", per_page))
    radius = 2
    total = len(posts)
    pages = ceil(total / per_page)  # this is the number of pages
    offset = (page - 1) * per_page  # offset for SQL query

    session['stock_component_url'] = url_for('stock_component.index', page=page,
                                             per_page=per_page)  # save last URL for going back. easier than using cookies

    if page > pages + 1 or page < 1:
        abort(404, "Out of range")

    posts = db.execute(
        "SELECT * FROM stock_component ORDER BY created DESC LIMIT ? OFFSET ?", (per_page, offset)
    ).fetchall()

    return render_template("stock_component/view_stock_component.html", posts=posts, total=total, per_page=per_page, pages=pages,
                           page=page,
                           radius=radius)


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

        if not (stock_id.isdecimal() and component_id.isdecimal()):
            flash("Stock and component ID must be valid numbers")
            passed = False

        if units.isdecimal():
            flash("Input valid units")
            passed = False

        if passed:
            db = get_db()
            db.execute(
                "INSERT INTO stock_component (stock_id, component_id, amount, units) VALUES (?, ?, ?, ?)",
                (stock_id, component_id, amount, units),
            )
            db.commit()

            db.execute("INSERT INTO stock (name, id) VALUES (?, ?)",
                       (stock_name, stock_id))  # SQL does a check so you'll get a error if the id isn't unique
            db.commit()

            # return redirect(url_for("stock_component.index"))
            return redirect(session['stock_component_url'])

    return render_template("stock_component/create_stock_component.html", back=session['stock_component_url'])


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
            )  # update stock_component table

            db.commit()
            # return redirect(url_for("stock_component.index"))
            return redirect(session['stock_component_url'])

    return render_template("stock_component/update_stock_component.html", post=post, back=session['stock_component_url'])


@bp.route("/stock_component/<int:id>/delete", methods=("GET", "POST"))
def delete(id):
    get_post(id)
    db = get_db()
    db.execute("DELETE FROM stock_component WHERE id = ?", (id,))
    db.commit()
    # return redirect(url_for("stock_component.index"))
    return redirect(session['stock_component_url'])
