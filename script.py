import os
import time
import json
import pickle
import threading
import requests
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


def scroll_page(driver, delay=SCROLL_DELAY, max_attempts=SCROLL_MAX_ATTEMPTS):
    # scroll the page until the height doesn't change for max_attempts
    last_height = driver.execute_script("return document.body.scrollHeight")
    attempts = 0
    initial_delay = delay  # store initial delay

    # using a fixed loop for 3 iterations
    while attempts < max_attempts:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        print(f"scrolling page, waiting {delay} seconds...")
        time.sleep(delay)
        new_height = driver.execute_script("return document.body.scrollHeight")

        if new_height > last_height:
            print("page height changed, continue scrolling.")
            attempts = 0  # reset attempts when height changes
            last_height = new_height
            delay = initial_delay  # reset delay if scroll is successful
        else:
            attempts += 1
            print(f"page height did not change, attempts: {attempts}/{max_attempts}.")
            delay += 1  # increase delay if no change

    print("finished scrolling page.")


def wait_for_element(driver, locator, timeout=TIMEOUT):
    # wait until the element is present on the page
    wait = WebDriverWait(driver, timeout)
    return wait.until(EC.presence_of_element_located(locator))


def load_cookies(driver, cookie_file=COOKIES_FILE):
    # load cookies from pickle file into the driver
    try:
        with open(cookie_file, "rb") as file:
            cookies = pickle.load(file)
            for cookie in cookies:
                driver.add_cookie(cookie)
            print("cookies added successfully.")
    except Exception as e:
        print(f"error loading cookies: {e}")


def extract_id_from_client_cache_key(key: str) -> str:
    # extract id from clientCacheKey by removing suffix and extension
    if "_" in key:
        key = key.split("_")[0]
    key = key.split(".")[0]
    return key


def update_ids_json(client_cache_keys, filename=OUTPUT_JSON):
    # update json file with ids and downloaded status
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    for key in client_cache_keys:
        id_value = extract_id_from_client_cache_key(key)
        if id_value not in data:
            data[id_value] = {"downloaded": False}

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"data updated to {filename}")


def download_video_task(id_value, lock, data):
    # download video for a given id
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    driver = webdriver.Chrome(options=options)
    try:
        url = BASE_VIDEO_URL.format(id_value)
        print(f"[{id_value}] processing: {url}")
        driver.get(url)

        # load cookies and refresh to apply them
        load_cookies(driver)
        driver.refresh()

        # wait for the video element to appear
        video_element = wait_for_element(driver, (By.XPATH, VIDEO_ELEMENT_XPATH), timeout=10)
        video_src = video_element.get_attribute("src")
        if not video_src:
            print(f"[{id_value}] no video src found, skipping.")
            return

        print(f"[{id_value}] found video src: {video_src}")

        # determine file extension, default to .mp4 if not found
        parsed_url = urlparse(video_src)
        ext = os.path.splitext(parsed_url.path)[1] or ".mp4"
        file_path = os.path.join("result", f"{id_value}{ext}")

        response = requests.get(video_src, stream=True)
        response.raise_for_status()
        with open(file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f"[{id_value}] download successful, saved to {file_path}")

        # safely update downloaded status using lock
        with lock:
            data[id_value]["downloaded"] = True

    except Exception as e:
        print(f"[{id_value}] error during download: {e}")
    finally:
        driver.quit()


def download_videos():
    # download videos for ids that are not downloaded yet
    if not os.path.exists(OUTPUT_JSON):
        print(f"{OUTPUT_JSON} does not exist. please run crawl first!")
        return

    with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    pending_ids = [id_value for id_value, info in data.items() if not info.get("downloaded", False)]
    if not pending_ids:
        print("no videos to download!")
        return

    os.makedirs("result", exist_ok=True)

    lock = threading.Lock()
    print(f"starting download with {WORKER_THREADS} worker threads...")

    with ThreadPoolExecutor(max_workers=WORKER_THREADS) as executor:
        futures = {executor.submit(download_video_task, id_value, lock, data): id_value for id_value in pending_ids}
        for future in as_completed(futures):
            id_value = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"[{id_value}] error in thread: {e}")

    # update json file with new download status
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print("download process complete and json updated.")


def run_process():
    # initialize chrome driver (visible mode by default)
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless")  # uncomment if headless mode is preferred
    driver = webdriver.Chrome(options=options)

    # open the web page for crawling
    driver.get(WEB_URL)

    # wait until the main element appears; refresh if not found
    retries = 0
    while retries < MAX_RETRIES:
        try:
            wait_for_element(driver, (By.XPATH, ELEMENT_XPATH))
            print("element appeared!")
            break
        except Exception as e:
            print(f"element not found, retrying {retries + 1}/{MAX_RETRIES}... error: {e}")
            driver.refresh()
            retries += 1

    if retries == MAX_RETRIES:
        print("element not found after retries, exiting process.")
        driver.quit()
        return

    # load cookies and refresh to apply them
    load_cookies(driver)
    driver.refresh()

    # wait until the photo list is present
    wait_for_element(driver, (By.CSS_SELECTOR, USER_PHOTO_LIST_SELECTOR))

    # scroll the page to load more content
    scroll_page(driver, delay=SCROLL_DELAY, max_attempts=SCROLL_MAX_ATTEMPTS)

    # wait until video card images appear
    wait_for_element(driver, (By.CSS_SELECTOR, VIDEO_CARD_IMG_SELECTOR))

    # get all video card images
    video_cards = driver.find_elements(By.CSS_SELECTOR, VIDEO_CARD_IMG_SELECTOR)

    # extract clientCacheKey from image src
    client_cache_keys = []
    for img in video_cards:
        img_url = img.get_attribute("src")
        if img_url:
            parsed_url = urlparse(img_url)
            params = parse_qs(parsed_url.query)
            if "clientCacheKey" in params:
                client_cache_keys.append(params["clientCacheKey"][0])

    # print extracted clientCacheKeys
    print("clientCacheKey list:")
    for key in client_cache_keys:
        print(key)

    # update json file with new ids
    update_ids_json(client_cache_keys, filename=OUTPUT_JSON)

    driver.quit()

    # download videos that are not downloaded yet
    download_videos()


def main():
    # run the process up to 5 times if the number of downloaded videos does not increase
    max_attempts = 5
    prev_count = 0

    for attempt in range(max_attempts):
        print(f"\nattempt {attempt + 1}")
        run_process()

        # count number of files in the "result" folder
        if os.path.exists("result"):
            current_count = len(os.listdir("result"))
        else:
            current_count = 0

        print(f"current download count: {current_count}")

        # if new videos were downloaded, stop further attempts
        if current_count > prev_count:
            print("video count increased, stopping further runs.")
            break
        else:
            print("no increase in video count, trying again.")

        prev_count = current_count

    print("process complete.")


if __name__ == "__main__":
    main()
