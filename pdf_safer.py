#-*- coding:utf-8 -*-

import pycurl
import cStringIO
import string
import re
from bs4 import BeautifulSoup as bs
from captcha_scraper import Carrier
from core import bunyan
from core.settings import LOGFILE
from core import database4 as db4
from time import sleep
import pdb


QUERY_URL = "http://safer.fmcsa.dot.gov/keywordx.asp"
NAME_QUERY_ARGS = "searchstring=%%2A%s%%2A&SEARCHTYPE="
USERAGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/27.0.1453.65 Safari/537.36"

logger = bunyan.Logger(LOGFILE)



def curl_request(url, getargs=False, custom_cObj=False, useragent=USERAGENT, verbose=False):
    if custom_cObj:
        curlobj = custom_cObj
    else:
        curlobj = pycurl.Curl()
    buf = cStringIO.StringIO()
    curlobj.setopt(curlobj.URL, str(url))
    curlobj.setopt(curlobj.USERAGENT, str(useragent))
    curlobj.setopt(curlobj.CONNECTTIMEOUT, 15)
    curlobj.setopt(curlobj.TIMEOUT, 15)
    if getargs:
        try:
            curlobj.setopt(curlobj.POSTFIELDS, str(getargs))
        except UnicodeEncodeError:
            raise pycurl.error
    curlobj.setopt(curlobj.WRITEFUNCTION, buf.write)
    curlobj.setopt(curlobj.VERBOSE, verbose)
    curlobj.perform()
    return buf.getvalue()


def fitness_isolate_name(record):
    nameline = record[2]
    delimiters = ['-', '\n']
    delimiters = filter(lambda d: d in nameline, delimiters)
    delim_positions = [nameline.index(d) for d in delimiters]
    if delim_positions:
        delimiter = delimiters[delim_positions.index(min(delim_positions))]
        return nameline.split(delimiter ,1)[0].strip()
    else:
        return nameline


def fitness_isolate_citystate(record):
    citystateline = record[2]
    delimiters = ['-', '\n']
    delimiters = filter(lambda d: d in citystateline, delimiters)
    delim_positions = [citystateline.index(d) for d in delimiters]
    delimiter = delimiters[delim_positions.index(max(delim_positions))]
    delimiter = delimiters[delim_positions.index(min(delim_positions))]
    result = citystateline.rsplit(delimiter, 1)[1]
    return filter(lambda s: s not in string.digits, result).strip()


def standard_isolate_name(record):
    nameline = record[1]
    delimiters = ['-', '\n']
    delimiters = filter(lambda d: d in nameline, delimiters)
    delim_positions = [nameline.index(d) for d in delimiters]
    if delim_positions:
        delimiter = delimiters[delim_positions.index(min(delim_positions))]
        return nameline.split(delimiter ,1)[0].strip()
    else:
        return nameline


def standard_isolate_citystate(record):
    citystateline = record[1]
    delimiters = ['-', '\n']
    delimiters = filter(lambda d: d in citystateline, delimiters)
    delim_positions = [citystateline.index(d) for d in delimiters]
    delimiter = delimiters[delim_positions.index(max(delim_positions))]
    delimiter = delimiters[delim_positions.index(min(delim_positions))]
    result = citystateline.rsplit(delimiter, 1)[1]
    return filter(lambda s: s not in string.digits, result).strip()


def standard_isolate_state(record):
    citystate = standard_isolate_citystate(record)
    try:
        state = citystate.split(',')[1].strip()
    except IndexError:
        state = None
    return state


def search_by_name(record, category):
    fitness_type_categories = ['fitness', 'nonfitness']
    standard_type_categories = ['dismissals', 'revocations']
    try:
        if category in fitness_type_categories:
            isolate_name = fitness_isolate_name
            isolate_citystate = fitness_isolate_citystate
        elif category in standard_type_categories:
            isolate_name = standard_isolate_name
            isolate_citystate = standard_isolate_citystate
        else:
            raise Exception("Unknown record category: %s" % category)
        name = isolate_name(record)
        citystate = isolate_citystate(record)
    except:
        logger.write("Misssing name or citystate in expected place, skipping record: %s" % ' '.join(record))
        return []
    getargs = NAME_QUERY_ARGS % name.replace(' ', '+')
    try:
        sleep(0.15)
        matchpage = curl_request(QUERY_URL, getargs)
    except pycurl.error:
        return []
    if "Sorry, no records matching" in matchpage:
        return []
    else:
        matchsoup = bs(matchpage, 'lxml')
        carriers = matchsoup.findAll(attrs={"scope": "rpw"})
        locations = [c.next_sibling.next_sibling.text for c in carriers]
        links = [th.a for th in carriers]
        matches = zip(links, locations)
        matches = filter(lambda m: m[0].text == name, matches)
        matches = filter(lambda m: m[1] == citystate, matches)
        results = [m[0]['href'].replace(' ', '+') for m in matches]
        results = ['http://safer.fmcsa.dot.gov/' + r for r in results]
    return results


def get_record(carrier, date, write_cond=None):
    repeat = 0
    repeat_limit = 5
    if not write_cond:
        write_cond = lambda: record.scrape_error_status == None
    record = carrier # emphasis on 1st syllable
    while True:
        try:
            record.scrape()
        except pycurl.error:
            if repeat < repeat_limit:
                repeat += 1
                logger.write("Curl Error. Sleeping for 5s")
                sleep(5)
                continue
            else:
                return False
        except Exception as e: # Progressive sleep is handled elsewhere, yes?
            print e
            sleep(0.25)
        if write_cond():
            db4.insert_or_replace(record, date)
        return True


def dictify(records, secname):
    """ Given a list of tuples comprising carrier records, return a
    dictionary associating each value in the tuple with an attribute of
    the Carrier object appropriate to the given section (i.e. mapping
    section specific tuple orderings to dict keys)

    """
    attrs = []
    for record in records:
        attrs.append( {'mc_num': record[0],
                       'legal_name': standard_isolate_name(record),
                       'state': standard_isolate_state(record)
                      })
        if secname == 'dismissals':
            attrs[-1]['dni_bool'] = "True"
        elif secname == 'revocations':
            attrs[-1]['revoc_date'] = record[2]
            attrs[-1]['revoc_status'] = record[3]
        else:
            raise Exception("Section name error")
    return attrs


class PDFCarrier(Carrier):
    def __init__(self, origin, snapshoturl=None):
        self._snapshot_url = snapshoturl
        super(PDFCarrier, self).__init__('', origin=origin)

    def _getSnapshotPage(self, snapshoturl=None):
        if snapshoturl:
            self._snapshot_url = snapshoturl
        if not self._snapshot_url:
            raise Exception("No Snapshot Page")
        else:
            return curl_request(self._snapshot_url)

