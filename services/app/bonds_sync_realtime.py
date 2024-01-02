from bonds_sync_daily import BondSync
from utilities import current_sg_time
from extensions import db
from datetime import datetime, timedelta
from models import BondYieldRealtime, Asset
from app import app
import logging
from logging_config import write_to_logfile
import traceback

# def get_latest_value(country, year):
#     with app.app_context():
#         latest_bond_yield = (BondYieldRealtime.query
#                         .join(Asset)  # Assuming 'country' is the relationship attribute in BondYield
#                         .filter(
#                             Asset.name == country,
#                             Asset.period == year
#                         )
#                         .order_by(BondYieldRealtime.datetime.desc())
#                         .first())
#     if not latest_bond_yield:
#         return None
    
#     return latest_bond_yield.bond_yield



def write_to_database(df):

    # write_to_logfile("realtime_data", "writing to database")

    try:
        datetime_now = current_sg_time()
        rounded_datetime = datetime_now - timedelta(seconds=datetime_now.second, microseconds=datetime_now.microsecond)
        total_min = rounded_datetime.hour * 60 + rounded_datetime.minute

        write_to_logfile("realtime_data", f"{rounded_datetime}")

        for timeframe in [240, 120, 60, 30, 15, 5, 1]:
            if total_min % timeframe == 0:
                highest_timeframe = timeframe
                break

        write_to_logfile("realtime_data", datetime_now)

        with app.app_context():

            for (country_name, period), row in df.iterrows():

                # Assuming you have a function get_country_id to map country names to IDs
                asset = db.session.query(Asset).filter_by(name=country_name, period=int(period)).first()
                if not asset:
                    asset = Asset(name=country_name, period=period)
                    write_to_logfile("realtime_data", "asset added!")

                latest_entry = BondYieldRealtime.latest_entry(asset.id)

                # Create a new instance of the model
                if row['Status'] == "open":
                    BondYieldRealtime(
                        datetime=rounded_datetime,
                        asset_id=asset.id,
                        bond_yield=row['Yield'],
                        is_open=1 if latest_entry and latest_entry.is_close == 1 else 0,
                        timeframe=highest_timeframe
                    )
                    
                elif latest_entry and not latest_entry.is_close == 1:
                    latest_entry.is_close == 1
                    db.session.commit()

    except Exception as e:
        write_to_logfile("realtime_data", traceback.format_exc())

def main():
    write_to_logfile("realtime_data", "entry")
    bond_sync_controller = BondSync()
    print(bond_sync_controller.cert_path)
    new_data = bond_sync_controller.get_new_data(retries=3)
    if new_data == None:
        write_to_logfile("realtime_data", f"failed to get data for {datetime.strftime(current_sg_time(), '%Y-%m-%d %H:%M')}")
    else:
        new_data_df = bond_sync_controller.convert_realtime_to_df(new_data)
        write_to_database(new_data_df)

if __name__ == "__main__":
    main()