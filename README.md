# Horse Racing Bot Chat

UK & Ireland daily racing tips from 6 independent bots.

## Features

- **6 Bots** with distinct personalities that decide naturally (favourite / each-way / longshot)
- Interactive page matching the original prototype (Today / Tomorrow / Big Races / Doubles & Accas / Leaderboard)
- Stars show multi-bot agreement
- Confidence % with colour coding
- Leaderboard tracking (daily / weekly / monthly / yearly + betting style)
- Free data via scraping (Sporting Life / Racing TV public feeds)
- Ready for GitHub Pages + later GitHub Actions auto-update

## Bots

| Bot              | Colour     | Style focus                          |
|------------------|------------|--------------------------------------|
| BloodlineBetty   | Pink       | Breeding, pedigree, early form       |
| DevilAdvocate    | Purple     | Contrarian, questions the favourite  |
| FormFox          | Blue       | Recent form & speed figures          |
| HotTrainer       | Red        | Trainer / jockey combinations        |
| PaceProphet      | Orange     | Pace maps & race shape               |
| ValueHunter      | Green      | Odds vs estimated probability        |

Each bot is free to tip a short-priced favourite if confidence is high, switch to an each-way when the odds make more sense, or take a big price when it sees genuine value.

## Project Structure

```
horse-racing-bot-chat/
├── index.html
├── css/styles.css
├── js/
│   ├── app.js
│   ├── bots.js
│   └── storage.js
├── data/
│   ├── tips-YYYY-MM-DD.json
│   └── leaderboard.json
├── scripts/
│   ├── scrape_racecards.py
│   ├── generate_tips.py
│   └── update_leaderboard.py
└── README.md
```

## Quick Start

1. Clone this repo
2. Open `index.html` in a browser (or serve with any static server)
3. For live data:
   ```bash
   cd scripts
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   python scrape_racecards.py --date today
   python generate_tips.py
   ```
4. Refresh the page

## Leaderboard

Tracks for each bot:
- Win rate
- ROI (level stakes)
- Average odds of selections
- Style distribution (short / E/W / longshot)
- Daily / Weekly / Monthly / Yearly records

Data is stored in `localStorage` and can be exported/imported as JSON.

## Licence

Personal use. Free scraping sources are used at your own risk and subject to the sites' terms.
