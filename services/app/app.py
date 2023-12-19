from flask import Flask, request, jsonify, Response
from flask.cli import with_appcontext
import os
import logging

from config import Config
from extensions import db
from models import BondYield

app = Flask(__name__)
app.config.from_object(Config)

app.logger.addHandler(logging.StreamHandler())
app.logger.setLevel(logging.INFO)

db.init_app(app)

@app.cli.command("create_db")
@with_appcontext
def create_db():
    db.create_all()
    db.session.commit()

@app.cli.command("remove_db")
@with_appcontext
def remove_db():
    db.drop_all()
    db.session.commit()

@app.route("/get_bond/<country>", methods=['GET', 'POST'])
def get_bond(country):

    print(country)
    return Response("Your response body goes here", status=200, mimetype='text/plain')

if __name__ == "__main__":
    app.run(debug=True)