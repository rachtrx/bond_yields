from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver import FirefoxProfile
from sqlalchemy.orm import Session
from selenium.webdriver.firefox.service import Service

from datetime import datetime, timedelta
import time
import pandas as pd
import requests
from io import StringIO
from pathlib import Path
import shutil

import json
import os
import re
import socket
import subprocess
import threading
import sys
from queue import Queue


import logging
import traceback

from extensions import db
from models import BondYield, Asset
from app import app
from logging_config import write_to_logfile, OK, NO_CONTENT

# count = 1

from dotenv import load_dotenv
load_dotenv(".env")

##############################
# CREATING PROFILE AND CERT
##############################

write_lock = threading.Lock()

MAX_THREADS = 2

class BondSync():

    def __init__(self):
        self.jobs = Queue()
        self.realtime_url = 'https://www.investing.com/rates-bonds/world-government-bonds?maturity_from=10&maturity_to=310'

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        self.profile_path = "/home/app/my_firefox_profiles/selenium_profile"
        self.cert_path = '/root/.mitmproxy/mitmproxy-ca-cert.pem'
        self.setup_profile()
        options = FirefoxOptions()
        options.profile = self.profile_path
        options.binary_location='/usr/bin/firefox'
        options.add_argument("--headless")  # Run in headless mode
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-gpu')
        
        self.options = options

    #############################
    # SETUP (RUN IN INIT)
    #############################

    def is_certificate_installed(self):
        # Command to list certificates in the Firefox profile
        command = [
            'certutil', '-L',
            '-d', f'sql:{self.profile_path}'
        ]

        # Run the command and capture the output
        result = subprocess.run(command, capture_output=True, text=True)

        # Check if the certificate is in the output
        return self.cert_path in result.stdout

    def setup_profile(self):
        profile = FirefoxProfile()

        profile_path = profile.path
        
        if not os.path.exists(self.profile_path):
            os.makedirs(self.profile_path)
        shutil.copytree(profile_path, self.profile_path, dirs_exist_ok=True)
        # print("Permanent profile created at:", self.profile_path)

        if not self.is_certificate_installed():
            # Construct the certutil command
            certutil_command = [
                'certutil', '-A', '-n', 'mitmproxy', '-t', 'TCu,Cuw,Tuw',
                '-i', self.cert_path, '-d', f'sql:{self.profile_path}'
            ]

            # Run the certutil command
            subprocess.run(certutil_command)
            # print("CERT ADDED")

        # print("profile set up!")


    ##################################################################
    # SENDING HTTP REQUESTS FOR REALTIME DATA / GETTING COUNTRIES LIST
    ##################################################################
            
    @staticmethod
    def get_service():
        geckodriver_path = '/usr/local/bin/geckodriver'  # Replace with your geckodriver path
        return Service(geckodriver_path)

    def get_new_data(self, retries):

        with webdriver.Firefox(options=self.options, service=self.get_service()) as driver:
            try:
                driver.set_page_load_timeout(5)
                driver.get(self.realtime_url)
            except TimeoutException:
                pass
                # print("TImeout, continuing to extract element")
            except Exception as e:
                logging.error(traceback.format_exc())
            finally:
                
                for _ in range(retries):
                    try:
                        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, 'rates_bonds_table_99')))
                        # Initialize a list to store the data
                        data = []

                        # Find all the rows in the table
                        rows = driver.find_elements(By.XPATH, '//tr[contains(@id, "pair_")]')

                        for row in rows:
                            try:
                                # Check if the row contains "2Y" or "5Y"
                                period = row.find_element(By.XPATH, './/td/a[contains(text(), " 2Y") or contains(text(), " 5Y")]')
                                if period:
                                    # Extract the last value
                                    last = row.find_element(By.XPATH, './/td[3]').text
                                    # Check for the clock icon status
                                    status = 'closed' if row.find_elements(By.XPATH, './/span[contains(@class, "redClockIcon")]') else 'open'
                                    # Append the extracted data to the list
                                    data.append((period.text, last, status))

                            except NoSuchElementException as e:
                                continue

                        # Close the WebDriver
                        driver.quit()

                        # Return the data
                        return data
                    except TimeoutException:
                        pass
                    except Exception as e:
                        logging.error(traceback.format_exc())

                driver.quit()
                return None


    def convert_realtime_to_df(self, data):
        
        df = pd.DataFrame(data=data, columns=['Name', 'Yield', 'Status'])

        df = df[df['Name'].notna() & df['Name'].str.strip().ne('')]

        # format the countries
        df['Country'] = df['Name'].apply(lambda x: ' '.join(x.split()[:-1]))
        df['Country'] = df['Country'].str.lower().str.replace(" ", "-", regex=True)

        # format the period
        df['Name'] = df['Name'].apply(lambda x: x.split()[-1][:-1]) # remove the Y as well
        df.rename(columns = {'Name': 'Period'}, inplace=True)

        # hierachical index
        df = df.set_index(['Country', 'Period'])

        # drop the top level if the 2nd level is only 1 index (ie only either has 2Y or 5Y)
        unique_top_level = df.index.get_level_values(0).unique()
        indices_to_drop = [idx for idx in unique_top_level if len(df.loc[idx]) != 2]
        df.drop(index=indices_to_drop, level=0, inplace = True)
        return df

    @staticmethod
    def get_countries(df):
        countries_list = df.index.get_level_values(0).unique().tolist()
        return countries_list
    
    ###################################################################
    # CHECK FOR DATABASE AND PROXY AVAILABILITY BEFORE RUNNING THREADS
    ###################################################################
    
    @staticmethod
    def is_process_running(host, port, retries=5, delay=10):
        for _ in range(retries):
            try:
                # Try to create a socket connection to the proxy
                with socket.create_connection((host, port), timeout=10):
                    return True
            except OSError:
                time.sleep(delay)  # Wait before retrying
        return False

    ###########################################
    # RUN ALL THREADS AFTER ADDING TO JOB QUEUE
    ###########################################

    def run_all_threads(self):
        try:
            # Check if mitmdump is running
            proxy_host = '127.0.0.1'
            proxy_port = 8080

            database_host = os.environ.get("SQL_HOST")
            database_port = os.environ.get("SQL_PORT")

            if self.is_process_running(proxy_host, proxy_port) and self.is_process_running(database_host, database_port):
                logging.info("Proxy and database are running. Starting main functionality.")
                # Rest of your script
            else:
                logging.error("Proxy or database not started!")
                exit(1)

            data = self.get_new_data(retries=2)
            df = self.convert_realtime_to_df(data)
            countries_list = self.get_countries(df)

            # print(countries_list)

            # BUG Seems like does not work for Docker
            # PROXY = "127.0.0.1:8080"
            # webdriver.DesiredCapabilities.FIREFOX['proxy'] = {
            #     "httpProxy": PROXY,
            #     "ftpProxy": PROXY,
            #     "sslProxy": PROXY,
            #     "proxyType": "Manual",
            # }
            # webdriver.DesiredCapabilities.FIREFOX['marionette'] = True
            
            for country in countries_list:
                for year in ('2', '5'):
                    latest_date = self.get_latest_date(country, int(year))
                    if not latest_date or latest_date + timedelta(days=1) < datetime.now().date():
                        
                        new_from_date = latest_date + timedelta(days=1) if latest_date else None
                        # if not latest_date:
                        #     print(f"Getting data for {country} {year}Y as no latest date")
                        # else:
                        #     print(f"Getting data for {country} {year}Y as latest date was {datetime.strftime(latest_date, "%Y/%m/%d")}")
                        self.jobs.put((country, year, new_from_date))

            for _ in range(MAX_THREADS):
                worker = threading.Thread(target=CountryYearData.extract_data_into_database, args=(self.jobs, self.options))
                worker.start()
        except Exception as e:
            logging.error(traceback.format_exc())

    @staticmethod
    def get_latest_date(country, year):
        with app.app_context():
            latest_bond_yield = (BondYield.query
                            .join(Asset)  # Assuming 'country' is the relationship attribute in BondYield
                            .filter(
                                Asset.name == country,
                                Asset.period == year
                            )
                            .order_by(BondYield.date.desc())
                            .first())
        if not latest_bond_yield:
            # logging.info(f"no latest date for {country} {year}Y")
            return None
        
        return latest_bond_yield.date

