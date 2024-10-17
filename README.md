# ShoxxTwitchBot

Twitch Chat Bot using the Python API

How To:
plan for the future: as executable for windows / bash script for unix
For now: Runnable Python file.

This is based on the python twitch API here: `https://pytwitchapi.dev/en/stable/`

1. Get Python (prefrably 3.11+ [though docs says 3.7 is fine], prefrably venv) with pip
2. `pip install -r requirements.txt`
3. go to `https://dev.twitch.tv/` and log in with the account you wish to speak as in chat (could be your user account, or a designated bot account). Said account needs to have 2FA active (go to creater dashboard + settings to set up 2FA)
4. Navigate to your console, "Register New Application"
5. Fill in details of the app:
   - Give it a swanky name,
   - add `http://localhost:17563` to the redirect URLS
   - set Category: ChatBot
   - set Client Type Confidential
   - (if neccessary, appease the reCAPTCHA)
6. Go to Manage Application, get ClientID and create a new Client Secret.
7. Save both in a .env file in the same folder as main.py with the syntax:

```text
CLIENT_ID = "BUNCHANUMBERS"
CLIENT_SECRED = "BUNCHALETTERS"
```

8. In main.py remove the "\_BFTD" from the client ID and Secret in the lines below `load_dotenv`

TODO:

- pokemon functionality to say "pokemon fire"
