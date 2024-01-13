from flask import Flask, request, render_template, redirect, url_for, send_file
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

app = Flask(__name__)

db = sqlite3.connect("queries.db", check_same_thread=False)
cur = db.cursor()
owner_icon = "👑"
mod_icon = "🔧"
regular_icon = "🧑‍🌾"
subscriber_icon = "⭐"
allowed_ip = []  # store the nightbot ips here. or your own ip for testing purpose
cur.execute(
    "CREATE TABLE IF NOT EXISTS QUERIES(channel_id VARCHAR(40), message_id VARCHAR(40), clip_desc VARCHAR(40), time int, time_in_seconds int, user_id VARCHAR(40), user_name VARCHAR(40), stream_link VARCHAR(40), webhook VARCHAR(40), delay int, userlevel VARCHAR(40))"
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
        x["webhook"] = y[8]
        x["delay"] = y[9]
        x[
            "direct_download_link"
        ] = f"http://{request.host}{url_for('video', clip_id=x['id'])}"
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
        management_webhook.content = f"<t:{int(time.time())}:F>"
        management_webhook.execute()
    else:
        print("No management webhook found")
        

def run_scheduled_jobs():
    schedule.run_all() # initially run all the jobs
    while True:
        schedule.run_pending()
        time.sleep(1)


@app.before_request
def before_request():
    # if request is for /clip or /delete or /edit then check if its from real account
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
        ch["link"] = f"http://{request.host}{url_for('exports', channel_id=ch_id[0])}"
        returning.append(ch)
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
    return f"You can download the export from http://{request.host}{url_for('exports', channel_id=channel_id)}"


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
    )


# /clip/<message_id>/<clip_desc>?showlink=true&screenshot=true&dealy=-10
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
        return "No live stream found"
    # only get the previous chat and don't wait for new one
    vid = YouTubeChatDownloader().get_video_data(video_id=vid["videoId"])
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
        message_to_return += f" See all clips at http://{request.host}{url_for('exports', channel_id=channel_id)}"

    # insert the entry to database
    cur.execute(
        "INSERT INTO QUERIES VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        ),
    )
    db.commit()
    if screenshot and webhook_url:
        webhook = DiscordWebhook(
            url=webhook_url,
            username=user_name,
            avatar_url=user_image,
            allowed_mentions={"role": [], "user": [], "everyone": False},
        )
        file_name = take_screenshot(url, clip_time)
        with open(file_name, "rb") as f:
            webhook.add_file(file=f.read(), filename="ss.jpg")
        print(
            f"Sent screenshot to {user_name} from {channel_id} with message -> {clip_desc} {url}"
        )
        webhook.execute()
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
    clip = download_and_store(clip_id)
    if not clip:
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
    return send_file(clip, as_attachment=True)


if __name__ == "__main__":
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

    context = ("/root/certs/cert.pem", "/root/certs/key.pem")
    use_ssl = False
    if all([os.path.exists(x) for x in context]) and use_ssl:
        print("Starting with ssl")
        app.run(host="0.0.0.0", port=5001, ssl_context=context, debug=False)
    else:
        print("Starting without ssl")
        app.run(host="0.0.0.0", port=5001, debug=False)
