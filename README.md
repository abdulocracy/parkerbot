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
3. Copy [example.env](example.env) to `.env`, customize it.
4. Source `.env`:
   ```shell
   source .env
   ```
5. Execute the app:
   ```shell
   ./main.py
   ```

## Running as a container

1. Customize the [compose.yml](compose.yml) if necessary, you might want to change the data
   volume's path or make it a named volume.
2. Copy [example.env](example.env) to `.env` and customize it.
3. Run locally as described above at least once on a machine with a web browser.
   This is needed to get a valid `token.pickle` for YouTube. Copy it to the data
   directory where you want to run the container.
4. Run the container, this is an example with `podman-compose`:
   ```shell
   podman-compose up -d
   ```
