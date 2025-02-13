import os
import time
import json
import pickle
import threading
import requests
import logging
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from constant import (
    BASE_VIDEO_URL,
    ELEMENT_XPATH,
    USER_PHOTO_LIST_SELECTOR,
    VIDEO_CARD_IMG_SELECTOR,
    VIDEO_ELEMENT_XPATH,
    TIMEOUT,
    MAX_RETRIES,
    SCROLL_DELAY,
    SCROLL_MAX_ATTEMPTS,
    COOKIES_FILE,
    OUTPUT_JSON,
    WORKER_THREADS,
    WEB_URL
)

# delete old log file if exists
LOG_FILE = "script.log"
if os.path.exists(LOG_FILE):
    os.remove(LOG_FILE)

# setup logger to log to file and console
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# file handler
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)


def scroll_page(driver, delay=SCROLL_DELAY, max_attempts=SCROLL_MAX_ATTEMPTS):
    # scroll the page until height stops changing for max_attempts
    last_height = driver.execute_script("return document.body.scrollHeight")
    attempts = 0
    initial_delay = delay  # store the initial delay

    while attempts < max_attempts:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        logger.info(f"scrolling page, waiting {delay} seconds...")
        time.sleep(delay)
        new_height = driver.execute_script("return document.body.scrollHeight")

        if new_height > last_height:
            logger.info("page height changed, continue scrolling.")
            attempts = 0  # reset attempts when height changes
            last_height = new_height
            delay = initial_delay  # reset delay on success
        else:
            attempts += 1
            logger.info(f"page height did not change, attempts: {attempts}/{max_attempts}.")
            delay += 1  # increase delay if no change

    logger.info("finished scrolling page.")


def wait_for_element(driver, locator, timeout=TIMEOUT):
    # wait for element to be present on page
    wait = WebDriverWait(driver, timeout)
    return wait.until(EC.presence_of_element_located(locator))


def load_cookies(driver, cookie_file=COOKIES_FILE):
    # load cookies from pickle file into driver
    try:
        with open(cookie_file, "rb") as file:
            cookies = pickle.load(file)
            for cookie in cookies:
                driver.add_cookie(cookie)
            logger.info("cookies added successfully.")
    except Exception as e:
        logger.error(f"error loading cookies: {e}")


def extract_id_from_client_cache_key(key: str) -> str:
    # extract id from clientCacheKey by removing suffix and extension
    if "_" in key:
        key = key.split("_")[0]
    key = key.split(".")[0]
    return key


def update_ids_json(client_cache_keys, channel_name, filename=OUTPUT_JSON):
    # update json file with ids and download status for given channel
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    if channel_name not in data:
        data[channel_name] = {}

    for key in client_cache_keys:
        id_value = extract_id_from_client_cache_key(key)
        if id_value not in data[channel_name]:
            data[channel_name][id_value] = {"downloaded": False}

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    logger.info(f"data updated to {filename} for channel '{channel_name}'.")


