import os

from flask import *

def create_app(test_config=None):
    # create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY='dev',
        DATABASE=os.path.join(app.instance_path, 'flaskr.sqlite'),
    )

    if test_config is None:
        # load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    from . import db
    db.init_app(app)

    from . import mainview
    app.register_blueprint(mainview.bp)
    app.add_url_rule('/', endpoint='index')

    from . import component
    app.register_blueprint(component.bp)
    app.add_url_rule('/', endpoint='index')

    from . import stock
    app.register_blueprint(stock.bp)
    app.add_url_rule('/', endpoint='index')

    from . import stock_component
    app.register_blueprint(stock_component.bp)
    app.add_url_rule('/', endpoint='index')

    from . import sample_stock
    app.register_blueprint(sample_stock.bp)
    app.add_url_rule('/', endpoint='index')

    from . import sample
    app.register_blueprint(sample.bp)
    app.add_url_rule('/', endpoint='index')

    from . import measurement
    app.register_blueprint(measurement.bp)
    app.add_url_rule('/', endpoint='index')

    return app