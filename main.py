from flask import Flask, request, render_template, redirect, url_for, send_file, session
import dns.resolver, dns.reversename
from bs4 import BeautifulSoup
import subprocess
import schedule
import threading
import os
from json import load, dump
import time
from bs4 import BeautifulSoup
from requests import get
from flask import request
from discord_webhook import DiscordWebhook
import sqlite3
from typing import Optional, Tuple

from urllib.parse import parse_qs
import scrapetube
from chat_downloader.sites import YouTubeChatDownloader
import logging

# we are in /var/www/clip_nighbot
import os
try:
    os.chdir("/var/www/clip_nightbot")
except FileNotFoundError:
    # we are working locally
    pass

logging.basicConfig(
    filename='./record.log', 
    level=logging.DEBUG, 
    format=f'%(asctime)s %(levelname)s %(name)s %(threadName)s : %(message)s'
)


app = Flask(__name__)

global download_lock
download_lock = True
db = sqlite3.connect("queries.db", check_same_thread=False)
cur = db.cursor()
owner_icon = "👑"
mod_icon = "🔧"
regular_icon = "🧑‍🌾"
subscriber_icon = "⭐"
allowed_ip = ["18.191.224.244"]  # store the nightbot ips here. or your own ip for testing purpose
cur.execute(
    "CREATE TABLE IF NOT EXISTS QUERIES(channel_id VARCHAR(40), message_id VARCHAR(40), clip_desc VARCHAR(40), time int, time_in_seconds int, user_id VARCHAR(40), user_name VARCHAR(40), stream_link VARCHAR(40), webhook VARCHAR(40), delay int, userlevel VARCHAR(40), ss_id VARCHAR(40), ss_link VARCHAR(40))"
)
db.commit()
# check if there is a column named webhook in QUERIES table, if not then add it
cur.execute("PRAGMA table_info(QUERIES)")
data = cur.fetchall()
colums = [xp[1] for xp in data]
if "webhook" not in colums:
    cur.execute("ALTER TABLE QUERIES ADD COLUMN webhook VARCHAR(40)")
    db.commit()
    print("Added webhook column to QUERIES table")

if "delay" not in colums:
    cur.execute("ALTER TABLE QUERIES ADD COLUMN delay INT")
    db.commit()
    print("Added delay column to QUERIES table")

if "userlevel" not in colums:
    cur.execute("ALTER TABLE QUERIES ADD COLUMN userlevel VARCHAR(40)")
    db.commit()
    print("Added userlevel column to QUERIES table")

if "ss_id" not in colums:
    cur.execute("ALTER TABLE QUERIES ADD COLUMN ss_id VARCHAR(40)")
    db.commit()
    print("Added ss_id column to QUERIES table")

if "ss_link" not in colums:
    cur.execute("ALTER TABLE QUERIES ADD COLUMN ss_link VARCHAR(40)")
    db.commit()
    print("Added ss_link column to QUERIES table")

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
def create_managment_webhook():
    if not management_webhook_url:
        return None
    wh = DiscordWebhook(
        url=management_webhook_url,
        allowed_mentions={"role": [], "user": [], "everyone": False},
    )
    return wh
if management_webhook_url:
    management_webhook = create_managment_webhook() # we implement this function because we have to recreate this wh again and again to use.
    management_webhook.content = "Bot started"
    try:
        management_webhook.execute()
    except request.exceptions.MissingSchema:
        pass
    management_webhook = create_managment_webhook()

def get_channel_clips(channel_id: str):
    if not channel_id:
        return {}
    cur.execute(f"select * from QUERIES where channel_id=?", (channel_id,))
    data = cur.fetchall()
    l = []    
    for y in data:
        x = {}
        level = y[10]
        if not level:
            level = "everyone"
        x["link"] = y[7]
        x["author"] = {"name": y[6], "id": y[5], "level": level}
        x["clip_time"] = y[
            4
        ]  # time in stream when clip was made. if stream starts at 0
        x["time"] = y[3]  # real life time when clip was made
        x["message"] = y[2]
        x["stream_id"] = y[7].replace("https://youtu.be/", "").split("?")[0]
        x["dt"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.localtime(y[3]))
        x["hms"] = time_to_hms(y[4])
        x["id"] = y[1][-3:] + str(int(y[4]))
        x["delay"] = y[9]
        if request.is_secure:
            htt = "https://"
        else:
            htt = "http://"
        x[
            "direct_download_link"
        ] = f"{htt}{request.host}{url_for('video', clip_id=x['id'])}"
        x["discord"] ={
            "webhook": y[8],
            "ss_id": y[11],
            "ss_link": y[12]
        }
        l.append(x)
    l.reverse()
    return l


