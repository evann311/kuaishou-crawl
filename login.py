import pickle
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait

options = webdriver.ChromeOptions()
# options.add_argument("--headless")  # Chạy ở chế độ không hiển thị trình duyệt nếu cần
driver = webdriver.Chrome(options=options)

url = "https://www.kuaishou.com/profile/3x7f5im53vzjz2w"
driver.get(url)

cookie_names = [
    "userId",
    "kuaishou.server.webday7_st",
    "kuaishou.server.webday7_ph"
]

wait = WebDriverWait(driver, 60)
for cookie_name in cookie_names:
    wait.until(lambda d: d.get_cookie(cookie_name) is not None)


# Lấy cookies sau khi đăng nhập đã cập nhật
cookies = driver.get_cookies()
print("Cookies hiện tại:", cookies)

# Lưu cookies vào file pickle
with open("cookies.pkl", "wb") as file:
    pickle.dump(cookies, file)

driver.quit()
