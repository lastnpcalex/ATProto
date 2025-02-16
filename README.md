# Bluesky AT Protocol Post Explorer
This README provides a concise overview of how the script works and how to set it up. This script uses the atproto Python SDK to convert a Bluesky post URL into an AT URI and then fetches post details, likes, quote posts, and replies.

## Requirements

- Python 3.8+
- [atproto SDK](https://github.com/bluesky-social/atproto)  
  Install via:
  ```bash
  pip install atproto


## Setup

Create a JSON credentials file (e.g., `creds.json`) with the following format:

```json
{
  "bluesky_url": "https://bsky.app/profile/<handle>/post/<rkey>",
  "username": "<your_username>",
  "password": "<your_app_password>"
}


## Usage 
Run the script and enter your credentials file name when prompted:
python script.py

The script will:

- **Log in to Bluesky** using your username and app password.
- **Convert the provided Bluesky URL** to a valid AT URI.
- **Fetch and display** the post details, likes, quote posts, and replies.

**Endpoints Used:**

- **resolve_handle**: Resolves a user handle to a DID.
- **post.get**: Retrieves the post details.
- **get_likes**: Fetches likes for the post.
- **get_quotes**: Retrieves posts quoting the target post.
- **get_post_thread**: Fetches replies to the post.


