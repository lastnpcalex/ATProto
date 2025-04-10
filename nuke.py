import re
import json
import sys
import time
import pickle
import math
from datetime import datetime, timedelta
from atproto import Client
from atproto.exceptions import AtProtocolError

# Support for date parsing
from dateutil import parser as date_parser

def load_credentials_from_file(filename: str):
    """
    Load credentials from a JSON file.
    Returns a tuple: (username, password)
    """
    with open(filename, 'r', encoding='utf-8') as f:
        data = json.load(f)
    username = data.get("username")
    password = data.get("password")
    return username, password

def fetch_user_posts(client, cursor=None, limit=100):
    """
    Fetch posts made by the authenticated user.
    Returns a tuple of (posts, next_cursor)
    """
    try:
        # Get the user's DID (decentralized identifier)
        user_did = client.me.did
        
        # Fetch user's posts with maximum allowed limit
        # Note: 100 is currently the maximum Bluesky allows
        response = client.app.bsky.feed.get_author_feed({
            'actor': user_did,
            'limit': limit,
            'cursor': cursor
        })
        
        posts = []
        for feed_item in response.feed:
            # Make sure this post is by the user (not a mention or reply from someone else)
            if (hasattr(feed_item, 'post') and 
                hasattr(feed_item.post, 'uri') and 
                hasattr(feed_item.post, 'author') and 
                hasattr(feed_item.post.author, 'did') and 
                feed_item.post.author.did == user_did):
                posts.append(feed_item.post)
        
        next_cursor = getattr(response, 'cursor', None)
        return posts, next_cursor
    except Exception as e:
        print(f"Error fetching posts: {e}")
        return [], None

