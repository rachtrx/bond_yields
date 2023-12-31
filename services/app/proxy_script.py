from mitmproxy import ctx, http
from datetime import datetime, timedelta
import re
import os
import json
from models import BondYield
from app import app

import traceback

from logging_config import write_to_logfile, OK, NO_CONTENT

class CaptureAuthHeader:
    def request(self, flow: http.HTTPFlow) -> None:

        # Check if the request URL meets the criteria. its always in the form /api/financialdata/historical/23703?start_date=2023-11-20&end-date=2023-12-18&time-frame=Daily&add-missing-rows=false
        if flow.request.pretty_url.startswith("https://api.investing.com") and \
           flow.request.pretty_url.endswith("add-missing-rows=false"):
            try:
                _id = self.get_req_id(flow.request.pretty_url)
                sending = True
                if not flow.is_replay:
                    latest_date = self.get_latest_date_by_ref_id(_id)
                    if not latest_date:
                        flow.request.query["start-date"] = "2000-01-01"
                    else:
                        next_day = latest_date + timedelta(days=1)
                        if next_day < datetime.now().date():
                            write_to_logfile(_id, f"Latest date was {latest_date}")
                            flow.request.query["start-date"] = next_day.strftime('%Y-%m-%d')
                            flow.request.query["end-date"] = datetime.now().strftime('%Y-%m-%d')
                        else:
                            sending = False
                            write_to_logfile(_id, f"Status code 204")
                            complete_file = f"/home/app/data/{_id}_COMPLETE.txt"
                            open(complete_file, 'w').close()
                            flow.response = http.Response.make(
                                status_code=NO_CONTENT,
                                content=b"Database is up to date",
                                headers={"Content-Type": "text/plain"}
                            )
                if sending == True:        
                    flow.request.headers["user-agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    flow.request.headers["Accept"] = "application/json, text/plain, */*"
                    flow.request.headers["Accept-Encoding"] = "gzip, deflate, br"
                    flow.request.headers["Accept-Language"] = "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7"
                    flow.request.headers["Cache-Control"] = "no-cache"
                    flow.request.headers["Domain-Id"] = "www"
                    flow.request.headers["Origin"] = "https://www.investing.com"
                    flow.request.headers["Referer"] = "https://www.investing.com/"
                    flow.request.headers["Sec-Ch-Ua"] = '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"'
                    flow.request.headers["Sec-Ch-Ua-Mobile"] = "?0"
                    flow.request.headers["Sec-Ch-Ua-Platform"] = '"Windows"'
                    flow.request.headers["Sec-Fetch-Dest"] = "empty"
                    flow.request.headers["Sec-Fetch-Mode"] = "cors"
                    flow.request.headers["Sec-Fetch-Site"] = "same-site"
                    with open("/home/app/logs/cookie.log", 'r') as file:
                        cookie = file.read().strip()
                    flow.request.headers["Cookie"] = cookie

                    write_to_logfile(_id, f"(PROXY) Getting data from {flow.request.query["start-date"]} to {flow.request.query["end-date"]}")
            except Exception as e:
                write_to_logfile(_id, traceback.format_exc())

    def response(self, flow: http.HTTPFlow) -> None:
        # Check if the URL matches the pattern for which you want to log the response
        if flow.request.pretty_url.startswith("https://api.investing.com") and \
           flow.request.pretty_url.endswith("add-missing-rows=false"):
            _id = self.get_req_id(flow.request.pretty_url)
            if _id:
                complete_file = f"/home/app/data/{_id}_COMPLETE.txt"
                if flow.response.status_code != OK and flow.response.status_code != NO_CONTENT:
                    write_to_logfile(_id, f"status code: {flow.response.status_code}")
                    return
                
                data = json.loads(flow.response.get_text())
                
                if data['data'] == None or flow.response.status_code == NO_CONTENT:
                    open(complete_file, 'w').close()
                    return
                
                # block_file = f"/home/app/data/{_id}_BLOCK.txt"
                # print(json.dumps(data, indent=4))
                if flow.is_replay:
                    append = True
                else:
                    append = False
                try:
                    pending_file = self.write_to_file(_id, flow.response.status_code, data, append)
                    if pending_file:
                        if len(data["data"]) > 4999: # investing.com returns max 5000 rows
                            # print(f"NEW START DATE: {flow.request.query["start-date"]}")
                            resend_flow = flow.copy()
                            latest_resp_date = self.get_latest_resp_date(data)
                            # print(f"LATEST RESP DATE {latest_resp_date}")
                            resend_flow.request.query["start-date"] = latest_resp_date
                            resend_flow.request.query["end-date"] = datetime.now().strftime('%Y-%m-%d')
                            ctx.master.commands.call("replay.client", [resend_flow])
                            # print(f"REPLAY FLOW SENT")
                            return
                        os.rename(pending_file, pending_file.replace("_PENDING", "_COMPLETE"))
                    else:
                        write_to_logfile(_id, f"Something went wrong when appending data for ID {_id}")
                except IOError as e:
                    # Handle error, e.g., logging or retrying
                    write_to_logfile(_id, traceback.format_exc())
                except Exception as e:
                    write_to_logfile(_id, traceback.format_exc())

    def get_latest_resp_date(self, body):
        datetime_str = body["data"][0]["rowDateTimestamp"]
        date_object = datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M:%SZ") + timedelta(days=1)
        formatted_date = date_object.strftime("%Y-%m-%d")
        return formatted_date

    def write_to_file(self, _id, status_code, response_data, append):
        filename = f"/home/app/data/{_id}_PENDING.txt"
        try:
            with open(filename, 'a+') as file:  # 'a+' mode for appending and reading
                if append:
                    file.seek(0)  # Go to the start of the file to read existing data
                    current_data = json.load(file)
                    current_data["data"] = response_data["data"] + current_data["data"]
                    write_to_logfile(_id, f"Appended data for {filename}")
                    # except json.JSONDecodeError:
                else:
                    current_data = dict(zip(["status_code", "data"], [status_code, response_data["data"]]))
                    write_to_logfile(_id, f"Added data for {filename}")
                
                file.seek(0)  # Go to the start of the file before writing
                file.truncate()  # Clear the file content before writing new data
                json.dump(current_data, file)  # Write the updated data
        except IOError as e:
            # Handle error, e.g., logging or retrying
            write_to_logfile(_id, traceback.format_exc())
            return 0

        return filename

    def get_req_id(self, url):
        match = re.search(r'historical/(\d+)\?start-date', url)

        if not match:
            return
            
        _id = match.group(1)
        return _id

    def get_latest_date_by_ref_id(self, _id):
        latest_bond_yield = None
        with app.app_context():
            latest_bond_yield = BondYield.query.filter_by(ref_id=_id).order_by(BondYield.date.desc()).first()
            write_to_logfile(_id, f"(PROXY) latest bond yield for {_id}: {latest_bond_yield.date if latest_bond_yield else None}")
        if not latest_bond_yield:
            return None
        
        date_object = latest_bond_yield.date
        return date_object


addons = [CaptureAuthHeader()]
