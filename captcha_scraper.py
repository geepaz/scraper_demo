import requests
from scraper3b import USERAGENT
from scraper3b import Carrier as CarrierBase
from selenium import webdriver
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from urllib import urlretrieve
from time import sleep
import pdb
from reCaptcha_v2 import solve_captcha
import pycurl
import cStringIO
import re

GET_CARRIER_QUERY_URL = "RemovedForSecurity"
TWOCAPTCHA_API_KEY = 'RemovedForSecurity'
GOOGLE_KEY = 'RemovedForSecurity'
TWOCAPTCHA_REQUEST_URL = 'RemovedForSecurity'
TWOCAPTCHA_STATUS_URL = 'RemovedForSecurity'
CAPTCHA_RETRY_MAX = 3
PHANTOMJS_PATH = '/phantomjs-2.1.1-linux-x86_64 (2)/bin/phantomjs'

desired_capab = dict(DesiredCapabilities.PHANTOMJS)
desired_capab["phantomjs.page.settings.userAgent"] = USERAGENT


def curlRequest(url, postdata=False, custom_cObj=None, useragent=USERAGENT, verbose=False):
    if custom_cObj:
        curlobj = custom_cObj
    else:
        curlobj = pycurl.Curl()
    buf = cStringIO.StringIO()
    curlobj.setopt(curlobj.URL, str(url))
    curlobj.setopt(curlobj.USERAGENT, str(useragent))
    curlobj.setopt(curlobj.CONNECTTIMEOUT, 15)
    curlobj.setopt(curlobj.TIMEOUT, 15)
    if postdata:
        curlobj.setopt(curlobj.POSTFIELDS, str(postdata))
    curlobj.setopt(curlobj.WRITEFUNCTION, buf.write)
    curlobj.setopt(curlobj.VERBOSE, verbose)
    curlobj.perform()
    return buf.getvalue()

# def postCurlRequest(url):




def Captcha_Solver(image_path):
    captchafile = {'file': open(image_path, 'rb')}
    data = {'key': TWOCAPTCHA_API_KEY, 'method': 'post'}
    response = requests.post(TWOCAPTCHA_REQUEST_URL, files=captchafile, data=data)
    captcha = None
    if response.ok and response.text.find('OK') > -1:
        reqid = response.text[response.text.find('|') + 1:]
        print("[+] Capcha id: " + reqid)
        for timeout in range(40):
            response = requests.get(TWOCAPTCHA_STATUS_URL.format(TWOCAPTCHA_API_KEY, reqid))
            if response.text.find('CAPCHA_NOT_READY') > -1:
                sleep(3)
            if response.text.find('ERROR') > -1:
                captcha = False
            if response.text.find('OK') > -1:
                captcha = response.text.split('|')[1]
    else:
        print("", response.text)

    return captcha


def get_dom_html(driver):
    sleep(0.1)
    js_code = "return document.getElementsByTagName('html')[0].innerHTML;"
    return driver.execute_script(js_code)


class Carrier(CarrierBase):
    browser = webdriver.PhantomJS(desired_capabilities=desired_capab, executable_path=PHANTOMJS_PATH)
    _main_report_html = ""

    def _handle_report_exc(self, html_attr, section_title):
        exc_msg = "Missing %s HTML. Carrier Query Page must be scraped first."
        if not html_attr:
            raise Exception(exc_msg % section_title)

    def _getCarrierQueryPage(self):
        self.browser.get(GET_CARRIER_QUERY_URL)
        self.browser.find_element_by_id('usdot_number').send_keys(self.usdot_num)
        response_code = solve_captcha()
        url = "RemovedForSecurity" % self.usdot_num
        form_url = url + "&g_recaptcha_response=" + str(response_code)
        result = curlRequest(form_url)
        while "Please enter the challenge question" in result:
            sleep(2)
            print("resolving reCaptchv2")
            response_code = solve_captcha()
            url = "RemovedForSecurity" % self.usdot_num
            form_url = url + "&g_recaptcha_response=" + str(response_code)
            result = curlRequest(form_url)
        apcant_regex = re.compile('(?<=apcant_id" value=")(\d*)', re.IGNORECASE)
        apcant_results = apcant_regex.findall(result)
        pv_apcant_id = str(apcant_results[0])
        pv_path_result = re.findall('(?<=vpath" value="LIVIEW )(\d*)', result, re.IGNORECASE)
        pv_path = str(pv_path_result[0])

        url = "RemovedForSecurity" % (pv_apcant_id,pv_path)
        self.browser.get(url)

        self._main_report_html = get_dom_html(self.browser)

        insurance_xpath = '/html/body/font/center[1]/a[1]'
        self.browser.find_element_by_xpath(insurance_xpath).click()
        self._insurance_report_html = get_dom_html(self.browser)
          ins_history_xpath = '/html/body/font/center[1]/a[3]'
        try:
            self.browser.find_element_by_xpath(ins_history_xpath).click()
          except NoSuchElementException:
            ins_history_xpath = '/html/body/font/center[2]/a[3]'
            self.browser.find_element_by_xpath(ins_history_xpath).click()
        self._ins_history_report_html = get_dom_html(self.browser)
        query_page_html = get_dom_html(self.browser)
        return query_page_html

    def _getReport_Main(self):
        self._handle_report_exc(self._main_report_html, "Main Report")
        return self._main_report_html

    def _getReport_Section(self, section):
        if section == 'activeinsurance':
            self._handle_report_exc(self._insurance_report_html, "Active/Pending Insurance Report")
            return self._insurance_report_html
        if section == 'insurancehistory':
            self._handle_report_exc(self._ins_history_report_html, "Insurance History Report")
            return self._ins_history_report_html
        raise NotImplementedError
