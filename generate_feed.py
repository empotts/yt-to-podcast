from feedgen.feed import FeedGenerator
import yt_dlp as youtube_dl
from b2sdk.v2 import B2Api, InMemoryAccountInfo
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# Configuration
MAX_EPISODES = 5  # Keep last 5 episodes per channel
B2_BUCKET = "yt-to-podcast"
FEED_FILE = "feed.xml"

def connect_b2():
    info = InMemoryAccountInfo()
    b2_api = B2Api(info)
    b2_api.authorize_account(
        "production", 
        os.environ["B2_KEY_ID"], 
        os.environ["B2_APP_KEY"]
    )
    return b2_api.get_bucket_by_name(B2_BUCKET)

def upload_to_b2(bucket, local_path, video_id):
    b2_filename = f"episodes/{video_id}.mp3"
    if bucket.get_file_info_by_name(b2_filename):
        return f"https://f002.backblazeb2.com/file/{B2_BUCKET}/{b2_filename}"
    
    bucket.upload_local_file(local_path, b2_filename)
    return f"https://f002.backblazeb2.com/file/{B2_BUCKET}/{b2_filename}"

def clean_old_episodes(bucket):
    all_files = [(f.file_name, f.upload_timestamp) for f in bucket.ls("episodes/")]
    all_files.sort(key=lambda x: x[1], reverse=True)
    
    # Keep only latest MAX_EPISODES * number_of_channels
    with open("channels.txt") as f:
        channel_count = len(f.readlines())
    
    to_keep = MAX_EPISODES * channel_count
    for file in all_files[to_keep:]:
        bucket.delete_file_version(file[0])

def get_processed_videos():
    processed = set()
    if os.path.exists("processed_videos.txt"):
        with open("processed_videos.txt") as f:
            processed.update(f.read().splitlines())
    return processed

def create_feed():
    bucket = connect_b2()
    processed = get_processed_videos()
    ydl_opts = {
    'format': 'bestaudio/best',
    'outtmpl': '%(id)s.%(ext)s',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
    }],
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.youtube.com/'
    },
    'ratelimit': 10000000,
    'sleep_interval': 30,
    'retries': 5,
    'ignoreerrors': True,
    
    }
    if os.environ.get('YT_USERNAME') and os.environ.get('YT_PASSWORD'):
        ydl_opts.update({
            'username': os.environ.get('YT_USERNAME'),
            'password': os.environ.get('YT_PASSWORD'),
        })
    



    fg = FeedGenerator()
    fg.title('YouTube Podcast')
    fg.link(href='https://empotts.github.io/yt-to-podcast/feed.xml')
    fg.description('Auto-generated podcast from YouTube channels')

    new_entries = []
    
    with open("channels.txt") as channels:
        for channel_url in channels:
            channel_url = channel_url.strip()
            if not channel_url:  # Skip empty lines
                continue
                
            try:
                with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(channel_url, download=False)
                    
                    # First, get the latest MAX_EPISODES videos
                    latest_entries = info.get('entries', [])[-MAX_EPISODES:]
                    
                    # Then filter out already processed videos
                    unprocessed_entries = [e for e in latest_entries if e.get('id') not in processed]
                    
                    print(f"Processing {len(unprocessed_entries)} new videos from {channel_url}")
                    
                    for entry in unprocessed_entries:
                        try:
                            ydl.download([entry['webpage_url']])
                            mp3_file = f"{entry['id']}.mp3"
                            audio_url = upload_to_b2(bucket, mp3_file, entry['id'])
                            
                            fe = fg.add_entry()
                            fe.id(entry['id'])
                            fe.title(entry['title'])
                            fe.description(entry.get('description', ''))
                            fe.enclosure(audio_url, 0, 'audio/mpeg')
                            fe.pubDate(entry['upload_date'])
                            
                            new_entries.append(entry['id'])
                            os.remove(mp3_file)
                            print(f"Successfully processed: {entry['title']}")
                        except Exception as e:
                            print(f"Failed processing {entry['id']}: {str(e)}")
            except Exception as e:
                print(f"Error processing channel {channel_url}: {str(e)}")

    # Update processed list
    with open("processed_videos.txt", "a") as f:
        f.write("\n".join(new_entries) + "\n")

    clean_old_episodes(bucket)
    fg.rss_file(FEED_FILE)

if __name__ == "__main__":
    create_feed()