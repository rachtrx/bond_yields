from flask import Flask, request, jsonify, Response
from flask.cli import with_appcontext
import os
import logging
import traceback

from config import Config
from extensions import db
from models import BondYield, Country
from sqlalchemy import inspect
from sqlalchemy.orm import joinedload
from datetime import datetime

import pandas as pd
import pytz
import json

timezone = pytz.timezone('Asia/Singapore')

# Configure the logging
logging.basicConfig(
    filename='/home/app/logs/main.log',  # Log file path
    filemode='a',  # Append mode
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Log message format
    level=logging.INFO  # Log level
)

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

@app.cli.command("create_db")
@with_appcontext
def create_db():
    # Create an inspector
    inspector = inspect(db.engine)

    # List of all tables that should be created
    # Replace 'YourModel' with actual model class names
    tables = [Country.__tablename__, BondYield.__tablename__]

    # Iterate over the tables and check if they exist
    for table in tables:
        if not inspector.has_table(table):
            print(f"Creating table: {table}")
            # Reflect only the specific table
            db.Model.metadata.create_all(db.engine, tables=[db.Model.metadata.tables[table]])
        else:
            print(f"Table {table} already exists.")

    db.session.commit()

@app.cli.command("remove_db")
@with_appcontext
def remove_db():
    db.drop_all()
    db.session.commit()

@app.route("/get_bond", methods=['GET'])
def get_bond():

    try:
        countries = request.args.get('countries') # this already splits on +
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        if not countries:
            return Response("Bad Request: No parameter for 'countries'", status=400)
        if not start_date:
            return Response("Bad Request: No parameter for 'start_date'", status=400)
        if not end_date:
            return Response("Bad Request: No parameter for 'end_date'", status=400)

        try:
            start_date = datetime.strptime(start_date, "%d-%m-%Y").strftime("%Y-%m-%d")
            end_date = datetime.strptime(end_date, "%d-%m-%Y").strftime("%Y-%m-%d")
        except ValueError:
            return Response("Bad Request: Format for date is wrong", status=400)

        query = db.session.query(BondYield).join(Country)
        if countries != "All":
            country_list = countries.split()
            logging.info(country_list)
            query = query.filter(Country.name.in_(country_list))
        if start_date != "All":
            logging.info(start_date)
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(BondYield.date >= start_date)
        if end_date != "All":
            logging.info(end_date)
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(BondYield.date <= end_date)

        bond_yield_records = query.all()

        data = [
            {
                'Date': record.date,
                'Country': record.country.name,  # Assuming 'name' is an attribute of Country
                'Period': f"{record.period}Y",
                'bond_yield': record.bond_yield,
            }
            for record in bond_yield_records
        ]

        df = pd.DataFrame(data)

        df['bond_yield'] = pd.to_numeric(df['bond_yield'], errors='coerce')

        pivot_df = df.pivot_table(index='Date', columns=['Country', 'Period'], values='bond_yield')
        pivot_df.sort_values(by="Date", inplace=True)

        pivot_df.rename_axis(index=None, inplace=True)

        # logging.info(pivot_df.head())

        html_table = pivot_df.to_html()
        return Response(html_table, mimetype='text/html')
    except Exception as e:
        logging.error(traceback.format_exc())
        return Response("Internal Server Error", status=500, mimetype='text/html')

if __name__ == "__main__":
    app.run(debug=True)