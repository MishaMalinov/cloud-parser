# LINK = "https://www.myqnapcloud.com/smartshare/76f5f806np2m2676sux5w18d_03d5e4592k982o5p105380x60465g2g4"
# LINK = "https://www.myqnapcloud.com/share/76f5f806np2m2676sux5w18d_03d5e4592k982o5p105380x60465g2g4#!/home/Aber"
# LINK = "https://www.myqnapcloud.com/share/76f5f806np2m2676sux5w18d_03d5e4592k982o5p105380x60465g2g4#!/home/Aber/AL00038"


from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from time import sleep

def parse_items(url: str):
    # Налаштування браузера (без вікна, щоб було легше)
    options = Options()
    options.add_argument("--headless=true")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    # Запускаємо ChromeDriver (потрібно мати встановлений chromedriver)
    service = Service()
    driver = webdriver.Chrome(service=service, options=options)

    # try:
    print('ready to parse')
    driver.get(url)

    sleep(3)
    # беремо всі <a> з ng-if (там і файли, і папки)
    anchors = driver.find_elements(By.CSS_SELECTOR, "a[ng-if]")

    folders, files = [], []

    for a in anchors:
        text = a.text.strip()
        href = a.get_attribute("href")
        ng_if = a.get_attribute("ng-if")

        if "== 'directory'" in ng_if:
            folders.append((text, href))
        elif "!= 'directory'" in ng_if:
            files.append((text, href))

    return folders, files

if __name__ == "__main__":
    test_url = LINK  # ← сюди підстав свій лінк
    folders, files = parse_items(test_url)

    print("📂 Folders:")
    for name, link in folders:
        print(f"  {name} -> {link}")

    print("\n📄 Files:")
    for name, link in files:
        print(f"  {name} -> {link}")
