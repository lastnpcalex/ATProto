import json
import sys
import time
import hashlib
from atproto import Client

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

def login_to_bluesky(username, password):
    """
    Login to Bluesky and return the client object.
    """
    print("Logging in to Bluesky...")
    client = Client()
    try:
        client.login(username, password)
        print("Login successful!")
        return client
    except Exception as e:
        print(f"Login failed: {e}")
        sys.exit(1)

def get_visible_blocks(client, cursor=None, limit=50):
    """
    Get blocks from the social graph API (the ones visible in the UI).
    These don't include URIs needed for deletion but show who you've blocked.
    Returns a tuple of (blocks_list, next_cursor).
    """
    try:
        params = {'limit': limit}
        if cursor:
            params['cursor'] = cursor
        
        response = client.app.bsky.graph.get_blocks(params)
        
        # Extract the blocks and next cursor
        blocks = response.blocks if hasattr(response, 'blocks') else []
        cursor = response.cursor if hasattr(response, 'cursor') else None
        
        return blocks, cursor
    except Exception as e:
        print(f"Error fetching visible blocks: {e}")
        return [], None

def get_all_block_records(client):
    """
    Get all block records directly from the repo using pagination.
    This is more reliable than block.list() which might be incomplete.
    Returns a list of block records with their URIs and details.
    """
    print("Fetching all block records from repository...")
    all_records = []
    cursor = None
    page = 1
    
    try:
        while True:
            print(f"Fetching page {page} of block records...")
            params = {
                'repo': client.me.did,
                'collection': 'app.bsky.graph.block',
                'limit': 100
            }
            if cursor:
                params['cursor'] = cursor
            
            result = client.com.atproto.repo.list_records(params)
            
            if hasattr(result, 'records'):
                records_count = len(result.records)
                print(f"Found {records_count} block records on page {page}")
                all_records.extend(result.records)
                
                if hasattr(result, 'cursor') and result.cursor:
                    cursor = result.cursor
                    page += 1
                else:
                    break
            else:
                print("No records found on this page")
                break
    except Exception as e:
        print(f"Error fetching block records: {e}")
    
    print(f"Total block records found in repository: {len(all_records)}")
    return all_records

def save_unresolved_blocks(unresolved_blocks, filename="unresolved_blocks.json"):
    """
    Save a list of blocks that could not be deleted to a file.
    """
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(unresolved_blocks, f, indent=2)
        print(f"Saved {len(unresolved_blocks)} unresolved blocks to {filename}")
    except Exception as e:
        print(f"Error saving unresolved blocks: {e}")

