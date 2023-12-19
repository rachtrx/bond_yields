from mitmproxy import ctx, http
import datetime
import re
import os
import json

class CaptureAuthHeader:
    def request(self, flow: http.HTTPFlow) -> None:

        # Check if the request URL meets the criteria. its always in the form /api/financialdata/historical/23703?start_date=2023-11-20&end-date=2023-12-18&time-frame=Daily&add-missing-rows=false
        if flow.request.pretty_url.startswith("https://api.investing.com") and \
           flow.request.pretty_url.endswith("add-missing-rows=false"):
            _id = self.get_req_id(flow.request.pretty_url) # TODO CHECK IN DB
            # latest_date = self.check_latest_date(_id) # TODO
            flow.request.query["start-date"] = "2000-01-01" # TODO SET LATEST DATE
            flow.request.query["end-date"] = datetime.datetime.now().strftime('%Y-%m-%d')
            flow.request.headers["user-agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36"

    def response(self, flow: http.HTTPFlow) -> None:
        # Check if the URL matches the pattern for which you want to log the response
        if flow.request.pretty_url.startswith("https://api.investing.com") and \
           flow.request.pretty_url.endswith("add-missing-rows=false"):
            _id = self.get_req_id(flow.request.pretty_url)
            if _id:
                self.write_to_file(_id, flow.response)

    def write_to_file(self, _id, response):
        data_directory = "/home/app/data/"
        # data_directory = os.getcwd() + "/notebooks/"
        filename = os.path.join(data_directory, f"{_id}.txt")
        print(filename)

        text = dict(zip(["status_code", "body"], [response.status_code, json.loads(response.text)]))
        print(response.status_code)
        with open(filename, 'w') as file:
            file.write(json.dumps(text))

    def get_req_id(self, url):
        match = re.search(r'historical/(\d+)\?start-date', url)

        if not match:
            return
            
        _id = match.group(1)
        return _id

    # def check_latest_date():


addons = [CaptureAuthHeader()]
