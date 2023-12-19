from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.common.exceptions import TimeoutException
from selenium.webdriver import FirefoxProfile
from sqlalchemy.orm import Session

import datetime
import time
import pandas as pd
import requests
from io import StringIO
from extensions import db

import shutil

from models import BondYield

import json
import os
import re
import socket
import subprocess

count = 1

PROFILE_PATH = "/home/app/my_firefox_profiles/selenium_profile"
CERT_PATH = '/root/.mitmproxy/mitmproxy-ca-cert.pem'

def setup_profile():
    profile = FirefoxProfile()

    profile_path = profile.path
    
    if not os.path.exists(PROFILE_PATH):
        os.makedirs(PROFILE_PATH)
    shutil.copytree(profile_path, PROFILE_PATH, dirs_exist_ok=True)
    print("Permanent profile created at:", PROFILE_PATH)

    if not is_certificate_installed(PROFILE_PATH, 'mitmproxy'):
        # Construct the certutil command
        certutil_command = [
            'certutil', '-A', '-n', 'mitmproxy', '-t', 'TCu,Cuw,Tuw',
            '-i', CERT_PATH, '-d', f'sql:{PROFILE_PATH}'
        ]

        # Run the certutil command
        subprocess.run(certutil_command)
        print("CERT ADDED")

def is_proxy_running(host, port, retries=5, delay=10):
    for _ in range(retries):
        try:
            # Try to create a socket connection to the proxy
            with socket.create_connection((host, port), timeout=10):
                return True
        except OSError:
            time.sleep(delay)  # Wait before retrying
    return False

# The request URL

def get_new_data(url, headers):
    req = requests.get(url, headers=headers, verify=CERT_PATH)
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
    df.rename(columns = {'Name': 'Period', 'Yield': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}, inplace=True)
    df = df.set_index(['Country', 'Period'])
    df = df.transpose()
    return df

def get_countries(df):
    countries_list = [country.lower().replace(" ", "-") for country in df.columns.get_level_values(0).unique().tolist()]
    return countries_list

def get_id(driver, url, retries):
    global count
    try:
        driver.get(url)
    except Exception as e:
        print("Error:", e)
        # Handle the exception or re-raise it
    finally:
        for _ in range(retries):
            try:
                print("checking for element")
                script_element = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, '__NEXT_DATA__'))
                )
                if script_element:
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
                    instrument_id = new_json['dataStore']['pageInfoStore']['identifiers']['instrument_id']
                
                    return instrument_id
            except TimeoutException:
                return None

def main():

    setup_profile()

    # Check if mitmdump is running
    proxy_host = '127.0.0.1'
    proxy_port = 8080

    if is_proxy_running(proxy_host, proxy_port):
        print("Proxy is running. Starting main functionality.")
        # Rest of your script
    else:
        print("Proxy is not running. Exiting.")
        exit(1)

    url = 'https://www.investing.com/rates-bonds/world-government-bonds?maturity_from=10&maturity_to=310'

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
    }

    df = get_new_data(url, headers)
    countries_list = get_countries(df)

    print(countries_list)

    options = FirefoxOptions()
    options.profile = PROFILE_PATH
    options.add_argument("--headless")  # Run in headless mode
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-gpu')

    # BUG Seems like does not work for Docker
    # PROXY = "127.0.0.1:8080"
    # webdriver.DesiredCapabilities.FIREFOX['proxy'] = {
    #     "httpProxy": PROXY,
    #     "ftpProxy": PROXY,
    #     "sslProxy": PROXY,
    #     "proxyType": "Manual",
    # }
    # webdriver.DesiredCapabilities.FIREFOX['marionette'] = True

    with webdriver.Firefox(options=options) as driver:
        driver.get("http://icanhazip.com/")
        ip_address = driver.find_element(By.TAG_NAME, 'body').text.strip()
        print(f"The IP address detected by WebDriver is: {ip_address}")
        driver.set_page_load_timeout(5)  # Set timeout to 10 seconds
        for country in countries_list:
            for year in ('2', '5'):
                found = 0
                historical_data_url = f"https://www.investing.com/rates-bonds/{country}-{year}-year-bond-yield-historical-data"
                print(historical_data_url)
                try:
                    instrument_id = get_id(driver, historical_data_url, retries = 2)
                    rename_file(instrument_id, country, year)
                    found = 1
                except FileNotFoundError:
                    print("checking for substring")
                    if "-bond-yield" in historical_data_url:
                        print("substring found")
                        print(historical_data_url.replace("-bond-yield", ""))
                        instrument_id = get_id(driver, historical_data_url.replace("-bond-yield", ""), retries = 2)
                        rename_file(instrument_id, country, year)
                        found = 1
                except Exception as e:
                    print(f"Error: {e}")
                finally:
                    if found == 0:
                        print(f"Data for {country} {year}Y was not found")
                    
        driver.quit()

        # for country in countries_list:
        #     for year in ('2', '5'):
        #         write_to_database(country, year) # TODO use in rename file?


