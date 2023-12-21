from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.common.exceptions import TimeoutException
from selenium.webdriver import FirefoxProfile
from sqlalchemy.orm import Session

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
from queue import Queue


import logging
import traceback

from extensions import db
from models import BondYield, Country
from app import app
from logging_config import write_to_logfile, OK, NO_CONTENT

# count = 1

##############################
# CREATING PROFILE AND CERT
##############################

write_lock = threading.Lock()

MAX_THREADS = 5

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
        print("Permanent profile created at:", self.profile_path)

        if not self.is_certificate_installed():
            # Construct the certutil command
            certutil_command = [
                'certutil', '-A', '-n', 'mitmproxy', '-t', 'TCu,Cuw,Tuw',
                '-i', self.cert_path, '-d', f'sql:{self.profile_path}'
            ]

            # Run the certutil command
            subprocess.run(certutil_command)
            print("CERT ADDED")


    ##################################################################
    # SENDING HTTP REQUESTS FOR REALTIME DATA / GETTING COUNTRIES LIST
    ##################################################################


    def get_new_data(self):
        req = requests.get(self.realtime_url, headers=self.headers, verify=self.cert_path)
        html_content = StringIO(req.text)
        tables = pd.read_html(html_content)
        df = pd.concat(tables, ignore_index=True)
        df.dropna(subset=['Name'], inplace=True)
        df.dropna(axis=1, how='all', inplace=True)
        df = df.loc[:, ['Name', 'Yield']]
        mask = (df.Name.str.endswith(' 2Y') | df.Name.str.endswith(' 5Y'))
        df = df.loc[mask]
        df = df.reset_index(drop=True)
        df['Country'] = df['Name'].apply(lambda x: ' '.join(x.split()[:-1]))
        df['Name'] = df['Name'].apply(lambda x: x.split()[-1])
        df.rename(columns = {'Name': 'Period', 'Yield': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}, inplace=True)
        df = df.set_index(['Country', 'Period'])

        # drop the top level if the 2nd level is only 1 index
        unique_top_level = df.index.get_level_values(0).unique()
        indices_to_drop = [idx for idx in unique_top_level if len(df.loc[idx]) != 2]
        df.drop(index=indices_to_drop, level=0, inplace = True)
        df = df.transpose()
        return df

    @staticmethod
    def get_countries(df):
        countries_list = [country.lower().replace(" ", "-") for country in df.columns.get_level_values(0).unique().tolist()]
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

            df = self.get_new_data()
            countries_list = self.get_countries(df)

            print(countries_list)

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
                        if not latest_date:
                            print(f"Getting data for {country} {year}Y as no latest date")
                        else:
                            print(f"Getting data for {country} {year}Y as latest date was {datetime.strftime(latest_date, "%Y/%m/%d")}")
                        self.jobs.put((country, year))

            for _ in range(MAX_THREADS):
                worker = threading.Thread(target=CountryYearData.extract_data_into_database, args=(self.jobs, self.options))
                worker.start()
        except Exception as e:
            logging.error(traceback.format_exc())

    @staticmethod
    def get_latest_date(country, year):
        with app.app_context():
            latest_bond_yield = (BondYield.query
                            .join(Country)  # Assuming 'country' is the relationship attribute in BondYield
                            .filter(
                                Country.name == country,
                                BondYield.period == year
                            )  # Assuming 'name' is the attribute in Country
                            .order_by(BondYield.date.desc())
                            .first())
        if not latest_bond_yield:
            return None
        
        return latest_bond_yield.date

class CountryYearData():

    url_list_path = "/home/app/logs/url_list.log"

    def __init__(self, country, year):
        self.country = country
        self._id = None
        self.year = year
        self.data_directory = Path("/home/app/data")
    
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

            try:
                new_country_year = cls(country, year)
                new_country_year.run_main_thread(options)
            except Exception as e:
                logging.error(traceback.format_exc())
            finally:
                jobs.task_done()

    ###########################################
    # DETERMINE POSSIBLE URLS FOR SELENIUM
    ###########################################

    def get_possible_urls(self):

        print("getting urls")

        country = self.country

        if self.country == "u.k.":
            country = "uk"
        if self.country == "belgium":
            country = "belguim"

        url_1 = f"https://www.investing.com/rates-bonds/{country}-{self.year}-year-bond-yield-historical-data"
        url_2 = f"https://www.investing.com/rates-bonds/{country}-{self.year}-year-historical-data"
        url_3 = f"https://www.investing.com/rates-bonds/{country}-{self.year}-year-bond-yield"
        url_4 = f"https://www.investing.com/rates-bonds/{country}-{self.year}-years-bond-yield"
        url_5 = f"https://www.investing.com/rates-bonds/{country}-{self.year}-year"

        return [url_1, url_2, url_3, url_4, url_5]

    def match_possible_urls(self):
        try:
            with open(self.url_list_path, 'r') as file:
                content = file.read().strip()
                file.seek(0)
                if content:
                    url_dict = json.load(file)
                    official_url = url_dict.get(f"{self.country}_{self.year}", {}).get("url")
                    if official_url:
                        print(f"shortcut url found for {self.country}_{self.year}")
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
        print(url)
        global count
        try:
            driver.get(url)
        except TimeoutException:
            print("TImeout, continuing to extract element")
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

                        os.listdir()
                    # else:
                        # print("no element found")
                except TimeoutException:
                    print("NO ID, RETRYING")
                    return None
                except Exception as e:
                    logging.error(traceback.format_exc())


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
            df.sort_values(by='date', ascending=True, inplace=True)

            with app.app_context():
                country = db.session.query(Country).filter_by(name=self.country).first()
                if not country:
                    country = Country(name=self.country)

                # Iterate over the DataFrame and insert bond yields
                for _, row in df.iterrows():
                    BondYield(date=row['date'], country_name=self.country, country_id=country.id, bond_yield=row['yield'], period=self.year, ref_id = self._id)
        
        except Exception as e:
            write_to_logfile(self._id, traceback.format_exc())
        finally:
            os.remove(self.complete_file)

    ###########################################
    # RUN MAIN FOR EACH COUNTRY AND CALLBACK
    ###########################################

    def run_main_thread(self, options):
        with webdriver.Firefox(options=options) as driver:
            try:
                driver.set_page_load_timeout(5)  # Set timeout to 10 seconds

                self.url_list = self.get_possible_urls()
                print(self.url_list)
            
                found = 0
                attempt_count = 0
                max_attempts = len(self.url_list)

                official_url = self.match_possible_urls()

                while attempt_count < max_attempts and not found:
                    try:
                        historical_data_url = self.url_list[attempt_count]
                        # get the instrument id, or return None if 404 returned
                        self.get_id(driver, historical_data_url, retries=2)

                        print(f"instrument id: {self._id}")
                        if self._id is None:
                            raise FileNotFoundError

                        if not official_url or historical_data_url != official_url:
                            self.update_url_list_file(historical_data_url)

                        self.update_file() # ADD TO DATABASE
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
        bond_sync_controller = BondSync()
        bond_sync_controller.run_all_threads()
    except Exception as e:
        logging.error(traceback.format_exc())
    
    # TODO CLEAR ALL FILES

    