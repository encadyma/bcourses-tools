## 
## cli/dl-kaltura.py
## Downloads videos from Kaltura (external tool #78985) with
## Selenium WebDriver informed by the bCourses API.
##
## Starts a Selenium session, authenticates as a Calnet user, 
## asks for a course to download from, then downloads all
## found videos to a target location.
##
## Copyright (c) 2022 Kevin Mo
##

## Libraries
import shutil
import time
import re
import os
import sys
import requests
# from selenium import webdriver
from seleniumwire import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from getpass import getpass
import json
from api import auth
from tqdm import tqdm, trange
from tqdm.contrib.concurrent import thread_map

## STEP 0: Common variables
DATA_LOCATION = "D:/Class/Lectures"
IMPLICIT_WAIT_PERIOD = 10       # how long the driver should wait to find elements before quitting (general)
IMPLICIT_LONG_PERIOD = 30       # how long the driver should wait to find elements before quitting (ajax/spa elements)
LECTURE_FETCH_PERIOD = 10       # how long the driver should stream lectures to fetch all download links/resources
FETCH_ALL_STALL_TIME = 3        # how long the driver should stall before expanding more through the expand button
NUM_PARALLEL_THREADS = 5        # how many parallel threads to download lecture resources
DRIVER_HEADLESS_MODE = True     # whether to run the driver in headless mode (browser does not show up)
DRIVER_AUDIO_DISABLE = True     # whether to disable browser audio on the driver

## STEP 1: Start session and load cookies
options = Options()
if DRIVER_HEADLESS_MODE:
    options.add_argument("--headless")
if DRIVER_AUDIO_DISABLE:
    options.set_preference("media.volume_scale", "0.0")
driver = webdriver.Firefox(options=options)
driver.implicitly_wait(IMPLICIT_WAIT_PERIOD)

## STEP 2: Direct to bcourses, then check auth.berkeley.edu
BCOURSES_URL = "https://bcourses.berkeley.edu"
driver.get("https://bcourses.berkeley.edu")
if auth.check_calnet_auth(driver):
    # Prompt user for username
    uid = input("CalNet ID: ")
    pwd = getpass("CalNet password: ")
    print("Performing authentication using credentials...")
    auth.perform_calnet_auth(driver, uid, pwd)

wait = WebDriverWait(driver, IMPLICIT_WAIT_PERIOD)
if not wait.until(EC.url_contains(BCOURSES_URL)):
    raise Exception("Could not navigate to bCourses url")

## STEP 3: Navigate to bCourses API and parse JSON
BCOURSES_API = "https://bcourses.berkeley.edu/api/v1/courses"
page_num = 1
selected_class = None

while True:
    driver.get(BCOURSES_API + "?page=" + str(page_num))

    json_content = driver.find_element(By.ID, "json").text
    all_classes = json.loads(json_content)

    if not isinstance(all_classes, list):
        print("Received unexpected JSON response from bCourses API.")
    
    print()
    print("Select a class to download from:")
    for i, bclass in enumerate(all_classes):
        if "name" not in bclass:
            bclass["name"] = "Unknown class"
        print(str(i+1) + ") " + bclass["name"] + " (class ID #" + str(bclass["id"]) + ")")

    class_option = input("Select an numbered option ('b' for last page, 'n' for next page): ")

    if class_option == 'b':
        page_num = max(1, page_num-1)
    elif class_option == 'n':
        page_num = page_num + 1
    else:
        try:
            class_idx = int(class_option)
            selected_class = all_classes[class_idx-1]
            break
        except:
            print("Invalid input or numbered option!")

if selected_class is None:
    raise Exception("No class ID found.")

print("\nSelected " + selected_class["name"])

## STEP 3.5: Initialize directory for video transfer
final_dir = DATA_LOCATION + "/" + re.sub(r'[^\w\s\(\)]', '', selected_class["name"])
if os.path.isdir(final_dir):
    print("Folder already detected for this class in data directory.")
    confirm_del = input("Delete this directory to proceed? (y/N): ")
    if confirm_del.lower() != "y":
        sys.exit(1)
    print("Deleting class directory...")
    shutil.rmtree(final_dir)

os.makedirs(final_dir, exist_ok=False)

## STEP 4: Navigate to Kaltura and pull all videos
driver.get(BCOURSES_URL + "/courses/" + str(selected_class["id"]) + "/external_tools/78985")
kaltura_frame = driver.find_element(By.ID, "tool_content")
driver.switch_to.frame(kaltura_frame)

# Fetch more gallery items by clicking on
# the more button
print("Fetching all videos from Kaltura library...")
try:
    while True:
        expand_more = driver.find_element(By.CSS_SELECTOR, ".endless-scroll-more > .btn")
        expand_more.click()
        time.sleep(FETCH_ALL_STALL_TIME)
except:
    print("Expanded all videos from the listing as possible.")

gallery_elems = driver.find_elements(By.CLASS_NAME, "galleryItem")
num_elems = len(gallery_elems)

class GalleryItem:
    def __init__(self, elem, index=-1):
        self.index = index
        self.title = elem.find_element(By.CLASS_NAME, "thumb_name_content").text
        self.author = elem.find_element(By.CLASS_NAME, "userLink").text
        self.date_added = elem.find_element(By.CSS_SELECTOR, ".thumbTimeAdded > span > span").text
        self.thumbnail = elem.find_element(By.CLASS_NAME, "thumb_img").get_attribute("src")
        self.video_url = elem.find_element(By.CLASS_NAME, "item_link").get_attribute("href")
        self.download_urls = {}
        self.srt_urls = {}
        self.download_path = None
        self.processed = False
        self.downloaded = False

    def __str__(self):
        return "(#" + self.str_index() + ") " + self.title + " - " + self.author

    def get_folder_name(self):
        return re.sub(r'[^\w\s\(\)]', '', str(self))

    def str_index(self):
        if self.index < 0:
            return "UNK"
        return f'{self.index:03}'

