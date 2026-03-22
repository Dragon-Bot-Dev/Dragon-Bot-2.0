# 🐉 Dragon Bot 2.0

The high-performance automation engine for **Clash of Clans**. Designed for high-volume requests and deep tactical analysis, Dragon Bot 2.0 bridges the gap between the Supercell API and your Discord community.


---

## ⚙️ Technical Stack

* **Python**
* **MySQL Backend** 
* **Railway** 

Dragon Bot 2.0 is built for **Data Persistence** and **Consistency**:

* **9-Minute Heartbeat:** An optimized polling cycle that keeps the bot's state synchronized with live game data.
* **MySQL Backend:** Utilizing a persistent relational database to map Discord server IDs to Clan Tags, ensuring zero data loss during reboots.
* **Buffered Connectivity:** Handles large-volume API requests with built-in error handling for Supercell API rate limits.

---

## Features

Dragon Bot 2.0 is divided into four core operational modules, designed to handle everything from individual player growth to high-level clan war strategy.

### Tactical War Intelligence
Advanced monitoring for standard Wars and Clan War Leagues (CWL).

* **Real-time War Tracking:** Live stats, hit rates, and roster progress for ongoing wars.
* **Opponent Scouting:** Deep-dive analysis of enemy rosters, hero equipment levels, and defensive capabilities to optimize attack assignments.
* **CWL Architecture:** Full schedule visualization and round-by-round matchup scouting.

### Clan Tools
Centralized tools to manage clan health and automated event tracking.

* **Automated Event Monitoring:** Live tracking for Raid Weekends and Capital progress with historical season archives.
* **Member Management:** Dynamic rosters ranked by trophies or activity, and advanced clan search parameters.
* **Admin Control Panel:** Granular settings for linking clans, toggling reminder webhooks, and managing database persistence.

### Deep Player Analytics
Granular data retrieval for individual account progression.

* **Equipment & Hero Tracking:** specialized monitoring for the latest Hero Equipment meta and upgrade progress.
* **Troop & Spell Audits:** Instant visualization of player levels, including equipments, heroes and spells.
* **Identity Mapping:** A persistent linking system that bridges Discord IDs to Clash of Clans player tags via our MySQL backend.

### 📡 Community & Store Automation
Keeping your server synchronized with the wider Clash of Clans ecosystem and maximizing player rewards.

* **Automated News Hooks:** Integrated webhooks for real-time posts from r/ClashOfClansLeaks and official news sources, ensuring your clan is always ahead of the meta.
* **Supercell Store Integration:** Automated "Zero-Touch" claiming for free weekly rewards from the official Supercell Store. This module handles the manual chores of checking the store, so your members never miss out on free loot.
  
---

## Get Started

1.  **Invite the Bot:** [Add Dragon Bot 2.0 to your Server](https://discord.com/oauth2/authorize?client_id=1322658381974208522&permissions=2214709312&integration_type=0&scope=bot+applications.commands)
2.  **Configuration:** Use `/setclantag` to bind your clan to the server.
3.  **Registration:** Use `/link` to link your Player Tag to your Discord account.
4.  **Assistance:** Use `/help` to view the full suite of tactical commands.

---

## 🛠️ Installation & Deployment

### **Prerequisites**
* Python 3.10+
* A running **MySQL** instance
* Clash of Clans API Developer Token
* 


## 👤 Author
**Bryan** | *Lead Developer*

Developed under the **Dragon-Bot-CoC** Organization.