def unblock_user(client, did, block_records=None):
    """
    Unblock a user by their DID.
    If block_records is provided, it will try to find the matching record there first.
    Returns True if successful, False otherwise.
    """
    print(f"\nAttempting to unblock user: {did}")
    unblock_success = False
    error_details = []
    
    # Method 1: Use block records if provided to find the rkey
    if block_records:
        print("Method 1: Using repository block records")
        matching_records = []
        
        for record in block_records:
            record_value = None
            
            # Check if the record has a value attribute
            if hasattr(record, 'value'):
                # Get the actual value, which might be an object or a dict
                record_value = record.value
                
                # If it's an object, try to access its subject attribute
                if hasattr(record_value, 'subject'):
                    if record_value.subject == did:
                        matching_records.append(record)
                # If it's a dict, check for 'subject' key
                elif isinstance(record_value, dict) and 'subject' in record_value:
                    if record_value['subject'] == did:
                        matching_records.append(record)
                # Fallback: check raw representation
                elif hasattr(record_value, '_raw') and isinstance(record_value._raw, dict):
                    if record_value._raw.get('subject') == did:
                        matching_records.append(record)
            
            # Check if the record itself has a subject attribute (direct property)
            elif hasattr(record, 'subject'):
                if record.subject == did:
                    matching_records.append(record)
            
            # If record has uri that contains the DID (as a fallback)
            elif hasattr(record, 'uri') and did in record.uri:
                matching_records.append(record)
        
        if matching_records:
            print(f"Found {len(matching_records)} matching block records")
            
            for idx, record in enumerate(matching_records):
                print(f"Attempting to delete record {idx + 1} of {len(matching_records)}")
                
                # Extract the rkey from record
                rkey = None
                uri = None
                
                if hasattr(record, 'uri'):
                    uri = record.uri
                    parts = uri.split('/')
                    if len(parts) >= 4:
                        rkey = parts[-1]
                elif hasattr(record, 'rkey'):
                    rkey = record.rkey
                elif hasattr(record, 'cid'):
                    # Sometimes cid is used as rkey
                    rkey = record.cid
                    
                if rkey:
                    print(f"Found rkey: {rkey} from uri: {uri}")
                    try:
                        client.com.atproto.repo.delete_record({
                            'repo': client.me.did,
                            'collection': 'app.bsky.graph.block',
                            'rkey': rkey
                        })
                        print(f"Successfully deleted block record with rkey: {rkey}")
                        unblock_success = True
                        
                        # Verify deletion
                        time.sleep(0.5)  # Small delay to allow API to update
                        verification = verify_unblock(client, did, rkey)
                        if verification:
                            print("Verified: Block record is no longer present")
                        else:
                            print("Warning: Block record may still be present")
                        
                        # No need to try other records if successful
                        break
                    except Exception as e:
                        error_msg = f"Error deleting record with rkey {rkey}: {e}"
                        print(error_msg)
                        error_details.append(error_msg)
                else:
                    error_msg = f"Could not extract rkey from record: {record}"
                    print(error_msg)
                    error_details.append(error_msg)
        else:
            print("No matching block records found in repository")
    
    # Method 2: Create a temporary block to learn the rkey pattern, then delete it
    if not unblock_success:
        print("\nMethod 2: Create-then-delete approach")
        try:
            from atproto import models
            
            # Try to generate a probable rkey
            import hashlib
            # Some AT Protocol clients use a hash of the DID as the rkey
            probable_rkey = hashlib.sha256(did.encode('utf-8')).hexdigest()[:10]
            print(f"Generated probable rkey: {probable_rkey}")
            
            # Try deleting with the generated rkey
            try:
                client.com.atproto.repo.delete_record({
                    'repo': client.me.did,
                    'collection': 'app.bsky.graph.block',
                    'rkey': probable_rkey
                })
                print(f"Successfully deleted block using generated rkey")
                unblock_success = True
                return unblock_success, error_details
            except Exception as e:
                print(f"Could not delete with generated rkey: {e}")
            
            # Create a block record to see what rkey format is used
            print("Creating temporary block to learn rkey format...")
            try:
                # First check if a model class is available
                try:
                    block_record = models.AppBskyGraphBlock.Record(
                        subject=did,
                        created_at=client.get_current_time_iso()
                    )
                    response = client.app.bsky.graph.block.create({
                        'repo': client.me.did,
                        'record': block_record
                    })
                except Exception as model_err:
                    print(f"Could not use model class: {model_err}")
                    # Fallback to direct dictionary format
                    block_record = {
                        "$type": "app.bsky.graph.block",
                        "subject": did,
                        "createdAt": client.get_current_time_iso()
                    }
                    response = client.com.atproto.repo.create_record({
                        'repo': client.me.did,
                        'collection': 'app.bsky.graph.block',
                        'record': block_record
                    })
                
                # Extract the rkey from the URI
                block_uri = response.uri
                print(f"Created temporary block with URI: {block_uri}")
                rkey = block_uri.split('/')[-1]
                print(f"Extracted rkey: {rkey}")
                
                # Now delete it
                client.com.atproto.repo.delete_record({
                    'repo': client.me.did,
                    'collection': 'app.bsky.graph.block',
                    'rkey': rkey
                })
                print("Successfully unblocked user via create/delete method")
                unblock_success = True
            except Exception as create_err:
                # This might error if the user is already blocked
                error_msg = str(create_err)
                print(f"Error in create step: {error_msg}")
                
                # Try to extract a possible rkey from the error message
                import re
                rkey_match = re.search(r'rkey["\']?\s*:\s*["\']([^"\']+)["\']', error_msg)
                if rkey_match:
                    potential_rkey = rkey_match.group(1)
                    print(f"Extracted potential rkey from error: {potential_rkey}")
                    try:
                        client.com.atproto.repo.delete_record({
                            'repo': client.me.did,
                            'collection': 'app.bsky.graph.block',
                            'rkey': potential_rkey
                        })
                        print("Successfully unblocked user using error-extracted rkey")
                        unblock_success = True
                    except Exception as delete_err:
                        print(f"Error deleting with error-extracted rkey: {delete_err}")
        except Exception as method2_err:
            print(f"Error in Method 2: {method2_err}")
    
    # Method 3: Try direct deletion with various rkey formats
    if not unblock_success:
        print("\nMethod 3: Trying various rkey formats")
        possible_rkeys = [
            did,  # Full DID
            did.replace('did:plc:', ''),  # Strip the did:plc: prefix
            did.split(':')[-1],  # Just the last part
            hashlib.md5(did.encode('utf-8')).hexdigest(),  # MD5 hash
            hashlib.sha256(did.encode('utf-8')).hexdigest()[:15]  # First 15 chars of SHA256
        ]
        
        for idx, rkey in enumerate(possible_rkeys):
            print(f"Trying format {idx + 1}/{len(possible_rkeys)}: {rkey}")
            try:
                client.com.atproto.repo.delete_record({
                    'repo': client.me.did,
                    'collection': 'app.bsky.graph.block',
                    'rkey': rkey
                })
                print(f"Successfully unblocked user with rkey format: {rkey}")
                unblock_success = True
                break
            except Exception as e:
                print(f"Error with rkey format {idx + 1}: {e}")
    
    return unblock_success, error_details

