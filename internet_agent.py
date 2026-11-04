import urllib.request
import urllib.parse
from bs4 import BeautifulSoup
import json
import os
import re
from playwright.sync_api import sync_playwright

import logging
logger = logging.getLogger("meow.tools")


TRACKERS_FILE = "trackers.json"

def search_web(query, num_results=5):
    """Scrapes DuckDuckGo HTML search results for links, titles, and snippets."""
    try:
        url = "https://html.duckduckgo.com/html/"
        data = urllib.parse.urlencode({"q": query}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Content-Type": "application/x-www-form-urlencoded"
            }
        )
        import ssl
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, context=context, timeout=10) as response:
            html = response.read()
            soup = BeautifulSoup(html, "html.parser")
            results = []
            for result in soup.find_all('div', class_='result'):
                title_elem = result.find('a', class_='result__a')
                snippet_elem = result.find('a', class_='result__snippet')
                if title_elem:
                    title = title_elem.text.strip()
                    link = title_elem['href']
                    # Resolve relative links
                    if link.startswith('//'):
                        link = 'https:' + link
                    elif link.startswith('/'):
                        link = 'https://duckduckgo.com' + link
                    
                    # Extract target URL if redirect
                    if 'uddg=' in link:
                        parsed = urllib.parse.urlparse(link)
                        qs = urllib.parse.parse_qs(parsed.query)
                        if 'uddg' in qs:
                            link = qs['uddg'][0]
                            
                    snippet = snippet_elem.text.strip() if snippet_elem else ""
                    results.append({"title": title, "link": link, "snippet": snippet})
                    if len(results) >= num_results:
                        break
            return results
    except Exception as e:
        logger.error(f"[INTERNET AGENT ERROR] Search failed for query '{query}': {e}")
        return []

def scrape_url(url):
    """Fetches a webpage, cleans up boilerplates (styles, scripts), and returns clean body text."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        )
        import ssl
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, context=context, timeout=10) as response:
            html = response.read()
            soup = BeautifulSoup(html, "html.parser")
            # Remove scripts and visual layouts
            for elem in soup(["script", "style", "nav", "header", "footer"]):
                elem.decompose()
            text = soup.get_text()
            # Clean up whitespace
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text_clean = "\n".join(chunk for chunk in chunks if chunk)
            if len(text_clean) > 2500:
                text_clean = text_clean[:2500] + "\n...[TRUNCATED]..."
            return text_clean
    except Exception as e:
        return f"Failed to scrape webpage: {e}"

def open_browser_and_navigate(url):
    """Launches a visible Chromium browser window and navigates to the URL, letting the user watch."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            page.goto(url)
            page.wait_for_timeout(12000) # Wait 12 seconds
            browser.close()
            return "Successfully launched headful browser and navigated to site."
    except Exception as e:
        return f"Playwright automation failed: {e}"

# --- PRICE TRACKER PERSISTENCE & DAEMON CHECKERS ---

def load_trackers():
    if os.path.exists(TRACKERS_FILE):
        try:
            with open(TRACKERS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_trackers(trackers):
    with open(TRACKERS_FILE, "w") as f:
        json.dump(trackers, f, indent=4)

def add_tracker(name, url, selector, threshold):
    trackers = load_trackers()
    trackers.append({
        "name": name,
        "url": url,
        "selector": selector,
        "threshold": float(threshold),
        "last_price": None
    })
    save_trackers(trackers)

def parse_price_from_text(text):
    # Strip commas and find decimal/numeric sequences
    clean_text = text.replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)", clean_text)
    if match:
        return float(match.group(1))
    return None

def find_price_in_dict(d):
    if not isinstance(d, dict):
        return None
    offers = d.get("offers")
    if offers:
        if isinstance(offers, list) and len(offers) > 0:
            offers = offers[0]
        if isinstance(offers, dict):
            price = offers.get("price")
            if price is not None:
                try:
                    return float(str(price).replace(",", ""))
                except Exception:
                    pass
    price = d.get("price")
    if price is not None and not isinstance(price, (dict, list)):
        try:
            return float(str(price).replace(",", ""))
        except Exception:
            pass
    for val in d.values():
        if isinstance(val, dict):
            res = find_price_in_dict(val)
            if res is not None:
                return res
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    res = find_price_in_dict(item)
                    if res is not None:
                        return res
    return None

