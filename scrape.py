from ddgs import DDGS
import os
import requests
import time
from ddgs.exceptions import RatelimitException
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

# Suppress SSL warnings since we're skipping verification for problematic sites
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def download_images(query, folder, target_count=300, retry_delay=5, max_retries=3):
    os.makedirs(folder, exist_ok=True)
    
    # Create a session with retry strategy
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # Headers to avoid brotli encoding issues
    headers = {
        'Accept-Encoding': 'gzip, deflate',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    downloaded_count = 0
    image_index = 0
    seen_urls = set()  # Track downloaded URLs to avoid duplicates
    
    for attempt in range(max_retries):
        try:
            with DDGS() as ddgs:
                # Use pagination to get more results
                page = 1
                max_pages = 10  # Limit pages to avoid excessive requests
                results_per_page = 100  # Request 100 results per page
                
                while downloaded_count < target_count and page <= max_pages:
                    print(f"Fetching page {page} for '{query}'...")
                    # Use pagination to get different results
                    results = ddgs.images(query, max_results=results_per_page, page=page)
                    
                    if not results:
                        print(f"No results on page {page}. Stopping.")
                        break
                    
                    results_processed = 0
                    new_urls_found = 0
                    
                    for r in results:
                        if downloaded_count >= target_count:
                            print(f"Successfully downloaded {downloaded_count} images for '{query}'")
                            return
                        
                        url = r.get("image")
                        if not url or url in seen_urls:
                            continue
                        
                        seen_urls.add(url)
                        new_urls_found += 1
                        results_processed += 1
                        
                        # Retry individual image download
                        success = False
                        for img_retry in range(3):
                            try:
                                response = session.get(
                                    url, 
                                    timeout=(10, 30),  # (connect, read) timeout
                                    headers=headers,
                                    verify=False,  # Skip SSL verification for problematic sites
                                    stream=True
                                )
                                response.raise_for_status()
                                
                                # Save image
                                filename = f"{folder}/{query.replace(' ', '_')}_{image_index}.jpg"
                                with open(filename, "wb") as f:
                                    for chunk in response.iter_content(chunk_size=8192):
                                        f.write(chunk)
                                
                                downloaded_count += 1
                                image_index += 1
                                success = True
                                
                                if downloaded_count % 50 == 0:
                                    print(f"Downloaded {downloaded_count}/{target_count} images for '{query}'...")
                                
                                # Small delay to avoid overwhelming servers
                                time.sleep(0.1)
                                break  # Success, exit retry loop
                                
                            except requests.exceptions.SSLError as e:
                                if img_retry < 2:
                                    continue
                                # Skip SSL errors after retries
                                break
                            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                                if img_retry < 2:
                                    time.sleep(1)
                                    continue
                                # Skip timeout/connection errors after retries
                                break
                            except Exception as e:
                                if img_retry < 2:
                                    continue
                                # Skip other errors after retries
                                break
                        
                        if not success and downloaded_count % 100 == 0:
                            print(f"Progress: {downloaded_count}/{target_count} successful downloads...")
                    
                    print(f"Page {page}: Found {new_urls_found} new URLs, downloaded {downloaded_count}/{target_count} total")
                    
                    if new_urls_found == 0:
                        print(f"No new URLs on page {page}. Trying next page...")
                    
                    page += 1
                    time.sleep(2)  # Brief delay between pages to avoid rate limiting
                
                if downloaded_count >= target_count:
                    print(f"Successfully downloaded {downloaded_count} images for '{query}'")
                    return
                else:
                    print(f"Downloaded {downloaded_count}/{target_count} images after {page - 1} pages.")
                    break
                    
        except RatelimitException:
            if attempt < max_retries - 1:
                print(f"Rate limited. Waiting {retry_delay} seconds before retry {attempt + 1}/{max_retries}...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                print(f"Rate limit exceeded after {max_retries} attempts. Downloaded {downloaded_count}/{target_count} images for '{query}'.")
                return
        except Exception as e:
            print(f"Error processing '{query}': {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                raise
    
    print(f"Final count: {downloaded_count}/{target_count} images downloaded for '{query}'")

download_images("maracuyá fruit", "dataset/maracuya", target_count=300)
download_images("passion fruit", "dataset/passion_fruit", target_count=300)