def safe_to_dict(obj):
    """
    Safely convert an object to a dictionary for serialization.
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

class RateLimitManager:
    """
    Manages rate limits for Bluesky API operations.
    - Tracks points used
    - Handles waiting when approaching limits
    - Processes rate limit responses
    """
    # ATProto rate limits
    HOURLY_LIMIT = 5000
    DAILY_LIMIT = 35000
    
    # Points per operation
    POINTS = {
        'delete': 1,
        'create': 3,
        'update': 2
    }
    
    def __init__(self):
        self.hourly_points = 0
        self.daily_points = 0
        self.hour_start = datetime.now()
        self.day_start = datetime.now()
        
    def add_operation(self, operation_type):
        """Add points for an operation and return the new total"""
        points = self.POINTS.get(operation_type, 1)
        
        # Reset counters if needed
        self._check_reset_periods()
        
        # Add points
        self.hourly_points += points
        self.daily_points += points
        
        return self.hourly_points
    
    def _check_reset_periods(self):
        """Check and reset period counters if needed"""
        now = datetime.now()
        
        # Check if hour has passed
        if now - self.hour_start > timedelta(hours=1):
            self.hourly_points = 0
            self.hour_start = now
            print("\nHourly rate limit period reset.")
        
        # Check if day has passed
        if now - self.day_start > timedelta(days=1):
            self.daily_points = 0
            self.day_start = now
            print("\nDaily rate limit period reset.")
    
    def wait_if_needed(self, next_operation_type='delete'):
        """
        Wait if needed to avoid hitting rate limits.
        Returns the suggested wait time in seconds.
        """
        self._check_reset_periods()
        
        points = self.POINTS.get(next_operation_type, 1)
        next_total = self.hourly_points + points
        
        # If we're close to the limit, calculate wait time
        if next_total >= self.HOURLY_LIMIT * 0.95:  # 95% of limit
            # Time remaining in the current hour period
            time_passed = datetime.now() - self.hour_start
            seconds_left_in_hour = 3600 - time_passed.total_seconds()
            
            if seconds_left_in_hour <= 0:
                # Hour should have reset - force a reset check
                self._check_reset_periods()
                return 0
                
            points_remaining = self.HOURLY_LIMIT - self.hourly_points
            
            if points_remaining <= points:
                # We need to wait for the hour to reset
                print(f"\nApproaching hourly rate limit ({self.hourly_points}/{self.HOURLY_LIMIT} points).")
                print(f"Waiting for {seconds_left_in_hour:.1f} seconds until the rate limit resets.")
                return seconds_left_in_hour
            
            # We're getting close, so slow down progressively
            slowdown_factor = 1 - (points_remaining / (self.HOURLY_LIMIT * 0.05))
            wait_time = 5 + (55 * slowdown_factor)  # Between 5-60 seconds
            
            if wait_time > 5:
                print(f"\nSlowing down to avoid rate limits ({self.hourly_points}/{self.HOURLY_LIMIT} points).")
                print(f"Adding {wait_time:.1f} second delay.")
            
            return wait_time
            
        return 0  # No waiting needed
    
    def handle_rate_limit_error(self, error):
        """
        Handle a rate limit error and return how long to wait.
        Extracts the reset time from the error if possible.
        """
        wait_time = 3600  # Default: wait an hour
        
        # Try to extract reset time from error
        if hasattr(error, 'response') and error.response:
            headers = getattr(error.response, 'headers', {})
            reset_header = headers.get('ratelimit-reset')
            
            if reset_header:
                try:
                    # Parse the reset time
                    reset_time = int(reset_header)
                    wait_time = max(reset_time, 60)  # At least 60 seconds
                    print(f"Rate limit reset time specified: {wait_time} seconds")
                except (ValueError, TypeError):
                    print("Couldn't parse rate limit reset header")
        
        return wait_time

def delete_post(client, post_uri, rate_manager):
    """
    Delete a post given its URI.
    Tries first with client.delete_post if available, then falls back to the standard API.
    Returns True if successful, False otherwise.
    Handles rate limiting.
    """
    try:
        # First try the convenience method if it exists
        if hasattr(client, 'delete_post'):
            result = client.delete_post(post_uri)
            rate_manager.add_operation('delete')
            return result
        
        # Fall back to the standard API
        pattern = r'at://([^/]+)/[^/]+/([^/]+)'
        match = re.match(pattern, post_uri)
        if not match:
            print(f"Invalid post URI format: {post_uri}")
            return False
        
        repo, rkey = match.groups()
        
        client.com.atproto.repo.delete_record({
            'repo': repo,
            'collection': 'app.bsky.feed.post',
            'rkey': rkey
        })
        rate_manager.add_operation('delete')
        return True
    except AtProtocolError as e:
        # Check if it's a rate limit error
        if hasattr(e, 'status_code') and e.status_code == 429:
            wait_time = rate_manager.handle_rate_limit_error(e)
            print(f"Rate limit hit. Waiting for {wait_time} seconds before continuing...")
            time.sleep(wait_time)
            # Try again after waiting
            return delete_post(client, post_uri, rate_manager)
        else:
            print(f"Error deleting post {post_uri}: {e}")
            return False
    except Exception as e:
        print(f"Error deleting post {post_uri}: {e}")
        return False

def estimate_total_posts(client):
    """
    Estimate the total number of posts the user has made.
    Does an initial calculation based on the first few batches.
    """
    try:
        # Initialize counters
        total_count = 0
        batch_count = 0
        max_batches_to_check = 5  # Check up to 5 batches for estimation
        cursor = None
        
        print("Sampling posts to estimate total count...")
        
        # Loop through several batches to get a better estimate
        while batch_count < max_batches_to_check:
            posts, next_cursor = fetch_user_posts(client, cursor, limit=100)
            count = len(posts)
            total_count += count
            batch_count += 1
            
            print(f"Batch {batch_count}: Found {count} posts")
            
            if not next_cursor or count == 0:
                # We've reached the end
                print(f"Reached end of posts after {batch_count} batches")
                break
                
            cursor = next_cursor
            
            # If we've checked enough batches and still have more,
            # make a projection for the total
            if batch_count == max_batches_to_check and next_cursor:
                # We've sampled several batches but there are more posts
                print(f"Sampled {total_count} posts, but there are more...")
                
                # Try to get profile info to see total post count if available
                try:
                    user_did = client.me.did
                    profile = client.app.bsky.actor.get_profile({'actor': user_did})
                    if hasattr(profile, 'postsCount'):
                        posts_count = profile.postsCount
                        print(f"Profile reports {posts_count} total posts")
                        return posts_count, posts
                except Exception as e:
                    print(f"Couldn't get post count from profile: {e}")
                
                # Estimate based on what we've seen so far
                # This is a rough projection - assuming uniform distribution
                if batch_count > 0:
                    avg_per_batch = total_count / batch_count
                    # If we consistently get full batches, estimate there are a lot more
                    if avg_per_batch > 90:  # Close to the max 100 per batch
                        print("Account appears to have many posts (1000+)")
                        return "1000+", posts
                
                return f"{total_count}+", posts
        
        print(f"Total posts found: {total_count}")
        return total_count, posts
    except Exception as e:
        print(f"Error estimating posts: {e}")
        return "unknown", []

def ask_for_deletion_mode():
    """
    Ask the user which deletion mode they want to use.
    Returns a tuple of (mode, parameters)
    """
    print("\n" + "=" * 80)
    print("BLUESKY POST DELETION OPTIONS")
    print("=" * 80)
    print("1. Delete ALL posts")
    print("2. Delete last N posts")
    print("3. Delete posts made before a specific date")
    print("=" * 80)
    
    while True:
        choice = input("\nSelect an option (1-3): ").strip()
        
        if choice == '1':
            return 'all', None
        elif choice == '2':
            while True:
                try:
                    n = int(input("Enter number of most recent posts to delete: ").strip())
                    if n <= 0:
                        print("Please enter a positive number.")
                        continue
                    return 'last_n', n
                except ValueError:
                    print("Please enter a valid number.")
        elif choice == '3':
            while True:
                date_str = input("Enter date (YYYY-MM-DD): ").strip()
                try:
                    # Parse the date string
                    cut_off_date = date_parser.parse(date_str).replace(hour=0, minute=0, second=0, microsecond=0)
                    return 'before_date', cut_off_date
                except Exception:
                    print("Invalid date format. Please use YYYY-MM-DD.")
        else:
            print("Invalid option. Please select 1, 2, or 3.")

def should_delete_post(post, mode, params):
    """
    Determine if a post should be deleted based on the selected mode and parameters.
    """
    if mode == 'all':
        return True
    elif mode == 'last_n':
        # This will be handled differently - we'll limit the number of posts we fetch
        return True
    elif mode == 'before_date':
        cut_off_date = params
        post_date = None
        
        # Try to extract the date from the post
        if hasattr(post, 'indexedAt'):
            try:
                post_date = date_parser.parse(post.indexedAt)
            except Exception:
                pass
                
        if post_date is None and hasattr(post, 'record') and hasattr(post.record, 'createdAt'):
            try:
                post_date = date_parser.parse(post.record.createdAt)
            except Exception:
                pass
        
        if post_date is None:
            # If we can't determine the date, we'll skip it to be safe
            print(f"  Warning: Couldn't determine date for post {post.uri}, skipping")
            return False
            
        # Delete if the post was made before the cut-off date
        return post_date < cut_off_date
    
    return False

def main():
    # Get credentials
    filename = input("Enter the credential file name (JSON format): ").strip()
    try:
        username, password = load_credentials_from_file(filename)
    except Exception as e:
        print(f"Error loading credentials: {e}")
        sys.exit(1)
        
    if not username or not password:
        print("Missing required authentication fields (username, password) in the credentials file.")
        sys.exit(1)
    
    # Set up parameters
    backup_filename = input("Enter backup pickle filename (default: bluesky_posts_backup.pickle): ").strip() or "bluesky_posts_backup.pickle"
    
    # Initialize client and login FIRST to get account details
    print("Logging in to Bluesky...")
    client = Client()
    try:
        client.login(username, password)
        print(f"Login successful as {username}!")
        
        # Get account details to display in warning
        user_did = client.me.did
        user_handle = getattr(client.me, 'handle', username)
        
        # Get display name if available
        try:
            profile = client.app.bsky.actor.get_profile({'actor': user_did})
            display_name = getattr(profile, 'displayName', None)
        except Exception:
            display_name = None
            
        account_info = f"@{user_handle}"
        if display_name:
            account_info = f"{display_name} ({account_info})"
        account_info += f" [DID: {user_did}]"
        
    except Exception as e:
        print(f"Login failed: {e}")
        sys.exit(1)
    
    # Ask for deletion mode
    deletion_mode, deletion_params = ask_for_deletion_mode()
    
    # Estimate total posts
    estimated_posts_to_delete = "unknown"
    time_estimate = "unknown"
    
    print("\nEstimating number of posts to delete...")
    estimated_total_posts, first_batch = estimate_total_posts(client)
    
    # Calculate time estimates based on mode
    if deletion_mode == 'all':
        estimated_posts_to_delete = estimated_total_posts
        if isinstance(estimated_total_posts, int):
            estimated_points = estimated_total_posts  # 1 point per delete
            estimated_hours = math.ceil(estimated_points / 5000)
            time_estimate = f"about {estimated_hours} hour(s)" if estimated_hours > 0 else "less than an hour"
        elif isinstance(estimated_total_posts, str) and estimated_total_posts.endswith('+'):
            # For "1000+" or similar format
            base_number = estimated_total_posts.rstrip('+')
            if base_number.isdigit():
                minimum_points = int(base_number)
                minimum_hours = math.ceil(minimum_points / 5000)
                time_estimate = f"at least {minimum_hours} hour(s), likely more"
            else:
                time_estimate = "several hours, depending on post count"
        else:
            time_estimate = "several hours, depending on post count"
    
    elif deletion_mode == 'last_n':
        n = deletion_params
        if isinstance(estimated_total_posts, int):
            estimated_posts_to_delete = min(n, estimated_total_posts)
            estimated_hours = math.ceil(estimated_posts_to_delete / 5000)
            time_estimate = f"about {estimated_hours} hour(s)" if estimated_hours > 0 else "less than an hour"
        else:
            estimated_posts_to_delete = f"up to {n}"
            estimated_hours = math.ceil(n / 5000)
            time_estimate = f"up to {estimated_hours} hour(s)"
    
    elif deletion_mode == 'before_date':
        cut_off_date = deletion_params
        # We can't easily estimate how many posts are before the date without fetching them all
        estimated_posts_to_delete = f"posts before {cut_off_date.strftime('%Y-%m-%d')}"
        time_estimate = "varies depending on how many posts match"
    
    # Format warning message based on deletion mode
    warning_message = "WARNING: "
    confirmation_prompt = ""
    
    if deletion_mode == 'all':
        warning_message += f"You are about to DELETE ALL POSTS from account:"
        confirmation_prompt = f"Are you sure you want to delete ALL POSTS from {account_info}?"
    elif deletion_mode == 'last_n':
        warning_message += f"You are about to DELETE YOUR LAST {deletion_params} POSTS from account:"
        confirmation_prompt = f"Are you sure you want to delete your LAST {deletion_params} POSTS from {account_info}?"
    elif deletion_mode == 'before_date':
        date_str = deletion_params.strftime('%Y-%m-%d')
        warning_message += f"You are about to DELETE ALL POSTS BEFORE {date_str} from account:"
        confirmation_prompt = f"Are you sure you want to delete ALL POSTS BEFORE {date_str} from {account_info}?"
    
    # Add confirmation with ACCOUNT DETAILS and ESTIMATED TIME before starting
    print("\n" + "=" * 80)
    print(warning_message)
    print(f"   {account_info}")
    print(f"Estimated posts to delete: {estimated_posts_to_delete}")
    print(f"Estimated time to complete: {time_estimate}")
    print(f"The process will respect Bluesky's rate limits (5000 points/hour)")
    print("All posts will be backed up locally before deletion.")
    print("Please make sure you understand what this means before continuing.")
    print("=" * 80)
    
    confirm = input(f"\n{confirmation_prompt}\nType 'YES DELETE' to confirm: ")
    if confirm != "YES DELETE":
        print("Operation cancelled.")
        sys.exit(0)
    
    # Initialize rate limit manager
    rate_manager = RateLimitManager()
    
    # Fetch and process posts
    print("Starting to fetch and delete posts...")
    all_posts = []
    deleted_count = 0
    skipped_count = 0
    cursor = None
    
    # For 'last_n' mode, we need to limit how many posts we process
    posts_left_to_delete = None
    if deletion_mode == 'last_n':
        posts_left_to_delete = deletion_params
    
    # Add first batch to all_posts if we have it
    if first_batch:
        all_posts.extend(first_batch)
        print(f"First batch: {len(first_batch)} posts")
    
    try:
        batch_count = 0
        total_batches = "multiple"
        if isinstance(estimated_total_posts, int) and estimated_total_posts > 0:
            total_batches = math.ceil(estimated_total_posts / 100)
        
        while True:
            batch_count += 1
            
            # If we're in 'last_n' mode and have processed enough posts, we're done
            if deletion_mode == 'last_n' and posts_left_to_delete <= 0:
                print(f"Reached the target of {deletion_params} posts. Completed.")
                break
            
            # If we don't have a first batch already, fetch posts
            if not first_batch or cursor:
                print(f"\nFetching batch {batch_count}/{total_batches if isinstance(total_batches, int) else total_batches}...")
                
                # For 'last_n' mode, limit the fetch size to what we still need
                fetch_limit = 100
                if deletion_mode == 'last_n' and posts_left_to_delete < 100:
                    fetch_limit = posts_left_to_delete
                
                posts, cursor = fetch_user_posts(client, cursor, limit=fetch_limit)
                
                if not posts:
                    print("No more posts found.")
                    break
                
                print(f"Fetched {len(posts)} posts.")
                all_posts.extend(posts)
                first_batch = None  # Reset for next iterations
            else:
                # Use the first batch we already have
                posts = first_batch
                first_batch = None  # Reset for next iterations
            
            # Save the backup after each fetch to ensure data isn't lost
            print(f"Saving backup to {backup_filename}...")
            try:
                with open(backup_filename, 'wb') as f:
                    pickle.dump([safe_to_dict(post) for post in all_posts], f)
                print(f"Saved {len(all_posts)} posts to backup file.")
            except Exception as e:
                print(f"Error saving backup: {e}")
                continue
            
            # Process the current batch
            print(f"Processing batch {batch_count} ({len(posts)} posts) for deletion...")
            for i, post in enumerate(posts):
                post_uri = post.uri
                post_text = getattr(post.record, 'text', '[No text]') if hasattr(post, 'record') else '[No text]'
                truncated_text = (post_text[:50] + '...') if len(post_text) > 50 else post_text
                
                # Show progress for large batches
                progress = f"[{i+1}/{len(posts)}] "
                
                # Check if we should delete this post based on mode
                if not should_delete_post(post, deletion_mode, deletion_params):
                    print(f"\n{progress}Skipping post (doesn't match criteria): {post_uri}")
                    print(f"Content: {truncated_text}")
                    skipped_count += 1
                    continue
                
                # Check if we need to wait for rate limits
                wait_time = rate_manager.wait_if_needed('delete')
                if wait_time > 0:
                    print(f"Waiting {wait_time:.1f} seconds to avoid rate limits...")
                    time.sleep(wait_time)
                
                print(f"\n{progress}Deleting post: {post_uri}")
                print(f"Content: {truncated_text}")
                
                if delete_post(client, post_uri, rate_manager):
                    deleted_count += 1
                    
                    # Update 'last_n' counter if needed
                    if deletion_mode == 'last_n':
                        posts_left_to_delete -= 1
                    
                    print(f"Successfully deleted post. Total deleted: {deleted_count}")
                    print(f"Rate limit points used: {rate_manager.hourly_points}/{rate_manager.HOURLY_LIMIT} this hour")
                else:
                    print(f"Failed to delete post.")
                
                # Check if we need a small delay between operations
                actual_delay = rate_manager.wait_if_needed('delete') / 10
                if actual_delay > 0:
                    print(f"Pausing for {actual_delay:.1f} seconds...")
                    time.sleep(actual_delay)
                
                # If we're in 'last_n' mode and have processed enough posts, we're done with this batch
                if deletion_mode == 'last_n' and posts_left_to_delete <= 0:
                    break
            
            # If we're in 'last_n' mode and have processed enough posts, we're done
            if deletion_mode == 'last_n' and posts_left_to_delete <= 0:
                print(f"Reached the target of {deletion_params} posts. Completed.")
                break
            
            if not cursor:
                print("No more posts to fetch. Completed.")
                break
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
    finally:
        # Final summary
        print("\n" + "=" * 80)
        print(f"Process complete!")
        if deletion_mode == 'all':
            print(f"Deletion mode: All posts")
        elif deletion_mode == 'last_n':
            print(f"Deletion mode: Last {deletion_params} posts")
        elif deletion_mode == 'before_date':
            date_str = deletion_params.strftime('%Y-%m-%d')
            print(f"Deletion mode: All posts before {date_str}")
        print(f"Total posts backed up: {len(all_posts)}")
        print(f"Total posts deleted: {deleted_count}")
        print(f"Total posts skipped: {skipped_count}")
        print(f"Backup saved to: {backup_filename}")
        print("=" * 80)

if __name__ == '__main__':
    main()
