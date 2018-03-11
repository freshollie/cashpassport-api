import uuid
import argparse
import logging

from flask import Flask, request, jsonify
from connector import CashpassportConnector, CashpassportConnectorError, CashpassportConnectionError

_LOG_LEVEL_STRINGS = ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG']

def _log_level_string_to_int(log_level_string):
    '''
    Used for recognising the log level argument
    '''
    
    log_level_string = log_level_string.upper()
    if not log_level_string in _LOG_LEVEL_STRINGS:
        message = 'invalid choice: {0} (choose from {1})'.format(log_level_string, _LOG_LEVEL_STRINGS)
        raise argparse.ArgumentTypeError(message)

    log_level_int = getattr(logging, log_level_string, logging.INFO)
    # check the logging log_level_choices have not changed from our expected values
    assert isinstance(log_level_int, int)

    return log_level_int
    
token_to_api = {}

app = Flask(__name__)

DEV = False

@app.route("/login", methods=["POST"])
def login():
    data = request.form

    error = ""
    if "user" not in data:
        error = "Must specify username"
    elif "pass" not in data:
        error = "Must specify password"
    elif "message" not in data:
        error = "Must specify secret message"
    elif "answer" not in data:
        error = "Must specify secret answer"
    elif "zone" not in data:
        error = "Must specify timezone"

    if error:
        return jsonify({"error": error})

    user_id = data["user"]
    password = data["pass"]
    message = data["message"]
    answer = data["answer"]
    time_zone = data["zone"]

    user_api = CashpassportConnector(user_id, password, message, answer, time_zone)

    try:
        user_api.login()
    except CashpassportConnectorError as error:
        return jsonify({"success": False, "error": error.message, "code": error.code})

    token = uuid.uuid4().hex

    if DEV:
        token = "1"

    token_to_api[token] = user_api

    return jsonify({"success": True, "token": token})

@app.route("/get-balance", methods=["GET"])
def get_balance():
    token = request.args.get("token")

    if not token or token not in token_to_api:
        return jsonify({"error": "invalid token", "code": 20})

    user_api = token_to_api[token]

    try:
        balance = user_api.get_balance()
    except CashpassportConnectorError as error:
        if error.code == CashpassportConnector.ERROR_LOGGED_OUT:
            del token_to_api[token]
            return jsonify({"error": "invalid token", "code": 20})

        return jsonify({"error": error.message, "code": error.code})

    return jsonify({"balance": balance})

@app.route("/get-transactions", methods=["GET"])
def get_transactions():
    token = request.args.get("token")
    from_ts = request.args.get("from")

    if not token or token not in token_to_api:
        return jsonify({"error": "invalid token", "code": 20})

    if not from_ts:
        from_ts = 0

    try:
        from_ts = int(from_ts)
    except ValueError:
        return jsonify({"error": "from must be an int", "code": 50})

    user_api = token_to_api[token]

    try:
        transactions = user_api.get_transactions(from_ts=from_ts)
    except CashpassportConnectorError as error:
        if error.code == CashpassportConnector.ERROR_LOGGED_OUT:
            del token_to_api[token]
            return jsonify({"error": "invalid token", "code": 20})

        return jsonify({"error": error.message, "code": error.code})

    return jsonify({"transactions": transactions})

@app.route("/logout", methods=["POST"])
def logout():
    token = request.args.get("token")

    if not token or token not in token_to_api:
        return jsonify({"error": "invalid token", "code": 20})

    user_api = token_to_api[token]

    if user_api.is_logged_in():
        try:
            user_api.logout()
        except CashpassportConnectorError:
            pass

    del token_to_api[token]

    return jsonify({"success": True})

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='cashpassport-api')

    parser.add_argument('--log-level',
                        default='DEBUG',
                        dest='log_level',
                        type=_log_level_string_to_int,
                        nargs='?',
                        help='Set the logging output level. {0}'.format(_LOG_LEVEL_STRINGS))

    args = parser.parse_args()

    logging.basicConfig(format='%(asctime)s.%(msecs)03d %(levelname)-8s %(name)s:: %(message)s',
                        level=args.log_level,
                        datefmt='%Y-%m-%d %H:%M:%S')

    app.run(debug=True, threaded=True)