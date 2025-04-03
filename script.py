import re
import json
import sys
from atproto import Client
from atproto.xrpc_client import XrpcClient

def parse_at_uri(uri: str):
    """
    A simple parser for AT URIs in the expected format:
       at://<did>/app.bsky.feed.post/<rkey>
    Returns a tuple (did, rkey).
    """
    if not uri.startswith("at://"):
        raise ValueError("Invalid AT URI format")
    remainder = uri[len("at://"):]
    parts = remainder.split("/")
    if len(parts) < 3:
        raise ValueError("AT URI does not have enough parts")
    did = parts[0]
    rkey = parts[2]
    return did, rkey

def convert_bluesky_url(url: str, client: Client) -> str:
    """
    Convert a Bluesky URL (e.g. https://bsky.app/profile/<handle>/post/<rkey>)
    into a valid AT URI: at://<did>/app.bsky.feed.post/<rkey>
    
    This involves:
      1. Extracting the handle and rkey from the URL.
      2. Resolving the handle to a DID using the SDK.
    """
    pattern = r'https://bsky\.app/profile/([^/]+)/post/([^/]+)'
    match = re.match(pattern, url)
    if not match:
        raise ValueError("Invalid Bluesky URL format. Expected format: https://bsky.app/profile/<handle>/post/<rkey>")
    handle, rkey = match.groups()
    
    # Resolve the handle to a DID.
    resolve_resp = client.com.atproto.identity.resolve_handle({'handle': handle})
    did = resolve_resp.did  # Assumes the response object has a 'did' attribute.
    
    # Construct the AT URI.
    at_uri = f"at://{did}/app.bsky.feed.post/{rkey}"
    return at_uri

def fetch_post_details(client: Client, at_uri: str):
    """
    Fetch the post details using the atproto SDK.
    
    This call uses the DID (resolved from the AT URI) and the record key.
    """
    did, rkey = parse_at_uri(at_uri)
    post = client.app.bsky.feed.post.get(did, rkey)
    return post

def fetch_raw_record(client: XrpcClient, at_uri: str):
    """
    Fetch the raw record data using the com.atproto.repo.get_record endpoint.
    This provides the complete record without any filtering or processing.
    """
    did, rkey = parse_at_uri(at_uri)
    params = {
        'repo': did,
        'collection': 'app.bsky.feed.post',
        'rkey': rkey
    }
    raw_record = client.xrpc_client.get('com.atproto.repo.getRecord', params)
    return raw_record

def fetch_repo_status(client: XrpcClient, did: str):
    """
    Fetch repository status which includes merkle tree information.
    """
    params = {'did': did}
    repo_status = client.xrpc_client.get('com.atproto.repo.describeRepo', params)
    return repo_status

def fetch_record_commit_path(client: XrpcClient, at_uri: str):
    """
    Fetch the commit path for a specific record which provides
    information about its position in the merkle tree.
    """
    did, rkey = parse_at_uri(at_uri)
    params = {
        'repo': did,
        'collection': 'app.bsky.feed.post',
        'rkey': rkey
    }
    try:
        commit_path = client.xrpc_client.get('com.atproto.repo.getRecordCommitPath', params)
        return commit_path
    except Exception as e:
        print(f"Error fetching commit path: {e}")
        return None

def fetch_likes(client: Client, at_uri: str):
    """
    Fetch likes for the given post AT URI.
    
    Calls the app.bsky.feed.get_likes endpoint with the URI.
    """
    params = {'uri': at_uri, 'limit': 50}
    likes_resp = client.app.bsky.feed.get_likes(params)
    return likes_resp

def fetch_quotes(client: Client, at_uri: str):
    """
    Fetch quote posts related to the given post AT URI.
    
    This endpoint returns posts that quote the target post.
    """
    params = {'uri': at_uri, 'limit': 50}
    try:
        quotes_resp = client.app.bsky.feed.get_quotes(params)
        return quotes_resp
    except Exception as e:
        print("Error fetching quotes:", e)
        return None

def fetch_replies(client: Client, at_uri: str):
    """
    Fetch the thread (i.e. replies) for the given post AT URI.
    Using depth=1 to fetch immediate replies.
    """
    params = {'uri': at_uri, 'depth': 1}
    try:
        replies_resp = client.app.bsky.feed.get_post_thread(params)
        return replies_resp
    except Exception as e:
        print("Error fetching replies:", e)
        return None

