# Clip_Nightbot: Stream Clipping Simplified

The primary goal of Clip_Nightbot is to streamline the clipping process, addressing challenges faced by one of my favorite streamers. Here's how you can make the most of it:
## Monetization
This program is a free for small streamers (have less than 40 viewers) and for selected people. </br>
<a href="https://surajbhari.stck.me" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a> </br>
Most of the donations goes back to development and hosting costing. 
## Nightbot Command:

```markdown
!addcom !clip $(urlfetch https://streamsnip.com/clip/$(chatid)/$(querystring))
```
Just adding this command will get you started. but if you want to have a discord message. or customization then read below.

If you want to send a discord message. then I would need to add a webhook URL alongside the youtube channel ID. for that contact me here.<br>
![Discord Badge](https://dcbadge.vercel.app/api/shield/408994955147870208) </br>
[![Server Badge](https://dcbadge.vercel.app/api/server/2XVBWK99Vy)](https://discord.gg/2XVBWK99Vy)


## Optional Arguments:

- `showlink` (default: true) - Display the link where all clips can be viewed.
- `screenshot` (default: false) - Enable or disable screenshot capture. If enabled the nightbot may not get response in given time and will say "Timed out" message. but it will still clip.
- `delay` (default: 0) - Introduce an artificial delay to the command. Useful for scheduling links in the future or past.
- `silent` (default: 2||Highest) - Level of the clipping message. see example below. </br> 
  ![image](https://github.com/SurajBhari/clip_nightbot/assets/45149585/1010c32e-ad75-4a75-b732-9e3b2ddc6d44)


### Examples:

- `https://streamsnip.com/clip/$(chatid)/$(querystring)?showlink=false&screenshot=false` - No links, no screenshots.
- `https://streamsnip.com/clip/$(chatid)/$(querystring)?showlink=false` - No links, but with screenshots.
- `https://streamsnip.com/clip/$(chatid)/$(querystring)?screenshot=false` - Links provided, no screenshots.
- `https://streamsnip.com/clip/$(chatid)/$(querystring)?delay=-20` - Set a delay in the past by 20 seconds.

## Other Commands
1. `!delete <clip_id>` - delete the given clip
```markdown
!addcom !delete $(urlfetch https://streamsnip.com/delete/$(query)) -ul=moderator
```
⚠️ don't remove the `-ul=moderator` part, otherwise anyone can delete your clips. </br>
![image](https://github.com/SurajBhari/clip_nightbot/assets/45149585/35d174c8-5f3f-4bb8-a6f7-15fc59ee0c43) </br>


2. `!edit <clip_id> <new_title>` - edit the title of the given clip
```markdown
!addcom !edit $(urlfetch https://streamsnip.com/edit/$(querystring)) -ul=moderator
```
⚠️ don't remove the `-ul=moderator` part, otherwise anyone can edit your clips. </br>
![image](https://github.com/SurajBhari/clip_nightbot/assets/45149585/f76e4bc6-dc20-4fa1-b58a-e237b4f7ba8f) </br>


3. `!clips` or `!export` - gives link where you can see all the clips 
```markdown
!addcom !export $(urlfetch https://streamsnip.com/export)
```
![image](https://github.com/SurajBhari/clip_nightbot/assets/45149585/2be98062-d9f7-4e91-879f-e940ad0c1ffa) </br>


4. `!cliptest` - test if the clipper is working, basically checks if the website is reachable.
```markdown
!addcom !cliptest $(urlfetch https://streamsnip.com/)
```

#### Super Advanced, Proceed with caution here
5. `!search` gives the last clip that had the query in in it
 ```markdown
 !addcom !search $(urlfetch https://streamsnip.com/search/$(querystring))
```
SUPER PRO MODE </br>
Idea from [here](https://community.nightdev.com/t/clip-command-then-have-lastclip-automatically-update/35360), You can combine !search command to give out timestamp to particular events in the stream </br>
A combo can look like this 
```
!addcom !clipkill $(urlfetch https://streamsnip.com/clip/$(chatid)/kill-automated)
!addcom !lastkill $(urlfetch https://streamsnip.com/search/kill-automated)
```
Want more advanced ? here </br>
There is one more endpoint named `/searchx/<clip-desc>` that returns JSON of the clip with that clip-desc.</br>
THIS IS JUST 1 EXAMPLE. SKY IS THE LIMIT HERE
```
!addcom !lastkilltime $(eval clip=$(urlfetch json https://streamsnip.com/searchx/kill-automated); clip['hms'])
```
returning data looks something like this </br>
![carbon (3)](https://github.com/SurajBhari/clip_nightbot/assets/45149585/f7709890-6959-4a25-8a6d-292c9d20e10b)


6. `!uptime` gives uptime of the latest stream of the channel that called this command
   ```markdown
   !addcom !uptime $(urlfetch https://streamsnip.com/uptime)
   ```

7. `!streaminfo` ADVANCED - this gives streaminfo in JSON format that you can use to do some other stuff.
   data looks something like this.
   ![carbon](https://github.com/SurajBhari/clip_nightbot/assets/45149585/811ec86a-9d69-4cc3-bde5-2d2cc66bd5ac)


### Additional Customization:

You can use `-ul=userlevel` to limit clipping to specific user levels (e.g., mods). Find user levels [here](https://docs.nightbot.tv/commands/commands#advanced-usage) to reduce spam and grant clipping access to specific individuals.  </br>
![image](https://github.com/SurajBhari/clip_nightbot/assets/45149585/47c433a9-fe83-42e2-996c-6ada0f0a73b1)  </br> 
![image](https://github.com/SurajBhari/clip_nightbot/assets/45149585/e86288bf-ff37-4a88-a45b-e891d5b5f8e0)  </br>

---
