import asyncio
import random
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright

def clean_and_format_cookies(raw_cookies_list):
    """
    Cleans raw browser cookies and translates them into Playwright-compliant formats.
    """
    cleaned = []
    for cookie in raw_cookies_list:
        c = {
            "name": cookie.get("name"),
            "value": cookie.get("value"),
            "domain": cookie.get("domain"),
            "path": cookie.get("path", "/"),
        }
        
        if "expirationDate" in cookie and isinstance(cookie["expirationDate"], (int, float)):
            c["expires"] = float(cookie["expirationDate"])
        elif "expires" in cookie and isinstance(cookie["expires"], (int, float)):
            c["expires"] = float(cookie["expires"])
            
        if "httpOnly" in cookie:
            c["httpOnly"] = bool(cookie["httpOnly"])
        if "secure" in cookie:
            c["secure"] = bool(cookie["secure"])
            
        same_site_raw = str(cookie.get("sameSite", "Lax")).lower()
        if same_site_raw in ["no_restriction", "none"]:
            c["sameSite"] = "None"
        elif same_site_raw in ["lax"]:
            c["sameSite"] = "Lax"
        elif same_site_raw in ["strict"]:
            c["sameSite"] = "Strict"
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

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, # Keep False to visually debug
            args=["--disable-blink-features=AutomationControlled",
                "--no-sandbox",             # Required for Linux/Railway containers
                "--disable-setuid-sandbox", # Required for Linux/Railway containers
                "--disable-dev-shm-usage",]
        )
        
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            locale="en-US"
        )
        
        await context.add_cookies(playwright_cookies)
        page = await context.new_page()

        try:
            # 1. PAGE LOAD & HYDRATION
            await page.goto("https://store.supercell.com/clashofclans", wait_until="load", timeout=30000)
            await page.wait_for_timeout(3000)

            # 2. DISMISS CONSENT & PROMO OVERLAYS
            try:
                accept_btn = page.get_by_role("button", name=re.compile(r"accept|agree|allow|ok", re.IGNORECASE))
                if await accept_btn.is_visible(timeout=2000):
                    await accept_btn.click(force=True)
                
                close_btn = page.locator('button[aria-label*="close" i], button[class*="close" i]')
                if await close_btn.first.is_visible(timeout=2000):
                    await close_btn.first.click(force=True)
            except Exception:
                pass

            # 3. AUTHENTICATION CHECK
            login_btn = page.get_by_role("button", name=re.compile(r"log in", re.IGNORECASE))
            try:
                if await login_btn.is_visible(timeout=3000):
                    return {"success": False, "error": "Auth cookies expired or invalid. Please re-export and run /link again."}
            except Exception:
                pass

            # 4. TRIGGER BONUS TRACK MODAL
            await page.mouse.wheel(0, 600) 
            await page.wait_for_timeout(1500) 

            modal_header = page.get_by_text(re.compile(r"bonus track", re.IGNORECASE))
            if not await modal_header.is_visible(timeout=1500):
                triggers = [
                    page.locator('[data-testid="bonus-footer"] button'), 
                    page.locator('[data-testid="bonus-footer"]'),        
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
                        if await first_match.is_visible(timeout=1500):
                            await first_match.scroll_into_view_if_needed()
                            await first_match.click(force=True)
                            clicked = True
                            await page.wait_for_timeout(1500)
                            break
                    except Exception:
                        continue

            try:
                await page.get_by_text(re.compile(r"bonus track", re.IGNORECASE)).wait_for(timeout=8000)
            except Exception as e:
                print(f"⚠️ Modal failed to open. Capturing debug files...")
                await page.screenshot(path="debug_modal_failed.png", full_page=True)
                html_content = await page.content()
                with open("debug_page.html", "w", encoding="utf-8") as f:
                    f.write(html_content)
                print(f"✅ Saved debug_modal_failed.png and debug_page.html to your local directory.")
                return {
                    "success": False, 
                    "error": "Could not open Bonus Track modal. Check local debug_modal_failed.png."
                }

            # --- TAB 1: CLAIM BONUSES ---
            actual_claims = 0
            
            # Bound the loop to prevent infinite clicking if UI gets stuck
            for _ in range(10):
                try:
                    # Regex ^claim\b matches "Claim" and "CLAIM" but specifically avoids "Claimed"
                    claim_btn = page.get_by_role("button", name=re.compile(r"^claim\b", re.IGNORECASE)).first
                    
                    if await claim_btn.is_visible(timeout=2000):
                        await claim_btn.scroll_into_view_if_needed()
                        await claim_btn.click(force=True, timeout=4000)
                        actual_claims += 1
                        await page.wait_for_timeout(2500)
                        
                        # Dismiss the "Reward Claimed" popup overlay if it appears
                        try:
                            ok_btn = page.get_by_role("button", name=re.compile(r"^ok$|^close$|^awesome$", re.IGNORECASE)).first
                            if await ok_btn.is_visible(timeout=2000):
                                await ok_btn.click(force=True)
                                await page.wait_for_timeout(1000)
                            else:
                                close_icon = page.locator('button[aria-label*="close" i]').first
                                if await close_icon.is_visible(timeout=1000):
                                    await close_icon.click(force=True)
                                    await page.wait_for_timeout(1000)
                        except Exception:
                            pass
                    else:
                        break # Exits loop when no more claimable buttons are found
                except Exception as e:
                    print(f"DEBUG Claim Loop: {e}")
                    break
            
            results["claimed"] = actual_claims

            # --- EXTRACT SEASON TIMER ---
            try:
                # Target the parent container holding the "Time Left" text
                timer_el = page.locator('text="Time Left"').locator("xpath=..")
                if await timer_el.is_visible(timeout=2000):
                    timer_text = await timer_el.inner_text()
                    lines = [t.strip() for t in timer_text.split('\n') if t.strip()]
                    # Usually outputs: ['Time Left', '2d 14h']
                    results["season_timer"] = lines[-1] if len(lines) > 1 else None
            except Exception as e:
                print(f"DEBUG Timer: {e}")
                results["season_timer"] = None

            # --- NEXT REWARD PROGRESS ---
            try:
                await page.wait_for_timeout(1000)
                bonus_items = page.locator('[class*="bonusTrackItem_item"], [class*="bonusTrackItem_content"], [data-testid*="track-item"]')
                count = await bonus_items.count()
                
                for i in range(count):
                    item = bonus_items.nth(i)
                    content = await item.inner_text()
                    
                    if "Claimed" not in content and not re.search(r"^claim\b", content, re.IGNORECASE):
                        results["next_reward"] = " ".join(content.split())
                        break
            except Exception as e:
                print(f"DEBUG: Scraper failed to find next reward: {e}")
                results["next_reward"] = None

            # --- TAB 2: MISSIONS ---
            missions_btn = page.get_by_role("button", name=re.compile(r"missions", re.IGNORECASE))
            if await missions_btn.is_visible(timeout=3000):
                await missions_btn.click(force=True)
                await page.wait_for_timeout(2500) # Give extra time for React DOM to render missions

            # Substring locators: Targets the base name "item" and "clashofclans" ignoring the random hashes
            mission_cards = page.locator('div[class*="item_"][class*="clashofclans"]')
            m_count = await mission_cards.count()

            # Fallback if the primary structure fails
            if m_count == 0:
                mission_cards = page.locator('[class*="MissionItem"], [class*="Missions_item"], [data-testid*="mission"]')
                m_count = await mission_cards.count()

            for i in range(m_count):
                card = mission_cards.nth(i)
                try:
                    text_content = await card.inner_text()
                    lines = [line.strip() for line in text_content.split('\n') if line.strip()]
                    text_lower = text_content.lower()

                    if len(lines) >= 2 and ("pts" in text_lower or "points" in text_lower or "+" in text_lower):
                        title = ""
                        progress = ""
                        reward = ""

                        # 1. Handle Supercell's "Completed!" HTML structure
                        if "completed!" in text_lower:
                            progress = "COMPLETED"
                            try:
                                # The title is the line immediately following "Completed!"
                                comp_index = [idx for idx, s in enumerate(lines) if 'completed!' in s.lower()][0]
                                title = lines[comp_index + 1]
                            except IndexError:
                                title = lines[0]
                        
                        # 2. Handle standard "In Progress" HTML structure
                        else:
                            title = lines[0]
                            for line in lines:
                                if "/" in line:
                                    progress = line
                                    break
                            if not progress:
                                progress = lines[1] # fallback

                        # 3. Extract Reward Points
                        for line in reversed(lines):
                            if "pts" in line.lower() or "points" in line.lower() or "+" in line:
                                reward = line
                                break

                        mission_dict = {
                            "title": title.strip()[:100],
                            "progress": progress.strip(),
                            "reward": reward.strip()
                        }
                        
                        if mission_dict not in results["missions"]:
                            results["missions"].append(mission_dict)
                            
                except Exception:
                    continue

            results["success"] = True

        except Exception as e:
            results["error"] = str(e)
        finally:
            await browser.close()
            
    return results