#!/usr/bin/env python3
"""parkerbot: Matrix bot to generate YouTube (music) playlists from links sent to a channel."""

import os
import re
import sqlite3
import asyncio
import pickle
from datetime import datetime, timedelta
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from nio import AsyncClient, MatrixRoom, RoomMessageText

load_dotenv()
DB_PATH = os.getenv("DB_PATH")
MATRIX_SERVER = os.getenv("MATRIX_SERVER")
MATRIX_ROOM = os.getenv("MATRIX_ROOM")
MATRIX_USER = os.getenv("MATRIX_USER")
MATRIX_PASSWORD = os.getenv("MATRIX_PASSWORD")
PLAYLIST_TITLE = os.getenv("PLAYLIST_TITLE")
YOUTUBE_CLIENT_SECRETS_FILE = os.getenv("YOUTUBE_CLIENT_SECRETS_FILE")
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()


def create_tables():
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
    credentials = None
    # The file token.pickle stores the user's access and refresh tokens.
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
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
            with open("token.pickle", "wb") as token:
                pickle.dump(credentials, token)

    return build("youtube", "v3", credentials=credentials)


def get_monday_date():
    today = datetime.now()
    return today - timedelta(days=today.weekday())


def create_playlist(youtube, title):
    response = (
        youtube.playlists()
        .insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": title,
                    "description": "Weekly playlist created by ParkerBot",
                },
                "status": {"privacyStatus": "public"},
            },
        )
        .execute()
    )

    return response["id"]


def get_or_create_playlist(youtube, monday_date):
    playlist_title = f"{PLAYLIST_TITLE} {monday_date.strftime('%Y-%m-%d')}"

    # Check if playlist exists in the database
    cursor.execute(
        "SELECT playlist_id FROM playlists WHERE title = ?", (playlist_title,)
    )
    row = cursor.fetchone()
    if row:
        return row[0]  # Playlist already exists

    # If not, create a new playlist on YouTube and save it in the database
    playlist_id = create_playlist(youtube, playlist_title)
    with conn:
        cursor.execute(
            "INSERT INTO playlists (title, playlist_id, creation_date) VALUES (?, ?, ?)",
            (playlist_title, playlist_id, monday_date),
        )

    return playlist_id


def add_video_to_playlist(youtube, playlist_id, video_id):
    youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        },
    ).execute()


async def message_callback(room, event):
    youtube_link_pattern = r"(https?://(?:www\.|music\.)?youtube\.com/(?!playlist\?list=)watch\?v=[\w-]+|https?://youtu\.be/[\w-]+)"
    if event.sender != MATRIX_USER:
        sender = event.sender
        message_body = event.body
        room_id = room.room_id
        monday_date = get_monday_date()
        youtube = get_authenticated_service()
        playlist_id = get_or_create_playlist(youtube, monday_date)
        youtube_links = re.findall(youtube_link_pattern, message_body)

        if message_body == "!pow":
            playlist_link = f"https://www.youtube.com/playlist?list={playlist_id}"
            reply_msg = f"{sender}, here's the playlist of the week: {playlist_link}"
            await client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": reply_msg
                }
            )

        if youtube_links:
            timestamp = event.server_timestamp
            for link in youtube_links:
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

            for link in youtube_links:
                video_id = link.split("v=")[-1]

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


async def main():
    create_tables()
    global client
    client = AsyncClient(MATRIX_SERVER, MATRIX_USER)
    client.add_event_callback(message_callback, RoomMessageText)
    print(await client.login(MATRIX_PASSWORD))
    await client.join(MATRIX_ROOM)
    await client.sync_forever(timeout=10000)  # milliseconds


if __name__ == "__main__":
    asyncio.run(main())
