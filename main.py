#!/usr/bin/env python3
"""parkerbot: Matrix bot to generate YouTube (music) playlists from links sent to a channel."""

import argparse
import asyncio
import os
import pickle
import re
import sqlite3
import time
from datetime import datetime, timedelta

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient import errors
from nio import AsyncClient, RoomMessageText, SyncResponse

DATA_DIR = os.getenv("DATA_DIR", "./")
DB_PATH = os.path.join(DATA_DIR, "parkerbot.sqlite3")
TOKEN_PATH = os.path.join(DATA_DIR, "sync_token")
PICKLE_PATH = os.path.join(DATA_DIR, "token.pickle")

MATRIX_SERVER = os.getenv("MATRIX_SERVER")
MATRIX_ROOM = os.getenv("MATRIX_ROOM")
MATRIX_USER = os.getenv("MATRIX_USER")
MATRIX_PASSWORD = os.getenv("MATRIX_PASSWORD")

YOUTUBE_PLAYLIST_TITLE = os.getenv("YOUTUBE_PLAYLIST_TITLE")
YOUTUBE_CLIENT_SECRETS_FILE = os.getenv("YOUTUBE_CLIENT_SECRETS_FILE")
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Matrix bot to generate YouTube (music) playlists from links sent to a channel."
    )
    parser.add_argument(
        "--backwards-sync",
        action="store_true",
        help="Run backwards sync on start (this may cause you to exceed your daily API quota).",
    )
    return parser.parse_args()


