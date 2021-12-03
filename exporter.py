import os
import sys
import requests
import json
from datetime import datetime
import time
import argparse
from dotenv import load_dotenv
import shutil

env_file = os.path.join(os.path.dirname(__file__), ".env")
if os.path.isfile(env_file):
    load_dotenv(env_file)

# write handling


def post_response(response_url, text):
    requests.post(response_url, json={"text": text})


# use this to say anything
# will print to stdout if no response_url is given
# or post_response to given url if provided
def handle_print(text, response_url=None):
    if response_url is None:
        print(text)
    else:
        post_response(response_url, text)


# pagination handling


def get_at_cursor(url, params, cursor=None, response_url=None):
    if cursor is not None:
        params["cursor"] = cursor

    # slack api (OAuth 2.0) now requires auth tokens in HTTP Authorization header
    # instead of passing it as a query parameter
    try:
        headers = {"Authorization": "Bearer %s" % os.environ["SLACK_USER_TOKEN"]}
    except KeyError:
        handle_print("Missing SLACK_USER_TOKEN in environment variables", response_url)
        sys.exit(1)

    while True:
        trycnt = 3  # max try cnt
        while trycnt > 0:
            try:
                r = requests.get(url, headers=headers, params=params)
                trycnt = 0 # success
            except ChunkedEncodingError as ex:
                if trycnt <= 0:
                    print("Failed to retrieve: " + url + "\n" + str(ex))  # done retrying
                else:
                    trycnt -= 1  # retry
                    time.sleep(0.5)  # wait 1/2 second then retry

        if r.status_code == 429:
            time.sleep(int(r.headers["Retry-After"]))
        elif r.status_code != 200:
            handle_print("ERROR: %s %s" % (r.status_code, r.reason), response_url)
            sys.exit(1)
        else:
            break

    d = r.json()

    try:
        if d["ok"] is False:
            handle_print("I encountered an error: %s" % d, response_url)
            sys.exit(1)

        next_cursor = None
        if "response_metadata" in d and "next_cursor" in d["response_metadata"]:
            next_cursor = d["response_metadata"]["next_cursor"]
            if str(next_cursor).strip() == "":
                next_cursor = None

        return next_cursor, d

    except KeyError as e:
        handle_print("Something went wrong: %s." % e, response_url)
        return None, []


def paginated_get(url, params, combine_key=None, response_url=None):
    next_cursor = None
    result = []
    while True:
        next_cursor, data = get_at_cursor(
            url, params, cursor=next_cursor, response_url=response_url
        )

        try:
            result.extend(data) if combine_key is None else result.extend(
                data[combine_key]
            )
            
        except KeyError:
            handle_print("Something went wrong: %s." % e, response_url)
            sys.exit(1)

        if next_cursor is None:
            break

    return result


# GET requests


def channel_list(team_id=None, response_url=None):
    params = {
        # "token": os.environ["SLACK_USER_TOKEN"],
        "team_id": team_id,
        "types": "private_channel",
        "limit": 200,
    }

    return paginated_get(
        "https://slack.com/api/conversations.list",
        params,
        combine_key="channels",
        response_url=response_url,
    )


def channel_history(channel_id, start_ts, end_ts, response_url=None):
    params = {
        # "token": os.environ["SLACK_USER_TOKEN"],
        "channel": channel_id,
        "limit": 200,
        "oldest": start_ts,
        "latest": end_ts
    }

    return paginated_get(
        "https://slack.com/api/conversations.history",
        params,
        combine_key="messages",
        response_url=response_url,
    )


def user_list(team_id=None, response_url=None):
    params = {
        # "token": os.environ["SLACK_USER_TOKEN"],
        "limit": 200,
        "team_id": team_id,
    }
    
    return paginated_get(
        "https://slack.com/api/users.list",
        params,
        combine_key="members",
        response_url=response_url,
    )



def channel_replies(timestamp, channel_id, response_url=None):
    replies = []
    #for timestamp in timestamps:
    params = {
        # "token": os.environ["SLACK_USER_TOKEN"],
        "channel": channel_id,
        "ts": timestamp,
        "limit": 200,
    }

    replies = paginated_get(
            "https://slack.com/api/conversations.replies",
            params,
            combine_key="messages",
            response_url=response_url,
        )

    return replies

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-o",
        help="Directory in which to save output files (if left blank, prints to stdout)"
    )
    parser.add_argument(
        "--lc", action="store_true", help="List all conversations in your workspace"
    )
    parser.add_argument(
        "--lu", action="store_true", help="List all users in your workspace"
    )
    parser.add_argument(
        "--all", action="store_true", help="Get all messages and threads for all accessible private conversations"
    )
    parser.add_argument(
        "--skipfiles", action="store_true", help="Skip importing files (workaround for \"Just import their messages\" import mode)"
    )
    a = parser.parse_args()

    ts = str(datetime.strftime(datetime.now(), "%m-%d-%Y_%H%M%S"))

    def save(data, dirname, filename):
        if a.o is None:
            if filename == "channel_list":
                for channel in data:
                    print("{} {}".format(channel["id"], channel["name"]))
            elif filename == "user_list":
                for user in data:
                    print("{} {}".format(user["id"], user["name"]))
            else:
                print(data)
        else:
            out_dir_parent = os.path.abspath(os.path.expanduser(os.path.expandvars(a.o)))
            out_dir = os.path.join(out_dir_parent, "slack_export_%s/%s" % (ts, dirname))
            filename = filename + ".json"
            os.makedirs(out_dir, exist_ok=True)
            full_filepath = os.path.join(out_dir, filename)
            print("Writing output to %s" % full_filepath)
            with open(full_filepath, mode="w") as f:
                    f.write(data)
    
    def makezip():
        out_dir_parent = os.path.abspath(os.path.expanduser(os.path.expandvars(a.o)))
        out_dir = os.path.join(out_dir_parent, "slack_export_%s" % ts)
        shutil.make_archive(out_dir, 'zip', out_dir)

    if a.lc:
        data = channel_list()
        save(data, ".", "channel_list")
    if a.lu:
        data = user_list()
        save(data, ".", "user_list")
    elif a.all:
        #combine_key="messages"
        ch_list = channel_list()
        u_list = user_list()
        save(json.dumps(ch_list), ".", "channels")
        save(json.dumps(u_list), ".", "users")

        for channel in ch_list:
            ch_id = channel["id"]
            ch_name = channel["name"]
            start_ts = float(str(channel["created"]) + ".0")
            end_ts = float(time.time())
            while start_ts < end_ts:
                tmp_end_ts = start_ts + 86400.0
                ch_hist = channel_history(ch_id, str(start_ts), str(tmp_end_ts))
                filename = datetime.utcfromtimestamp(start_ts).strftime('%Y-%m-%d')
                tmp_ch_hist = ch_hist.copy()
                for message in ch_hist:
                    #Костыль начинается здесь
                    if a.skipfiles:
                        if "files" in message:
                            if "url_private" in message["files"][0]:
                                message["text"] = message["text"] + " _This file was here:_ " + message["files"][0]["url_private"]
                            else:
                                message["text"] = message["text"] + " _File was deleted:_ "
                            del message['files']
                            del message['upload']
                    #Костыль заканчивается здесь
                    if "thread_ts" in message and "subtype" not in message:
                        reply = channel_replies(message["thread_ts"], ch_id)
                        tmp_ch_hist.extend(reply)
                if tmp_ch_hist:
                    save(json.dumps(tmp_ch_hist), ch_name, filename)
                start_ts = start_ts + 86400.0

        if a.o:
            makezip()
