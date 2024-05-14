from flask import (
    Flask,
    request,
    render_template,
    redirect,
    url_for,
    send_file,
    session,
    jsonify,
)
from flask_cors import CORS
import dns.resolver, dns.reversename
from bs4 import BeautifulSoup
import subprocess
import os
import yt_dlp
from json import load, dump, loads, dumps
import time
from bs4 import BeautifulSoup
from requests import get
from flask import request
from discord_webhook import DiscordWebhook, DiscordEmbed
import sqlite3
from typing import Optional, Tuple, List
from flask_sitemap import Sitemap

from urllib import parse
from urllib.parse import parse_qs
import scrapetube
from chat_downloader.sites import YouTubeChatDownloader
from chat_downloader import ChatDownloader
import logging
from datetime import datetime, timedelta
import cronitor

from util import *
from Clip import Clip

# we are in /var/www/clip_nighbot
import os

try:
    os.chdir("/var/www/clip_nightbot")
except FileNotFoundError:
    local = True
    # we are working locally
    pass
else:
    local = False

if not local:
    logging.basicConfig(
        filename="./record.log",
        level=logging.ERROR,
        format=f"%(asctime)s %(levelname)s %(name)s %(threadName)s : %(message)s",
    )

try:
    testing = load(open("testing_config.json", "r"))
except FileNotFoundError:
    cronitor.api_key = None
else:
    cronitor.api_key = testing["api_key"]

if not local:
    monitor = cronitor.Monitor.put(key="Streamsnip-Clips-Performance", type="job")
else:
    monitor = None


app = Flask(__name__)
CORS(app)
ext = Sitemap(app=app)

global download_lock
download_lock = False
conn = sqlite3.connect("queries.db", check_same_thread=False)
# cur = db.cursor() # this is not thread safe. we will create a new cursor for each thread
owner_icon = "👑"
mod_icon = "🔧"
regular_icon = "🧑‍🌾"
subscriber_icon = "⭐"
allowed_ip = [
    "127.0.0.1",
    "52.15.46.178",
]  # store the nightbot ips here. or your own ip for testing purpose
show_fake_error = False # for blacklisted channel show fake error message or not 
requested_myself = (
    False  # on startup we request ourself so that apache build the cache.
)
base_domain = (
    "https://streamsnip.com"  # just for the sake of it. store the base domain here
)
chat_id_video = {}  # store chat_id: vid. to optimize clip command
downloader_base_url = "https://azure-internal-verse.glitch.me"
project_name = "StreamSnip"
project_logo = base_domain + "/static/logo.png"
project_repo_link = "https://github.com/SurajBhari/clip_nightbot"
project_logo_discord = "https://raw.githubusercontent.com/SurajBhari/clip_nightbot/main/static/256_discord_ss.png" # link to logo that is used in discord 

if not project_logo_discord:
    project_logo_discord = project_logo

with conn:
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS QUERIES(channel_id VARCHAR(40), message_id VARCHAR(40), clip_desc VARCHAR(40), time int, time_in_seconds int, user_id VARCHAR(40), user_name VARCHAR(40), stream_link VARCHAR(40), webhook VARCHAR(40), delay int, userlevel VARCHAR(40), ss_id VARCHAR(40), ss_link VARCHAR(40))"
    )
    conn.commit()
    cur.execute("PRAGMA table_info(QUERIES)")
    data = cur.fetchall()
    colums = [xp[1] for xp in data]
    if "webhook" not in colums:
        cur.execute("ALTER TABLE QUERIES ADD COLUMN webhook VARCHAR(40)")
        conn.commit()
        print("Added webhook column to QUERIES table")

    if "delay" not in colums:
        cur.execute("ALTER TABLE QUERIES ADD COLUMN delay INT")
        conn.commit()
        print("Added delay column to QUERIES table")

    if "userlevel" not in colums:
        cur.execute("ALTER TABLE QUERIES ADD COLUMN userlevel VARCHAR(40)")
        conn.commit()
        print("Added userlevel column to QUERIES table")

    if "ss_id" not in colums:
        cur.execute("ALTER TABLE QUERIES ADD COLUMN ss_id VARCHAR(40)")
        conn.commit()
        print("Added ss_id column to QUERIES table")

    if "ss_link" not in colums:
        cur.execute("ALTER TABLE QUERIES ADD COLUMN ss_link VARCHAR(40)")
        conn.commit()
        print("Added ss_link column to QUERIES table")

    if "private" not in colums:
        cur.execute("ALTER TABLE QUERIES ADD COLUMN private VARCHAR(40)")
        conn.commit()
        print("Added private column to QUERIES table")

    if "message_level" not in colums:
        cur.execute(
            "ALTER TABLE QUERIES ADD COLUMN message_level INT"
        )  # we store this for the sole purpose of rebuilding the message on !edit
        conn.commit()
        print("Added message_level column to QUERIES table")

# if there is no folder named clips then make one
if not os.path.exists("clips"):
    os.makedirs("clips")
    print("Created clips folder")

try:
    with open("creds.json", "r") as f:
        creds = load(f)
except FileNotFoundError:
    with open("creds.json", "w") as f:
        dump({}, f)
        creds = {}
management_webhook_url = creds.get("management_webhook", None)
management_webhook = None
if management_webhook_url and not local:
    management_webhook = DiscordWebhook(
        management_webhook_url
    )  # we implement this function because we have to recreate this wh again and again to use.
    management_webhook.content = "Bot started"
    try:
        management_webhook.execute()
    except request.exceptions.MissingSchema:
        pass

def is_blacklisted(channel_id):
    try:
        with open("blacklisted.json", "r") as f:
            data = load(f)
    except FileNotFoundError:
        data = []
    return channel_id in data

def get_clip(clip_id, channel=None) -> Optional[Clip]:
    with conn:
        cur = conn.cursor()
        if channel:
            cur.execute(
                "SELECT * FROM QUERIES WHERE channel_id=? AND message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
                (
                    channel,
                    f"%{clip_id[:3]}",
                    int(clip_id[3:]) - 1,
                    int(clip_id[3:]) + 1,
                ),
            )
        else:
            cur.execute(
                "SELECT * FROM QUERIES WHERE message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
                (f"%{clip_id[:3]}", int(clip_id[3:]) - 1, int(clip_id[3:]) + 1),
            )
        data = cur.fetchall()
    if not data:
        return None
    x = Clip(data[0])
    return x

def get_video_clips(video_id) ->  List[Optional[Clip]]:
    with conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM QUERIES WHERE stream_link like ?", (f"%{video_id}%",)
        )
        data = cur.fetchall()
    if not data:
        return []
    l = []
    for y in data:
        x = Clip(y)
        l.append(x)
    return l


def get_channel_clips(channel_id=None) -> List[Clip]:
    with conn:
        cur = conn.cursor()
        if channel_id:
            cur.execute(f"select * from QUERIES where channel_id=?", (channel_id,))
        else:
            cur.execute(f"select * from QUERIES ORDER BY time ASC")
        data = cur.fetchall()
    l = []
    for y in data:
        x = Clip(y)
        l.append(x)
    l.reverse()
    return l


