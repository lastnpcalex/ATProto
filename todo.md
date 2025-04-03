# TODO List for Bluesky Thread Explorer

## Bug Fixes

### Time Stamp Issues
- [ ] Standardize timestamp handling across the application
- [ ] Add proper timezone display for post timestamps
- [ ] Fix inconsistent date formatting between different post types
- [ ] Handle missing timestamp fields gracefully

### Image Handling
- [ ] Fix URL fetching for posts with images
- [ ] Improve image reference extraction from different record structures
- [ ] Handle image arrays consistently in both embedded content and media sections
- [ ] Add support for displaying image dimensions and file size information

### Thread Navigation
- [ ] Fix handling of threads where some posts are from blocked users
- [ ] Improve parent/root post detection when thread structure is incomplete
- [ ] Add better error handling when thread context cannot be properly retrieved
- [ ] Handle deleted posts in thread gracefully

## UX Improvements

### Terminal Interface
- [ ] Add color coding for different elements (posts, replies, navigation options)
- [ ] Improve formatting of long post content
- [ ] Add pagination for long threads with many replies
- [ ] Implement a more intuitive navigation system (perhaps use arrow keys)
- [ ] Add a help command that explains available options

### Content Display
- [ ] Format mentions and URLs in post text for better readability
- [ ] Add support for displaying embedded links and link cards
- [ ] Improve display of code blocks and formatted text in posts
- [ ] Add option to filter or expand thread view

### Performance & Technical
- [ ] Cache post data to reduce redundant API calls
- [ ] Implement rate limiting handling to prevent API lockouts
- [ ] Add session persistence to allow resuming exploration later
- [ ] Optimize memory usage for large thread exploration

## New Features

### Export & Sharing
- [ ] Add ability to export thread or post to text/markdown/HTML
- [ ] Implement simple statistics about thread (depth, participants, etc.)

### Authentication
- [ ] Add support for token-based authentication
- [ ] Implement secure credential storage
- [ ] Add option to use environment variables for credentials

### Search & Discovery
- [ ] Add ability to search for posts by keyword
- [ ] Implement user timeline browsing
- [ ] Add support for exploring feeds and lists

## Code Quality
- [ ] Refactor code into more modular components
- [ ] Add comprehensive error handling and logging
- [ ] Improve code documentation and comments
- [ ] Add unit tests for core functionality