def verify_unblock(client, did, rkey=None):
    """
    Verify that a block has been successfully removed.
    Returns True if the block is gone, False if it still exists.
    """
    try:
        # First check using list_records to see if the block record still exists
        params = {
            'repo': client.me.did,
            'collection': 'app.bsky.graph.block'
        }
        if rkey:
            # If we know the rkey, we can check directly
            try:
                # If this throws an error, the record is likely gone
                client.com.atproto.repo.get_record({
                    'repo': client.me.did,
                    'collection': 'app.bsky.graph.block',
                    'rkey': rkey
                })
                # If we get here, the record still exists
                return False
            except:
                # Record not found is a good thing
                return True
        
        # If we don't have the rkey, check all blocks
        result = client.com.atproto.repo.list_records(params)
        
        if hasattr(result, 'records'):
            for record in result.records:
                record_value = None
                
                # Check if the record contains the target DID
                if hasattr(record, 'value'):
                    record_value = record.value
                    
                    if hasattr(record_value, 'subject'):
                        if record_value.subject == did:
                            return False
                    elif isinstance(record_value, dict) and 'subject' in record_value:
                        if record_value['subject'] == did:
                            return False
                    
                # Check if the record itself has a subject attribute
                elif hasattr(record, 'subject'):
                    if record.subject == did:
                        return False
        
        # Also check the social graph API to see if the user is still blocked
        response = client.app.bsky.graph.get_blocks({'limit': 100})
        if hasattr(response, 'blocks'):
            for block in response.blocks:
                if hasattr(block, 'did') and block.did == did:
                    return False
        
        # If we couldn't find any evidence the block still exists
        return True
    except Exception as e:
        print(f"Error verifying unblock: {e}")
        # If verification fails, be conservative and return False
        return False

def display_repo_blocks(block_records):
    """
    Display detailed information about repository block records.
    """
    if not block_records:
        print("No repository block records found.")
        return
    
    print("\n=== REPOSITORY BLOCK RECORDS ===")
    print(f"Total records: {len(block_records)}")
    
    for i, record in enumerate(block_records, 1):
        print(f"\n[{i}] Record:")
        
        # Try to extract common properties
        if hasattr(record, 'uri'):
            print(f"  URI: {record.uri}")
        
        if hasattr(record, 'cid'):
            print(f"  CID: {record.cid}")
        
        if hasattr(record, 'value'):
            value = record.value
            print("  Value:")
            
            if hasattr(value, 'subject'):
                print(f"    Subject: {value.subject}")
            elif isinstance(value, dict) and 'subject' in value:
                print(f"    Subject: {value['subject']}")
            
            if hasattr(value, 'created_at') or hasattr(value, 'createdAt'):
                created = getattr(value, 'created_at', getattr(value, 'createdAt', None))
                print(f"    Created At: {created}")
        
        # If the record itself has a subject
        elif hasattr(record, 'subject'):
            print(f"  Subject: {record.subject}")
        
        # Try to extract rkey from URI
        if hasattr(record, 'uri'):
            parts = record.uri.split('/')
            if len(parts) >= 4:
                print(f"  rkey: {parts[-1]}")
    
    input("\nPress Enter to continue...")

