import re
import json
import sys
from atproto import Client

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
    Convert a Bluesky URL (e.g. https://bsky.app/profile/<handle or DID>/post/<rkey>)
    into a valid AT URI: at://<did>/app.bsky.feed.post/<rkey>
    """
    pattern = r'https://bsky\.app/profile/([^/]+)/post/([^/]+)'
    match = re.match(pattern, url)
    if not match:
        raise ValueError("Invalid Bluesky URL format. Expected format: https://bsky.app/profile/<handle or DID>/post/<rkey>")
    handle_or_did, rkey = match.groups()
    
    print(f"Converting URL... Handle or DID: {handle_or_did}, Record key: {rkey}")
    
    if handle_or_did.startswith('did:'):
        did = handle_or_did
        print(f"Using DID directly: {did}")
    else:
        try:
            resolve_resp = client.com.atproto.identity.resolve_handle({'handle': handle_or_did})
            did = resolve_resp.did
            print(f"Resolved handle {handle_or_did} to DID: {did}")
        except Exception as e:
            print(f"Error resolving handle: {e}")
            raise
    
    at_uri = f"at://{did}/app.bsky.feed.post/{rkey}"
    return at_uri

def is_at_uri(uri: str) -> bool:
    """Check if a string is an AT URI."""
    return uri.startswith("at://") and "/app.bsky.feed.post/" in uri

def is_bluesky_url(url: str) -> bool:
    """Check if a string is a Bluesky URL."""
    pattern = r'https://bsky\.app/profile/([^/]+)/post/([^/]+)'
    return bool(re.match(pattern, url))

def make_clickable(url: str) -> str:
    """Make a URL clickable in terminals that support it."""
    return f"\033]8;;{url}\033\\{url}\033]8;;\033\\"

def extract_images_from_record(record_value):
    """Extract image URLs from a record value from both 'embed' and 'media' keys."""
    images = []
    if isinstance(record_value, dict):
        # Check for images in 'embed'
        if 'embed' in record_value:
            embed = record_value['embed']
            if isinstance(embed, dict) and 'images' in embed:
                for img in embed['images']:
                    alt = img.get('alt', 'No description')
                    if 'image' in img and 'ref' in img['image']:
                        image_ref = img['image']['ref']
                        if isinstance(image_ref, dict):
                            ref_url = image_ref.get('$link')
                        else:
                            ref_url = None
                        images.append({'alt': alt, 'ref': ref_url})
        # Fallback: Check for images in 'media'
        if 'media' in record_value and isinstance(record_value['media'], list):
            for m in record_value['media']:
                if m.get('type') == 'image' and m.get('url'):
                    images.append({
                        'alt': m.get('alt', 'No description'),
                        'ref': m.get('url')
                    })
    return images

def extract_text_from_record(record_value):
    """
    Attempt to extract the post text from the record_value.
    It checks multiple possible keys and nesting structures.
    """
    if isinstance(record_value, dict):
        if 'text' in record_value and record_value['text']:
            return record_value['text']
        if 'record' in record_value and isinstance(record_value['record'], dict):
            rec = record_value['record']
            if 'text' in rec and rec['text']:
                return rec['text']
            if 'value' in rec and isinstance(rec['value'], dict):
                val = rec['value']
                if 'text' in val and val['text']:
                    return val['text']
                if 'content' in val and val['content']:
                    return val['content']
        if 'value' in record_value and isinstance(record_value['value'], dict):
            val = record_value['value']
            if 'text' in val and val['text']:
                return val['text']
            if 'content' in val and val['content']:
                return val['content']
    return "No text content"

def fetch_post_details(client, at_uri):
    """
    Fetch and return details about a post given its AT URI.
    Returns a dict with post details or None if there was an error.
    Also adds a clickable app URL for the post.
    """
    try:
        did, rkey = parse_at_uri(at_uri)
        params = {
            'repo': did,
            'collection': 'app.bsky.feed.post',
            'rkey': rkey
        }
        record = client.com.atproto.repo.get_record(params)
        record_value = record.value

        # Ensure record_value is a dictionary
        if not isinstance(record_value, dict):
            record_value = safe_to_dict(record_value)
        
        author_display = did
        try:
            author_info = client.app.bsky.actor.get_profile({'actor': did})
            if hasattr(author_info, 'handle'):
                author_handle = author_info.handle
                display_name = getattr(author_info, 'displayName', None)
                if display_name:
                    author_display = f"{display_name} (@{author_handle})"
                else:
                    author_display = f"@{author_handle}"
        except Exception:
            pass
        
        text = extract_text_from_record(record_value)
        created_at = record_value.get('createdAt') or record_value.get('indexedAt') or "Unknown time"
        web_url = f"https://bsky.app/profile/{did}/post/{rkey}"
        
        return {
            'uri': at_uri,
            'web_url': web_url,
            'author': author_display,
            'text': text,
            'created_at': created_at
        }
    except Exception as e:
        print(f"Error fetching post details: {e}")
        return None

def safe_to_dict(obj):
    """
    Safely convert an object to a dictionary for JSON serialization.
    """
    if hasattr(obj, 'to_dict'):
        return obj.to_dict()
    elif hasattr(obj, '__dict__'):
        return {k: safe_to_dict(v) for k, v in obj.__dict__.items() if not k.startswith('_')}
    elif isinstance(obj, list):
        return [safe_to_dict(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: safe_to_dict(v) for k, v in obj.items()}
    else:
        return obj

def process_post(client: Client, at_uri: str):
    """
    Process a post using its AT URI.
    Returns a tuple: (replies_resp, parent_uri, root_uri)
    """
    print("\n" + "=" * 80)
    print(f"Processing: {at_uri}")
    print("=" * 80)
    
    parent_uri = None
    root_uri = None
    
    try:
        did, rkey = parse_at_uri(at_uri)
    except Exception as e:
        print(f"Error parsing URI: {e}")
        return None, None, None
    
    try:
        web_url = f"https://bsky.app/profile/{did}/post/{rkey}"
        print(f"\nBluesky Web URL: {make_clickable(web_url)}")
    except Exception as e:
        print(f"Error creating web URL: {e}")
    
    try:
        params = {
            'repo': did,
            'collection': 'app.bsky.feed.post',
            'rkey': rkey
        }
        record = client.com.atproto.repo.get_record(params)
        record_value = record.value

        # Convert record_value to a dict if necessary
        if not isinstance(record_value, dict):
            record_value = safe_to_dict(record_value)
        
        print("\nSuccessfully fetched post data")
    except Exception as e:
        print(f"Error fetching record: {e}")
        return None, None, None
    
    print("\n" + "-" * 80)
    print("POST CONTENT")
    print("-" * 80)
    
    # Display author info
    author_did = did
    try:
        if author_did.startswith('did:'):
            try:
                author_info = client.app.bsky.actor.get_profile({'actor': author_did})
                if hasattr(author_info, 'handle'):
                    author_handle = author_info.handle
                    display_name = getattr(author_info, 'displayName', None)
                    if display_name:
                        print(f"Author: {display_name} (@{author_handle})")
                    else:
                        print(f"Author: @{author_handle} ({author_did})")
                else:
                    print(f"Author DID: {author_did}")
            except Exception as e:
                print(f"Author DID: {author_did} (Unable to fetch profile: {e})")
        else:
            print(f"Author ID: {author_did}")
    except Exception as e:
        print(f"Author DID: {author_did} (Error: {e})")
    
    created_at = record_value.get('createdAt') or record_value.get('indexedAt') or "Unknown time"
    print(f"Posted: {created_at}")
    
    text = extract_text_from_record(record_value)
    if text == "No text content":
        try:
            thread_params = {'uri': at_uri}
            thread_resp = client.app.bsky.feed.get_post_thread(thread_params)
            if thread_resp and hasattr(thread_resp, 'thread') and hasattr(thread_resp.thread, 'post'):
                thread_post = thread_resp.thread.post
                if hasattr(thread_post, 'record') and hasattr(thread_post.record, 'text'):
                    text = thread_post.record.text
                elif hasattr(thread_post, 'text'):
                    text = thread_post.text
        except Exception as e:
            print(f"Note: Alternative text extraction failed: {e}")
    
    print(f"\nText: {text}")
    
    # Display clickable app URL (again) with the AT URI
    print(f"URI: {at_uri}")
    print(f"App URL: {make_clickable(web_url)}")
    
    # Extract and display images with clickable URLs
    images = extract_images_from_record(record_value)
    if images:
        print("\nImages:")
        for i, img in enumerate(images, 1):
            if img['ref']:
                clickable_image_url = make_clickable(img['ref'])
            else:
                clickable_image_url = "No URL available"
            print(f"  [{i}] {img['alt']}: {clickable_image_url}")
    
    # Check for reply info
    reply_info = None
    if isinstance(record_value, dict):
        if 'reply' in record_value:
            reply_info = record_value['reply']
        elif 'record' in record_value and isinstance(record_value['record'], dict) and 'reply' in record_value['record']:
            reply_info = record_value['record']['reply']
        
        if isinstance(reply_info, dict):
            if 'parent' in reply_info and isinstance(reply_info['parent'], dict) and 'uri' in reply_info['parent']:
                parent_uri = reply_info['parent']['uri']
            if 'root' in reply_info and isinstance(reply_info['root'], dict) and 'uri' in reply_info['root']:
                root_uri = reply_info['root']['uri']
    
    if not (parent_uri or root_uri):
        try:
            params = {'uri': at_uri}
            thread_resp = client.app.bsky.feed.get_post_thread(params)
            if thread_resp and hasattr(thread_resp, 'thread'):
                thread = thread_resp.thread
                if hasattr(thread, 'parent'):
                    if hasattr(thread.parent, 'uri'):
                        parent_uri = thread.parent.uri
                    elif hasattr(thread.parent, 'post') and hasattr(thread.parent.post, 'uri'):
                        parent_uri = thread.parent.post.uri
                if hasattr(thread, 'root'):
                    if hasattr(thread.root, 'uri'):
                        root_uri = thread.root.uri
                    elif hasattr(thread.root, 'post') and hasattr(thread.root.post, 'uri'):
                        root_uri = thread.root.post.uri
        except Exception as e:
            print(f"Note: Unable to fetch additional thread context: {e}")
    
    if reply_info or parent_uri or root_uri:
        print("\n" + "-" * 80)
        print("THREAD CONTEXT")
        print("-" * 80)
        if root_uri and root_uri != parent_uri:
            print("\nROOT POST:")
            root_details = fetch_post_details(client, root_uri)
            if root_details:
                print(f"  Author: {root_details['author']}")
                print(f"  Posted: {root_details['created_at']}")
                print(f"  Text: {root_details['text']}")
                print(f"  URI: {root_details['uri']}")
                print(f"  App URL: {make_clickable(root_details['web_url'])}")
            else:
                print(f"  URI: {make_clickable(root_uri)}")
                print("  (Unable to fetch details)")
        if parent_uri:
            print("\nPARENT POST:")
            parent_details = fetch_post_details(client, parent_uri)
            if parent_details:
                print(f"  Author: {parent_details['author']}")
                print(f"  Posted: {parent_details['created_at']}")
                print(f"  Text: {parent_details['text']}")
                print(f"  URI: {parent_details['uri']}")
                print(f"  App URL: {make_clickable(parent_details['web_url'])}")
            else:
                print(f"  URI: {make_clickable(parent_uri)}")
                print("  (Unable to fetch details)")
        print("\nCURRENT POST:")
        is_me = hasattr(client, 'me') and client.me and client.me.did == author_did
        author_display = "You" if is_me else author_did
        print(f"  Author: {author_display}")
        print(f"  Posted: {created_at}")
        #print(f"  Text: {text}")
        print(f"  URI: {at_uri}")
        print(f"  App URL: {make_clickable(web_url)}")
    
    print("\n" + "-" * 80)
    print("REPLIES")
    print("-" * 80)
    
    replies_resp = None
    try:
        params = {'uri': at_uri, 'depth': 1}
        replies_resp = client.app.bsky.feed.get_post_thread(params)
        if replies_resp and hasattr(replies_resp, 'thread'):
            thread = replies_resp.thread
            reply_uris = []
            children = []
            if hasattr(thread, 'replies'):
                children = thread.replies
            elif hasattr(thread, 'children'):
                children = thread.children
            if children:
                for i, reply in enumerate(children):
                    try:
                        if hasattr(reply, 'post'):
                            r_post = reply.post
                            r_author = "Unknown"
                            if hasattr(r_post, 'author'):
                                if hasattr(r_post.author, 'handle'):
                                    r_author = r_post.author.handle
                                    if hasattr(r_post.author, 'displayName') and r_post.author.displayName:
                                        r_author = f"{r_post.author.displayName} (@{r_author})"
                            r_created_at = getattr(r_post, 'indexedAt', getattr(r_post, 'createdAt', "Unknown time"))
                            r_text = "No text content"
                            if hasattr(r_post, 'record') and hasattr(r_post.record, 'text'):
                                r_text = r_post.record.text
                            elif hasattr(r_post, 'text'):
                                r_text = r_post.text
                            elif hasattr(r_post, 'value') and isinstance(r_post.value, dict) and 'text' in r_post.value:
                                r_text = r_post.value['text']
                            r_uri = r_post.uri if hasattr(r_post, 'uri') else "Unknown URI"
                            try:
                                did_r, rkey_r = parse_at_uri(r_uri)
                                r_app_url = f"https://bsky.app/profile/{did_r}/post/{rkey_r}"
                            except Exception:
                                r_app_url = "Unknown"
                            reply_uris.append(r_uri)
                            reply_num = i + 1
                            print(f"\n[{reply_num}] {r_author} replied at {r_created_at}:")
                            print(f"  {r_text}")
                            print(f"  URI: {r_uri}")
                            print(f"  App URL: {make_clickable(r_app_url)}")
                    except Exception as e:
                        print(f"Error reading reply: {e}")
                if reply_uris:
                    print("\n" + "-" * 80)
                    print("REPLY URIS (for quick access)")
                    print("-" * 80)
                    for i, uri in enumerate(reply_uris, start=1):
                        print(f"[{i}] {uri}")
            else:
                print("No direct replies found.")
        else:
            print("No replies found.")
    except Exception as e:
        print(f"Error fetching replies: {e}")
    
    print("\n" + "-" * 80)
    print("NAVIGATION OPTIONS")
    print("-" * 80)
    
    if parent_uri:
        print(f"[p] View parent post: {parent_uri}")
    if root_uri and root_uri != parent_uri:
        print(f"[r] View root post: {root_uri}")
    
    num_replies = 0
    if replies_resp and hasattr(replies_resp, 'thread'):
        thread = replies_resp.thread
        if hasattr(thread, 'replies'):
            num_replies = len(thread.replies)
        elif hasattr(thread, 'children'):
            num_replies = len(thread.children)
    
    if num_replies > 0:
        print(f"[1-{num_replies}] View reply")
    
    print("[n] Enter new URI/URL")
    print("[q] Quit")
    
    return replies_resp, parent_uri, root_uri

def load_credentials_from_file(filename: str):
    """
    Load credentials from a JSON file.
    Supports both old format (with bluesky_url) and new format (auth only).
    Returns a tuple: (optional_url, username, password)
    """
    with open(filename, 'r', encoding='utf-8') as f:
        data = json.load(f)
    username = data.get("username")
    password = data.get("password")
    optional_url = data.get("bluesky_url")
    return optional_url, username, password

def main():
    filename = input("Enter the credential file name (JSON format): ").strip()
    try:
        optional_url, username, password = load_credentials_from_file(filename)
    except Exception as e:
        print(f"Error loading credentials: {e}")
        sys.exit(1)
        
    if not username or not password:
        print("Missing required authentication fields (username, password) in the credentials file.")
        sys.exit(1)
    
    print("Logging in to Bluesky...")
    client = Client()
    try:
        client.login(username, password)
        print("Login successful!")
    except Exception as e:
        print(f"Login failed: {e}")
        sys.exit(1)
    
    at_uri = None
    replies_resp = None
    parent_uri = None
    root_uri = None
    
    if optional_url:
        print(f"Found URL in credentials: {optional_url}")
        try:
            if is_at_uri(optional_url):
                at_uri = optional_url
            else:
                at_uri = convert_bluesky_url(optional_url, client)
            replies_resp, parent_uri, root_uri = process_post(client, at_uri)
        except Exception as e:
            print(f"Error processing initial URL from credentials: {e}")
            print("Continuing to interactive mode...")
    else:
        print("No initial URL provided in credentials.")
        print("Starting in interactive mode...")
        while not at_uri:
            user_input = input("\nEnter a Bluesky URL or AT URI: ").strip()
            if not user_input:
                continue
            try:
                if is_at_uri(user_input):
                    at_uri = user_input
                elif is_bluesky_url(user_input):
                    at_uri = convert_bluesky_url(user_input, client)
                else:
                    print("Invalid input. Please enter a valid Bluesky URL or AT URI.")
                    continue
                replies_resp, parent_uri, root_uri = process_post(client, at_uri)
            except Exception as e:
                print(f"Error processing input: {e}")
    
    while True:
        choice = input("\nEnter option: ").strip().lower()
        if choice == 'q':
            print("Exiting...")
            break
        elif choice == 'n':
            user_input = input("Enter URI/URL: ").strip()
            try:
                if is_at_uri(user_input):
                    at_uri = user_input
                elif is_bluesky_url(user_input):
                    at_uri = convert_bluesky_url(user_input, client)
                else:
                    print("Invalid input. Please enter a valid Bluesky URL or AT URI.")
                    continue
                replies_resp, parent_uri, root_uri = process_post(client, at_uri)
            except Exception as e:
                print(f"Error processing input: {e}")
        elif choice == 'p' and parent_uri:
            try:
                replies_resp, parent_uri, root_uri = process_post(client, parent_uri)
            except Exception as e:
                print(f"Error navigating to parent: {e}")
        elif choice == 'r' and root_uri and root_uri != parent_uri:
            try:
                replies_resp, parent_uri, root_uri = process_post(client, root_uri)
            except Exception as e:
                print(f"Error navigating to root: {e}")
        elif choice.isdigit() and replies_resp and hasattr(replies_resp, 'thread'):
            try:
                thread = replies_resp.thread
                children = []
                if hasattr(thread, 'replies'):
                    children = thread.replies
                elif hasattr(thread, 'children'):
                    children = thread.children
                reply_index = int(choice) - 1
                if 0 <= reply_index < len(children):
                    reply_uri = children[reply_index].post.uri
                    replies_resp, parent_uri, root_uri = process_post(client, reply_uri)
                else:
                    print(f"Invalid reply number. Please choose 1-{len(children)}")
            except Exception as e:
                print(f"Error navigating to reply: {e}")
        else:
            print("Invalid option")

if __name__ == '__main__':
    main()
