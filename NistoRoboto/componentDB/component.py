import os
from os.path import *

from flask import *
from werkzeug.exceptions import *
from werkzeug.utils import secure_filename

from componentDB.utility.component_object import ComponentObject
from componentDB.utility.utility_function import isfloat, csvread, csvwrite, pagination, page_range
from flaskr.db import get_db

bp = Blueprint("component", __name__)


@bp.route("/component/<int:page>", methods=("GET", "POST"))
def index(page):
    db = get_db()

    filter_by = request.form.get('filter', 'id')

    posts = db.execute(
        f"SELECT * FROM component ORDER BY {filter_by}"
    ).fetchall()

    paged = pagination(page, posts)

    session['component_url'] = url_for('component.index',
                                       page=page)  # save last URL for going back. easier than using cookies

    page_range(page, paged.pages)

    if paged.unified:

        return render_template("component/view_component_unified.html", posts=posts, total=paged.total,
                               unified=paged.unified, filter_by=filter_by)

    else:

        posts = db.execute(
            "SELECT * FROM component ORDER BY id DESC LIMIT ? OFFSET ?", (paged.per_page, paged.offset)
        ).fetchall()

        return render_template("component/view_component.html", posts=posts, total=paged.total, per_page=paged.per_page,
                               pages=paged.pages, page=page, radius=paged.radius, unified=paged.unified)


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


@bp.route("/component/upload", methods=("GET", "POST"))
def upload():
    if request.method == "POST":

        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']

        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)

        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(join(dirname(realpath(__file__)), 'static/uploads'), filename))
            data = csvread(join('static/uploads/', filename))

            """Processing"""
            for row in data:
                if row[7] != '':
                    row[7] = float(row[7].strip())

                insert(row[0].strip(), row[1].strip(), float(row[2].strip()), row[3].strip(), float(row[4].strip()),
                       row[5].strip(), row[6].strip(), row[7])

        return redirect(session['component_url'])

    return render_template("component/upload_component.html", back=session['component_url'])


@bp.route("/component/create", methods=("GET", "POST"))
def create():
    if request.method == "POST":

        component = componentobj()

        if component.passed:
            insert(component.name, component.description, component.mass, component.mass_units, component.density,
                   component.density_units, component.formula, component.sld)

            return redirect(session['component_url'])

    return render_template("component/create_component.html", back=session['component_url'])


def insert(name, description, mass, mass_units, density, density_units, formula, sld):
    db = get_db()

    posts = db.execute(
        "SELECT id FROM component WHERE name = ?", (name,)
    ).fetchone()

    if posts is None:

        db.execute(
            "INSERT INTO component (name, description, mass, mass_units, density, density_units, formula, sld) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, description, mass, mass_units, density, density_units, formula, sld),
        )

    else:

        update_help(posts[0], ComponentObject(name, description, mass, mass_units, density, density_units, formula, sld, True))

    db.commit()


def update_help(id, component):
    db = get_db()
    db.execute(
        "UPDATE component SET name = ?, description = ?, mass = ?, mass_units = ?, density = ?, density_units = ?, formula = ?, sld = ? WHERE id = ?",
        (component.name, component.description, component.mass, component.mass_units, component.density,
         component.density_units, component.formula, component.sld, id)
    )
    db.commit()


@bp.route("/component/<int:id>/update", methods=("GET", "POST"))
def update(id):
    post = get_post(id)

    if request.method == "POST":
        component = componentobj()

        if component.passed:
            update_help(id, component)
            return redirect(session['component_url'])

    return render_template("component/update_component.html", post=post, back=session['component_url'])


@bp.route("/component/export")
def export():
    path = csvwrite('component', 'static/export', '/component_export.txt')
    return send_from_directory(path, 'component_export.txt', as_attachment=True)


@bp.route("/component/send_json", methods=("GET", "POST"))
def send_json():
    if request.method == "POST":
        dictionary = request.get_json()
        db = get_db()
        for entry in dictionary:

            entry['id'] = int(entry['id'])
            entry['mass'] = float(entry['mass'])
            entry['density'] = float(entry['density'])
            if entry['sld'] != '':
                entry['sld'] = float(entry['sld'])

            posts = db.execute(
                "SELECT * FROM component WHERE id = ?", (entry['id'],),
            ).fetchall()
            if len(posts) == 0:
                insert(entry['name'], entry['description'], entry['mass'], entry['mass_units'], entry['density'],
                       entry['density_units'], entry['formula'], entry['sld'])
            else:
                update_help(entry['id'],
                            ComponentObject(entry['name'], entry['description'], entry['mass'], entry['mass_units'],
                                            entry['density'], entry['density_units'], entry['formula'], entry['sld'],
                                            True))

    return "Send JSONS to this url."


@bp.route("/component/json")
def generate_json():
    db = get_db()
    posts = db.execute(
        "SELECT id, name, description, mass, mass_units, density, density_units, formula, sld FROM component ORDER BY id",
    ).fetchall()

    component_list = []

    for i, post in enumerate(posts):
        component_list.append({})

        component_list[i]['id'] = post[0]
        component_list[i]['name'] = post[1]
        component_list[i]['description'] = post[2]
        component_list[i]['mass'] = post[3]
        component_list[i]['mass_units'] = post[4]
        component_list[i]['density'] = post[5]
        component_list[i]['density_units'] = post[6]
        component_list[i]['formula'] = post[7]
        component_list[i]['sld'] = post[8]

    return jsonify(component_list)


@bp.route("/component/<int:id>/delete", methods=("GET", "POST"))
def delete(id):
    get_post(id)
    db = get_db()
    db.execute("DELETE FROM component WHERE id = ?", (id,))
    db.commit()
    return redirect(session['component_url'])