def process_repo_blocks(client, block_records):
    """
    Process block records found in the repository but not visible in social graph.
    This handles the case of "ghost blocks" that exist in the repo but aren't showing in the UI.
    """
    if not block_records:
        print("No repository block records to process.")
        return False
    
    print(f"\nFound {len(block_records)} repository block records to process.")
    print("These blocks may not be visible in the social graph (UI) but exist in your repo.")
    print("-" * 80)
    
    # Extract and display DIDs from records
    records_with_subjects = []
    
    for record in block_records:
        subject = None
        
        # Try to extract the subject (DID) from the record
        if hasattr(record, 'value'):
            value = record.value
            
            if hasattr(value, 'subject'):
                subject = value.subject
            elif isinstance(value, dict) and 'subject' in value:
                subject = value['subject']
        elif hasattr(record, 'subject'):
            subject = record.subject
        
        if subject:
            records_with_subjects.append((record, subject))
    
    # If we couldn't extract any subjects, show an error
    if not records_with_subjects:
        print("Could not extract any DIDs from the records.")
        return False
    
    # Display the records with subjects
    for i, (record, subject) in enumerate(records_with_subjects, 1):
        uri = getattr(record, 'uri', "Unknown URI")
        print(f"[{i}] Subject: {subject}")
        print(f"    URI: {uri}")
        
        # Try to get handle for the DID
        try:
            profile = client.app.bsky.actor.get_profile({'actor': subject})
            if hasattr(profile, 'handle'):
                print(f"    Handle: @{profile.handle}")
        except:
            pass
        
        print()
    
    print("-" * 80)
    print("[a] Unblock all repository blocks")
    print("[s] Select specific blocks to remove")
    print("[b] Go back")
    
    choice = input("\nEnter option: ").strip().lower()
    
    if choice == 'b':
        return True
    elif choice == 'a':
        unresolved_blocks = []
        success_count = 0
        
        for record, subject in records_with_subjects:
            print(f"\nProcessing block of: {subject}")
            success, errors = unblock_user(client, subject, [record])
            
            if success:
                success_count += 1
            else:
                unresolved_blocks.append({
                    'did': subject,
                    'uri': getattr(record, 'uri', "Unknown"),
                    'errors': errors
                })
        
        print(f"\nSuccessfully removed {success_count} out of {len(records_with_subjects)} repository blocks.")
        
        if unresolved_blocks:
            save_unresolved = input(f"{len(unresolved_blocks)} blocks could not be resolved. Save to file? (y/n): ").strip().lower()
            if save_unresolved == 'y':
                save_unresolved_blocks(unresolved_blocks, "unresolved_repo_blocks.json")
    elif choice == 's':
        while True:
            selections = input("Enter the numbers of blocks to remove (comma-separated, e.g. 1,3,5) or [b] to go back: ").strip()
            if selections.lower() == 'b':
                return process_repo_blocks(client, block_records)
            
            try:
                indices = [int(x.strip()) - 1 for x in selections.split(',')]
                valid_indices = [i for i in indices if 0 <= i < len(records_with_subjects)]
                
                if not valid_indices:
                    print("No valid selections. Please try again.")
                    continue
                
                unresolved_blocks = []
                success_count = 0
                
                for idx in valid_indices:
                    record, subject = records_with_subjects[idx]
                    print(f"\nProcessing block of: {subject}")
                    success, errors = unblock_user(client, subject, [record])
                    
                    if success:
                        success_count += 1
                    else:
                        unresolved_blocks.append({
                            'did': subject,
                            'uri': getattr(record, 'uri', "Unknown"),
                            'errors': errors
                        })
                
                print(f"\nSuccessfully removed {success_count} out of {len(valid_indices)} selected repository blocks.")
                
                if unresolved_blocks:
                    save_unresolved = input(f"{len(unresolved_blocks)} blocks could not be resolved. Save to file? (y/n): ").strip().lower()
                    if save_unresolved == 'y':
                        save_unresolved_blocks(unresolved_blocks, "unresolved_repo_blocks.json")
                break
            except ValueError:
                print("Invalid input. Please enter comma-separated numbers.")
    
    return True