def write_to_database(_id, country, year):
    with open(f"{_id}.txt", 'r') as f:
        content = f.read()

        try:
            data = json.loads(content)
            print(json.dumps(data, indent=4))
        except json.JSONDecodeError:
            print("Error: the file content is not valid JSON.")  
        except Exception as e:
            print(f"Error: {e}")

    extracted_data = [
        {"yield": item["last_close"], "date": item["rowDateTimestamp"]}
        for item in data['body']['data']
    ]

    # Create a DataFrame from the extracted data
    df = pd.DataFrame(extracted_data)
    df['date'] = df.date.apply(lambda x: x.split('T')[0])
    df['date'] = pd.to_datetime(df['date'])
    df['date'] = df['date'].dt.strftime('%Y/%m/%d')

    session = Session(bind=db.engine)

    # Iterate over the DataFrame and insert bond yields
    for _, row in df.iterrows():
        bond_yield = BondYield(date=row['date'], country_name=country, bond_yield=row['yield'])
        session.add(bond_yield)

    # Commit the session to insert the bond yields
    session.commit()
    session.close()

def rename_file(_id, country, year):

    print(f"id for {country}: {_id}")

    if _id is None:
        raise FileNotFoundError

    data_directory = "/home/app/data"
    # data_directory = os.getcwd()
    
    dir_list = os.listdir(data_directory)
    
    filename = None

    for _file in dir_list:
        if _file == f"{_id}.txt":
            filename = _file
            break  # Exit the loop as soon as we find the file

    if filename:
        write_to_database(country, year)
        print("FILE FOUND")
        new_filename = f"{_id}_{country}_{year}.txt"
        os.rename(data_directory + '/' + filename, data_directory + '/' + new_filename)
        print("FILE RENAMED")
    else:
        print("FILE NOT FOUND BUT ID SENT")
        
            
            # # Open and read the file
            # try:
            #     with open(file_path, 'r') as file:
            #         # extract_data
            # except json.JSONDecodeError as e:
            #     print(f"Error reading JSON from file {filename}: {e}")
            # except FileNotFoundError:
            #     print(f"File {filename} not found in the directory {data_directory}.")
            # except Exception as e:
            #     print(f"An unexpected error occurred: {e}")


def is_certificate_installed(profile_path, cert_name):
    # Command to list certificates in the Firefox profile
    command = [
        'certutil', '-L',
        '-d', f'sql:{profile_path}'
    ]

    # Run the command and capture the output
    result = subprocess.run(command, capture_output=True, text=True)

    # Check if the certificate is in the output
    return cert_name in result.stdout

def get_firefox_profile_path():
    # Path to the Firefox profile directory
    profiles_dir = os.path.expanduser("~/.mozilla/firefox/")

    try:
        # Run the command to list profile directories
        output = subprocess.check_output(["ls", profiles_dir], text=True)

        # Split the output to get individual directory names
        profiles = output.strip().split('\n')

        # Logic to pick the correct profile (this part may need customization)
        # Example: picking the first profile
        profile = profiles[0] if profiles else None

        return os.path.join(profiles_dir, profile) if profile else None
    except subprocess.CalledProcessError as e:
        print("Error while getting Firefox profile path:", e)
        return None


if __name__ == "__main__":
    main()
    print("FINISHED")