def time_to_hms(seconds: int):
    hour = int(seconds / 3600)
    minute = int(seconds / 60) % 60
    second = int(seconds) % 60
    if hour < 10:
        hour = f"0{hour}"
    if minute < 10:
        minute = f"0{minute}"
    if second < 10:
        second = f"0{second}"
    if int(hour):
        hour_minute_second = f"{hour}:{minute}:{second}"
    else:
        hour_minute_second = f"{minute}:{second}"
    return hour_minute_second


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
    channel_link = f"https://youtube.com/channel/{channel_id}"
    html_data = get(channel_link).text
    soup = BeautifulSoup(html_data, "html.parser")
    channel_image = soup.find("meta", property="og:image")["content"]
    channel_name = soup.find("meta", property="og:title")["content"]
    return channel_name, channel_image


def take_screenshot(video_url: str, seconds: int):
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


def get_webhook_url(channel_id):
    with open("creds.json", "r") as f:
        creds = load(f)

    try:
        webhook_url = creds[channel_id]
    except KeyError:
        return None
    return webhook_url


def get_clip_with_desc(clip_desc: str, channel_id: str) -> Optional[dict]:
    clips = get_channel_clips(channel_id)
    for clip in clips:
        if clip_desc.lower() in clip["message"].lower():
            return clip
    return None


def download_and_store(clip_id):
    data = cur.execute(
        "SELECT * FROM QUERIES WHERE  message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
        (f"%{clip_id[:3]}", int(clip_id[3:]) - 1, int(clip_id[3:]) + 1),
    )
    data = cur.fetchall()
    if not data:
        return None
    video_url = data[0][7]
    timestamp = data[0][4]
    output_filename = f"./clips/{clip_id}"
    # if there is a file that start with that clip in current directory then don't download it
    files = [
        os.path.join("clips", x) for x in os.listdir("./clips") if x.startswith(clip_id)
    ]
    if files:
        return files[0]
    # real thing happened at 50. but we stored timestamp with delay. take back that delay
    delay = data[0][9]
    timestamp += -1 * delay
    if not delay:
        delay = -60
    l = [timestamp, timestamp + delay]
    start_time = min(l)
    end_time = max(l)

    start_time = time_to_hms(start_time)
    end_time = time_to_hms(end_time)
    params = [
        "yt-dlp",
        "--output",
        f"{output_filename}",
        "--download-sections",
        f"*{start_time}-{end_time}",
        "--quiet",
        "--no-warnings",
        "--match-filter",
        "!is_live & live_status!=is_upcoming & availability=public",
        video_url,
    ]
    current_time = time.time()
    try:
        subprocess.run(params, check=True, timeout=60)
    except subprocess.TimeoutExpired as e:
        pass
    except subprocess.CalledProcessError as e:
        return None
    print("Completed the process in ", time.time() - current_time)
    files = [
        os.path.join("clips", x) for x in os.listdir("./clips") if x.startswith(clip_id)
    ]
    if files:
        return files[0]

def periodic_task():
    if management_webhook_url:
        management_webhook = create_managment_webhook()
        management_webhook.add_file(file=open("queries.db", "rb"), filename="queries.db")
        management_webhook.add_file(file=open("record.log", "rb"), filename="record.log")
        management_webhook.content = f"<t:{int(time.time())}:F>"
        try:
            management_webhook.execute()
        except request.exceptions.MissingSchema:
            print("Invalid webhook url")
            return
    else:
        print("No management webhook found")
        

def run_scheduled_jobs():
    while True:
        schedule.run_pending()
        time.sleep(1)


@app.before_request
def before_request():
    # if request is for /clip or /delete or /edit then check if its from real 
    if "/clip" in request.path or "/delete" in request.path or "/edit" in request.path:
        ip = request.remote_addr
        if ip in allowed_ip:
            print(f"Request from {ip} is allowed, known ip")
            return
        addrs = dns.reversename.from_address(ip)
        try:
            if not str(dns.resolver.resolve(addrs, "PTR")[0]).endswith(
                ".nightbot.net."
            ):
                raise ValueError("Not a nightbot request")
            else:
                print(f"Request from {ip} is allowed")
                allowed_ip.append(ip)
        except Exception as e:
            print(e)
            return "Not able to auth"
    else:
        pass


@app.route("/")
def slash():
    # this offload the load from every slash request to only the time when the script is initially ran
    cur.execute(f"SELECT channel_id FROM QUERIES ORDER BY time DESC")
    data = cur.fetchall()
    returning = []
    known_channels = []
    for ch_id in data:
        ch = {}
        if ch_id[0] in known_channels:
            continue
        known_channels.append(ch_id[0])
        if ch_id[0] in channel_info:
            ch["image"] = channel_info[ch_id[0]]["image"]
            ch["name"] = channel_info[ch_id[0]]["name"]
        else:
            channel_name, channel_image = get_channel_name_image(ch_id[0])
            ch["image"] = channel_image
            ch["name"] = channel_name
            channel_info[ch_id[0]] = {}
            channel_info[ch_id[0]]["name"] = channel_name
            channel_info[ch_id[0]]["image"] = channel_image
        ch["id"] = ch_id[0]
        if request.is_secure:
            htt = "https://"
        else:
            htt = "http://"
        ch["link"] = f"{htt}{request.host}{url_for('exports', channel_id=ch_id[0])}"
        returning.append(ch)
    """
    for ch in returning:
        ch["clips"] = get_channel_clips(ch["id"])
    NOT A GOOD IDEA. THIS WILL MAKE THE PAGE LOAD SLOWLY. rather show that on admin page.
    """
    return render_template("home.html", data=returning)


