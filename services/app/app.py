from flask import Flask, request, jsonify, Response, render_template
from flask.cli import with_appcontext
import os
import logging
import traceback

from config import Config
from extensions import db
from models import BondYield, Asset, BondYieldRealtime
from sqlalchemy import inspect, desc
from sqlalchemy.orm import joinedload, aliased
from datetime import datetime
from utilities import timeframes

import pandas as pd
import pytz
import json

timezone = pytz.timezone('Asia/Singapore')

# Configure the logging
logging.basicConfig(
    filename='/var/log/main.log',  # Log file path
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
    tables = [Asset.__tablename__, BondYield.__tablename__, BondYieldRealtime.__tablename__]

    # Iterate over the tables and check if they exist
    for table in tables:
        if not inspector.has_table(table):
            logging.info(f"Creating table: {table}")
            # Reflect only the specific table
            db.Model.metadata.create_all(db.engine, tables=[db.Model.metadata.tables[table]])
        else:
            logging.info(f"Table {table} already exists.")

    db.session.commit()

@app.cli.command("remove_db")
@with_appcontext
def remove_db():
    db.drop_all()
    db.session.commit()

@app.route("/get_realtime", methods=['GET'])
def get_realtime():
    try:
        countries = request.args.get('countries')
        timeframe = request.args.get('timeframe')

        try:
            max_rows = int(request.args.get('max_rows'))
        except ValueError:
            return Response("Bad Request: Max rows must be a number", status=400)

        if not countries:
            return Response("Bad Request: No parameter for 'countries'", status=400)
        if not timeframe:
            return Response("Bad Request: No parameter for 'timeframe'", status=400)
        if not max_rows:
            return Response("Bad Request: No parameter for 'max_rows'", status=400)
        if max_rows > 5000:
            return Response("Bad Request: Largest value for 'max_rows' is 5000", status=400)
        if not timeframes.get(timeframe):
            return Response("Bad Request: Timeframe must be one of the following values: ['1M', '5M', '15M', '30M', '1H', '2H', '4H']", status=400)

        timeframe = timeframes.get(timeframe)

        query = db.session.query(BondYieldRealtime).join(Asset)

        if countries != "All":
            country_list = countries.split()
            query = query.filter(Asset.name.in_(country_list))

        query = query.filter(
                BondYieldRealtime.timeframe == timeframe,
            ).order_by(
                desc(BondYieldRealtime.datetime)
            ).limit(max_rows)
            
        bond_yield_records = query.all()

        if len(bond_yield_records) == 0 and max_rows != 0:
            return Response("Bad Request: Country does not exist in database or has discontinued real time data", status=400)

        data = [
            {
                'DateTime': record.datetime,
                'Country': record.asset.name,  # Assuming 'name' is an attribute of Country
                'Period': f"{record.asset.period}Y",
                'bond_yield': record.bond_yield,
            }
            for record in bond_yield_records
        ]

        df = pd.DataFrame(data)

        df['bond_yield'] = pd.to_numeric(df['bond_yield'], errors='coerce')

        pivot_df = df.pivot_table(index='DateTime', columns=['Country', 'Period'], values='bond_yield')
        pivot_df.sort_values(by="DateTime", inplace=True)

        pivot_df.rename_axis(index=None, inplace=True)

        logging.info(pivot_df.head())

        html_table = pivot_df.to_html()
        return Response(html_table, mimetype='text/html')


    except Exception as e:
        logging.error(traceback.format_exc())
        return Response("Internal Server Error", status=500, mimetype='text/html')


@app.route("/get_historical", methods=['GET'])
def get_historical():

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

        query = db.session.query(BondYield).join(Asset)
        if countries != "All":
            country_list = countries.split()
            logging.info(country_list)
            query = query.filter(Asset.name.in_(country_list))
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
                'Country': record.asset.name,  # Assuming 'name' is an attribute of Country
                'Period': f"{record.asset.period}Y",
                'bond_yield': record.bond_yield,
            }
            for record in bond_yield_records
        ]

        df = pd.DataFrame(data)

        df['bond_yield'] = pd.to_numeric(df['bond_yield'], errors='coerce')

        pivot_df = df.pivot_table(index='Date', columns=['Country', 'Period'], values='bond_yield')
        pivot_df.sort_values(by="Date", inplace=True)

        pivot_df.rename_axis(index=None, inplace=True)

        logging.info(pivot_df.head())

        html_table = pivot_df.to_html()
        return Response(html_table, mimetype='text/html')
    except Exception as e:
        logging.error(traceback.format_exc())
        return Response("Internal Server Error", status=500, mimetype='text/html')
    
@app.route("/data", methods=['GET'])
def get_data():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)