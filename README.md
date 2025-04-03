# Bluesky Thread Explorer

A command-line tool for exploring and navigating through Bluesky posts and threads using the AT Protocol.

## Features

- Convert Bluesky web URLs to AT Protocol URIs
- Display full post content including text, images, and metadata
- View thread context (parent and root posts)
- Browse replies to posts
- Interactive navigation through thread hierarchies
- Terminal-friendly clickable links (in supported terminals)

## Requirements

- Python 3.8+
- `atproto` Python SDK

## Installation

1. Clone this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Authentication

Create a JSON credentials file (e.g., `creds.json`) with your Bluesky credentials:

```json
{
  "username": "your.handle",
  "password": "your-app-password",
  "bluesky_url": "https://bsky.app/profile/handle/post/postid"  // Optional
}
```

**Note**: For security, use an app-specific password rather than your main password. You can create one in your Bluesky account settings.

## Usage

Run the script:

```bash
python script.py
```

You'll be prompted to enter the path to your credentials file. If your credentials file includes a `bluesky_url`, the script will start by displaying that post. Otherwise, you'll be prompted to enter a URL or AT URI.

### Navigation Commands

- `[n]` - Enter a new URL or URI
- `[p]` - Navigate to parent post
- `[r]` - Navigate to root post
- `[1-X]` - Navigate to a specific reply
- `[q]` - Quit the application

## How It Works

The script performs the following operations:

1. Authenticates with the Bluesky API using your credentials
2. Parses and converts web URLs to AT Protocol URIs (format: `at://<did>/app.bsky.feed.post/<rkey>`)
3. Fetches post data, including:
   - Post text and creation time
   - Author information
   - Images and their alt text
   - Thread context (parent and root posts)
   - Replies to the current post
4. Provides an interactive interface for navigating between posts in a thread

## Example Session

```
Enter the credential file name (JSON format): creds.json
Logging in to Bluesky...
Login successful!

================================================================================
Processing: at://did:plc:abcdefg/app.bsky.feed.post/123456
================================================================================

Bluesky Web URL: https://bsky.app/profile/did:plc:abcdefg/post/123456

Successfully fetched post data

--------------------------------------------------------------------------------
POST CONTENT
--------------------------------------------------------------------------------
Author: Example User (@example.bsky.social)
Posted: 2023-06-15T14:30:00Z

Text: This is an example post with some text content.
URI: at://did:plc:abcdefg/app.bsky.feed.post/123456
App URL: https://bsky.app/profile/did:plc:abcdefg/post/123456

--------------------------------------------------------------------------------
REPLIES
--------------------------------------------------------------------------------

[1] Replier (@replier.bsky.social) replied at 2023-06-15T15:00:00Z:
  This is a reply to the original post
  URI: at://did:plc:hijklmn/app.bsky.feed.post/789012
  App URL: https://bsky.app/profile/did:plc:hijklmn/post/789012

--------------------------------------------------------------------------------
NAVIGATION OPTIONS
--------------------------------------------------------------------------------
[1-1] View reply
[n] Enter new URI/URL
[q] Quit

Enter option: 
```

## Troubleshooting

If you encounter authentication issues:
1. Verify your credentials are correct
2. Ensure you're using an app-specific password
3. Check your internet connection

For other issues, check the error messages which provide details about what went wrong.