@app.route("/ip")
def get_ip():
    return request.remote_addr


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
    return f"You can download the export from {htt}{request.host}{url_for('exports', channel_id=channel_id)}"


@app.route("/exports/<channel_id>")
@app.route("/e/<channel_id>")
def exports(channel_id=None):
    if not channel_id:
        return redirect(url_for("slash"))

    channel_link = f"https://youtube.com/channel/{channel_id}"
    html_data = get(channel_link).text
    soup = BeautifulSoup(html_data, "html.parser")
    try:
        channel_name, channel_image = get_channel_name_image(channel_id)
    except TypeError:
        return redirect(
            url_for("slash")
        )  # if channel is not found then redirect to home page
    data = get_channel_clips(channel_id)
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
        channel_id=channel_id
    )

@app.route("/channelstats/<channel_id>")
@app.route("/cs/<channel_id>")
@app.route("/channelstats")
def channel_stats(channel_id=None):
    if not channel_id:
        return redirect(url_for("slash"))
    cur.execute("SELECT * FROM QUERIES WHERE channel_id=?", (channel_id,))
    data = cur.fetchall()
    if not data:
        return redirect(url_for("slash"))
    clip_count = len(data)
    user_count = len(set([x[5] for x in data]))
    # "Name": no of clips
    user_clips = {}
    for x in data:
        if x[5] not in user_clips:
            user_clips[x[5]] = 0
        user_clips[x[5]] += 1
    # sort
    user_clips = {k: v for k, v in sorted(user_clips.items(), key=lambda item: item[1], reverse=True)}
    new_dict = {}
    # replace dict_keys with actual channel
    max_count = 0
    try:
        streamer_name, streamer_image = channel_info[channel_id]["name"], channel_info[channel_id]["image"]
    except KeyError:
        streamer_name, streamer_image = get_channel_name_image(channel_id)
        channel_info[channel_id] = {}
        channel_info[channel_id]["name"] = streamer_name
        channel_info[channel_id]["image"] = streamer_image

    # sort and get k top clippers
    user_clips={k: v for k, v in sorted(user_clips.items(), key=lambda item: item[1], reverse=True)}
    for k, v in user_clips.items():
        max_count += 1
        if max_count > 12:
            break
        if k in channel_info:
            new_dict[channel_info[k]["name"]] = v
        else:
            channel_name, image = get_channel_name_image(k)
            new_dict[channel_name] = v
            channel_info[k] = {}
            channel_info[k]["name"] = channel_name
            channel_info[k]["image"] = image
    new_dict['Others'] = sum(list(user_clips.values())[max_count:])
    user_clips = new_dict

    top_clippers = {}
    for x in data:
        if x[5] not in top_clippers:
            top_clippers[x[5]] = 0
        top_clippers[x[5]] += 1
    top_clippers = {k: v for k, v in sorted(top_clippers.items(), key=lambda item: item[1], reverse=True)}
    new = []
    count = 0
    for k, v in top_clippers.items():
        count += 1
        if count > 12:
            break
        if k in channel_info:
            new.append({
                "name": channel_info[k]["name"],
                "image": channel_info[k]["image"],
                "count": v,
                "link": f"https://youtube.com/channel/{k}",
                "otherlink": url_for("user_stats", channel_id=k)
            })
        else:
            channel_name, image = get_channel_name_image(k)
            new.append({
                "name": channel_name,
                "image": image,
                "count": v,
                "link": f"https://youtube.com/channel/{k}",
                "otherlink": url_for("user_stats", channel_id=k)
            })
            channel_info[k] = {}
            channel_info[k]["name"] = channel_name
            channel_info[k]["image"] = image
    top_clippers = new
    new_dict = {}
    # time trend
    # day : no_of_clips
    for clip in data:
        day = time.strftime("%Y-%m-%d", time.localtime(clip[3]))
        if day not in new_dict:
            new_dict[day] = 0
        new_dict[day] += 1
    time_trend = new_dict

    streamer_trend_data = {}
    # "clipper" : {day: no_of_clips}
    streamers_trend_days = []
    max_count = 0
    for clip in data:
        day = time.strftime("%Y-%m-%d", time.localtime(clip[3]))
        if clip[5] not in streamer_trend_data:
            streamer_trend_data[clip[5]] = {}
        if day not in streamer_trend_data[clip[5]]:
            streamer_trend_data[clip[5]][day] = 0
        streamer_trend_data[clip[5]][day] += 1
        if day not in streamers_trend_days:
            streamers_trend_days.append(day)
    streamers_trend_days.sort()
    # replace channel id with channel name
    new_dict = {}
    known_k = []
    max_count = 0
    # sort
    streamer_trend_data={k: v for k, v in sorted(streamer_trend_data.items(), key=lambda item: sum(item[1].values()), reverse=True)}
    for k, v in streamer_trend_data.items():
        max_count += 1
        if max_count > 12:
            break
        if k in channel_info:
            new_dict[channel_info[k]["name"]] = v
        else:
            channel_name, image = get_channel_name_image(k)
            new_dict[channel_name] = v
            channel_info[k] = {}
            channel_info[k]["name"] = channel_name
            channel_info[k]["image"] = image
        known_k.append(k)
    new_dict['Others'] = {}
    for k, v in streamer_trend_data.items():
        if k in known_k:
            continue
        for day, count in v.items():
            if day not in new_dict['Others']:
                new_dict['Others'][day] = 0
            new_dict['Others'][day] += count
    streamer_trend_data = new_dict
    time_distribution = {}
    for x in range(24):
        time = x
        if time < 10:
            time = f"0{time}"
        time_distribution[str(x)] = 0
    for clip in data:
        hm = time.strftime("%H", time.localtime(clip[3]))
        if hm not in time_distribution:
            time_distribution[hm] = 0
        time_distribution[hm] += 1
    message = f"Channel Stats for {streamer_name}. {user_count} users clipped\n{clip_count} clips till now. \nand counting."
    return render_template(
        "stats.html",
        message = message,
        clip_count=clip_count,
        user_count=user_count,
        clip_users=[(k, v) for k, v in user_clips.items()],
        top_clippers=top_clippers,
        channel_count = len(user_clips),
        times= list(time_trend.keys()),
        counts= list(time_trend.values()),
        streamer_trend_data=streamer_trend_data,
        streamers_trend_days=streamers_trend_days,
        streamers_labels = list(streamer_trend_data.keys()),
        time_distribution = time_distribution,
        channel_name=streamer_name,
        channel_image=streamer_image
        )


