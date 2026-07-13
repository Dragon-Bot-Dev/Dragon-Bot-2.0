import json
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright


ROOT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = ROOT_DIR / "config"

async def capture_session():

    CONFIG_PATH.mkdir(exist_ok=True)

    async with async_playwright() as p:
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        
        browser = await p.chromium.launch(headless=False)
        
        context = await browser.new_context(
            user_agent=user_agent,
            viewport={'width': 1000, 'height': 800} 
        )
        
        page = await context.new_page()
        
        await page.goto("https://store.supercell.com/clashofclans")
        print("Waiting for you to log in...")
        print("💡 Ensure you can see the 'Bonuses' bar at the bottom before time runs out.")
        
        # Gives you 90 seconds to handle the OTP
        await page.wait_for_timeout(90000) 

        # Manually grab sessionStorage 
        session_storage = await page.evaluate("() => JSON.stringify(sessionStorage)")
        
        # Save standard state (Cookies + LocalStorage) into the config directory
        auth_file = CONFIG_PATH / "auth.json"
        await context.storage_state(path=str(auth_file))
        
        # Save the config (User-Agent + SessionStorage + Viewport) into the config directory
        config_file = CONFIG_PATH / "browser_config.json"
        with open(config_file, "w") as f:
            json.dump({
                "user_agent": user_agent, 
                "session_storage": session_storage,
                "viewport": {"width": 1000, "height": 800}
            }, f)
            
        print(f"✅ Session and Fingerprint captured directly to: {CONFIG_PATH}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(capture_session())