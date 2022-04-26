## 
## lib/auth.py
## Provides functions for Calnet authentication over
## Selenium, including cookies export.
##
## Copyright (c) 2022 Kevin Mo
##

import pickle
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

COOKIES_NAME = "cookies.pkl"

def save_cookies(driver):
    """
    Save cookies given a Selenium driver.
    """
    pickle.dump(driver.get_cookies(), open(COOKIES_NAME, "wb"))
    return True

def load_cookies(driver):
    """
    Load cookies given a Selenium driver.
    """
    try:
        cookies = pickle.load(open(COOKIES_NAME, "rb"))
        for cookie in cookies:
            driver.add_cookie(cookie)
    except IOError:
        pass

    return driver

def check_calnet_auth(driver):
    """
    Returns whether CalNet authentication is ready.
    """
    return "auth.berkeley.edu" in driver.current_url

def perform_calnet_auth(driver, cid, pwd):
    """
    Perform authentication with CalNet, given
    that driver is at auth.berkeley.edu.
    """
    print("Performing Calnet authentication")
    print("Current URL:", driver.current_url)

    if not check_calnet_auth(driver):
        raise Exception("Cannot perform authentication at current state.")

    # Target user input and then submit
    cid_box = driver.find_element_by_id("username")
    pwd_box = driver.find_element_by_id("password")
    submit_box = driver.find_element_by_id("submit")

    cid_box.send_keys(cid)
    pwd_box.send_keys(pwd)
    submit_box.click()

    # Handle incorrect login attempt
    if "auth.berkeley.edu" in driver.current_url:
        print("Incorrect login attempt detected.")
        raise Exception("Incorrect CalNet credentials")

    # Check the presence of Duo 2FA
    try:
        if "duosecurity.com" not in driver.current_url:
            return True

        print()
        print("IMPORTANT: Complete the 2FA process on the automated browser.")
        print("Complete the process through push notification, security key, etc.")
        print()

        # Stall for success or trust box
        wait = WebDriverWait(driver, 30)
        trust_box = wait.until(EC.element_to_be_clickable((By.ID, "trust-browser-button")))
        print("Detected trust browser button, clicking...")
        trust_box.click()

        wait = WebDriverWait(driver, 10)
        if not wait.until(EC.url_contains("duosecurity.com")):
            raise Exception("2FA did not complete successfully")
        else:
            print("Detected redirect, authentication is a success!")
    except:
        print("Timed out or could not locate Duo 2FA prompt.")

    