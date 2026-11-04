import os
import re
import time
import urllib.request
import urllib.parse
import csv
from bs4 import BeautifulSoup

import companion

def get_desktop_path():
    # Prioritize original/local desktop (non-OneDrive)
    local_desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.exists(local_desktop):
        return local_desktop
        
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        val, type_ = winreg.QueryValueEx(key, "Desktop")
        winreg.CloseKey(key)
        return os.path.expandvars(val)
    except Exception:
        path1 = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
        if os.path.exists(path1):
            return path1
        return os.path.join(os.path.expanduser("~"), "Desktop")

def search_duckduckgo(query, max_results=5):
    url = "https://html.duckduckgo.com/html/"
    params = urllib.parse.urlencode({"q": query})
    full_url = f"{url}?{params}"
    print(f"[AGENT SEARCH] Querying DuckDuckGo: '{query}'")
    
    try:
        req = urllib.request.Request(
            full_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")
            
        soup = BeautifulSoup(html, "html.parser")
        results = []
        
        result_divs = soup.select(".result")
        for div in result_divs[:max_results]:
            title_tag = div.select_one(".result__a")
            snippet_tag = div.select_one(".result__snippet")
            
            if title_tag:
                title = title_tag.get_text(strip=True)
                link = title_tag.get("href")
                
                # Parse redirect url out of ddg wrapper
                if "/l/?uddg=" in link:
                    link = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("uddg", [link])[0]
                    
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
                results.append({
                    "title": title,
                    "url": link,
                    "snippet": snippet
                })
        return results
    except Exception as e:
        print(f"[AGENT SEARCH ERROR] DuckDuckGo search failed: {e}")
        return []

def scrape_url_text(url, max_chars=3000):
    print(f"[AGENT SCRAPER] Reading text from: {url}")
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        with urllib.request.urlopen(req, timeout=6) as response:
            info = response.info()
            if "text/html" not in info.get_content_type():
                return ""
            html = response.read().decode("utf-8", errors="ignore")
            
        soup = BeautifulSoup(html, "html.parser")
        # strip script and layout tags
        for element in soup(["script", "style", "meta", "noscript", "header", "footer", "nav"]):
            element.decompose()
            
        text = soup.get_text(separator=" ")
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:max_chars]
    except Exception as e:
        print(f"[AGENT SCRAPER WARNING] Could not scrape {url}: {e}")
        return ""

def run_agent_flow(goal, api_key, model_type="nvidia", progress_callback=None):
    if progress_callback:
        progress_callback("Formulating research plan...")
        
    system_prompt = "You are Mark's autonomous search planner. Generate exactly 2 relevant search queries (one per line) based on the user's goal. Output ONLY the queries, no numbering or introduction."
    
    # Generate search queries using LLM
    if model_type == "gemini":
        planner_resp = companion.call_gemini(api_key, system_prompt, [], f"User goal: {goal}", max_tokens=100)
    else:
        planner_resp = companion.call_nvidia(api_key, system_prompt, [], f"User goal: {goal}", max_tokens=100)
        
    queries = []
    for q in planner_resp.split("\n"):
        q_clean = q.strip().replace('"', '').replace("'", "")
        # Strip list indicators like "1. ", "2 - ", "1) "
        q_clean = re.sub(r'^\d+[\.\-\)\s]+', '', q_clean).strip()
        if q_clean:
            queries.append(q_clean)
            
    if not queries:
        queries = [goal]
        
    # Limit to top 2 queries for speed
    queries = queries[:2]
    
    all_results = {}
    for q in queries:
        if progress_callback:
            progress_callback(f"Searching web for: {q}...")
        res = search_duckduckgo(q, max_results=3)
        for item in res:
            all_results[item["url"]] = item
            
    if not all_results:
        return "I searched the web but couldn't find any results matching your request, Boss."
        
    # Scrape top 3 pages to gather detailed text content
    scraped_data = []
    urls_to_scrape = list(all_results.keys())[:3]
    for idx, url in enumerate(urls_to_scrape):
        if progress_callback:
            progress_callback(f"Scraping page {idx+1}/{len(urls_to_scrape)}...")
        page_text = scrape_url_text(url)
        item = all_results[url]
        scraped_data.append({
            "title": item["title"],
            "url": url,
            "snippet": item["snippet"],
            "body": page_text[:1500] if page_text else ""
        })
        time.sleep(1) # polite delay
        
    # Format gathered data for LLM shortlister
    data_summary = ""
    for idx, d in enumerate(scraped_data):
        data_summary += f"--- Source {idx+1} ({d['url']}) ---\nTitle: {d['title']}\nSnippet: {d['snippet']}\nContent: {d['body']}\n\n"
        
    if progress_callback:
        progress_callback("Analyzing pages and compiling report...")
        
    shortlist_prompt = (
        "You are an expert data compiler. The user's goal is:\n"
        f"'{goal}'\n\n"
        "Here is the gathered web research data:\n"
        f"{data_summary}\n"
        "Instructions:\n"
        "1. Extract matches matching the goal (e.g. internships, jobs, contacts, detail rows).\n"
        "2. Compile a list of the top 10 matches.\n"
        "3. Format your response ONLY as a clean comma-separated CSV block. Include columns like: Name/Title, Detail/Location, Description, Source URL.\n"
        "4. Output ONLY the CSV block. Do not include markdown code block syntax (like ```csv) or introductions."
    )
    
    system_prompt = "You compile and format structured research CSV reports. Output only valid CSV."
    
    if model_type == "gemini":
        csv_output = companion.call_gemini(api_key, system_prompt, [], shortlist_prompt, max_tokens=1000)
    else:
        csv_output = companion.call_nvidia(api_key, system_prompt, [], shortlist_prompt, max_tokens=1000)
        
    # Clean up CSV block
    csv_lines = [line.strip() for line in csv_output.split("\n") if line.strip()]
    csv_clean = []
    for line in csv_lines:
        if line.startswith("```"):
            continue
        csv_clean.append(line)
        
    csv_text = "\n".join(csv_clean)
    
    # Save CSV to Desktop
    desktop = get_desktop_path()
    report_path = os.path.join(desktop, "agent_report.csv")
    try:
        with open(report_path, "w", encoding="utf-8-sig", newline="") as f:
            f.write(csv_text)
            
        print(f"[AGENT] Saved report successfully to: {report_path}")
        return f"Research agent complete, Boss! I have searched the web, shortlisted the matches, and saved a compiled spreadsheet named 'agent_report.csv' on your Desktop."
    except Exception as e:
        print(f"[AGENT ERROR] Failed to save CSV: {e}")
        return f"Research complete, but I encountered an error writing the CSV file to your Desktop: {e}"