def create_simplified(clips: list) -> str:
    known_vid_id = []
    string = ""
    for clip in clips:
        if clip["stream_id"] not in known_vid_id:
            string += f"https://youtu.be/{clip['stream_id']}\n"
        string += f"{clip['author']['name']} -> {clip['message']} -> {clip['hms']}\n"
        string += f"Link: {clip['link']}\n\n\n"
        known_vid_id.append(clip["stream_id"])
    return string


def get_channel_name_image(channel_id: str) -> Tuple[str, str]:
    if channel_id in channel_info:
        try:
            return channel_info[channel_id]["name"], channel_info[channel_id]["image"]
        except Exception as e:
            logging.log(logging.ERROR, e)
    
    channel_link = f"https://youtube.com/channel/{channel_id}"
    html_data = get(channel_link).text
    soup = BeautifulSoup(html_data, "html.parser")
    try:
        channel_image = soup.find("meta", property="og:image")["content"]
        channel_name = soup.find("meta", property="og:title")["content"]
    except TypeError:  # in case the channel is deleted or not found
        channel_image = "https://yt3.googleusercontent.com/a/default-user=s100-c-k-c0x00ffffff-no-rj"
        channel_name = "<deleted channel>"
    channel_info[channel_id] = {"name": channel_name, "image": channel_image}
    return channel_name, channel_image


def take_screenshot(video_url: str, seconds: int) -> str:
    # Get the video URL using yt-dlp
    try:
        video_info = subprocess.check_output(
            ["yt-dlp", "-f", "bestvideo", "--get-url", video_url],
            universal_newlines=True,
        )
    except subprocess.CalledProcessError as e:
        print("Error:", e)
        exit(1)

    # Remove leading/trailing whitespace and newline characters from the video URL
    video_url = video_info.strip()
    file_name = "ss.jpg"

    # FFmpeg command
    ffmpeg_command = [
        "ffmpeg",
        "-y",  # say yes to prompts
        "-ss",
        str(seconds),  # Start time
        "-i",
        video_url,  # Input video URL
        "-vframes",
        "1",  # Number of frames to extract (1)
        "-q:v",
        "2",  # Video quality (2)
        "-hide_banner",  # Hide banner
        "-loglevel",
        "error",  # Hide logs
        file_name,  # Output image file
    ]

    try:
        subprocess.run(ffmpeg_command, check=True)
    except subprocess.CalledProcessError as e:
        print("Error:", e)
        exit(1)

    return file_name


def get_clip_with_desc(clip_desc: str, channel_id: str) -> Optional[Clip]:
    clips = get_channel_clips(channel_id)
    for clip in clips:
        if clip_desc.lower() in clip.desc.lower():
            return clip
    return None


def download_and_store(clip_id) -> str:
    with conn:
        cur = conn.cursor()
        data = cur.execute(
            "SELECT * FROM QUERIES WHERE  message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
            (f"%{clip_id[:3]}", int(clip_id[3:]) - 1, int(clip_id[3:]) + 1),
        )
        data = cur.fetchall()
    if not data:
        return None
    clip = Clip(data[0])
    video_url = clip.stream_link
    timestamp = clip.time_in_seconds
    output_filename = f"./clips/{clip_id}"
    # if there is a file that start with that clip in current directory then don't download it
    files = [
        os.path.join("clips", x) for x in os.listdir("./clips") if x.startswith(clip_id)
    ]
    if files:
        return files[0]
    # real thing happened at 50. but we stored timestamp with delay. take back that delay
    delay = clip.delay
    timestamp += -1 * delay
    if not delay:
        delay = -60
    l = [timestamp, timestamp + delay]
    start_time = min(l)
    end_time = max(l)
    params = {
        "download_ranges": yt_dlp.utils.download_range_func(
            [], [[start_time, end_time]]
        ),
        "match_filter": yt_dlp.utils.match_filter_func(
            "!is_live & live_status!=is_upcoming & availability=public"
        ),
        "no_warnings": True,
        "noprogress": True,
        "outtmpl": {"default": output_filename},
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(params) as ydl:
        try:
            ydl.download([video_url])
        except yt_dlp.utils.DownloadError as e:
            print(e)
            return  # this video is still live. we can't download it
    files = [
        os.path.join("clips", x) for x in os.listdir("./clips") if x.startswith(clip_id)
    ]
    if files:
        return files[0]


def mini_stats():
    today = datetime.strptime(
        datetime.now().strftime("%Y-%m-%d"), "%Y-%m-%d"
    ).timestamp()
    with conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM QUERIES WHERE time >= ? AND private is not '1' ",
            (today,),
        )
        data = cur.fetchall()
        today_count = data[0][0]
        cur.execute(
            "SELECT * FROM QUERIES where private is not '1' ORDER BY time DESC LIMIT 1"
        )
        data = cur.fetchall()
    if data:
        last_clip = Clip(data[0])
        last_clip = last_clip.json()
    return dict(today_count=today_count, last_clip=last_clip, data=generate_home_data())

@app.context_processor
def inject_mini_stats():
    # todays count
    if "user-agent" not in request.headers:
        return "bro where is your user-agent"
    if "nightbot" in request.headers["user-agent"].lower():
        return {}
    return mini_stats()


@app.before_request
def before_request():
    # if request is for /clip or /delete or /edit then check if its from real
    if "/clip" in request.path or "/delete" in request.path or "/edit" in request.path:
        if "/extension/clips/" in request.path:
            return
        ip = request.remote_addr
        if ip in allowed_ip:
            # print(f"Request from {ip} is allowed, known ip")
            return
        addrs = dns.reversename.from_address(ip)
        try:
            if not str(dns.resolver.resolve(addrs, "PTR")[0]).endswith(
                ".nightbot.net."
            ):
                raise ValueError("Not a nightbot request")
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, ValueError):
            return f"You are not Nightbot. are you ?, your ip {ip}"
        else:
            # print(f"Request from {ip} is allowed")
            allowed_ip.append(ip)
    else:
        pass

@app.route("/mini_stats")
def mini_stats_r():
    return mini_stats()

# this function exists just because google chrome assumes that the favicon is at /favicon.ico
@app.route("/favicon.ico")
def favicon():
    return send_file("static/logo.svg")


@app.route("/robots.txt")
def robots():
    return send_file("static/robots.txt")

def generate_home_data():
    with conn:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM QUERIES GROUP BY channel_id ORDER BY MAX(time) DESC;")
        data = cur.fetchall()
    returning = []
    for clip in data:
        ch = {} 
        channel_name, channel_image = get_channel_name_image(clip[0])
        ch["image"] = channel_image
        ch["name"] = channel_name
        ch["id"] = clip[0]
        ch["image"] = channel_image.replace(
            "s900-c-k-c0x00ffffff-no-rj", "s300-c-k-c0x00ffffff-no-rj"
        )
        ch["last_clip"] = Clip(clip).json()
        ch['last_clip_date'] = ch['last_clip']['dt'].split(" ")[0]
        if request.is_secure:
            htt = "https://"
        else:
            htt = "http://"
        ch["link"] = f"{htt}{request.host}{url_for('exports', channel_id=clip[0])}"
        #ch["last_clip"] = get_channel_clips(ch_id[0])[0].json()
        returning.append(ch)
    """
    for ch in returning:
        ch["clips"] = get_channel_clips(ch["id"])
    NOT A GOOD IDEA. THIS WILL MAKE THE PAGE LOAD SLOWLY. rather show that on admin page.
    """
    return returning


