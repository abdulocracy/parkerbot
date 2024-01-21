# ParkerBot

ParkerBot is a Matrix bot that monitors a channel for YouTube links and
generates weekly playlists from them.

## Running locally

1. Clone the repo
2. Install the dependencies, preferably in a venv:
   ```shell
   python3 -m venv venv
   source ./venv/bin/activate
   pip3 install -r requirements.txt
   ```
3. Copy `[example.env](example.env)` to `.env`, customize it.
4. Source `.env`:
   ```shell
   source .env
   ```
3. Execute the app:
   ```shell
   ./main.py
   ```

## Running as a container

1. Customize the compose.yml if necessary, you might want to change the data
   volume's path or make it a named volume.
3. Copy `[example.env](example.env)` to `.env` and customize it.
2. ```shell
   podman-compose up -d
   ```
