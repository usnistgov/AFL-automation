from math import ceil

from flask import *
from werkzeug.exceptions import abort

from componentDB.utility.component_object import ComponentObject
from componentDB.utility.utility_function import isfloat
from flaskr.db import get_db

bp = Blueprint("component", __name__)


@bp.route("/component/<int:page>", methods=("GET", "POST"))
def index(page):
    db = get_db()
    posts = db.execute(
        "SELECT * FROM component ORDER BY created DESC",
    ).fetchall()

    session['per_page'] = 10

    per_page = request.form.get("number")

    if per_page == '' or per_page is None:
        per_page = session['per_page']

    per_page = int(per_page)
    session['per_page'] = per_page

    radius = 2
    total = len(posts)
    pages = ceil(total / per_page)  # this is the number of pages
    offset = (page - 1) * per_page  # offset for SQL query

    session['component_url'] = url_for('component.index', page=page)  # save last URL for going back. easier than using cookies

    if page > pages + 1 or page < 1:
        abort(404, "Out of range")

    posts = db.execute(
        "SELECT * FROM component ORDER BY created DESC LIMIT ? OFFSET ?", (per_page, offset)
    ).fetchall()

    return render_template("component/view_component.html", posts=posts, total=total, per_page=per_page, pages=pages, page=page,
                           radius=radius)


def get_post(id, check_author=True):
    """
    :raise 404: if a post with the given id doesn't exist
    :raise 403: if the current user isn't the author
    """
    post = (
        get_db()
            .execute(
            "SELECT * FROM component WHERE id = ?",
            (id,),
        )
            .fetchone()
    )

    if post is None:
        abort(404, f"Component id {id} doesn't exist.")

    return post


def componentobj():
    name = request.form["name"]
    description = request.form["description"]
    mass = request.form["mass"]
    mass_units = request.form["mass_units"]
    density = request.form["density"]
    density_units = request.form["density_units"]
    formula = request.form["formula"]
    sld = request.form["sld"]

    passed = True

    if name.isdecimal() or mass_units.isdecimal() or density_units.isdecimal() or formula.isdecimal():
        flash("Input valid name, mass unit, density unit, and formula")
        passed = False

    if not (isfloat(mass) and isfloat(density) and isfloat(sld)):
        flash("Mass, density, and SLD (optional) must be numbers")
        passed = False

    return ComponentObject(name, description, mass, mass_units, density, density_units, formula, sld, passed)


@bp.route("/component/create", methods=("GET", "POST"))
def create():
    if request.method == "POST":

        component = componentobj()

        if component.passed:
            db = get_db()
            db.execute(
                "INSERT INTO component (name, description, mass, mass_units, density, density_units, formula, sld) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (component.name, component.description, component.mass, component.mass_units, component.density,
                 component.density_units, component.formula, component.sld),
            )
            db.commit()
            return redirect(session['component_url'])

    return render_template("component/create_component.html", back=session['component_url'])


@bp.route("/component/<int:id>/update", methods=("GET", "POST"))
def update(id):
    post = get_post(id)

    if request.method == "POST":
        component = componentobj()

        if component.passed:
            db = get_db()
            db.execute(
                "UPDATE component SET name = ?, description = ?, mass = ?, mass_units = ?, density = ?, density_units = ?, formula = ?, sld = ? WHERE id = ?",
                (component.name, component.description, component.mass, component.mass_units, component.density,
                 component.density_units, component.formula, component.sld, id)
            )
            db.commit()
            # return redirect(url_for("component.index", page=g.page, per_page=g.per_page))
            return redirect(session['component_url'])

    return render_template("component/update_component.html", post=post, back=session['component_url'])


@bp.route("/component/<int:id>/delete", methods=("GET", "POST"))
def delete(id):
    get_post(id)
    db = get_db()
    db.execute("DELETE FROM component WHERE id = ?", (id,))
    db.commit()
    #return redirect(url_for("component.index, page=1, per_page=10"))
    return redirect(session['component_url'])