def extract_reply_info(raw_record):
    """
    Extract reply information from a raw record,
    even if the reply is to a blocked user or post.
    """
    reply_info = None
    if 'value' in raw_record and 'reply' in raw_record['value']:
        reply_info = raw_record['value']['reply']
    return reply_info

def load_credentials_from_file(filename: str):
    """
    Load the Bluesky URL, username, and password from a JSON file.
    Expected keys: "bluesky_url", "username", "password"
    """
    with open(filename, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get("bluesky_url"), data.get("username"), data.get("password")

def main():
    # Prompt the user for the credentials file name.
    filename = input("Enter the credential file name (JSON format): ").strip()
    try:
        bluesky_url, username, password = load_credentials_from_file(filename)
    except Exception as e:
        print("Error loading credentials:", e)
        sys.exit(1)
        
    if not bluesky_url or not username or not password:
        print("Missing required fields in the credentials file.")
        sys.exit(1)
    
    # Initialize the client and log in.
    client = Client()
    client.login(username, password)
    
    # Convert the provided Bluesky URL to a valid AT URI.
    try:
        at_uri = convert_bluesky_url(bluesky_url, client)
    except Exception as e:
        print("Error converting URL:", e)
        sys.exit(1)
    
    print("Converted AT URI:", at_uri)
    
    # Fetch and display the post details.
    try:
        post = fetch_post_details(client, at_uri)
    except Exception as e:
        print("Error fetching post details:", e)
        sys.exit(1)
    
    print("\n--- Post Details ---")
    print("Post URI:", post.uri)
    if hasattr(post, 'embed') and post.embed is not None:
        print("Embedded Record:")
        print(post.embed)
    else:
        print("No embedded record.")
    
    # NEW: Fetch and display raw record data
    try:
        raw_record = fetch_raw_record(client, at_uri)
        print("\n--- Raw Record Data ---")
        print(json.dumps(raw_record, indent=2))
        
        # Extract reply information from raw record
        reply_info = extract_reply_info(raw_record)
        if reply_info:
            print("\n--- Reply Information (Including Blocked) ---")
            print(json.dumps(reply_info, indent=2))
    except Exception as e:
        print("Error fetching raw record:", e)
    
    # NEW: Fetch and display merkle tree information
    did, _ = parse_at_uri(at_uri)
    try:
        repo_status = fetch_repo_status(client, did)
        print("\n--- Repository (Merkle Tree) Information ---")
        print(json.dumps(repo_status, indent=2))
    except Exception as e:
        print("Error fetching repository status:", e)
    
    # NEW: Fetch and display record commit path
    try:
        commit_path = fetch_record_commit_path(client, at_uri)
        if commit_path:
            print("\n--- Record Commit Path (Merkle Tree Position) ---")
            print(json.dumps(commit_path, indent=2))
    except Exception as e:
        print("Error fetching commit path:", e)
    
    # Fetch and display likes.
    likes_resp = fetch_likes(client, at_uri)
    if hasattr(likes_resp, 'likes') and likes_resp.likes:
        print("\n--- Likes ---")
        for like in likes_resp.likes:
            print(f"{like.actor.handle} liked at {like.created_at}")
    else:
        print("No likes found.")
    
    # Fetch and display quote posts.
    quotes_resp = fetch_quotes(client, at_uri)
    if quotes_resp and hasattr(quotes_resp, 'quotes') and quotes_resp.quotes:
        print("\n--- Quote Posts ---")
        for quote in quotes_resp.quotes:
            print(f"{quote.actor.handle} quoted at {quote.created_at}:")
            if hasattr(quote, 'record') and hasattr(quote.record, 'text'):
                print("  Quote text:", quote.record.text)
    else:
        print("No quote posts found.")
    
    # Fetch and display replies.
    replies_resp = fetch_replies(client, at_uri)
    if replies_resp and hasattr(replies_resp, 'thread') and replies_resp.thread:
        print("\n--- Replies ---")
        if hasattr(replies_resp.thread, 'children') and replies_resp.thread.children:
            for reply in replies_resp.thread.children:
                try:
                    author = reply.post.author.handle
                    created_at = reply.post.created_at
                    text = reply.post.record.text
                    print(f"{author} replied at {created_at}:")
                    print("  Reply text:", text)
                except Exception as e:
                    print("Error reading reply:", e)
        else:
            print("No direct replies found in thread.")
    else:
        print("No replies found.")

if __name__ == '__main__':
    main()