def extract_price_from_json_ld(html_or_soup):
    try:
        if isinstance(html_or_soup, str):
            soup = BeautifulSoup(html_or_soup, "html.parser")
        else:
            soup = html_or_soup
            
        scripts = soup.find_all("script", type="application/ld+json")
        for s in scripts:
            try:
                data = json.loads(s.string or s.text or "")
                if isinstance(data, list):
                    items = data
                else:
                    items = [data]
                    
                for item in items:
                    price = find_price_in_dict(item)
                    if price is not None:
                        return price
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"[JSON-LD PARSE WARNING]: {e}")
    return None

def check_price_of_url(url, selector=".price"):
    # If selector is default, try domain-specific selectors
    if selector == ".price":
        if "flipkart" in url.lower():
            selector = "._30jeq3, .Nx9r88, ._16Jk6d, .price"
        elif "amazon" in url.lower():
            selector = ".a-price-whole, #priceblock_ourprice, #priceblock_dealprice, #price_inside_buybox, .price"
        elif "ebay" in url.lower():
            selector = ".x-price-primary, .price"

    # First try urllib + JSON-LD
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        )
        import ssl
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, context=context, timeout=8) as response:
            html = response.read()
            soup = BeautifulSoup(html, "html.parser")
            
            # Try JSON-LD first
            price = extract_price_from_json_ld(soup)
            if price is not None:
                return price
                
            # Try the group selector
            for sel in selector.split(","):
                elem = soup.select_one(sel.strip())
                if elem:
                    price = parse_price_from_text(elem.text.strip())
                    if price is not None:
                        return price
    except Exception as e:
        logger.warning(f"[URLLIB PRICE FETCH WARNING] {e}. Falling back to Playwright...")
    # Fallback to Playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=20000)
            
            # Try extracting JSON-LD first from loaded DOM
            html_content = page.content()
            price = extract_price_from_json_ld(html_content)
            if price is not None:
                browser.close()
                return price
                
            # Fallback to selector queries
            for sel in selector.split(","):
                try:
                    sel = sel.strip()
                    page.wait_for_selector(sel, timeout=4000)
                    content = page.locator(sel).first.inner_text()
                    price = parse_price_from_text(content.strip())
                    if price is not None:
                        break
                except Exception:
                    continue
            browser.close()
            return price
    except Exception as e:
        logger.error(f"[PLAYWRIGHT PRICE FETCH ERROR] Failed for {url}: {e}")
        return None

def check_tracker_prices():
    trackers = load_trackers()
    updated = False
    alerts = []
    
    for tracker in trackers:
        url = tracker["url"]
        selector = tracker["selector"]
        threshold = tracker["threshold"]
        
        price = check_price_of_url(url, selector)
        if price is not None:
            tracker["last_price"] = price
            updated = True
            
            if price <= threshold:
                alerts.append({
                    "name": tracker["name"],
                    "price": price,
                    "threshold": threshold,
                    "url": url
                })
        else:
            logger.warning(f"[PRICE TRACKER WARNING] Could not fetch price for: {tracker['name']}")
    if updated:
        save_trackers(trackers)
        
    return alerts

def automate_irctc_search(source, destination):
    import time
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=["--start-maximized"])
            context = browser.new_context(viewport=None)
            page = context.new_page()
            
            logger.info(f"[IRCTC AUTOMATION] Navigating to IRCTC...")
            page.goto("https://www.irctc.co.in/nget/trainSearch", timeout=30000)
            
            try:
                page.click("button:has-text('OK')", timeout=5000)
                logger.info("[IRCTC AUTOMATION] Closed alert popup.")
            except Exception:
                pass
                
            logger.info(f"[IRCTC AUTOMATION] Entering source station: {source}...")
            # Click and select "From" station autocomplete input
            from_input = page.locator("p-autocomplete[id='origin'] input")
            from_input.click()
            from_input.fill("")
            from_input.type(source, delay=100)
            page.wait_for_timeout(1000)
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
            
            logger.info(f"[IRCTC AUTOMATION] Entering destination station: {destination}...")
            # Click and select "To" station autocomplete input
            to_input = page.locator("p-autocomplete[id='destination'] input")
            to_input.click()
            to_input.fill("")
            to_input.type(destination, delay=100)
            page.wait_for_timeout(1000)
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
            
            logger.info("[IRCTC AUTOMATION] Clicking Search button...")
            page.click("button[type='submit']")
            
            logger.info("[IRCTC AUTOMATION] Automation complete. Browser window is active for user.")
            for _ in range(60):
                if page.is_closed():
                    break
                time.sleep(10)
                
            try:
                browser.close()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"[IRCTC AUTOMATION ERROR]: {e}")