@app.route("/userstats/<channel_id>")
@app.route("/us/<channel_id>")
@app.route("/userstats")
def user_stats(channel_id=None):
    if not channel_id:
        return redirect(url_for("slash"))
    cur.execute("SELECT * FROM QUERIES WHERE user_id=?", (channel_id,))
    data = cur.fetchall()
    if not data:
        return redirect(url_for("slash"))
    clip_count = len(data)
    user_count = len(set([x[0] for x in data]))
    # "Name": no of clips
    user_clips = {}
    for x in data:
        if x[0] not in user_clips:
            user_clips[x[0]] = 0
        user_clips[x[0]] += 1
    # sort
    user_clips = {k: v for k, v in sorted(user_clips.items(), key=lambda item: item[1], reverse=True)}
    new_dict = {}
    # replace dict_keys with actual channel
    max_count = 0
    try:
        streamer_name, streamer_image = channel_info[channel_id]["name"], channel_info[channel_id]["image"]
    except KeyError:
        streamer_name, streamer_image = get_channel_name_image(channel_id)
        channel_info[channel_id] = {}
        channel_info[channel_id]["name"] = streamer_name
        channel_info[channel_id]["image"] = streamer_image

    # sort and get k top clippers
    user_clips={k: v for k, v in sorted(user_clips.items(), key=lambda item: item[1], reverse=True)}
    for k, v in user_clips.items():
        max_count += 1
        if max_count > 12:
            break
        if k in channel_info:
            new_dict[channel_info[k]["name"]] = v
        else:
            channel_name, image = get_channel_name_image(k)
            new_dict[channel_name] = v
            channel_info[k] = {}
            channel_info[k]["name"] = channel_name
            channel_info[k]["image"] = image
    new_dict['Others'] = sum(list(user_clips.values())[max_count:])
    user_clips = new_dict

    top_clippers = {}
    for x in data:
        if x[0] not in top_clippers:
            top_clippers[x[0]] = 0
        top_clippers[x[0]] += 1
    top_clippers = {k: v for k, v in sorted(top_clippers.items(), key=lambda item: item[1], reverse=True)}
    new = []
    count = 0
    for k, v in top_clippers.items():
        count += 1
        if count > 12:
            break
        if k in channel_info:
            new.append({
                "name": channel_info[k]["name"],
                "image": channel_info[k]["image"],
                "count": v,
                "link": f"https://youtube.com/channel/{k}",
                "otherlink": url_for("channel_stats", channel_id=k)
            })
        else:
            channel_name, image = get_channel_name_image(k)
            new.append({
                "name": channel_name,
                "image": image,
                "count": v,
                "link": f"https://youtube.com/channel/{k}",
                "otherlink": url_for("channel_stats", channel_id=k)
            })
            channel_info[k] = {}
            channel_info[k]["name"] = channel_name
            channel_info[k]["image"] = image
    top_clippers = new
    new_dict = {}
    # time trend
    # day : no_of_clips
    for clip in data:
        day = time.strftime("%Y-%m-%d", time.localtime(clip[3]))
        if day not in new_dict:
            new_dict[day] = 0
        new_dict[day] += 1
    time_trend = new_dict

    streamer_trend_data = {}
    # "clipper" : {day: no_of_clips}
    streamers_trend_days = []
    max_count = 0
    for clip in data:
        day = time.strftime("%Y-%m-%d", time.localtime(clip[3]))
        if clip[0] not in streamer_trend_data:
            streamer_trend_data[clip[0]] = {}
        if day not in streamer_trend_data[clip[0]]:
            streamer_trend_data[clip[0]][day] = 0
        streamer_trend_data[clip[0]][day] += 1
        if day not in streamers_trend_days:
            streamers_trend_days.append(day)
    streamers_trend_days.sort()
    # replace channel id with channel name
    new_dict = {}
    known_k = []
    max_count = 0
    # sort
    streamer_trend_data={k: v for k, v in sorted(streamer_trend_data.items(), key=lambda item: sum(item[1].values()), reverse=True)}
    for k, v in streamer_trend_data.items():
        max_count += 1
        if max_count > 12:
            break
        if k in channel_info:
            new_dict[channel_info[k]["name"]] = v
        else:
            channel_name, image = get_channel_name_image(k)
            new_dict[channel_name] = v
            channel_info[k] = {}
            channel_info[k]["name"] = channel_name
            channel_info[k]["image"] = image
        known_k.append(k)
    new_dict['Others'] = {}
    for k, v in streamer_trend_data.items():
        if k in known_k:
            continue
        for day, count in v.items():
            if day not in new_dict['Others']:
                new_dict['Others'][day] = 0
            new_dict['Others'][day] += count
    streamer_trend_data = new_dict
    time_distribution = {}
    for x in range(24):
        time_distribution[str(x)] = 0
    for clip in data:
        hm = time.strftime("%H", time.localtime(clip[3]))
        if hm not in time_distribution:
            time_distribution[hm] = 0
        time_distribution[hm] += 1
    message = f"User Stats for {streamer_name}. Clipped\n{clip_count} clips in {user_count} channels till now. and counting."
    return render_template(
        "stats.html",
        message = message,
        clip_count=clip_count,
        user_count=user_count,
        clip_users=[(k, v) for k, v in user_clips.items()],
        top_clippers=top_clippers,
        channel_count = len(user_clips),
        times= list(time_trend.keys()),
        counts= list(time_trend.values()),
        streamer_trend_data=streamer_trend_data,
        streamers_trend_days=streamers_trend_days,
        streamers_labels = list(streamer_trend_data.keys()),
        time_distribution = time_distribution,
        channel_name=streamer_name,
        channel_image=streamer_image
        )
