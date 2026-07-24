import asyncio
import random
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright

def clean_and_format_cookies(raw_cookies_list):
    """
    Cleans raw browser cookies from typical extensions (like EditThisCookie) 
    and translates them into Playwright-compliant formats.
    """
    cleaned = []
    for cookie in raw_cookies_list:
        c = {
            "name": cookie.get("name"),
            "value": cookie.get("value"),
            "domain": cookie.get("domain"),
            "path": cookie.get("path", "/"),
        }
        
        if "expirationDate" in cookie:
            c["expires"] = cookie["expirationDate"]
        elif "expires" in cookie:
            c["expires"] = cookie["expires"]
            
        if "httpOnly" in cookie:
            c["httpOnly"] = cookie["httpOnly"]
        if "secure" in cookie:
            c["secure"] = cookie["secure"]
            
        same_site = cookie.get("sameSite", "Lax")
        if same_site == "no_restriction":
            c["sameSite"] = "None"
        elif same_site in ["Lax", "Strict", "None"]:
            c["sameSite"] = same_site
        else:
            c["sameSite"] = "Lax"
            
        cleaned.append(c)
    return cleaned

async def run_mission_worker(player_tag: str, cookies_json_str: str):
    try:
        raw_cookies = json.loads(cookies_json_str)
        playwright_cookies = clean_and_format_cookies(raw_cookies)
    except Exception as e:
        return {"success": False, "error": f"Failed to parse user cookie data: {e}"}

    results = {"success": False, "claimed": 0, "missions": []}

    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True) 
        
        # Enforce English locale so store text selectors always match
        context = await browser.new_context(
            user_agent=user_agent,
            viewport={'width': 1280, 'height': 800},
            locale="en-US"
        )
        
        await context.add_cookies(playwright_cookies)
        page = await context.new_page()

        try:
            await page.goto("https://store.supercell.com/clashofclans", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # --- 1. DISMISS COOKIE CONSENT BANNERS ---
            try:
                accept_btn = page.get_by_role("button", name=re.compile(r"accept|agree|allow|ok", re.IGNORECASE))
                if await accept_btn.is_visible(timeout=3000):
                    await accept_btn.click(force=True)
            except Exception:
                pass

            # --- 2. AUTHENTICATION CHECK ---
            login_btn = page.get_by_role("button", name=re.compile(r"log in", re.IGNORECASE))
            try:
                if await login_btn.is_visible(timeout=3000):
                    return {"success": False, "error": "Auth cookies expired or invalid. Please re-export and run /link again."}
            except Exception:
                pass

            # --- 3. TRIGGER BONUS TRACK MODAL ---
            # Scroll down to ensure bottom bar components mount
            await page.mouse.wheel(0, 500) 
            await page.wait_for_timeout(1500) 

            # Check if Bonus Track modal is already open
            modal_open = False
            bonus_header = page.get_by_text(re.compile(r"bonus track", re.IGNORECASE))
            if await bonus_header.is_visible(timeout=2000):
                modal_open = True

            if not modal_open:
                # Candidates to trigger the bottom bonus bar
                triggers = [
                    page.get_by_text(re.compile(r"bonuses to claim", re.IGNORECASE)),
                    page.get_by_text(re.compile(r"to next store bonus", re.IGNORECASE)),
                    page.get_by_text(re.compile(r"store bonus", re.IGNORECASE)),
                    page.locator('[class*="bonusTrack"]'),
                    page.locator('[class*="bottomBar"]')
                ]

                clicked = False
                for trigger in triggers:
                    try:
                        first_match = trigger.first
                        if await first_match.is_visible(timeout=2000):
                            await first_match.click(force=True)
                            clicked = True
                            break
                    except Exception:
                        continue

                # Fallback: Click near bottom-center of window where the sticky bar resides
                if not clicked:
                    await page.mouse.click(640, 750)

            # Wait for Bonus Track modal to load
            await page.get_by_text(re.compile(r"bonus track", re.IGNORECASE)).wait_for(timeout=10000)

            # --- TAB 1: CLAIM BONUSES ---
            claim_btns = page.get_by_role("button", name="CLAIM", exact=True)
            actual_claims = 0
            
            button_count = await claim_btns.count()
            if button_count > 0:
                for i in range(button_count):
                    try:
                        await claim_btns.nth(0).click(force=True, timeout=5000)
                        actual_claims += 1
                        await page.wait_for_timeout(random.randint(1500, 2500))
                    except Exception:
                        continue
                
                results["claimed"] = actual_claims

            # --- NEXT REWARD PROGRESS ---
            try:
                await page.wait_for_timeout(1000)
                bonus_items = page.locator('[class*="bonusTrackItem_item__"]')
                count = await bonus_items.count()
                
                for i in range(count):
                    item = bonus_items.nth(i)
                    content = await item.inner_text()
                    
                    if "Claimed" not in content:
                        results["next_reward"] = " ".join(content.split())
                        break
            except Exception as e:
                print(f"DEBUG: Scraper failed to find next reward: {e}")
                results["next_reward"] = None

            # --- TAB 2: MISSIONS ---
            missions_btn = page.get_by_role("button", name=re.compile(r"missions", re.IGNORECASE))
            if await missions_btn.is_visible(timeout=3000):
                await missions_btn.click(force=True)
                await page.wait_for_timeout(1500)

            mission_cards = page.locator('[class*="bonusMissionItem_item__"]')
            m_count = await mission_cards.count()

            for i in range(m_count):
                card = mission_cards.nth(i)
                try:
                    title = await card.locator('[class*="bonusMissionItem_title"]').inner_text()
                    progress = await card.locator('[class*="bonusMissionItem_progressText"], [class*="bonusMissionItem_compltetedText"]').inner_text()
                    points = await card.locator('[class*="PointsTag_PointsLabel"]').inner_text()

                    results["missions"].append({
                        "title": title.strip(),
                        "progress": progress.strip(),
                        "reward": points.strip()
                    })
                except Exception:
                    continue

            results["success"] = True

        except Exception as e:
            results["error"] = str(e)
        finally:
            await browser.close()
            
    return results