gallery_items = [GalleryItem(g, index=num_elems-i) for i, g in enumerate(gallery_elems)]

print("This tool will download", len(gallery_items), "videos from the Kaltura gallery.\n")
driver.switch_to.parent_frame()

# Regex patterns
re_vid = re.compile(r"\/(scf\/hls)\/p\/(\d+)\/sp\/(\d+)\/serveFlavor\/entryId\/(\w+)\/v\/\d+\/ev\/\d+\/flavorId\/(\w+)\/name\/([\w\.]+)\/seg-(\d+)-[\w\-]+.ts")
re_str = re.compile(r"\/api_v3\/index.php\/service\/caption_captionAsset\/action\/serve\/captionAssetId\/(\w+)\/ks\/([\w\-\_]+)\/.srt")

print("Now processing detailed metadata and download links for all videos.")
print("This process will take a while to complete.")

def process_gallery_item(gallery_item):
    """
    Gather full information for each video and
    find video + srt links from browser requests.
    """
    # Read in requests
    def read_requests(request):
        if request.host == "cfvod.kaltura.com":
            vid_match = re_vid.match(request.path)
            srt_match = re_str.match(request.path)

            if vid_match:
                gallery_item.download_urls[vid_match.group(4) + '.mp4'] = request.url.replace("/scf/hls/", "/pd/")
            elif srt_match:
                gallery_item.srt_urls[srt_match.group(1) + '.srt'] = request.url
            
    # Reset all requests to proxy
    del driver.requests
    driver.request_interceptor = read_requests
    driver.get(gallery_item.video_url)

    wait = WebDriverWait(driver, IMPLICIT_LONG_PERIOD)
    wait.until(EC.visibility_of_all_elements_located((By.CLASS_NAME, "userLink")))
    gallery_item.author = driver.find_element(By.CLASS_NAME, "userLink").text

    wait = WebDriverWait(driver, IMPLICIT_LONG_PERIOD)
    wait.until(EC.visibility_of_all_elements_located((By.CSS_SELECTOR, "#js-entry-create-at > span")))
    gallery_item.date_added = driver.find_element(By.CSS_SELECTOR, "#js-entry-create-at > span").text

    wait = WebDriverWait(driver, IMPLICIT_LONG_PERIOD)
    wait.until(EC.element_to_be_clickable((By.ID, "kplayer_ifp")))
    play_frame = driver.find_element(By.ID, "kplayer_ifp")
    driver.switch_to.frame(play_frame)

    play_button = driver.find_element(By.CLASS_NAME, "largePlayBtn")
    play_button.click()

    # Open quality options
    settings_button = driver.find_element(By.CSS_SELECTOR, ".sourceSelector > button")
    settings_button.click()
    
    """
    pbar = trange(50, position=1)
    for _ in pbar:
        time.sleep(0.1)
        pbar.set_description("Reading network")
    """
    time.sleep(LECTURE_FETCH_PERIOD)

    gallery_item.processed = True
    del driver.request_interceptor

def print_gallery_item(gallery_item):
    print(str(gallery_item))
    print(gallery_item.date_added)
    print(gallery_item.thumbnail)
    print(gallery_item.video_url)
    print(gallery_item.download_urls)
    print(gallery_item.srt_urls)

with tqdm(gallery_items, position=0) as pbar:
    for gallery_item in pbar:
        pbar.set_description("Processing '" + gallery_item.title + "'")
        process_gallery_item(gallery_item)

print()
print("All links have finished pre-processing.")

print()
print("Creating the required folders for each lecture and")
print("saving pre-processed metadata...")
with tqdm(gallery_items, position=0) as pbar:
    for gallery_item in pbar:
        pbar.set_description("Allocating '" + gallery_item.title + "'")
        # Create the subfolder
        dl_path = final_dir + "/" + gallery_item.get_folder_name()
        os.makedirs(dl_path)
        gallery_item.download_path = dl_path

        with open(dl_path + "/download.json", 'w') as f:
            f.write(json.dumps(gallery_item.__dict__, indent=4))

# Close the driver connection
driver.close()

## STEP 5: Download all the lecture data in parallel
print()
print("Downloading lecture data in parallel (# of streams: " + str(NUM_PARALLEL_THREADS) + ").")
print("This process will take very long depending on your internet speed,")
print("but should take less time to finish towards the end.")

def download_lecture(gallery_item):
    dl_path = gallery_item.download_path
    # Download all subtitles
    dl_list = {**gallery_item.download_urls, **gallery_item.srt_urls}
    for fname in dl_list:
        if not os.path.exists(dl_path + "/" + fname):
            r = requests.get(dl_list[fname], stream=True)
            if r.status_code == 200:
                total_length = int(r.headers.get("Content-Length"))
                with tqdm.wrapattr(r.raw, "read", total=total_length, desc=gallery_item.title + " (" + fname + ")") as raw:
                    # save the output to a file
                    with open(dl_path + "/" + fname, 'wb') as output:
                        shutil.copyfileobj(raw, output)
                
                """
                with open(dl_path + "/" + fname, "wb") as f:
                    for chunk in r:
                        f.write(chunk)
                """
            else:
                print("Encountered unexpected status code", r.status_code, "while downloading", fname)
    
    gallery_item.downloaded = True
    return gallery_item

next_items = thread_map(download_lecture, gallery_items, max_workers=NUM_PARALLEL_THREADS, position=0)

print()
print("Status Report:")
print("Total videos downloaded", sum([i.downloaded for i in next_items]), "out of", len(next_items))
print("Tool has finished execution.")
