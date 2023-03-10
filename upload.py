from selenium import webdriver
from selenium_scripts import *

driver = webdriver.Firefox()
driver.implicitly_wait(5)  # Wait up to 5 secs before throwing an error if selenium cannot find the element (!important)
driver.get("https://www.youtube.com/upload")
elem = driver.find_element(By.XPATH, "//input[@type='file']")
elem.send_keys(r"C:\Users\ofaru\Desktop\Programming\python\reddit-content-farmer\archive\AskReddit\q18zrj\final.mp4")  # Window$
# elem.send_keys("/full/path/to/video.mp4"); # Linux