@app.route("/stats")
def stats():
    # get clips
    cur.execute("SELECT * FROM QUERIES")
    data = cur.fetchall()
    clip_count = len(data)
    user_count = len(set([x[5] for x in data]))
    # "Name": no of clips
    user_clips = {}
    for x in data:
        if x[0] not in user_clips:
            user_clips[x[0]] = 0
        user_clips[x[0]] += 1
    # sort
    user_clips = {k: v for k, v in sorted(user_clips.items(), key=lambda item: item[1], reverse=True)}
    # replace dict_keys with actual channel
    new_dict = {}   
    for k, v in user_clips.items():
        if k in channel_info:
            new_dict[channel_info[k]["name"]] = v
        else:
            channel_name, image = get_channel_name_image(k)
            new_dict[channel_name] = v
            channel_info[k] = {}
            channel_info[k]["name"] = channel_name
            channel_info[k]["image"] = image
    user_clips = new_dict

    top_clippers = {}
    for x in data:
        if x[5] not in top_clippers:
            top_clippers[x[5]] = 0
        top_clippers[x[5]] += 1
    top_clippers = {k: v for k, v in sorted(top_clippers.items(), key=lambda item: item[1], reverse=True)}
    new = []
    count = 0
    for k, v in top_clippers.items():
        count += 1
        if count > 12:
            break
        if k in channel_info:
            new.append({
                "name": channel_info[k]["name"],
                "image": channel_info[k]["image"],
                "count": v,
                "link": f"https://youtube.com/channel/{k}",
                "otherlink": url_for("user_stats", channel_id=k)
            })
        else:
            channel_name, image = get_channel_name_image(k)
            new.append({
                "name": channel_name,
                "image": image,
                "count": v,
                "link": f"https://youtube.com/channel/{k}",
                "otherlink": url_for("user_stats", channel_id=k)
            })
            channel_info[k] = {}
            channel_info[k]["name"] = channel_name
            channel_info[k]["image"] = image
    top_clippers = new
    new_dict = {}
    # time trend 
    # day : no_of_clips
    for clip in data:
        day = time.strftime("%Y-%m-%d", time.localtime(clip[3]))
        if day not in new_dict:
            new_dict[day] = 0
        new_dict[day] += 1
    time_trend = new_dict

    streamer_trend_data = {}
    # streamer: {day: no_of_clips}
    streamers_trend_days = []
    for clip in data:
        day = time.strftime("%Y-%m-%d", time.localtime(clip[3]))
        if clip[0] not in streamer_trend_data:
            streamer_trend_data[clip[0]] = {}
        if day not in streamer_trend_data[clip[0]]:
            streamer_trend_data[clip[0]][day] = 0
        streamer_trend_data[clip[0]][day] += 1
        if day not in streamers_trend_days:
            streamers_trend_days.append(day)
    streamers_trend_days.sort()
    # replace channel id with channel name
    new_dict = {}
    for k, v in streamer_trend_data.items():
        if k in channel_info:
            new_dict[channel_info[k]["name"]] = v
        else:
            channel_name, image = get_channel_name_image(k)
            new_dict[channel_name] = v
            channel_info[k] = {}
            channel_info[k]["name"] = channel_name
            channel_info[k]["image"] = image
    streamer_trend_data = new_dict
    time_distribution = {}
    for x in range(24):
        time_distribution[str(x)] = 0
    for clip in data:
        hm = time.strftime("%H", time.localtime(clip[3]))
        if hm not in time_distribution:
            time_distribution[hm] = 0
        time_distribution[hm] += 1
    message = f"{user_count} users clipped\n{clip_count} clips on \n{len(user_clips)} channels till now. \nand counting."
    return render_template(
        "stats.html", 
        message = message,
        clip_count=clip_count, 
        user_count=user_count, 
        clip_users=[(k, v) for k, v in user_clips.items()],
        top_clippers=top_clippers,
        channel_count = len(user_clips),
        times= list(time_trend.keys()),
        counts= list(time_trend.values()),
        streamer_trend_data=streamer_trend_data,
        streamers_trend_days=streamers_trend_days,
        streamers_labels = list(streamer_trend_data.keys()),
        time_distribution = time_distribution,
        channel_name="All channels",
        channel_image="/static/logo.svg"
        )