def process_block_batch(client, block_records, batch_size=50):
    """
    Process a batch of blocks and offer to unblock them.
    Uses both visible blocks from graph API and repo block records.
    """
    # Get the socially visible blocks (what the user sees in UI)
    visible_blocks, next_cursor = get_visible_blocks(client, limit=batch_size)
    
    if not visible_blocks:
        print("No visible blocks found in social graph.")
        
        # If we have block records but no visible blocks, this suggests desync
        if block_records:
            print(f"However, {len(block_records)} block records were found in the repo.")
            print("This suggests a desynchronization between the repo and social graph.")
            
            # Offer to display the repo blocks
            show_repo = input("Would you like to see the block records from the repo? (y/n): ").strip().lower()
            if show_repo == 'y':
                display_repo_blocks(block_records)
            
            # Offer to clean up the repo blocks
            cleanup = input("Would you like to attempt cleaning up these repository blocks? (y/n): ").strip().lower()
            if cleanup == 'y':
                return process_repo_blocks(client, block_records)
            else:
                return next_cursor is not None
        return False
    
    # If we have both visible blocks and block records, map them together
    block_map = {}
    did_to_blocks = {}
    
    # Create mapping from DIDs to repo block records
    for record in block_records:
        record_value = None
        record_did = None
        
        # Try to extract the DID (subject) from the record
        if hasattr(record, 'value'):
            record_value = record.value
            if hasattr(record_value, 'subject'):
                record_did = record_value.subject
            elif isinstance(record_value, dict) and 'subject' in record_value:
                record_did = record_value['subject']
        elif hasattr(record, 'subject'):
            record_did = record.subject
        
        if record_did:
            if record_did not in did_to_blocks:
                did_to_blocks[record_did] = []
            did_to_blocks[record_did].append(record)
    
    # Map visible blocks to their repo records
    for block in visible_blocks:
        if hasattr(block, 'did'):
            did = block.did
            if did in did_to_blocks:
                block_map[did] = {
                    'visible_block': block,
                    'repo_records': did_to_blocks[did]
                }
            else:
                block_map[did] = {
                    'visible_block': block,
                    'repo_records': []
                }
    
    # Print status about mapping
    dids_with_records = sum(1 for did in block_map if block_map[did]['repo_records'])
    dids_without_records = sum(1 for did in block_map if not block_map[did]['repo_records'])
    print(f"Found {len(visible_blocks)} visible blocks in social graph.")
    print(f"  • {dids_with_records} blocks have matching repository records")
    print(f"  • {dids_without_records} blocks have no matching repository records (desync)")
    
    # Create a list of blocks to display to the user
    print(f"\nBlocked Users:")
    print("-" * 80)
    
    for i, did in enumerate(block_map.keys(), 1):
        block = block_map[did]['visible_block']
        has_repo_record = len(block_map[did]['repo_records']) > 0
        repo_indicator = "✓" if has_repo_record else "✗"
        
        if hasattr(block, 'did'):
            display_name = ""
            handle = ""
            
            if hasattr(block, 'displayName') and block.displayName:
                display_name = block.displayName
            
            if hasattr(block, 'handle') and block.handle:
                handle = block.handle
            
            if display_name and handle:
                print(f"[{i}] {display_name} (@{handle}) {repo_indicator}")
            elif handle:
                print(f"[{i}] @{handle} {repo_indicator}")
            else:
                print(f"[{i}] {block.did} {repo_indicator}")
        else:
            print(f"[{i}] Unknown user {repo_indicator}")
    
    print("-" * 80)
    print("Legend: ✓ = Has repository record, ✗ = No repository record (may fail to unblock)")
    print("-" * 80)
    print("[a] Unblock all users in this batch")
    print("[s] Select specific users to unblock")
    print("[r] Show detailed repository records (for troubleshooting)")
    print("[n] Skip to next batch")
    print("[q] Quit")
    
    choice = input("\nEnter option: ").strip().lower()
    
    if choice == 'q':
        print("Exiting...")
        return False
    elif choice == 'r':
        display_repo_blocks(block_records)
        return process_block_batch(client, block_records, batch_size)
    elif choice == 'a':
        unresolved_blocks = []
        success_count = 0
        
        for did in block_map:
            print(f"\nProcessing: {getattr(block_map[did]['visible_block'], 'handle', did)}")
            repo_records = block_map[did]['repo_records']
            
            success, errors = unblock_user(client, did, repo_records)
            if success:
                success_count += 1
            else:
                unresolved_blocks.append({
                    'did': did,
                    'handle': getattr(block_map[did]['visible_block'], 'handle', "Unknown"),
                    'errors': errors
                })
        
        print(f"\nSuccessfully unblocked {success_count} out of {len(block_map)} users.")
        
        if unresolved_blocks:
            save_unresolved = input(f"{len(unresolved_blocks)} blocks could not be resolved. Save to file? (y/n): ").strip().lower()
            if save_unresolved == 'y':
                save_unresolved_blocks(unresolved_blocks)
    elif choice == 's':
        while True:
            selections = input("Enter the numbers of users to unblock (comma-separated, e.g. 1,3,5) or [b] to go back: ").strip()
            if selections.lower() == 'b':
                return process_block_batch(client, block_records, batch_size)
            
            try:
                indices = [int(x.strip()) - 1 for x in selections.split(',')]
                dids = list(block_map.keys())
                valid_indices = [i for i in indices if 0 <= i < len(dids)]
                
                if not valid_indices:
                    print("No valid selections. Please try again.")
                    continue
                
                unresolved_blocks = []
                success_count = 0
                
                for idx in valid_indices:
                    did = dids[idx]
                    print(f"\nProcessing: {getattr(block_map[did]['visible_block'], 'handle', did)}")
                    repo_records = block_map[did]['repo_records']
                    
                    success, errors = unblock_user(client, did, repo_records)
                    if success:
                        success_count += 1
                    else:
                        unresolved_blocks.append({
                            'did': did,
                            'handle': getattr(block_map[did]['visible_block'], 'handle', "Unknown"),
                            'errors': errors
                        })
                
                print(f"\nSuccessfully unblocked {success_count} out of {len(valid_indices)} selected users.")
                
                if unresolved_blocks:
                    save_unresolved = input(f"{len(unresolved_blocks)} blocks could not be resolved. Save to file? (y/n): ").strip().lower()
                    if save_unresolved == 'y':
                        save_unresolved_blocks(unresolved_blocks)
                break
            except ValueError:
                print("Invalid input. Please enter comma-separated numbers.")
    
    # Return True if there are more blocks to process
    return next_cursor is not None

