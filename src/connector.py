import calendar
import logging
import os
from datetime import datetime, timedelta

import dateutil.parser
import dateutil.tz
import mechanicalsoup
from bs4 import BeautifulSoup

MAIN_PATH = os.path.dirname(os.path.abspath(__file__))


def to_utc_timestamp(date_time):
    return calendar.timegm(date_time.utctimetuple())


class CashpassportConnectorError(Exception):
    ERROR_BAD_PASSWORD = 0
    ERROR_BAD_USER_ID = 1
    ERROR_BAD_SECURITY_MESSAGE = 2
    ERROR_BAD_SECURITY_ANSWER = 3

    ERROR_LOGGED_OUT = 9999

    ERROR_LOGIN_IN_PROGRESS = 5

    CONNECTION_ERROR = 28382

    def __init__(self, message, code):
        self.code = code
        self.message = message
        Exception.__init__(self, message)


class CashpassportConnectionError(CashpassportConnectorError):
    def __init__(self):
        CashpassportConnectorError.__init__(self,
                                            "Error connecting to cashpassport",
                                            CashpassportConnectorError.CONNECTION_ERROR)


class CashpassportConnector:
    '''
    Simple HTML parsing api which can send all the required information to log in,
    gather transaction details, and balance amounts from the cashpassport website.

    Seeing as this is probably completely against the terms of service of the site,
    I wouldn't execute this often. The site was build a very long time ago so they
    probably won't notice bot requests, but probably not worth being banned for.

    USE AT YOUR OWN RISK
    '''

    # lel
    FAKE_AGENT = "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36"

    LOGIN_PAGE_URL = "https://cardholder.mastercardworldwide.com/travelex/cardholder/public/app/registeredCardholderLogin"
    LOGOUT_PAGE_URL = "https://cardholder.mastercardworldwide.com/travelex/cardholder/public/app/logout"

    MAIN_PAGE_URL = "https://cardholder.mastercardworldwide.com/travelex/cardholder/cardHolderHome.view"
    VALIDATE_LOGIN_PAGE_URL = "https://cardholder.mastercardworldwide.com/travelex/cardholder/start/extAuth/app/registeredCardHolderPCFCheck"
    SECURITY_ANSWER_PAGE_URL = "https://cardholder.mastercardworldwide.com/travelex/cardholder/start/app/registeredCardHolderLoginSecurityQandA"

    BALANCE_URL = "https://cardholder.mastercardworldwide.com/travelex/cardholder/cardInfo.view?param=&dojo.preventCache="
    TRANSACTIONS_URL = "https://cardholder.mastercardworldwide.com/travelex/cardholder/currentActivity.view?param=&theme=plain&navId=6&dojo.preventCache="

    PKMS_LOGIN_PATH = "/pkmslogin.form"

    LOGIN_FORM_ID = "#registercardholderLoginUseridForm"
    PASSWORD_FORM_ID = "#registercardholderLoginPasswordVerifyForm"
    SECURITY_FORM_ID = "#challengeForm"

    USER_ID_INPUT = "userIdInput"
    SECURITY_PHRASE_CLASS = "security_phrase_value"
    AUTO_LOGIN_OPTION_NAME = "autoLogonOption"

    TRANSACTION_TYPE_PURCHACE = 0
    TRANSACTION_TYPE_WITHDRAWAL = 1
    TRANSACTION_TYPE_UNKNOWN = -1

    SOUP_CONFIG = {'features': 'html.parser'}

    CURRENT_STRING = "CURRENT"

    @staticmethod
    def _create_csrf_token_input(page):
        '''
        Direct port from the pages javascript

        Inserts the csrf token to the form for submitting
        '''
        token = CashpassportConnector._get_csrf_token_from_page(page)

        csrf_input = page.new_tag("input")
        csrf_input['type'] = 'hidden'
        csrf_input['name'] = 'csrfToken'
        csrf_input['id'] = 'csrfToken'
        csrf_input['value'] = token
        csrf_input['defaultValue'] = token
        csrf_input['readonly'] = "readonly"

        return csrf_input

    @staticmethod
    def _get_csrf_token_from_page(page):
        '''
        Returns the cstf token from the page by parsing the javascript
        '''
        return page.text.split('var sessionSynchronizationToken = "')[1].split('"')[0]

    @staticmethod
    def _money_string_to_float(money_string):
        return float(money_string.split(" ")[0].replace(",", ""))

    @staticmethod
    def _filter_transactions(all_transactions, from_ts=0):
        filtered_transactions = []
        for transaction in all_transactions:
            if transaction["ts"] >= from_ts:
                filtered_transactions.append(transaction)

        return filtered_transactions

    @staticmethod
    def _parse_cycles_from_page(page):
        periods = []
        options = BeautifulSoup(page, "html.parser").find("select", id="prepaidCycle").findAll("option")
        for option in options:
            if option["value"] != "":
                periods.append(option["value"])
        return periods

    def __init__(self, user_id, password, validation_message, security_answer, time_zone, dev=False):
        self.__DEV__ = dev

        self.log = logging.getLogger(CashpassportConnector.__name__ + "<%s>" % user_id)

        self.__time_zone = dateutil.tz.gettz(time_zone)

        self.__user_id = user_id
        self.__password = password
        self.__validation_message = validation_message
        self.__security_answer = security_answer
        self.__logged_in_token = False

        self.browser = None

        if not os.path.exists(os.path.join(MAIN_PATH, "test_pages")):
            os.mkdir(os.path.join(MAIN_PATH, "test_pages"))

    def get_user_id(self):
        return self.__user_id

    def login(self):
        if self.__DEV__:
            self.__logged_in_token = "DUMMY"
            return

        # Create a new session
        self.browser = mechanicalsoup.StatefulBrowser(soup_config=CashpassportConnector.SOUP_CONFIG)

        # Rather them not know we are a bot
        self.browser.session.headers['User-Agent'] = CashpassportConnector.FAKE_AGENT
            
        self.log.debug("Login")

        # First present our login id
        try:
            self.browser.open(CashpassportConnector.MAIN_PAGE_URL)
        except:
            raise CashpassportConnectionError()

        first_page = self.browser.get_current_page()

        csrf_token = CashpassportConnector._get_csrf_token_from_page(first_page)
        csrf_token_input = CashpassportConnector._create_csrf_token_input(first_page)

        self.browser.select_form(CashpassportConnector.LOGIN_FORM_ID)
        self.browser.get_current_form().form.append(csrf_token_input)

        self.browser[CashpassportConnector.USER_ID_INPUT] = self.__user_id # input username

        self.log.debug("Submitting username")

        try:
            self.browser.submit_selected()
        except:
            raise CashpassportConnectionError()

        # Verify it has the correct security message
        password_page = self.browser.get_current_page()

        found_message = password_page.find("div", class_=CashpassportConnector.SECURITY_PHRASE_CLASS)
        self.log.debug("Security message loaded = " + found_message.text)

        if not found_message.text:
            raise CashpassportConnectorError("Bad username",
                                             CashpassportConnectorError.ERROR_BAD_USER_ID)

        if found_message.text != self.__validation_message:
            self.log.debug("Bad site, wrong security message")
            raise CashpassportConnectorError("Bad security message",
                                             CashpassportConnectorError.ERROR_BAD_SECURITY_MESSAGE)
        else:
            self.log.debug("Page verified")

        # Parse the token from the page
        csrf_token_input = CashpassportConnector._create_csrf_token_input(password_page)

        # Verified page, so input password
        self.browser.select_form(CashpassportConnector.PASSWORD_FORM_ID)
        password_form = self.browser.get_current_form().form

        self.browser["password"] = self.__password # Input the password
        password_form["action"] = CashpassportConnector.PKMS_LOGIN_PATH
        password_form.append(csrf_token_input)
        
        self.log.debug("Submitting password")

        try:
            self.browser.submit_selected()
            # Manually open the urls to verify login
            self.browser.open(CashpassportConnector.VALIDATE_LOGIN_PAGE_URL)
        except:
            raise CashpassportConnectionError()

        # Security answer
        try:
            self.browser.select_form(CashpassportConnector.SECURITY_FORM_ID)
        except mechanicalsoup.LinkNotFoundError:
            raise CashpassportConnectorError("Bad password",
                                             CashpassportConnectorError.ERROR_BAD_PASSWORD)

        # Input the answer
        self.browser["securityAnswer"] = self.__security_answer

        security_form = self.browser.get_current_form().form

        csrf_token_input = CashpassportConnector._create_csrf_token_input(self.browser.get_current_page())

        # And fill in the csrf token
        security_form.insert(0, csrf_token_input)

        # Remove auto login from the form submission
        auto_login_checkbox = security_form.find_all("input", {"name": CashpassportConnector.AUTO_LOGIN_OPTION_NAME})[0]
        auto_login_checkbox["checked"] = "false"
        auto_login_checkbox["value"] = "false"

        self.log.debug("Submitting security answer")

        try:
            self.browser.submit_selected()
            self.browser.open(CashpassportConnector.MAIN_PAGE_URL)
        except:
            raise CashpassportConnectionError()

        if self.browser.get_current_page().find("a", href="/travelex/cardholder/chProfile.view"):
            self.log.debug("Login successful")
            self.__logged_in_token = csrf_token
        else:
            self.__logged_in_token = None
            self.log.debug("Login unsuccessful")
            self.log.debug(self.browser.get_current_page().find_all("a"))
            raise CashpassportConnectorError("Bad security answer",
                                             CashpassportConnectorError.ERROR_BAD_SECURITY_ANSWER)

    def is_logged_in(self):
        return self.__logged_in_token

    def logout(self):
        if self.__DEV__:
            self.__logged_in_token = None
            return True

        if self.is_logged_in():
            self.log.debug("Logging out")

            try:
                self.browser.open(CashpassportConnector.LOGOUT_PAGE_URL)
            except:
                raise CashpassportConnectionError()

            self.__logged_in_token = None
        return True

    def _get_authorised_page(self, authorised_url, post_data=None):
        '''
        Attempts to open a url which requires login and returns nothing if not logged in
        '''
        if self.browser and self.__logged_in_token:
            try:
                if post_data:
                    response = self.browser.post(authorised_url, data=post_data)
                else:
                    response = self.browser.get(authorised_url)
            except:
                raise CashpassportConnectionError()

            if response.url == authorised_url:
                # Replace all non ascii characters with question marks
                return response.text

        self.__logged_in_token = None
        raise CashpassportConnectorError("Not logged in",
                                         CashpassportConnectorError.ERROR_LOGGED_OUT)

    def _get_balance_page(self):
        if self.__DEV__:
            with open(os.path.join(MAIN_PATH, "test_pages/balance.html"), "r") as f:
                return str(f.read())
        else:
            page = self._get_authorised_page(CashpassportConnector.BALANCE_URL)
            with open(os.path.join(MAIN_PATH, "test_pages/balance.html"), "w") as f:
                f.write(page)
            return page

    def _get_transactions_page(self, period=None):
        if self.__DEV__:
            with open(os.path.join(MAIN_PATH, "test_pages/transactions.html"), "r") as f:
                return str(f.read())
        else:
            if period:
                page = self._get_authorised_page(
                    CashpassportConnector.TRANSACTIONS_URL,
                    {
                        "csrfToken": self.__logged_in_token,
                        "current": (period == CashpassportConnector.CURRENT_STRING),
                        "acrossCycles": False,
                        "theme": "plain",
                        "prepaidCycle": period,
                    }
                )
            else:
                page = self._get_authorised_page(CashpassportConnector.TRANSACTIONS_URL)

            with open(os.path.join(MAIN_PATH, "test_pages/transactions.html"), "w") as f:
                f.write(page)
            return page

    def _parse_transactions(self, page):
        soup = BeautifulSoup(page, "html.parser")
        transactions = []
        # There are 2 possible tables both with the same id
        for transactionTable in soup.findAll("table", id="txtable1"):
            for row in transactionTable.tbody:

                # And each row contains a transaction
                if row.find('td') != -1:
                    cells = row.findAll('td')

                    if len(cells) < 5:
                        continue

                    date_time_text = cells[0].getText()

                    verified = (cells[1].getText().lower() != "pending")

                    transaction_time = dateutil.parser.parse(date_time_text).replace(tzinfo=self.__time_zone)

                    # Unverified transactions seem to be behind by exactly 5 hours + whatever the UTC offset is.
                    # Probably a bug that has been around for years
                    if not verified:
                        transaction_time = transaction_time + timedelta(hours=(5 + transaction_time.utcoffset().total_seconds() / 3600))

                    # Turn the time string into epoch time
                    timestamp = to_utc_timestamp(transaction_time)

                    # Then we need to parse the place and type string
                    type_place_text = cells[3].getText()

                    # This character for some reason is always
                    # in the description after the transaction type
                    type_place_split = type_place_text.split(u'\xa0')

                    # Some transactions are for example the initial deposit which don't really count
                    place = "N/A"
                    type_string = ""
                    if len(type_place_split) > 1:
                        
                        type_string = "".join(type_place_split.pop(0).split())  # Take the first part of the split

                        # Takes the last part of the string, joins it all together, removes bad chacters,
                        # removes large spaces and new lines, and then removes "more" strings
                        place = " ".join(" ".join(type_place_split).strip().split()) \
                            .replace(" more . . .", "") \
                            .replace(",", "")

                        if place.startswith("-"):
                            # Our place does not need to start with a dash
                            place = place[2:]

                    if not place:
                        # Again, probably not a transaction, no place given
                        #continue
                        pass

                    # Convert the type name to its value
                    if type_string.lower() == "purchase":
                        transaction_type = CashpassportConnector.TRANSACTION_TYPE_PURCHACE
                    elif type_string.lower() == "withdrawal":
                        transaction_type = CashpassportConnector.TRANSACTION_TYPE_WITHDRAWAL
                    else:
                        transaction_type = CashpassportConnector.TRANSACTION_TYPE_UNKNOWN
                        self.log.error("Unknown transaction type: " + type_string)

                    amount = CashpassportConnector._money_string_to_float(cells[4].getText().strip())

                    transaction = {"ts": timestamp,
                                   "place": place,
                                   "amount": amount, 
                                   "type": transaction_type, 
                                   "verified": verified}
                    transactions.append(transaction)

        return transactions
            
    def get_transactions(self, from_ts=0):
        '''
        Parses the transaction page for all transactions until the given timestamp

        returns empty or not logged if it couldn't connect
        '''
        transactions = []

        self.log.debug("Retrieving history of transactions back to " + datetime.fromtimestamp(from_ts).isoformat())

        # We fetch the periods from the first page
        periods = [CashpassportConnector.CURRENT_STRING]

        pg_num = 0
        for period in periods:
            pg_num += 1
            self.log.debug("Fetching transaction history page: " + str(pg_num))

            transactions_page = self._get_transactions_page(period=period)

            self.log.debug("Parsing transactions")
            fetched_transactions = self._parse_transactions(transactions_page)
            required_transactions = CashpassportConnector._filter_transactions(fetched_transactions,
                                                                               from_ts=from_ts)

            transactions += required_transactions

            if len(required_transactions) != len(fetched_transactions):
                self.log.debug("Found all required transactions")
                break

            # As this is the first page, we find the periods on the page
            if pg_num == 1:
                periods += CashpassportConnector._parse_cycles_from_page(transactions_page)

        self.log.debug("Finished looking through transaction")
        return sorted(transactions, key=lambda x: x["ts"])

    def get_balance(self):
        page = self._get_balance_page()

        return CashpassportConnector._money_string_to_float(
            page.split('<div class="balanceTotal">')[1].split("</div>")[0].strip()
        )