@app.route("/admin")
def admin():
    clip_ids = []
    cur.execute("SELECT * FROM QUERIES")
    data = cur.fetchall()
    for clip in data:
        clip_id = clip[1][-3:] + str(int(clip[4]))
        clip_ids.append(clip_id)
    clip_ids.sort()
    clip_ids.reverse()
    channels = []
    cur.execute("SELECT channel_id FROM QUERIES")
    data = cur.fetchall()
    for x in data:
        if x[0] not in channels:
            channels.append(x[0])
    data = {}
    for channel in channels:
        data[channel] = get_channel_clips(channel)
    return render_template("admin.html", ids=clip_ids, data=data)

@app.route("/ed", methods=["POST"])
def edit_delete():
    actual_password = get_webhook_url("password") # i know this is not a good way to store password. but i am too lazy to implement a proper login system
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
        data = cur.execute(
            "SELECT * FROM QUERIES WHERE  message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
            (f"%{clip_id[:3]}", int(clip_id[3:]) - 1, int(clip_id[3:]) + 1),
        )
        data = cur.fetchall()
        if not data:
            return "Clip not found"
        old_name = data[0][2]
        cur.execute(
            "UPDATE QUERIES SET clip_desc=? WHERE message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
            (
                new_name,
                f"%{clip_id[:3]}",
                int(clip_id[3:]) - 1,
                int(clip_id[3:]) + 1,
            ),
        )
        db.commit()
        webhook_url = get_webhook_url(data[0][0])
        if webhook_url:
            hms = time_to_hms(int(data[0][4]))
            new_message = f"{clip_id} | **{new_name}** \n\n{hms}\n<{data[0][7]}>"
            if data[0][9]:
                new_message += f"\nDelayed by {data[0][9]} seconds."
            webhook = DiscordWebhook(
                url=webhook_url,
                id=data[0][8],
                allowed_mentions={"role": [], "user": [], "everyone": False},
                content=new_message,
            )
            try:
                webhook.edit()
            except Exception as e:
                print(e)
                pass
        return f"Edited clip ID {clip_id} from '{old_name}' to '{new_name}'."
    elif request.form.get("delete") == "Delete":
        if not request.form.get("clip", None):
            return "No Clip selected"
        # delete the clip
        data = cur.execute(
            "SELECT * FROM QUERIES WHERE  message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
            (f"%{clip_id[:3]}", int(clip_id[3:]) - 1, int(clip_id[3:]) + 1),
        )
        data = cur.fetchall()
        if not data:
            return "Clip not found"
        cur.execute(
            "DELETE FROM QUERIES WHERE  message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
            (f"%{clip_id[:3]}", int(clip_id[3:]) - 1, int(clip_id[3:]) + 1),
        )
        db.commit()
        webhook_url = get_webhook_url(data[0][0])
        if webhook_url:
            webhook = DiscordWebhook(
                url=webhook_url,
                id=data[0][8],
                allowed_mentions={"role": [], "user": [], "everyone": False},
            )
            try:
                webhook.delete()
            except:
                pass
            if data[0][11]: # if there is a screenshot then delete that too
                webhook = DiscordWebhook(
                    url=webhook_url,
                    id=data[0][11],
                    allowed_mentions={"role": [], "user": [], "everyone": False},
                )
                try:
                    webhook.delete()
                except:
                    pass
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
        return "Added"
    else:
        return "what ?"
    
    

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
    uptime = current_time - start_time
    uptime = time_to_hms(uptime)
    return f"Stream uptime is {uptime}"

