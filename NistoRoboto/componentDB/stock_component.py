"""Stock components are made here. Stocks are also made here based off the stock ID you give the stock component"""
from math import ceil

from flask import *
from werkzeug.exceptions import abort

from componentDB.utility.utility_function import isfloat
from flaskr.db import get_db

bp = Blueprint("stock_component", __name__)


@bp.route("/stock_component/<int:page>", methods=("GET", "POST"))
def index(page):
    db = get_db()
    posts = db.execute(
        "SELECT * FROM stock_component"
    ).fetchall()

    session['per_page'] = 10

    per_page = request.form.get("number")

    if per_page == '' or per_page is None:
        per_page = session['per_page']

    per_page = int(per_page)
    session['per_page'] = per_page

    stock_id = request.form.get("stock_id")

    radius = 2
    total = len(posts)
    pages = ceil(total / per_page)  # this is the number of pages
    offset = (page - 1) * per_page  # offset for SQL query

    session['stock_component_url'] = url_for('stock_component.index', page=page)  # save last URL for going back. easier than using cookies

    if page > pages + 1 or page < 1:
        abort(404, "Out of range")

    if stock_id == '' or stock_id is None:
        session['stock_id'] = ''
        posts = db.execute(
            "SELECT * FROM stock_component ORDER BY stock_id LIMIT ? OFFSET ?", (per_page, offset)
        ).fetchall()
    else:
        stock_id = int(stock_id)
        session['stock_id'] = stock_id
        posts = db.execute(
            "SELECT * FROM stock_component WHERE stock_id = ? ORDER BY stock_id LIMIT ? OFFSET ?", (stock_id, per_page, offset)
        ).fetchall()

    filtercount = len(posts)

    return render_template("stock_component/view_stock_component.html", posts=posts, total=total, filtercount=filtercount, per_page=per_page, pages=pages,
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
        volmass = request.form['volmass']

        if not (stock_id.isdecimal() and component_id.isdecimal() and isfloat(amount)):
            flash("Stock, component ID, and amount must be valid numbers")
            passed = False

        if units.isdecimal() or volmass.isdecimal():
            flash("Input valid units")
            passed = False

        if passed:
            db = get_db()
            db.execute(
                "INSERT INTO stock_component (stock_id, component_id, amount, units, volmass) VALUES (?, ?, ?, ?, ?)",
                (stock_id, component_id, amount, units, volmass),
            )
            db.commit()

            posts = db.execute(
                "SELECT * FROM stock WHERE id = ?", (stock_id,)
            ).fetchall()

            if len(posts) == 0:

                db.execute("INSERT INTO stock (name, id) VALUES (?, ?)",
                           (stock_name, stock_id))  # SQL does a check so you'll get a error if the id isn't unique
                db.commit()

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
        volmass = request.form['volmass']

        if not (stock_id.isdecimal() and component_id.isdecimal() and isfloat(amount)):
            flash("Stock, component ID, and amount must be valid numbers")
            passed = False

        if units.isdecimal() or volmass.isdecimal():
            flash("Input valid units")
            passed = False

        if passed:
            db = get_db()
            db.execute(
                "UPDATE stock_component SET stock_id = ?, component_id = ?, amount = ?, units = ?, volmass = ? WHERE id = ?",
                (stock_id, component_id, amount, units, volmass, id)
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
