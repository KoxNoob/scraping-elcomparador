# -*- coding: utf-8 -*-
import streamlit as st
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from bs4 import BeautifulSoup
import pandas as pd
import time

# ---------------------------
# Selenium driver initializer
# ---------------------------
def init_driver(headless=True):
    options = Options()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    # Use system geckodriver (no webdriver-manager)
    driver = webdriver.Firefox(options=options)
    return driver

# ---------------------------
# Scraping El Comparador Primera Division
# ---------------------------
def scrape_primera_division():
    url = "http://www.elcomparador.com/futbol/espa%C3%B1a/primeradivision"
    driver = init_driver()
    driver.get(url)
    time.sleep(4)  # wait for JS to load
    html = driver.page_source
    driver.quit()

    soup = BeautifulSoup(html, "html.parser")
    rows = []

    bookmakers = ["bet365", "codere", "williamhill", "bwin", "sportium", "888sport", "marathon", "betsson"]

    for match_div in soup.find_all("div", id="fila_evento"):
        # Get teams
        teams_div = match_div.find("div", id="celda_evento_partido")
        if teams_div:
            teams = " - ".join([t.strip() for t in teams_div.stripped_strings if "Estadísticas" not in t and "Pronósticos" not in t])
            if teams == "Evento":
                continue
        else:
            continue

        home_odds, draw_odds, away_odds = [], [], []

        cuotas_divs = match_div.find_all("div", id="fila_cuotas")
        if len(cuotas_divs) >= 3:
            for idx, fila in enumerate(cuotas_divs[:3]):
                cells = fila.find_all("div", id="celda_cuotas")[1:]  # skip first (apuesta)
                odds = [cell.get_text(strip=True) if cell.get_text(strip=True) else "-" for cell in cells]

                if idx == 0:
                    home_odds = odds
                elif idx == 1:
                    draw_odds = odds
                elif idx == 2:
                    away_odds = odds
        else:
            home_odds, draw_odds, away_odds = ["-"]*len(bookmakers), ["-"]*len(bookmakers), ["-"]*len(bookmakers)

        for i, bm in enumerate(bookmakers):
            row = {
                "Match": teams,
                "Bookmaker": bm,
                "1": home_odds[i] if i < len(home_odds) else "-",
                "X": draw_odds[i] if i < len(draw_odds) else "-",
                "2": away_odds[i] if i < len(away_odds) else "-"
            }
            # Calculate TRJ
            try:
                h = float(row["1"])
                d = float(row["X"])
                a = float(row["2"])
                row["TRJ (%)"] = round((1/h + 1/d + 1/a)*100, 2)
            except:
                row["TRJ (%)"] = "-"
            rows.append(row)

    df = pd.DataFrame(rows)
    return df

# ---------------------------
# Streamlit UI
# ---------------------------
st.title("⚽ Primera Division Odds Scraper")

if st.button("🔍 Scrape Primera Division"):
    with st.spinner("Scraping in progress..."):
        df = scrape_primera_division()
        if not df.empty:
            st.subheader("📌 Odds by Bookmaker")
            st.dataframe(df)
            # Optionally CSV download
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download CSV", csv, "primera_division_odds.csv", "text/csv")
        else:
            st.info("No data retrieved.")