@app.route("/stream_info")
def stream_info():
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
        user = parse_qs(request.headers["Nightbot-User"])
    except KeyError:
        return "Not able to auth"
    channel_id = channel.get("providerId")[0]
    return get_latest_live(channel_id)

# /clip/<message_id>/<clip_desc>?showlink=true&screenshot=true&dealy=-10&silent=2
@app.route("/clip/<message_id>/")
@app.route("/clip/<message_id>/<clip_desc>")
def clip(message_id, clip_desc=None):
    show_link = request.args.get("showlink", True)
    screenshot = request.args.get("screenshot", False)
    silent = request.args.get("silent", 2) # silent level. if not then 2
    try:
        silent = int(silent)
    except ValueError:
        silent = 2
    delay = request.args.get("delay", 0)
    show_link = False if show_link == "false" else True
    screenshot = True if screenshot == "true" else False
    try:
        delay = 0 if not delay else int(delay)
    except ValueError:
        return "Delay should be an integer (plus or minus)"
    request_time = time.time()
    if not message_id:
        return "No message id provided, You have configured it wrong. please contact AG at https://discord.gg/2XVBWK99Vy"
    if not clip_desc:
        clip_desc = "None"
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
        user = parse_qs(request.headers["Nightbot-User"])
        user_id = user.get("providerId")[0]
        user_level = user.get("userLevel")[0]
        channel_id = channel.get("providerId")[0]    
    except KeyError:
        # Streamlabs doesn't give headers. we assume 
        # that it is passed as argument instead
        # in this case we don't get message_id. store it as None
        message_id = None
        channel_id = request.args.get("channel_id", None)
        user_id = request.args.get("user_id", None)
        if not any([channel_id, user_id]):
            return "Not able to auth"
        channel = {"providerId": [channel_id]}
        user = {"providerId": [user_id]}
        user_level = "everyone"
    user_name, user_image = get_channel_name_image(user_id) # we are calling this regardless.
    webhook_url = get_webhook_url(channel_id)


    user_level = user.get("userLevel")[0]
    user_id = user.get("providerId")[0]
    user_name = user.get("displayName")[0]
    vid = get_latest_live(channel_id)
    clip_time = request_time - vid["start_time"] / 1000000 + 5 
    clip_time += delay
    url = "https://youtu.be/" + vid["original_video_id"] + "?t=" + str(int(clip_time))
    clip_id = message_id[-3:] + str(int(clip_time))

    # if clip_time is in seconds. then hh:mm:ss format would be like
    hour_minute_second = time_to_hms(clip_time)
    message_cc_webhook = (
        f"{clip_id} | **{clip_desc}** \n\n{hour_minute_second} \n<{url}>"
    )
    if delay:
        message_cc_webhook += f"\nDelayed by {delay} seconds."
    webhook_name = user_name
    if user_level == "owner":
        webhook_name += f" {owner_icon}"
    elif user_level == "moderator":
        webhook_name += f" {mod_icon}"
    elif user_level == "regular":
        webhook_name += f" {regular_icon}"
    elif user_level == "subscriber":
        webhook_name += f" {subscriber_icon}"

    message_to_return = f"Clip {clip_id} by {user_name} -> '{clip_desc[:32]}' Clipped at {hour_minute_second}"
    if delay:
        message_to_return += f" Delayed by {delay} seconds."
    if webhook_url:  # if webhook is not found then don't send the message
        message_to_return += " | sent to discord."
        webhook = DiscordWebhook(
            url=webhook_url,
            content=message_cc_webhook,
            username=webhook_name,
            avatar_url=user_image,
            allowed_mentions={"role": [], "user": [], "everyone": False},
        )
        webhook.execute()
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
        print(
            f"Sent screenshot to {user_name} from {channel_id} with message -> {clip_desc} {url}"
        )
        webhook.execute()
        ss_id = webhook.id
        ss_link = webhook.attachments[0]['url']
        # remove attribute from ss_link
        ss_link = ss_link.split("?")[0]
        
    else:
        ss_id = None
        ss_link = None
    # insert the entry to database
    cur.execute(
        "INSERT INTO QUERIES VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            ss_link
        ),
    )
    db.commit()

    if silent == 2:
        return message_to_return
    elif silent == 1:
        return clip_id
    else:
        return " "


