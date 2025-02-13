# constants.py

# basic url of the profile page
WEB_URL = "https://www.kuaishou.com/profile/3x7f5im53vzjz2w"

# basic url for video; '{}' will be replaced with the video id
BASE_VIDEO_URL = "https://www.kuaishou.com/short-video/{}"

# xpaths and css selectors used in the scraper
ELEMENT_XPATH = "//*[@id='app']/div[1]/section/div/div/div[1]/div[1]/div/div[2]/div/div/div/div/span[2]"
USER_PHOTO_LIST_SELECTOR = "div.user-photo-list"
VIDEO_CARD_IMG_SELECTOR = ".user-photo-list .video-card img"
VIDEO_ELEMENT_XPATH = "//*[@id='app']/div[1]/section/div/div/div/div[1]/div[2]/div[1]/div[2]/video"

# timeout and retry settings
TIMEOUT = 5          # max wait time in seconds
MAX_RETRIES = 3      # number of retries if an element is not found

# scroll settings
SCROLL_DELAY = 3         # initial scroll delay in seconds
SCROLL_MAX_ATTEMPTS = 2  # max consecutive scrolls without height change

# cookie file name
COOKIES_FILE = "cookies.pkl"

# output json file name to store results
OUTPUT_JSON = "client_cache_keys.json"

# number of worker threads for concurrent video downloads
WORKER_THREADS = 5