def define_tables():
    """Define tables for use with program."""
    with conn:
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT,
                message TEXT,
                timestamp DATETIME,
                UNIQUE (sender, message, timestamp))"""
        )
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                playlist_id TEXT UNIQUE,
                creation_date DATE)"""
        )
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS playlist_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id INTEGER,
                message_id INTEGER,
                FOREIGN KEY (playlist_id) REFERENCES playlists(id),
                FOREIGN KEY (message_id) REFERENCES messages(id),
                UNIQUE (playlist_id, message_id))"""
        )


def get_authenticated_service():
    """Get an authentivated YouTube service."""
    credentials = None
    # Stores the user's access and refresh tokens.
    if os.path.exists(PICKLE_PATH):
        with open(PICKLE_PATH, "rb") as token:
            credentials = pickle.load(token)

    # If there are no valid credentials available, let the user log in.
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                YOUTUBE_CLIENT_SECRETS_FILE,
                scopes=["https://www.googleapis.com/auth/youtube.force-ssl"],
            )
            credentials = flow.run_local_server(port=8080)
            # Save the credentials for the next run
            with open(PICKLE_PATH, "wb") as token:
                pickle.dump(credentials, token)

    return build("youtube", "v3", credentials=credentials)


def get_monday_date(timestamp):
    """Get Monday of the week for the given timestamp. Weeks start on Monday."""
    date = datetime.fromtimestamp(timestamp / 1000, datetime.UTC)
    return date - timedelta(days=date.weekday())


def make_playlist(youtube, title):
    """Make a playlist with given title."""
    response = (
        youtube.playlists()
        .insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": title,
                    "description": "Weekly playlist generated by ParkerBot",
                },
                "status": {"privacyStatus": "public"},
            },
        )
        .execute()
    )

    return response["id"]


def get_or_make_playlist(youtube, monday_date):
    """Get ID of playlist for given Monday's week, make if doesn't exist."""
    playlist_title = f"{YOUTUBE_PLAYLIST_TITLE} {monday_date.strftime('%Y-%m-%d')}"

    # Check if playlist exists in the database
    cursor.execute(
        "SELECT playlist_id FROM playlists WHERE title = ?", (playlist_title,)
    )
    row = cursor.fetchone()
    if row:
        return row[0]  # Playlist already exists

    # If not, make a new playlist on YouTube and save it in the database
    playlist_id = make_playlist(youtube, playlist_title)
    with conn:
        cursor.execute(
            "INSERT INTO playlists (title, playlist_id, creation_date) VALUES (?, ?, ?)",
            (playlist_title, playlist_id, monday_date),
        )

    return playlist_id


def add_video_to_playlist(youtube, playlist_id, video_id, retry_count=3):
    """Add video to playlist."""
    for attempt in range(retry_count):
        try:
            youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id},
                    }
                },
            ).execute()
            break
        except errors.HttpError as error:
            if attempt < retry_count - 1:
                time.sleep(2**attempt)
                continue
            raise error


def is_music(youtube, video_id):
    """Check whether a YouTube video is music."""
    video_details = youtube.videos().list(id=video_id, part="snippet").execute()

    # Check if the video category is Music (typically category ID 10)
    return video_details["items"][0]["snippet"]["categoryId"] == "10"


async def message_callback(client, room, event):
    """Event handler for received messages."""
    youtube_link_pattern = r"(https?://(?:www\.|music\.)?youtube\.com/(?!playlist\?list=)watch\?v=[\w-]+|https?://youtu\.be/[\w-]+)"
    sender = event.sender
    if sender != MATRIX_USER:
        body = event.body.strip()
        timestamp = event.server_timestamp
        room_id = room.room_id
        monday_date = get_monday_date(timestamp)
        youtube = get_authenticated_service()
        playlist_id = get_or_make_playlist(youtube, monday_date)
        youtube_links = re.findall(youtube_link_pattern, body)

        timestamp_sec = datetime.fromtimestamp(
            event.server_timestamp / 1000, datetime.UTC
        )  # milisec to sec
        current_time = datetime.now(datetime.UTC)

        if body == "!parkerbot" and current_time - timestamp_sec < timedelta(seconds=30):
            intro_message = ("Hi, I'm ParkerBot! I generate YouTube playlists "
                             "from links sent to this channel. You can find my source code here: "
                             "https://git.abdulocra.cy/abdulocracy/parkerbot")
            await client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": intro_message}
            )

        if body == "!pow" and current_time - timestamp_sec < timedelta(seconds=30):
            playlist_link = f"https://www.youtube.com/playlist?list={playlist_id}"
            reply_msg = f"{sender}, here's the playlist of the week: {playlist_link}"
            await client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": reply_msg},
            )

        for link in youtube_links:
            video_id = link.split("v=")[-1].split("&")[0].split("/")[-1]
            if is_music(youtube, video_id):
                try:
                    cursor.execute(
                        "INSERT INTO messages (sender, message, timestamp) VALUES (?, ?, ?)",
                        (sender, link, timestamp),
                    )
                    conn.commit()
                    print(f"Saved YouTube link from {sender}: {link}")
                except sqlite3.IntegrityError as e:
                    if "UNIQUE constraint failed" in str(e):
                        print(f"Entry already exists: {sender} {link} {timestamp}")
                    else:
                        raise e

                # Check if the link is already added to any playlist
                cursor.execute("SELECT id FROM messages WHERE message = ?", (link,))
                message_row = cursor.fetchone()

                if message_row:
                    cursor.execute(
                        "SELECT id FROM playlist_tracks WHERE message_id = ? AND playlist_id = ?",
                        (message_row[0], playlist_id),
                    )
                    track_row = cursor.fetchone()

                    if track_row:
                        print(f"Track already in playlist: {link}")
                    else:
                        # Add video to playlist and record it in the database
                        add_video_to_playlist(youtube, playlist_id, video_id)
                        with conn:
                            cursor.execute(
                                "INSERT INTO playlist_tracks (playlist_id, message_id) VALUES (?, ?)",
                                (playlist_id, message_row[0]),
                            )
                        print(f"Added track to playlist: {link}")


async def sync_callback(response):
    """Save Matrix sync token."""
    # Save the sync token to a file or handle it as needed
    with open(TOKEN_PATH, "w") as f:
        f.write(response.next_batch)


def load_sync_token():
    """Get an existing Matrix sync token if it exists."""
    try:
        with open(TOKEN_PATH, "r") as file:
            return file.read().strip()
    except FileNotFoundError:
        return None


async def get_client():
    """Returns configured and logged in Matrix client."""
    client = AsyncClient(MATRIX_SERVER, MATRIX_USER)
    client.add_event_callback(
        lambda room, event: message_callback(client, room, event), RoomMessageText
    )
    client.add_response_callback(sync_callback, SyncResponse)
    print(await client.login(MATRIX_PASSWORD))
    return client


async def backwards_sync(client, room, start_token):
    """Fetch and process historical messages from a given room."""
    print("Starting to process channel log...")
    from_token = start_token
    room_id = room.room_id
    while True:
        # Fetch room messages
        response = await client.room_messages(room_id, from_token, direction="b")

        # Process each message
        for event in response.chunk:
            if isinstance(event, RoomMessageText):
                await message_callback(client, room, event)

        # Break if there are no more messages to fetch
        if not response.end or response.end == from_token:
            break

        # Update the from_token for the next iteration
        from_token = response.end


async def main():
    """Get DB and Matrix client ready, and start syncing."""
    args = parse_arguments()
    define_tables()
    client = await get_client()
    sync_token = load_sync_token()

    if args.backwards_sync:
        init_sync = await client.sync(30000)
        room = await client.room_resolve_alias(MATRIX_ROOM)
        await backwards_sync(client, room, init_sync.next_batch)

    await client.sync_forever(30000, full_state=True, since=sync_token)


if __name__ == "__main__":
    asyncio.run(main())