class CountryYearData():

    url_list_path = "/var/log/url_list.log"

    def __init__(self, country, year, new_date):
        self.cloud = 1 if os.environ.get("CLOUD") == "1" else 0
        self.country = country
        self._id = None
        self.year = year
        self.data_directory = Path("/home/app/data")
        self.new_from_date = new_date
    
    @property
    def pending_file(self):
        return self.data_directory / f"{self._id}_PENDING.txt"
        
    @property
    def complete_file(self):
        return self.data_directory / f"{self._id}_COMPLETE.txt"

    ###########################################
    # RUN THREAD FOR EACH COUNTRY AND CALLBACK
    ###########################################
        
    @classmethod
    def extract_data_into_database(cls, jobs, options):
        while not jobs.empty():
            args = jobs.get()
            country = args[0]
            year = args[1]
            from_date = args[2]

            try:
                new_country_year = cls(country, year, from_date)
                new_country_year.run_main_thread(options)
            except Exception as e:
                logging.error(traceback.format_exc())
            finally:
                jobs.task_done()

    ###########################################
    # DETERMINE POSSIBLE URLS FOR SELENIUM
    ###########################################

    def get_possible_urls(self):

        # print("getting urls")

        country = self.country

        if self.country == "u.k.":
            country = "uk"
        if self.country == "belgium":
            country = "belguim"

        url_1 = f"https://www.investing.com/rates-bonds/{country}-{self.year}-year-bond-yield-historical-data"
        url_2 = f"https://www.investing.com/rates-bonds/{country}-{self.year}-years-bond-yield-historical-data"
        url_3 = f"https://www.investing.com/rates-bonds/{country}-{self.year}-year-historical-data"

        return [url_1, url_2, url_3]

    def match_possible_urls(self):
        try:
            with open(self.url_list_path, 'r') as file:
                content = file.read().strip()
                file.seek(0)
                if content:
                    url_dict = json.load(file)
                    official_url = url_dict.get(f"{self.country}_{self.year}", {}).get("url")
                    if official_url:
                        # print(f"shortcut url found for {self.country}_{self.year}: {official_url}")
                        # Strip whitespace and newlines from each line before comparing
                        try:
                            official_index = self.url_list.index(official_url)
                            self.url_list[0], self.url_list[official_index] = self.url_list[official_index], self.url_list[0]
                        except ValueError:
                            logging.error(f"Official URL {official_url} is not in the list for some reason")
                        return official_url
                    
        except json.JSONDecodeError as e:
            # Log the error or print a message
            print("URL list file error", traceback.format_exc())
        except FileNotFoundError as e:
            open(self.url_list_path, 'w').close()
        except Exception as e:
            logging.error(traceback.format_exc())
        return None

    def update_url_list_file(self, historical_data_url):
        with write_lock:
            try:
                with open(self.url_list_path, 'r+') as file:
                    content = file.read().strip()
                    file.seek(0)
                    if content:
                        url_dict = json.load(file)
                    else:
                        url_dict = {}

                    key = f"{self.country}_{self.year}"
                    url_dict.setdefault(key, {})  # create an empty dict for the key if it doesn't exist
                    url_dict[key]["url"] = historical_data_url
                    url_dict[key]["id"] = self._id
                    sorted_url_dict = {k: url_dict[k] for k in sorted(url_dict)}

                    file.seek(0)
                    file.truncate()
                    json.dump(sorted_url_dict, file, indent=4)

            except json.JSONDecodeError as e:
                write_to_logfile(self._id, traceback.format_exc())
            except Exception as e:
                logging.error(traceback.format_exc())


    #############################################################
    # SELENIUM FUNCTIONS USING FIREFOX BROWSER WITHIN EACH THREAD
    #############################################################

    def get_id(self, driver, url, retries):
        # print(url)
        # global count
        try:
            driver.get(url)
        except TimeoutException:
            pass
            # print("TImeout, continuing to extract element")
        except Exception as e:
            logging.error(traceback.format_exc())
        finally:
            for _ in range(retries):
                try:
                    # print("checking for element")
                    script_element = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.ID, '__NEXT_DATA__'))
                    )
                    if script_element:
                        # print("element found!")
                        script_content = script_element.get_attribute('textContent')

                        # driver.save_screenshot(f"/home/app/img/{count}.png")
                        
                        # page_source = driver.page_source
                        # with open(f"/home/app/page_source/{count}.html", "w", encoding="utf-8") as file:
                        #     file.write(page_source)
                        # count += 1

                        outer_json = json.loads(script_content)

                        # Now parse the inner JSON string which is escaped
                        state = outer_json['props']['pageProps']['state']
                        new_json = json.loads(state)
                        self._id = new_json['dataStore']['pageInfoStore']['identifiers']['instrument_id']

                        if not self.cloud:
                            return
                        else:
                            self.cloud_get_data(driver)
                    # else:
                        # print("no element found")
                except TimeoutException:
                    # print("NO ID, RETRYING")
                    pass
                except Exception as e:
                    logging.error(traceback.format_exc())


    ############################################
    # CLOUDFLARE BLOCKING UNFORTUNATELY
    ############################################

    def cloud_get_data(self, driver):
            
        try:
            # WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, '//table[contains(@class, "w-full text-xs leading-4 overflow-x-auto freeze-column-w-1")]')))
            # Initialize a list to store the data
            self.cloud_data = []

            # Find all the rows in the table
            rows = driver.find_elements(By.XPATH, '//tr[contains(@class, "historical-data-v2_price__atUfP")]')

            for row in rows:
                try:
                    time_el = row.find_element(By.XPATH, './/td/time[@datetime]')
                    if time_el:
                        date_obj = datetime.strptime(time_el.text, "%m/%d/%Y")
                        if self.new_from_date and not date_obj.date() > self.new_from_date:
                            continue
                        # Extract the yield, XPATH is 1 based indexing
                        bond_yield = row.find_element(By.XPATH, './/td[2]').text
                        # Append the extracted data to the list
                        self.cloud_data.append((bond_yield, date_obj))

                except NoSuchElementException as e:
                    continue
        
        except Exception as e:
            logging.error(traceback.format_exc())
        
    def cloud_write_to_database(self):
        
        if len(self.cloud_data) == 0:
            # write_to_logfile(self._id, "no new cloud data")
            return

        try:

            extracted_data = [
                {"yield": item[0], "date": item[1]}
                for item in self.cloud_data
            ]

            # write_to_logfile(self._id, f"writing to database: {extracted_data}")

            # Create a DataFrame from the extracted data
            df = pd.DataFrame(extracted_data)
            df['date'] = df['date'].dt.date

            write_to_logfile(self._id, df.info())
            df['date'] = pd.to_datetime(df['date'])
            df.sort_values(by='date', ascending=False, inplace=True)

            with app.app_context():
                asset = db.session.query(Asset).filter_by(name=self.country, period=int(self.year)).first()
                if not asset:
                    asset = Asset(name=self.country, period=self.year)

                # Iterate over the DataFrame and insert bond yields
                for _, row in df.iterrows():
                    BondYield(date=row['date'], asset_id=asset.id, bond_yield=row['yield'], ref_id = self._id)

            
        
        except Exception as e:
            write_to_logfile(self._id, traceback.format_exc())


    ####################################################################
    # WRITING TO DATABASE FROM FILE PRODUCED BY PROXY WITHIN EACH THREAD
    ####################################################################

    def wait_for_file_complete(self, timeout=2, retries=30):
        for _ in range(retries):
            if not self.complete_file.exists():
                time.sleep(timeout)
            else:
                break

        if self.complete_file.exists():
            with open(self.complete_file, 'r+') as file:
                content = file.read().strip()
                file.seek(0)
                if not content:
                    return NO_CONTENT
                else:
                    return OK
        return 0

    def update_file(self):

        status = self.wait_for_file_complete()

        if not status:
            if not self.pending_file.exists():
                write_to_logfile(self._id, "COMPLETE FILE NOT FOUND")
                return

            status = self.wait_for_file_complete()
            if not status:
                write_to_logfile(self._id, "COMPLETE FILE NOT FOUND")
                return
            
        if status == NO_CONTENT:
            write_to_logfile(self._id, f"COMPLETE FILE EMPTY")
            os.remove(self.complete_file)
            return

        self.write_to_database()
        write_to_logfile(self._id, "FILE ADDED TO DATABASE")


    def write_to_database(self):

        with open(self.complete_file, 'r') as f:
            content = f.read()

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            write_to_logfile(self._id, traceback.format_exc())
        except Exception as e:
            logging.error(traceback.format_exc())
        
        try:
            extracted_data = [
                {"yield": item["last_close"], "date": item["rowDateTimestamp"]}
                for item in data['data']
            ]

            # Create a DataFrame from the extracted data
            df = pd.DataFrame(extracted_data)
            df['date'] = df.date.apply(lambda x: x.split('T')[0])
            df['date'] = pd.to_datetime(df['date'])
            df.sort_values(by='date', ascending=False, inplace=True)

            with app.app_context():
                asset = db.session.query(Asset).filter_by(name=self.country, period=int(self.year)).first()
                if not asset:
                    asset = Asset(name=self.country, period=self.year)

                # Iterate over the DataFrame and insert bond yields
                for _, row in df.iterrows():
                    BondYield(date=row['date'], asset_id=asset.id, bond_yield=row['yield'], ref_id = self._id)
        
        except Exception as e:
            write_to_logfile(self._id, traceback.format_exc())
        finally:
            os.remove(self.complete_file)

    ###########################################
    # RUN MAIN FOR EACH COUNTRY AND CALLBACK
    ###########################################

    def run_main_thread(self, options):
        with webdriver.Firefox(options=options, service=BondSync.get_service()) as driver:
            try:
                driver.set_page_load_timeout(5)  # Set timeout to 10 seconds

                self.url_list = self.get_possible_urls()
                # print(self.url_list)
            
                found = 0
                attempt_count = 0
                max_attempts = len(self.url_list)

                official_url = self.match_possible_urls()

                while attempt_count < max_attempts and not found:
                    try:
                        historical_data_url = self.url_list[attempt_count]
                        # get the instrument id, or return None if 404 returned

                        # logging.info(historical_data_url)
                        
                        self.get_id(driver, historical_data_url, retries=2)

                        # print(f"instrument id: {self._id}")
                        if self._id is None:
                            raise FileNotFoundError

                        if not official_url or historical_data_url != official_url:
                            self.update_url_list_file(historical_data_url)

                        # CLOUD WILL HAVE LATEST DATE
                        if not self.cloud:
                            self.update_file() # ADD TO DATABASE
                        else:
                            self.cloud_write_to_database()

                        found = 1
                    except FileNotFoundError:
                        print("FileNotFoundError caught. Attempting to modify URL and retry.")
                        logging.error(f"Modifying URL to {historical_data_url}.")
                        # LOOPS BACK AND TRIES TO GET ID AGAIN IN TRY BLOCK
                    except Exception as e:
                        write_to_logfile(self._id, traceback.format_exc())
                    finally:
                        attempt_count += 1

                if not found:
                    write_to_logfile("failed_ids", f"Failed to extract data for {self.country} {self.year}Y after {max_attempts} attempts.")
            
            except Exception as e:
                logging.error(traceback.format_exc())
            finally:
                driver.quit()

if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "1" and os.environ.get('CLOUD') == "1":
            pass
        else:
            logging.info("entry")
            bond_sync_controller = BondSync()
            bond_sync_controller.run_all_threads()
    except Exception as e:
        logging.error(traceback.format_exc())
    
    # TODO CLEAR ALL FILES

    