@app.route("/delete/<clip_id>")
def delete(clip_id=None):
    if not clip_id:
        print("No Clip ID provided")
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
    except KeyError:
        return "Not able to auth"
    try:
        tis = int(clip_id[3:])
    except ValueError:
        return "Clip ID should be in format of 3 characters + time in seconds"
    channel_id = channel.get("providerId")[0]
    # an id is last 3 characters of message_id + time_in_seconds
    # get previous description
    cur.execute(
        "SELECT * FROM QUERIES WHERE channel_id=? AND message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
        (channel_id, f"%{clip_id[:3]}", tis - 1, tis + 1),
    )
    data = cur.fetchall()
    if not data:
        return "Clip ID not found"
    cur.execute(
        "DELETE FROM QUERIES WHERE channel_id=? AND message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
        (channel_id, f"%{clip_id[:3]}", tis - 1, tis + 1),
    )
    db.commit()
    webhook_url = get_webhook_url(channel_id)
    if webhook_url:
        webhook = DiscordWebhook(
            url=webhook_url,
            id=data[0][8],
            allowed_mentions={"role": [], "user": [], "everyone": False},
        )
        try:
            webhook.delete()
        except:
            pass
        if data[0][11]: # if there is a screenshot then delete that too
            webhook = DiscordWebhook(
                url=webhook_url,
                id=data[0][11],
                allowed_mentions={"role": [], "user": [], "everyone": False},
            )
            try:
                webhook.delete()
            except:
                pass

    return f"Deleted clip ID {clip_id}."


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
    clip_id = xxx.split(" ")[0]
    new_desc = " ".join(xxx.split(" ")[1:])

    channel_id = channel.get("providerId")[0]
    # an id is last 3 characters of message_id + time_in_seconds
    # get previous description
    try:
        cur.execute(
            "SELECT * FROM QUERIES WHERE channel_id=? AND message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
            (channel_id, f"%{clip_id[:3]}", int(clip_id[3:]) - 1, int(clip_id[3:]) + 1),
        )
    except ValueError:
        return "Clip ID should be in format of 3 characters + time in seconds"
    data = cur.fetchall()
    if not data:
        return "Clip ID not found"
    old_desc = data[0][2]
    cur.execute(
        "UPDATE QUERIES SET clip_desc=? WHERE channel_id=? AND message_id LIKE ? AND time_in_seconds >= ? AND time_in_seconds < ?",
        (
            new_desc,
            channel_id,
            f"%{clip_id[:3]}",
            int(clip_id[3:]) - 1,
            int(clip_id[3:]) + 1,
        ),
    )
    db.commit()
    webhook_url = get_webhook_url(channel_id)
    if webhook_url:
        hms = time_to_hms(int(data[0][4]))
        new_message = f"{clip_id} | **{new_desc}** \n\n{hms}\n<{data[0][7]}>"
        if data[0][9]:
            new_message += f"\nDelayed by {data[0][9]} seconds."
        webhook = DiscordWebhook(
            url=webhook_url,
            id=data[0][8],
            allowed_mentions={"role": [], "user": [], "everyone": False},
            content=new_message,
        )
        try:
            webhook.edit()
        except Exception as e:
            print(e)
            pass
    return f"Edited clip ID {clip_id} from '{old_desc}' to '{new_desc}'."


@app.route("/search/<clip_desc>")
def search(clip_desc=None):
    # returns the first clip['url'] that matches the description
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
    except KeyError:
        return "Not able to auth"
    clip = get_clip_with_desc(clip_desc, channel.get("providerId")[0])
    if clip:
        return clip["link"]
    return "Clip not found"


@app.route("/searchx/<clip_desc>")
def searchx(clip_desc=None):
    # returns the first clip['url'] that matches the description
    try:
        channel = parse_qs(request.headers["Nightbot-Channel"])
    except KeyError:
        return "Not able to auth"
    clip = get_clip_with_desc(clip_desc, channel.get("providerId")[0])
    if clip:
        return clip
    return "{}"


@app.route("/video/<clip_id>")
def video(clip_id):
    if not id:
        return redirect(url_for("slash"))
    global download_lock
    if download_lock:
        return "Disabled for now. We don't have enough resources to serve you at the moment."
    download_lock = True
    clip = download_and_store(clip_id)
    if not clip:
        download_lock = False
        return "Seems like you are trying to download a clip that is currently live. we currently doesn't support that."
    if ".part" in clip:
        # rename to mp4
        while True:
            try:
                os.rename(clip, clip.replace(".part", ".mp4"))
                break
            except:
                pass
        clip = clip.replace(".part", ".mp4")
    if "." not in clip:
        # reaname it to mp4
        while True:
            try:
                os.rename(clip, clip + ".mp4")
                break
            except:
                pass
        clip += ".mp4"
    download_lock = False
    return send_file(clip, as_attachment=True)

schedule.every(10).minutes.do(periodic_task)
scheduler_thread = threading.Thread(target=run_scheduled_jobs)
scheduler_thread.start()


channel_info = {}
cur.execute(f"SELECT channel_id FROM QUERIES ORDER BY time DESC")
data = cur.fetchall()


for ch_id in data:
    if ch_id[0] in channel_info:
        continue
    channel_info[ch_id[0]] = {}
    (
        channel_info[ch_id[0]]["name"],
        channel_info[ch_id[0]]["image"],
    ) = get_channel_name_image(ch_id[0])
    """
    context = ("/root/certs/cert.pem", "/root/certs/key.pem")
    try:
        app.run(host="0.0.0.0", port=443, ssl_context=context, debug=False)
    except FileNotFoundError:
        print("No certs found. running without ssl")
    app.run(host="0.0.0.0", port=80, debug=True)
    """