@app.route("/")
def slash():
    returning = generate_home_data()
    return render_template("home.html", data=returning)


@app.route("/data")
def data():
    return "Disabled"
    clips = get_channel_clips()
    clips = [x.json() for x in clips]
    return clips


def get_video_id(video_link):
    x = parse.urlparse(video_link)
    to_return = ""
    if x.path == "/watch":
        to_return = x.query.replace("v=", "")
    if "/live/" in x.path:
        to_return = x.path.replace("/live/", "")
    return to_return.split("&")[0]


@app.route("/ip")
def get_ip():
    return request.remote_addr


# this is for nightbot to give back export link
@app.route("/export")
def export():
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
    except KeyError:
        return "Not able to auth"
    channel_id = channel.get("providerId")[0]
    if request.is_secure:
        htt = "https://"
    else:
        htt = "http://"
    return f"You can see all the clips at {htt}{request.host}{url_for('exports', channel_id=channel_id)}"


# this is for ALL CLIPS
@app.route("/e")
@app.route("/exports")
@app.route("/e/")
@app.route("/exports/")
def clips():
    data = get_channel_clips()
    data = [x.json() for x in data if not x.private]
    return render_template(
        "export.html",
        data=data,
        clips_string=create_simplified(data),
        channel_name="All channels",
        channel_image="https://streamsnip.com/static/logo-grey.png",
        owner_icon=owner_icon,
        mod_icon=mod_icon,
        regular_icon=regular_icon,
        subscriber_icon=subscriber_icon,
        channel_id="all",
    )


# this is for specific channel
@app.route("/exports/<channel_id>")
@app.route("/e/<channel_id>")
def exports(channel_id=None):
    channel_name, channel_image = get_channel_name_image(channel_id)
    data = get_channel_clips(channel_id)
    data = [x.json() for x in data if not x.private]
    return render_template(
        "export.html",
        data=data,
        clips_string=create_simplified(data),
        channel_name=channel_name,
        channel_image=channel_image,
        owner_icon=owner_icon,
        mod_icon=mod_icon,
        regular_icon=regular_icon,
        subscriber_icon=subscriber_icon,
        channel_id=channel_id,
    )