def download_video_task(id_value, lock, data, channel_name):
    # download video for a given id
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    driver = webdriver.Chrome(options=options)
    try:
        url = BASE_VIDEO_URL.format(id_value)
        logger.info(f"[{id_value}] processing: {url}")
        driver.get(url)

        load_cookies(driver)
        driver.refresh()

        video_element = wait_for_element(driver, (By.XPATH, VIDEO_ELEMENT_XPATH), timeout=10)
        video_src = video_element.get_attribute("src")
        if not video_src:
            logger.info(f"[{id_value}] no video src found, skipping.")
            return

        logger.info(f"[{id_value}] found video src: {video_src}")

        parsed_url = urlparse(video_src)
        ext = os.path.splitext(parsed_url.path)[1] or ".mp4"
        # create channel folder if it doesn't exist
        channel_dir = os.path.join("result", channel_name)
        os.makedirs(channel_dir, exist_ok=True)
        file_path = os.path.join(channel_dir, f"{id_value}{ext}")

        response = requests.get(video_src, stream=True)
        response.raise_for_status()
        with open(file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        logger.info(f"[{id_value}] download successful, saved to {file_path}")

        with lock:
            data[channel_name][id_value]["downloaded"] = True

    except Exception as e:
        logger.error(f"[{id_value}] error during download: {e}")
    finally:
        driver.quit()


def download_videos(channel_name):
    # download videos for ids that are not downloaded for given channel
    if not os.path.exists(OUTPUT_JSON):
        logger.error(f"{OUTPUT_JSON} does not exist. please run crawl first!")
        return

    with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    if channel_name not in data:
        logger.error(f"no data found for channel '{channel_name}'.")
        return

    pending_ids = [id_value for id_value, info in data[channel_name].items() if not info.get("downloaded", False)]
    if not pending_ids:
        logger.info("no videos to download!")
        return

    # create channel folder if not exists
    os.makedirs(os.path.join("result", channel_name), exist_ok=True)

    lock = threading.Lock()
    logger.info(f"starting download with {WORKER_THREADS} worker threads for channel '{channel_name}'...")

    with ThreadPoolExecutor(max_workers=WORKER_THREADS) as executor:
        futures = {
            executor.submit(download_video_task, id_value, lock, data, channel_name): id_value
            for id_value in pending_ids
        }
        for future in as_completed(futures):
            vid = futures[future]
            try:
                future.result()
            except Exception as e:
                logger.error(f"[{vid}] error in thread: {e}")

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    logger.info("download process complete and json updated.")


def run_process():
    # initialize chrome driver (visible mode by default)
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless")  # uncomment if headless mode is preferred
    driver = webdriver.Chrome(options=options)

    driver.get(WEB_URL)

    retries = 0
    while retries < MAX_RETRIES:
        try:
            wait_for_element(driver, (By.XPATH, ELEMENT_XPATH))
            logger.info("main element appeared!")
            break
        except Exception as e:
            logger.error(f"element not found, retrying {retries + 1}/{MAX_RETRIES}... error: {e}")
            driver.refresh()
            retries += 1

    if retries == MAX_RETRIES:
        logger.error("element not found after retries, exiting process.")
        driver.quit()
        return None

    load_cookies(driver)
    driver.refresh()

    wait_for_element(driver, (By.CSS_SELECTOR, USER_PHOTO_LIST_SELECTOR))
    scroll_page(driver, delay=SCROLL_DELAY, max_attempts=SCROLL_MAX_ATTEMPTS)

    # get channel name from user name element
    try:
        channel_element = wait_for_element(driver, (By.CSS_SELECTOR, "div.profile-area p.user-name span"), timeout=TIMEOUT)
        channel_name = channel_element.text.strip()
        logger.info(f"found channel name: {channel_name}")
    except Exception as e:
        logger.error(f"error finding channel name: {e}")
        channel_name = "default_channel"

    wait_for_element(driver, (By.CSS_SELECTOR, VIDEO_CARD_IMG_SELECTOR))
    video_cards = driver.find_elements(By.CSS_SELECTOR, VIDEO_CARD_IMG_SELECTOR)

    client_cache_keys = []
    for img in video_cards:
        img_url = img.get_attribute("src")
        if img_url:
            parsed_url = urlparse(img_url)
            params = parse_qs(parsed_url.query)
            if "clientCacheKey" in params:
                client_cache_keys.append(params["clientCacheKey"][0])

    logger.info("extracted clientCacheKey list:")
    for key in client_cache_keys:
        logger.info(key)

    update_ids_json(client_cache_keys, channel_name, filename=OUTPUT_JSON)

    driver.quit()

    download_videos(channel_name)
    return channel_name


def main():
    # count consecutive attempts with no download increase
    no_increase_count = 0
    attempt = 1
    prev_count = 0
    channel_name = None

    while no_increase_count < 3:
        logger.info(f"\nattempt {attempt}")
        current_channel = run_process()
        if not current_channel:
            current_channel = "default_channel"
        channel_name = current_channel

        result_dir = os.path.join("result", channel_name)
        if os.path.exists(result_dir):
            current_count = len(os.listdir(result_dir))
        else:
            current_count = 0

        logger.info(f"current download count: {current_count}")

        if current_count > prev_count:
            logger.info("video count increased.")
            no_increase_count = 0
        else:
            no_increase_count += 1
            logger.info(f"no increase in video count for {no_increase_count} consecutive attempt(s).")

        prev_count = current_count
        attempt += 1

    logger.info("3 consecutive attempts with no increase in video count. process complete.")


if __name__ == "__main__":
    main()