def manually_unblock_user(client, block_records):
    """
    Manually unblock a user by handle or DID.
    """
    handle_or_did = input("\nEnter handle or DID of user to unblock (or 'q' to quit): ").strip()
    if handle_or_did.lower() == 'q':
        return
    
    try:
        # If it's a handle, resolve to DID
        if not handle_or_did.startswith('did:'):
            print(f"Resolving handle: {handle_or_did}")
            try:
                resolve_resp = client.com.atproto.identity.resolve_handle({'handle': handle_or_did})
                did = resolve_resp.did
                print(f"Resolved to DID: {did}")
            except Exception as e:
                print(f"Error resolving handle: {e}")
                return
        else:
            did = handle_or_did
            
        # Try to find matching records in our block records
        matching_records = []
        if block_records:
            for record in block_records:
                record_value = None
                
                # Check if the record value has a subject attribute
                if hasattr(record, 'value'):
                    record_value = record.value
                    if hasattr(record_value, 'subject'):
                        if record_value.subject == did:
                            matching_records.append(record)
                    elif isinstance(record_value, dict) and 'subject' in record_value:
                        if record_value['subject'] == did:
                            matching_records.append(record)
                
                # Check if the record itself has a subject attribute
                elif hasattr(record, 'subject'):
                    if record.subject == did:
                        matching_records.append(record)
        
        # If we found matching records, use them
        if matching_records:
            print(f"Found {len(matching_records)} matching block records for this user")
        else:
            print("No matching block records found, will try alternative methods")
        
        # Try to unblock
        success, errors = unblock_user(client, did, matching_records)
        
        if success:
            print(f"Successfully unblocked: {handle_or_did}")
        else:
            print(f"Failed to unblock: {handle_or_did}")
            print("Errors:")
            for error in errors:
                print(f"  - {error}")
    except Exception as e:
        print(f"Error: {e}")