@app.route("/channelstats/<channel_id>")
@app.route("/cs/<channel_id>")
@app.route("/channelstats")
def channel_stats(channel_id=None):
    if not channel_id:
        return redirect(url_for("slash"))
    if channel_id == "all":
        return redirect(url_for("stats"))
    with conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM QUERIES WHERE channel_id=? AND private is not '1'",
            (channel_id,),
        )
        data = cur.fetchall()
    if not data:
        return redirect(url_for("slash"))
    clips = []
    for x in data:
        clips.append(Clip(x))

    clip_count = len(clips)
    user_count = len(set([clip.user_id for clip in clips]))
    # "Name": no of clips
    user_clips = {}
    top_clippers = {}
    notes = {}
    for clip in clips:
        if clip.user_id not in user_clips:
            user_clips[clip.user_id] = 0
        user_clips[clip.user_id] += 1
        if clip.desc and clip.desc != "None":
            for word in clip.desc.lower().split():
                if word not in notes:
                    notes[word] = 0
                notes[word] += 1
        if clip.user_id not in top_clippers:
            top_clippers[clip.user_id] = 0
        top_clippers[clip.user_id] += 1
    # sort
    user_clips = {
        k: v
        for k, v in sorted(user_clips.items(), key=lambda item: item[1], reverse=True)
    }
    notes = {
        k: 5 + 5 * v
        for k, v in sorted(notes.items(), key=lambda item: item[1], reverse=True)
    }
    notes = dict(list(notes.items())[:200])
    new_dict = {}
    # replace dict_keys with actual channel
    max_count = 0
    streamer_name, streamer_image = get_channel_name_image(channel_id)
    # sort and get k top clippers
    user_clips = {
        k: v
        for k, v in sorted(user_clips.items(), key=lambda item: item[1], reverse=True)
    }
    for k, v in user_clips.items():
        max_count += 1
        if max_count > 12:
            break
        channel_name, image = get_channel_name_image(k)
        new_dict[channel_name] = v
    new_dict["Others"] = sum(list(user_clips.values())[max_count:])
    if new_dict["Others"] == 0:
        new_dict.pop("Others")
    user_clips = new_dict
    top_clippers = {
        k: v
        for k, v in sorted(top_clippers.items(), key=lambda item: item[1], reverse=True)
    }
    new = []
    count = 0
    for k, v in top_clippers.items():
        count += 1
        if count > 12:
            break
        channel_name, image = get_channel_name_image(k)
        new.append(
            {
                "name": channel_name,
                "image": image,
                "count": v,
                "link": f"https://youtube.com/channel/{k}",
                "otherlink": url_for("user_stats", channel_id=k),
            }
        )
    top_clippers = new
    new_dict = {}
    # time trend
    # day : no_of_clips
    for clip in clips:
        day = (clip.time + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        if day not in new_dict:
            new_dict[day] = 0
        new_dict[day] += 1
    time_trend = new_dict

    streamer_trend_data = {}
    # "clipper" : {day: no_of_clips}
    streamers_trend_days = []
    max_count = 0
    for clip in clips:
        day = (clip.time + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        if clip.user_id not in streamer_trend_data:
            streamer_trend_data[clip.user_id] = {}
        if day not in streamer_trend_data[clip.user_id]:
            streamer_trend_data[clip.user_id][day] = 0
        streamer_trend_data[clip.user_id][day] += 1
        if day not in streamers_trend_days:
            streamers_trend_days.append(day)
    streamers_trend_days.sort()
    # replace channel id with channel name
    new_dict = {}
    known_k = []
    max_count = 0
    # sort
    streamer_trend_data = {
        k: v
        for k, v in sorted(
            streamer_trend_data.items(),
            key=lambda item: sum(item[1].values()),
            reverse=True,
        )
    }
    for k, v in streamer_trend_data.items():
        max_count += 1
        if max_count > 12:
            break
        channel_name, image = get_channel_name_image(k)
        new_dict[channel_name] = v
        known_k.append(k)
    new_dict["Others"] = {}
    for k, v in streamer_trend_data.items():
        if k in known_k:
            continue
        for day, count in v.items():
            if day not in new_dict["Others"]:
                new_dict["Others"][day] = 0
            new_dict["Others"][day] += count
    if new_dict["Others"] == {}:
        new_dict.pop("Others")
    streamer_trend_data = new_dict
    time_distribution = {}
    for x in range(24):
        time_distribution[x] = 0
    for clip in clips:
        hm = int((clip.time + timedelta(hours=5, minutes=30)).strftime("%H"))
        time_distribution[hm] += 1
    message = f"Channel Stats for {streamer_name}. {user_count} users clipped\n{clip_count} clips till now. \nand counting."
    return render_template(
        "stats.html",
        message=message,
        notes=notes,
        clip_count=clip_count,
        user_count=user_count,
        clip_users=[(k, v) for k, v in user_clips.items()],
        top_clippers=top_clippers,
        channel_count=len(user_clips),
        times=list(time_trend.keys()),
        counts=list(time_trend.values()),
        streamer_trend_data=streamer_trend_data,
        streamers_trend_days=streamers_trend_days,
        streamers_labels=list(streamer_trend_data.keys()),
        time_distribution=time_distribution,
        channel_name=streamer_name,
        channel_image=streamer_image,
    )


@app.route("/userstats/<channel_id>")
@app.route("/us/<channel_id>")
@app.route("/userstats")
def user_stats(channel_id=None):
    if not channel_id:
        return redirect(url_for("slash"))
    with conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM QUERIES WHERE user_id=? AND private is not '1' ",
            (channel_id,),
        )
        data = cur.fetchall()
    if not data:
        return redirect(url_for("slash"))
    clips = []
    for x in data:
        clips.append(Clip(x))
    clip_count = len(clips)
    user_count = len(set([clip.channel for clip in clips]))
    # "Name": no of clips
    user_clips = {}
    top_clippers = {}
    notes = {}
    for clip in clips:
        if clip.channel not in user_clips:
            user_clips[clip.channel] = 0
        user_clips[clip.channel] += 1
        if clip.desc and clip.desc != "None":
            for word in clip.desc.lower().split():
                if word not in notes:
                    notes[word] = 0
                notes[word] += 1
        if clip.channel not in top_clippers:
            top_clippers[clip.channel] = 0
        top_clippers[clip.channel] += 1
    # sort
    notes = {
        k: 5 + 5 * v
        for k, v in sorted(notes.items(), key=lambda item: item[1], reverse=True)
    }
    notes = dict(list(notes.items())[:200])
    user_clips = {
        k: v
        for k, v in sorted(user_clips.items(), key=lambda item: item[1], reverse=True)
    }
    top_clippers = {
        k: v
        for k, v in sorted(top_clippers.items(), key=lambda item: item[1], reverse=True)
    }
    new_dict = {}
    # replace dict_keys with actual channel
    max_count = 0
    streamer_name, streamer_image = get_channel_name_image(channel_id)

    # sort and get k top clippers
    user_clips = {
        k: v
        for k, v in sorted(user_clips.items(), key=lambda item: item[1], reverse=True)
    }
    for k, v in user_clips.items():
        max_count += 1
        if max_count > 12:
            break
        channel_name, image = get_channel_name_image(k)
        new_dict[channel_name] = v
    new_dict["Others"] = sum(list(user_clips.values())[max_count:])
    if new_dict["Others"] == 0:
        new_dict.pop("Others")
    user_clips = new_dict
    new = []
    count = 0
    for k, v in top_clippers.items():
        count += 1
        if count > 12:
            break
        channel_name, image = get_channel_name_image(k)
        new.append(
            {
                "name": channel_name,
                "image": image,
                "count": v,
                "link": f"https://youtube.com/channel/{k}",
                "otherlink": url_for("channel_stats", channel_id=k),
            }
        )
    top_clippers = new
    new_dict = {}
    # time trend
    # day : no_of_clips
    for clip in clips:
        day = (clip.time + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        if day not in new_dict:
            new_dict[day] = 0
        new_dict[day] += 1
    time_trend = new_dict

    streamer_trend_data = {}
    # "clipper" : {day: no_of_clips}
    streamers_trend_days = []
    max_count = 0
    for clip in clips:
        day = (clip.time + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        if clip.channel not in streamer_trend_data:
            streamer_trend_data[clip.channel] = {}
        if day not in streamer_trend_data[clip.channel]:
            streamer_trend_data[clip.channel][day] = 0
        streamer_trend_data[clip.channel][day] += 1
        if day not in streamers_trend_days:
            streamers_trend_days.append(day)
    streamers_trend_days.sort()
    # replace channel id with channel name
    new_dict = {}
    known_k = []
    max_count = 0
    # sort
    streamer_trend_data = {
        k: v
        for k, v in sorted(
            streamer_trend_data.items(),
            key=lambda item: sum(item[1].values()),
            reverse=True,
        )
    }
    for k, v in streamer_trend_data.items():
        max_count += 1
        if max_count > 12:
            break
        channel_name, image = get_channel_name_image(k)
        new_dict[channel_name] = v
        known_k.append(k)
    new_dict["Others"] = {}
    for k, v in streamer_trend_data.items():
        if k in known_k:
            continue
        for day, count in v.items():
            if day not in new_dict["Others"]:
                new_dict["Others"][day] = 0
            new_dict["Others"][day] += count
    if new_dict["Others"] == {}:
        new_dict.pop("Others")
    streamer_trend_data = new_dict
    time_distribution = {}
    for x in range(24):
        time_distribution[x] = 0
    for clip in clips:
        hm = int((clip.time + timedelta(hours=5, minutes=30)).strftime("%H"))
        time_distribution[hm] += 1
    message = f"User Stats for {streamer_name}. Clipped\n{clip_count} clips in {user_count} channels till now. and counting."
    return render_template(
        "stats.html",
        message=message,
        notes=notes,
        clip_count=clip_count,
        user_count=user_count,
        clip_users=[(k, v) for k, v in user_clips.items()],
        top_clippers=top_clippers,
        channel_count=len(user_clips),
        times=list(time_trend.keys()),
        counts=list(time_trend.values()),
        streamer_trend_data=streamer_trend_data,
        streamers_trend_days=streamers_trend_days,
        streamers_labels=list(streamer_trend_data.keys()),
        time_distribution=time_distribution,
        channel_name=streamer_name,
        channel_image=streamer_image,
    )


@app.route("/stats")
def stats():
    # get clips
    with conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM QUERIES WHERE private is not '1'")
        data = cur.fetchall()
    clips = []
    three_months_ago = (datetime.now() - timedelta(days=28)).timestamp()
    for x in data:
        c = Clip(x)
        clips.append(c)
    clip_count = len(data)
    user_count = len(set([x[5] for x in data]))
    # "Name": no of clips
    user_clips = {}
    top_clippers = {}
    notes = {}
    for clip in clips:
        if clip.channel not in user_clips:
            user_clips[clip.channel] = 0
        user_clips[clip.channel] += 1
        if clip.desc and clip.desc != "None":
            for word in clip.desc.lower().split():
                if word not in notes:
                    notes[word] = 0
                notes[word] += 1
        if clip.user_id not in top_clippers:
            top_clippers[clip.user_id] = 0
        top_clippers[clip.user_id] += 1

    # sort
    user_clips = {
        k: v
        for k, v in sorted(user_clips.items(), key=lambda item: item[1], reverse=True)
    }
    # get only top 25 and other as sum of rest
    _user_clips = user_clips
    channel_count = len(_user_clips)
    user_clips = {}
    max_count = 0
    top_25_ids = []

    for k, v in _user_clips.items():
        max_count += 1
        if max_count > 25:
            break
        top_25_ids.append(k)
        user_clips[k] = v
    user_clips["Others"] = sum(list(_user_clips.values())[max_count-1:])
    if user_clips["Others"] == 0:
        user_clips.pop("Others")
    top_clippers = {
        k: v
        for k, v in sorted(top_clippers.items(), key=lambda item: item[1], reverse=True)
    }
    notes = {
        k:  v
        for k, v in sorted(notes.items(), key=lambda item: item[1], reverse=True)
    }
    notes = dict(list(notes.items())[:200])
    # replace dict_keys with actual channel
    new_dict = {}
    for k, v in user_clips.items():
        if k != "Others":
            channel_name, image = get_channel_name_image(k)
        else:
            channel_name = "Others"
        new_dict[channel_name] = v
    user_clips = new_dict
    new = []
    count = 0
    for k, v in top_clippers.items():
        count += 1
        if count > 12:
            break
        channel_name, image = get_channel_name_image(k)
        new.append(
            {
                "name": channel_name,
                "image": image,
                "count": v,
                "link": f"https://youtube.com/channel/{k}",
                "otherlink": url_for("user_stats", channel_id=k),
            }
        )
    top_clippers = new
    new_dict = {}
    # time trend
    # day : no_of_clips
    for clip in clips:
        day = (clip.time + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        if clip.time.timestamp() < three_months_ago:
            continue
        if day not in new_dict:
            new_dict[day] = 0
        new_dict[day] += 1
    time_trend = new_dict

    streamer_trend_data = {}
    # streamer: {day: no_of_clips}
    streamers_trend_days = []
    for clip in clips:
        day = (clip.time + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        if clip.time.timestamp() < three_months_ago:
            continue # we don't need to show old data
        channel_id = clip.channel
        if channel_id not in top_25_ids:
            channel_id = "Others"
        if channel_id not in streamer_trend_data:
            streamer_trend_data[channel_id] = {}
        if day not in streamer_trend_data[channel_id]:
            streamer_trend_data[channel_id][day] = 0
        streamer_trend_data[channel_id][day] += 1
        if day not in streamers_trend_days:
            streamers_trend_days.append(day)
    streamers_trend_days.sort()
    # only top 25 and others 
    streamer_trend_data = {
        k: v
        for k, v in sorted(
            streamer_trend_data.items(),
            key=lambda item: sum(item[1].values()),
            reverse=True,
        )
    }
    new_dict = {}
    known_k = []
    max_count = 0
    for k, v in streamer_trend_data.items():
        max_count += 1
        if k != "Others":
            channel_name, image = get_channel_name_image(k)
        else:
            channel_name = k
        new_dict[channel_name] = v
        known_k.append(k)
    if new_dict["Others"] == {}:
        new_dict.pop("Others")
    streamer_trend_data = new_dict
    time_distribution = {}
    for x in range(24):
        time_distribution[x] = 0
    for clip in clips:
        hm = int((clip.time + timedelta(hours=5, minutes=30)).strftime("%H"))
        time_distribution[hm] += 1

    message = f"{user_count} users clipped\n{clip_count} clips on \n{channel_count} channels till now. \nand counting."
    return render_template(
        "stats.html",
        message=message,
        notes=notes,
        clip_count=clip_count,
        user_count=user_count,
        clip_users=[(k, v) for k, v in user_clips.items()],
        top_clippers=top_clippers,
        channel_count=channel_count,
        times=list(time_trend.keys()),
        counts=list(time_trend.values()),
        streamer_trend_data=streamer_trend_data,
        streamers_trend_days=streamers_trend_days,
        streamers_labels=list(streamer_trend_data.keys()),
        time_distribution=time_distribution,
        channel_name="All channels",
        channel_image="https://streamsnip.com/static/logo-grey.png",
    )


@app.route("/admin")
def admin():
    clips = get_channel_clips()
    t = time.time()
    clip_ids = [x.id for x in clips]
    print(f"took {time.time()-t} to get clips")
    t = time.time()
    with open("creds.json", "r") as f:
        config = load(f)
    channel_info_admin = {}
    for key, value in config.items():
        if key in ["password", "management_webhook"]:
            continue
        get_channel_name_image(key)
        channel_info_admin[key] = channel_info[key]
        if request.is_secure:
            htt = "https://"
        else:
            htt = "http://"
        channel_info_admin[key][
            "link"
        ] = f"{htt}{request.host}{url_for('exports', channel_id=key)}"
    print(f"took {time.time()-t} to get channel info")
    return render_template("admin.html", ids=clip_ids, channel_info=channel_info_admin)

def get_channel_id(path):
    html_data = get(path).text
    soup = BeautifulSoup(html_data, "html.parser")
    identifier = soup.find('meta', itemprop="identifier")
    if not identifier:
        return None
    channel_id = identifier['content']
    return channel_id


@app.route("/approve")
def approve():
    # this is in format of https://streamsnip.com/approve?pass=somepassword&key=https://www.youtube.com/channel/UC5IRLz3Q-SADL71-sW-Z16Q&value=https://discord.com/api/webhooks/51313123122515125/sadfasdasd12rasfafase-VOkUSVo4clrbXSh6Mpa
    password = request.args.get("pass")
    key = request.args.get("key")
    value = request.args.get("value")

    if password != get_webhook_url("password"):
        return "Wrong password"
    if "youtube.com" not in key:
        return f"Key isn't of youtube {key}"
    if "discord.com/api/webhooks" not in value:
        return f"Value isn't of discord webhook {value}"

    channel_id = get_channel_id(key)
    if not channel_id:
        return "Channel id not found"

    with open("creds.json", "r") as f:
            creds = load(f)
    creds[channel_id] = value
    with open("creds.json", "w") as f:
        dump(creds, f, indent=4)

    channel_name, channel_image = get_channel_name_image(channel_id)
    webhook = DiscordWebhook(url=value, username=project_name, avatar_url=project_logo_discord)
    embed = DiscordEmbed(
        title=f"Welcome to {project_name}!", 
        description=f"I will send clips for {channel_name} here",
        )
    embed.add_embed_field(name="Add Nightbot command", value=f"If you haven't already. add Nightbot commands from [github]({project_repo_link}) .")
    embed.set_thumbnail(url=project_logo_discord)
    embed.set_color(0xebf0f7)
    webhook.add_embed(embed)
    webhook.execute()

    if "update_webhook" in creds:
        webhook = DiscordWebhook(url=creds["update_webhook"], username=project_name, avatar_url=project_logo_discord)
        embed = DiscordEmbed(
            title=f"New webhook added",
            description=f"New webhook added for {channel_name}",
        )
        embed.set_thumbnail(url=channel_image)
        embed.set_color(0xebf0f7)
        webhook.add_embed(embed)
        webhook.execute()
    return "Done"

@app.route("/ed", methods=["POST"])
def edit_delete():
    actual_password = get_webhook_url(
        "password"
    )  # i know this is not a good way to store password. but i am too lazy to implement a proper login system
    if not actual_password:
        return "Password not set"
    password = request.form.get("password")
    if password != actual_password:
        return "Invalid password"
    # get the clip id
    print(request.form)
    clip_id = request.form.get("clip")
    # get the action
    if request.form.get("rename") == "Rename":
        if not request.form.get("clip", None):
            return "No Clip selected"
        # edit the clip
        if not request.form.get("new_name", None):
            return "No new name provided"
        new_name = request.form.get("new_name").strip()
        clip = get_clip(clip_id)
        clip.edit(new_name, conn)
        return "Edited"

    elif request.form.get("delete") == "Delete":
        if not request.form.get("clip", None):
            return "No Clip selected"
        # delete the clip
        clip = get_clip(clip_id)
        if not clip:
            return "Clip not found"
        clip.delete(conn)
        return "Deleted"

    elif request.form.get("new") == "Submit":
        if not request.form.get("key", None):
            return "No key provided"
        if not request.form.get("value", None):
            return "No value provided"
        key = request.form.get("key").strip()
        value = request.form.get("value").strip()

        with open("creds.json", "r") as f:
            creds = load(f)
        creds[key] = value
        with open("creds.json", "w") as f:
            dump(creds, f, indent=4)

        channel_name, channel_image = get_channel_name_image(key)
        if value.startswith("https://discord"):
            webhook = DiscordWebhook(url=value, username=project_name, avatar_url=project_logo_discord)
            embed = DiscordEmbed(
                title=f"Welcome to {project_name}!", 
                description=f"I will send clips for {channel_name} here",
                )
            embed.add_embed_field(name="Add Nightbot command", value=f"If you haven't already. add Nightbot commands from [github]({project_repo_link}) .")
            embed.set_thumbnail(url=project_logo_discord)
            embed.set_color(0xebf0f7)
            webhook.add_embed(embed)
            webhook.execute()
        if "update_webhook" in creds:
            webhook = DiscordWebhook(url=creds["update_webhook"], username=project_name, avatar_url=project_logo_discord)
            embed = DiscordEmbed(
                title=f"New webhook added",
                description=f"New webhook added for {channel_name}",
            )
            embed.set_thumbnail(url=channel_image)
            embed.set_color(0xebf0f7)
            webhook.add_embed(embed)
            webhook.execute()
        return jsonify(creds)
    elif request.form.get("show") == "show":
        return jsonify(open("creds.json", "r").read())
    else:
        return f"what ? {request.form}" 


def get_latest_live(channel_id):
    vids = scrapetube.get_channel(channel_id, content_type="streams", limit=2, sleep=0)
    live_found_flag = False
    for vid in vids:
        if (
            vid["thumbnailOverlays"][0]["thumbnailOverlayTimeStatusRenderer"]["style"]
            == "LIVE"
        ):
            live_found_flag = True
            break
    if not live_found_flag:
        return None
    vid = YouTubeChatDownloader().get_video_data(video_id=vid["videoId"])
    return vid


@app.route("/add", methods=["POST", "GET"])
def add():
    if request.method == "GET":
        return render_template(
            "add.html", link="enter link", desc="!clip", password="password"
        )
    else:
        data = request.form
        if data.get("new") == "Submit":
            link = data.get("link", None)
            desc = data.get("command", None)
            if not desc:
                desc = "!clip"
            password = data.get("password", None)
            if not link or not password:
                return "Link/command/password not found"
            vid_id = get_video_id(link)
            if not vid_id:
                return "Invalid link"
            vid = YouTubeChatDownloader().get_video_data(video_id=vid_id)
            streamer_id = vid["author_id"]
            if not password == get_webhook_url(streamer_id):
                return "Invalid password"
            right_chats = []
            channel_clips = get_channel_clips(streamer_id)
            # rasterize the chat from delay
            xx = []
            for clip in channel_clips:
                if clip.delay:
                    clip.time_in_seconds -= clip.delay
                    clip.delay = 0
                if vid_id != clip.stream_id:
                    continue
                d = {
                    "id": clip.id,
                    "desc": clip.desc,
                }
                xx.append(d)
            with conn:
                for chat in ChatDownloader().get_chat(vid_id):
                    flag = False
                    time = int(chat["time_in_seconds"])
                    for x in xx:
                        if chat["message"] == f"{desc} {x['desc']}":
                            flag = True
                            break
                    if flag:
                        continue
                    if chat["message_type"] == "text_message":
                        if chat["message"].startswith(desc):
                            right_chats.append(chat)
            return render_template(
                "add.html", link=link, desc=desc, password=password, chats=right_chats
            )
        else:
            # second time
            link = data.get("link", None)
            vid_id = get_video_id(link)
            delay = data.get("delay")
            if not delay:
                delay = 0
            vid = YouTubeChatDownloader().get_video_data(video_id=vid_id)
            password = data.get("password", None)
            streamer_id = vid["author_id"]
            if not password == get_webhook_url(streamer_id):
                return "Invalid password"
            right_chats = []
            for chat in ChatDownloader().get_chat(vid_id):
                if chat["message_id"] in data.keys():
                    right_chats.append(chat)
            response = ""
            for chat in right_chats:
                clip_message = " ".join(chat["message"].split(" ")[1:])
                chat_id = vid_id
                try:
                    user_level = parse_user_badges(chat["author"]["badges"])
                except KeyError:
                    user_level = "everyone"
                headers = {
                    "Nightbot-Channel": f"providerId={streamer_id}",
                    "Nightbot-User": f"providerId={chat['author']['id']}&displayName={chat['author']['name']}&userLevel={user_level}",
                    "Nightbot-Response-Url": "https://api.nightbot.tv/1/channel/send/",
                    "videoID": vid_id,
                    "timestamp": str(chat["timestamp"]),
                }
                if request.is_secure:
                    htt = "https://"
                else:
                    htt = "http://"
                if local:
                    link = f"{htt}{request.host}/clip/{chat_id}/{clip_message}"
                else:
                    link = f"{htt}{request.host}/clip/{chat_id}/{clip_message}"
                if delay:
                    delay = int(delay)
                    link += f"?delay={delay}"
                r = get(link, headers=headers)
                response += r.text + "\n"
            return "Done" + "\n" + response


def parse_user_badges(badges) -> str:
    """owner - Channel Owner
    moderator - Channel Moderator
    subscriber - Paid Channel Subscriber
    everyone"""
    badges = [x["title"].split(" ")[0].lower() for x in badges]
    if "owner" in badges:
        return "owner"
    if "moderator" in badges:
        return "moderator"
    if "member" in badges:
        return "subscriber"
    return "everyone"


@app.route("/uptime")
def uptime():
    # returns the uptime of the bot
    # takes 1 argument seconds
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
        user = parse_qs(request.headers["Nightbot-User"])
    except KeyError:
        return "Not able to auth"
    channel_id = channel.get("providerId")[0]
    latest_live = get_latest_live(channel_id)
    if not latest_live:
        return "No live stream found"
    start_time = latest_live["start_time"] / 1000000
    current_time = time.time()
    uptime_seconds = current_time - start_time
    uptime = time_to_hms(uptime_seconds)
    level = request.args.get("level", 0)
    try:
        level = int(level)
    except ValueError:
        level = 0
    if not level:
        return f"Stream uptime is {uptime}"
    elif level == 1:
        return str(uptime)
    elif level == 2:
        # convert time to x hours y minutes z seconds
        uptime = uptime.split(":")
        string = "Stream is running from "
        if len(uptime) == 3:
            string += f"{uptime[0]} hours {uptime[1]} minutes & {uptime[2]} seconds."
        elif len(uptime) == 2:
            string += f"{uptime[0]} minutes & {uptime[1]} seconds."
        else:
            string += f"{uptime[0]} seconds."
        return str(string)
    else:
        return str(uptime_seconds)


@app.route("/stream_info")
def stream_info():
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
        user = parse_qs(request.headers["Nightbot-User"])
    except KeyError:
        return "Not able to auth"
    channel_id = channel.get("providerId")[0]
    return get_latest_live(channel_id)

@app.route("/recent")
@app.route("/record")
def recent():
    default_value = 5 
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
        user = parse_qs(request.headers["Nightbot-User"])
    except KeyError:
        return "Not able to auth"
    channel_id = channel.get("providerId")[0]
    clips = [clip for clip in get_channel_clips(channel_id) if not clip.private]
    string = ""
    request_count = request.args.get("count", default_value)
    try:
        request_count = int(request_count)
    except ValueError:
        request_count = default_value
        
    for clip in clips[:request_count]:
        if len(clip.desc) > 10:
            clip.desc = clip.desc[:10] + "..."
        string += f"{clip.desc} {clip.id} | "
    if len(string) > 256:
        return string[:256] # youtube limits to 256 characters. who are we to disobey
    return string

@app.route("/nstats")
@app.route("/nstat")
def nstats():
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
        user = parse_qs(request.headers["Nightbot-User"])
    except KeyError:
        return "Headers not found. Are you sure you are using nightbot ?"
    channel_id = channel.get("providerId")[0]
    user_id = user.get("providerId")[0]
    clips = get_channel_clips(channel_id)
    total_clips = len(clips)
    total_users = len(set([clip.user_id for clip in clips]))
    user_clip = [clip for clip in clips if clip.user_id == user_id]
    user_clip_count = len(user_clip)
    this_stream_count = 0
    try:
        this_stream_id = get_latest_live(channel_id)["original_video_id"]
    except:
        this_stream_id = None
    for clip in clips:
        if clip.stream_id == this_stream_id:
            this_stream_count += 1
        else:
            break # this is cause the clips are sorted by time. so if we find a clip that is not of this stream. we can break and save time
    
    percentage = (user_clip_count / total_clips) * 100 
    percentage = round(percentage, 2)
    today_count_string = f" ({this_stream_count} today)" if this_stream_count != 0 else f""
    return f"{total_clips} clips have been made {today_count_string} by total {total_users} users, out of which {user_clip_count} clips ({percentage}%) have been made by you."

# /clip/<message_id>/<clip_desc>?showlink=true&screenshot=true&dealy=-10&silent=2
@app.route("/clip/<message_id>/")
@app.route("/clip/<message_id>/<clip_desc>")
def clip(message_id, clip_desc=None):
    arguments = {k.replace("?", ""): request.args[k] for k in request.args}
    show_link = arguments.get("showlink", True)
    screenshot = arguments.get("screenshot", False)
    silent = arguments.get("silent", 2)  # silent level. if not then 2
    private = arguments.get("private", False)
    webhook = arguments.get("webhook", False)
    take_delays = arguments.get("take_delays", False)
    message_level = arguments.get(
        "message_level", 0
    )  # 0 is normal. 1 is to persist the defautl webhook name. 2 is for no record on discord message. 3 is for service badging
    try:
        message_level = int(message_level)
    except ValueError:
        message_level = 0
    logging.log(
        level=logging.INFO,
        msg=f"A request for clip with arguments {arguments} and headers {request.headers}",
    )
    if webhook and not webhook.startswith("https://discord.com/api/webhooks/"):
        webhook = f"https://discord.com/api/webhooks/{webhook}"
    try:
        silent = int(silent)
    except ValueError:
        silent = 2
    delay = arguments.get("delay", 0)
    show_link = False if show_link == "false" else True
    screenshot = True if screenshot == "true" else False
    private = True if private == "true" else False
    take_delays = True if take_delays == "true" else False
    
    try:
        delay = 0 if not delay else int(delay)
    except ValueError:
        return "Delay should be an integer (plus or minus)"
    if not clip_desc:
        clip_desc = "None"
    if take_delays:
        splitted = clip_desc.split()
        candidates = [splitted[0], splitted[-1]]
        for c in candidates:
            try:
                extra_delay = int(c)
                clip_desc = clip_desc.replace(c, "")
                delay += extra_delay
                break
            except ValueError:
                pass

    request_time = time.time()
    h_request_time = request.headers.get("timestamp")
    if h_request_time:
        try:
            request_time = float(h_request_time)
        except ValueError:
            return "The value of request time in headers must be a number"
        if len(str(int(request_time))) > 10:
            request_time = request_time / 1000000
            # this is because youtube unknownigly stores chat timing with very high precision.
    if not local:
        monitor.ping(state="run")
    if not message_id:
        return "No message id provided, You have configured it wrong. please contact AG at https://discord.gg/2XVBWK99Vy"
    
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
        user = parse_qs(request.headers["Nightbot-User"])
    except KeyError:
        return "Headers not found. Are you sure you are using nightbot ?"

    channel_id = channel.get("providerId")[0]
    webhook_url = get_webhook_url(channel_id) if not webhook else webhook
    user_level = user.get("userLevel")[0]
    user_id = user.get("providerId")[0]
    user_name = user.get("displayName")[0]
    if message_id in chat_id_video:
        vid = chat_id_video[message_id]
    else:
        vid = get_latest_live(channel_id)
        chat_id_video[message_id] = vid
    # if there is a video id passed through headers. we may want to use it instead
    h_vid = request.headers.get("videoID")
    if is_blacklisted(channel_id):
        if show_fake_error:
            return "Remote Server Returned Code 404"
        else:
            return "You are blacklisted from using this service. for undisclosed reasons. :)"
    if h_vid:
        vid = YouTubeChatDownloader().get_video_data(video_id=h_vid)
    if not vid:
        return "No LiveStream Found."
    clip_time = request_time - vid["start_time"] / 1000000 + 5
    clip_time += delay
    url = "https://youtu.be/" + vid["original_video_id"] + "?t=" + str(int(clip_time))
    clip_id = message_id[-3:] + str(int(clip_time))
    # if clip_time is in seconds. then hh:mm:ss format would be like
    hour_minute_second = time_to_hms(clip_time)
    is_privated_str = "(P) " if private else ""
    message_cc_webhook = f"{is_privated_str}{clip_id} | **{clip_desc}** \n\n{hour_minute_second} \n<{url}>"
    if delay:
        message_cc_webhook += f"\nDelayed by {delay} seconds."
    if message_level == 0:
        channel_name, channel_image = get_channel_name_image(user_id)
        webhook_name = user_name
    elif message_level == 1:
        channel_name, channel_image = "", ""
        webhook_name = ""
        message_cc_webhook += f"\nClipped by {user_name}"
    elif message_level == 2:
        webhook_name = ""
        channel_name, channel_image = "", ""
    else:
        webhook_name = "Streamsnip"
        channel_name, channel_image = (
            "Streamsnip",
            project_logo_discord,
        )

    if message_level == 0:
        if user_level == "owner":
            webhook_name += f" {owner_icon}"
        elif user_level == "moderator":
            webhook_name += f" {mod_icon}"
        elif user_level == "regular":
            webhook_name += f" {regular_icon}"
        elif user_level == "subscriber":
            webhook_name += f" {subscriber_icon}"

    if len(clip_desc) > 30:
        t_clip_desc = clip_desc[:30] + "..."
    else:
        t_clip_desc = clip_desc
    if t_clip_desc != "None":
        message_to_return = f"Clip {clip_id} by {user_name} -> '{t_clip_desc}' "
    else:
        message_to_return = f"Clip {clip_id} by {user_name} "
    if delay:
        message_to_return += f" Delayed by {delay} seconds."
    if webhook_url:  # if webhook is not found then don't send the message
        message_to_return += " | sent to discord."
        webhook = DiscordWebhook(
            url=webhook_url,
            content=message_cc_webhook,
            username=webhook_name,
            avatar_url=channel_image,
            allowed_mentions={"role": [], "user": [], "everyone": False},
        )
        response = webhook.execute()
        if not response.status_code == 200:
            return "Error in sending message to discord. Perhaps the webhook is invalid. Please contant AG at https://discord.gg/2XVBWK99Vy"
        webhook_id = webhook.id
    else:
        webhook_id = None

    if show_link:
        if request.is_secure:
            htt = "https://"
        else:
            htt = "http://"
        message_to_return += f" See all clips at {htt}{request.host}{url_for('exports', channel_id=channel_id)}"

    if screenshot and webhook_url:
        webhook = DiscordWebhook(
            url=webhook_url,
            username=user_name,
            avatar_url=channel_image,
            allowed_mentions={"role": [], "user": [], "everyone": False},
        )
        file_name = take_screenshot(url, clip_time)
        with open(file_name, "rb") as f:
            webhook.add_file(file=f.read(), filename="ss.jpg")
        webhook.execute()
        ss_id = webhook.id
        ss_link = webhook.attachments[0]["url"]
    else:
        ss_id = None
        ss_link = None
    # insert the entry to database
    with conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO QUERIES VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                channel_id,
                message_id,
                clip_desc,
                request_time,
                clip_time,
                user_id,
                user_name,
                url,
                webhook_id,
                delay,
                user_level,
                ss_id,
                ss_link,
                private,
                message_level,
            ),
        )
        conn.commit()
    if not local:
        monitor.ping(state="complete")
    if private:
        return "clipped 😉"
    if silent == 2:
        return message_to_return
    elif silent == 1:
        return clip_id
    else:
        return " "


@app.route("/delete/<clip_id>")
def delete(clip_id=None):
    if not clip_id:
        return "No Clip ID provided"
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
    except KeyError:
        return "Not able to auth"
    channel_id = channel.get("providerId")[0]
    arguments = {k.replace("?", ""): request.args[k] for k in request.args}
    silent = arguments.get("silent", 2)  # silent level. if not then 2
    try:
        silent = int(silent)
    except ValueError:
        return "Silent level should be an integer"
    returning_str = ""
    errored_str = ""
    for c in clip_id.split(" "):
        try:
            clip = get_clip(c, channel_id)
        except ValueError:
            clip = None
        if not clip:
            errored_str += f" {c}"
            continue
        if clip.delete(conn):
            returning_str += f" {c}"
        else:
            errored_str += f" {c}"
    if returning_str:
        returning_str = "Deleted clips with id" + returning_str
    if errored_str:
        errored_str = "Couldn't delete clips with id" + errored_str
    if silent == 0:
        return " "
    elif silent == 1:
        return returning_str
    else:
        return returning_str + errored_str


@app.route("/edit/<xxx>")
def edit(xxx=None):
    if not xxx:
        return "No Clip ID provided"
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
    except KeyError:
        return "Not able to auth"
    if len(xxx.split(" ")) < 2:
        return "Please provide clip id and new description"
    arguments = {k.replace("?", ""): request.args[k] for k in request.args}
    silent = arguments.get("silent", 2)  # silent level. if not then 2
    clip_id = xxx.split(" ")[0]
    new_desc = " ".join(xxx.split(" ")[1:])
    try:
        silent = int(silent)
    except ValueError:
        return "Silent level should be an integer"
    channel_id = channel.get("providerId")[0]
    clip = get_clip(clip_id, channel_id)
    old_desc = clip.desc
    if not clip:
        return "Clip ID not found"
    edited = clip.edit(new_desc, conn)
    if not edited:
        return "Couldn't edit the clip"
    if silent == 0:
        return " "
    elif silent == 1:
        return clip_id
    else:
        return (
            f"Edited clip {clip_id} from title '"
            + old_desc
            + "' to '"
            + new_desc
            + "'."
        )


@app.route("/search/<clip_desc>")
def search(clip_desc=None):
    # returns the first clip['url'] that matches the description
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
    except KeyError:
        return "Not able to auth"
    clip = get_clip_with_desc(clip_desc, channel.get("providerId")[0])
    level = request.args.get("level", 0)
    try:
        level = int(level)
    except ValueError:
        return "level should be an integer"
    if not clip:
        return "Clip not found"
    match level:
        case 0:
            return clip.stream_link
        case 1:
            return clip.id
        case 2:
            return f"{clip.desc} - {clip.stream_link}"
        case 3:
            return f"{clip.id} {clip.user_name} | {clip.desc} - {clip.stream_link}"
        case _:
            return clip.stream_link


@app.route("/searchx/<clip_desc>")
def searchx(clip_desc=None):
    # returns the first clip['url'] that matches the description
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
    except KeyError:
        return "Not able to auth"
    clip = get_clip_with_desc(clip_desc, channel.get("providerId")[0])
    if clip:
        return clip.json()
    return "{}"

@app.route("/extension/clips/<video_id>")
def extension_clips(video_id):
    clips = get_video_clips(video_id)
    return jsonify([clip.json() for clip in clips])


@app.route("/video/<clip_id>")
def video(clip_id):
    if not id:
        return redirect(url_for("slash"))
    global download_lock
    if download_lock:
        return "Disabled for now. We don't have enough resources to serve you at the moment."
    clip = get_clip(clip_id)
    delay = clip.delay
    timestamp = clip.time_in_seconds
    timestamp += -1 * delay
    if not delay:
        delay = -60
    l = [timestamp, timestamp + delay]
    start_time = min(l)
    end_time = max(l)
    return redirect(
        f"{downloader_base_url}/download/{clip.stream_id}/{start_time}/{end_time}"
    )


@ext.register_generator
def index():
    # Not needed if you set SITEMAP_INCLUDE_RULES_WITHOUT_PARAMS=True\
    yield "slash", {}
    with conn:
        cur = conn.cursor()
        cur.execute(f"SELECT channel_id FROM QUERIES ORDER BY time DESC")
        data = cur.fetchall()
    for channel in set([x[0] for x in data]):
        yield "channel_stats", {"channel_id": channel}
        yield "exports", {"channel_id": channel}

    yield "clips", {}
    yield "stats", {}


channel_info = {}
with conn:
    cur = conn.cursor()
    cur.execute(f"SELECT channel_id FROM QUERIES ORDER BY time DESC")
    data = cur.fetchall()


for ch_id in data:
    if local:
        break  # don't build cache on locally running.
    get_channel_name_image(ch_id[0])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80, debug=True)
