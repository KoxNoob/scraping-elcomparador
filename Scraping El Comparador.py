# -*- coding: utf-8 -*-
import streamlit as st
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from bs4 import BeautifulSoup
import time

# ---------------------------
# Helper: Selenium driver
# ---------------------------
def init_driver(headless=True):
    options = Options()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Firefox(options=options)  # system geckodriver
    return driver

# ---------------------------
# Helper: Google Sheet fetch
# ---------------------------
def get_competitions_from_sheet(sheet_url):
    # Extract spreadsheet ID from URL
    import re
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", sheet_url)
    if not match:
        st.error("Invalid Google Sheet URL")
        return pd.DataFrame()
    spreadsheet_id = match.group(1)

    credentials_dict = st.secrets.get("GOOGLE_SHEET_CREDENTIALS")
    if not credentials_dict:
        st.error("Missing GOOGLE_SHEET_CREDENTIALS in Streamlit secrets")
        return pd.DataFrame()

    credentials = Credentials.from_service_account_info(
        credentials_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    client = gspread.authorize(credentials)

    try:
        sheet = client.open_by_key(spreadsheet_id).sheet1
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        if "Compétition" not in df.columns or "URL" not in df.columns:
            st.error("Sheet must have columns 'Compétition' and 'URL'")
            return pd.DataFrame()
        return df
    except Exception as e:
        st.error(f"Error fetching sheet: {e}")
        return pd.DataFrame()

# ---------------------------
# Helper: Scraping
# ---------------------------
def scrape_primera_division(comp_url, selected_bookmakers, nb_matchs):
    driver = init_driver()
    driver.get(comp_url)
    time.sleep(4)
    html = driver.page_source
    driver.quit()

    soup = BeautifulSoup(html, "html.parser")
    rows = []

    bookmakers = [bm.lower() for bm in selected_bookmakers]

    for match_div in soup.find_all("div", id="fila_evento")[:nb_matchs]:
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
                cells = fila.find_all("div", id="celda_cuotas")[1:]  # skip first
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
                "Bookmaker": bm.capitalize(),
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
st.sidebar.title("📌 Menu")
menu_selection = st.sidebar.radio("Choose a sport", ["🏠 Home", "⚽ Football"])

if menu_selection == "🏠 Home":
    st.title("Welcome to the Betting Odds Scraper 🏠")
    st.write("Select a sport in the sidebar to start scraping odds.")

elif menu_selection == "⚽ Football":
    st.title("📊 Football - Primera Division Odds Scraper")

    sheet_url = "https://docs.google.com/spreadsheets/d/1Uh4GWhTX6Q4g9jX6rOBNeqlRxW92VvrHYFm91DJ-3Iw/edit?gid=2029065601"
    competitions_df = get_competitions_from_sheet(sheet_url)

    if not competitions_df.empty:
        selected_competitions = st.multiselect("📌 Select competitions", competitions_df["Compétition"].tolist(), default=["Primera Division"])
        bookmakers = ["Bet365", "Codere", "WilliamHill", "Bwin", "Sportium", "888sports", "Marathon", "Betsson"]
        selected_bookmakers = st.multiselect("🎰 Select bookmakers", bookmakers, default=bookmakers)
        nb_matchs = st.slider("🔢 Number of matches per competition", 1, 20, 5)

        if st.button("🔍 Start scraping"):
            with st.spinner("Scraping in progress..."):
                all_odds_df = pd.DataFrame()
                for comp in selected_competitions:
                    comp_url = competitions_df.loc[competitions_df["Compétition"] == comp, "URL"].values[0]
                    scraped_df = scrape_primera_division(comp_url, selected_bookmakers, nb_matchs)
                    all_odds_df = pd.concat([all_odds_df, scraped_df], ignore_index=True)

                if not all_odds_df.empty:
                    # TRJ average by bookmaker
                    trj_avg = all_odds_df.groupby("Bookmaker")["TRJ (%)"].mean().reset_index()
                    trj_avg = trj_avg.sort_values(by="TRJ (%)", ascending=False)
                    st.subheader("📊 Average TRJ by Bookmaker")
                    st.dataframe(trj_avg)

                    # Detailed table
                    st.subheader("📌 Detailed Odds")
                    st.dataframe(all_odds_df)

                    # CSV download
                    csv = all_odds_df.to_csv(index=False).encode('utf-8')
                    st.download_button("📥 Download CSV", csv, "primera_division_odds.csv", "text/csv")
                else:
                    st.info("No odds retrieved.")
    else:
        st.info("No competitions found in the sheet.")