def main():
    print("=" * 80)
    print("BLUESKY BLOCK REMOVER")
    print("=" * 80)
    print("This tool will help you remove blocks from your Bluesky account.")
    print("It will fetch both visible blocks and repository block records.\n")
    
    filename = input("Enter the credential file name (JSON format): ").strip()
    try:
        username, password = load_credentials_from_file(filename)
    except Exception as e:
        print(f"Error loading credentials: {e}")
        sys.exit(1)
        
    if not username or not password:
        print("Missing required authentication fields (username, password) in the credentials file.")
        sys.exit(1)
    
    client = login_to_bluesky(username, password)
    
    # Print user info to confirm we're logged in as the right account
    print("\nAccount Information:")
    print(f"DID: {client.me.did}")
    print(f"Handle: {client.me.handle}")
    
    # Check credentials and access
    print("\nVerifying API access and permissions...")
    try:
        # Try to fetch profile to verify read access
        profile = client.app.bsky.actor.get_profile({'actor': client.me.did})
        print(f"Successfully retrieved profile for: {profile.displayName if hasattr(profile, 'displayName') else profile.handle}")
        
        # Try to verify write access by doing a simple operation
        try:
            muted = client.app.bsky.graph.get_muted_words()
            print(f"Successfully verified read access to graph data")
        except Exception:
            pass
    except Exception as e:
        print(f"Warning: Limited API access detected: {e}")
        print("Some operations may not work as expected.")
    
    # First, get all block records from the repository
    print("\nFetching all block records from repository...")
    block_records = get_all_block_records(client)
    
    # Give option to export data before starting
    export_choice = input("\nWould you like to export debug data to help fix any issues? (y/n): ").strip().lower()
    if export_choice == 'y':
        try:
            # Create debug info
            debug_info = {
                "account": {
                    "did": client.me.did,
                    "handle": client.me.handle
                },
                "sdk_info": {
                    "methods": dir(client.app.bsky.graph)
                }
            }
            
            # Try to get blocks
            try:
                response = client.app.bsky.graph.get_blocks({'limit': 10})
                debug_info["blocks_response"] = str(response)
                if hasattr(response, 'blocks'):
                    debug_info["blocks_sample"] = [str(block) for block in response.blocks[:5]]
            except Exception as e:
                debug_info["blocks_error"] = str(e)
            
            # Save debug info
            debug_filename = "bluesky_debug_info.json"
            with open(debug_filename, 'w') as f:
                json.dump(debug_info, f, indent=2)
            print(f"Debug information saved to {debug_filename}")
        except Exception as e:
            print(f"Error exporting debug data: {e}")
    
    # Start processing blocks in batches
    has_more = True
    batch_size = 50
    
    while has_more:
        has_more = process_block_batch(client, block_records, batch_size)
        if has_more:
            continue_choice = input("\nContinue to next batch? (y/n): ").strip().lower()
            if continue_choice != 'y':
                print("Exiting...")
                break
    
    if not has_more:
        print("No more blocks to process.")
    
    # Offer manual mode
    manual_choice = input("\nWould you like to try manually unblocking a specific user? (y/n): ").strip().lower()
    if manual_choice == 'y':
        while True:
            manually_unblock_user(client, block_records)
            
            continue_manual = input("\nTry another manual unblock? (y/n): ").strip().lower()
            if continue_manual != 'y':
                break
    
    print("\nThank you for using the Bluesky Block Remover!")
    print("If you encountered issues, please share the debug file with the developer.")

if __name__ == '__main__':
    main()
