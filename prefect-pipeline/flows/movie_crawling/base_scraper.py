from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

class BaseScraper:
    def __init__(self):
        self.driver = self.init_driver()

    def init_driver(self):
        # Auto download suitable chromedriver 
        service = Service(ChromeDriverManager().install())
        options = webdriver.ChromeOptions()
        
        # Set Chrome options to reduce memory usage
        options.add_argument("--headless")
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--window-position=-2400,-2400")
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.45 Safari/537.36")

        driver = webdriver.Chrome(service=service, options=options)
        return driver

    def close_driver(self):
        self.driver.quit()
